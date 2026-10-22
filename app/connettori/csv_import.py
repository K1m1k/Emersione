"""Import/export CSV con schema, limiti e validazione preventiva."""
from __future__ import annotations

import csv
import io
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app.settori import ErroreRegistro, lista_settori, ottieni_settore

MAX_BYTES = 5 * 1024 * 1024
MAX_RIGHE = 25_000
MAX_COLONNE = 100
MAX_CAMPO_TESTO = 500
_HEADER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_CAMPI_COMUNI = {
    "id": {"tipo": "testo", "obbligatorio": True},
    "settore": {"tipo": "testo", "obbligatorio": True},
    "dipendenti_dichiarati": {"tipo": "numero", "obbligatorio": True, "minimo": 0},
}
_CAMPI_EXTRA = {
    # Indicatore trasversale facoltativo: la sua assenza non deve impedire
    # l'analisi settoriale né essere trasformata in zero.
    "costo_lavoro_per_addetto": {"tipo": "numero", "obbligatorio": False, "minimo": 0},
    "ragione_sociale": {"tipo": "testo", "obbligatorio": False},
    "citta": {"tipo": "testo", "obbligatorio": False},
    "dpi_acquistati": {"tipo": "numero", "obbligatorio": False, "minimo": 0},
    "valore_opera": {"tipo": "numero", "obbligatorio": False, "minimo": 0},
    "costo_manodopera_dichiarato": {"tipo": "numero", "obbligatorio": False, "minimo": 0},
    "categoria_opera": {"tipo": "testo", "obbligatorio": False},
    "tipo_commessa": {"tipo": "testo", "obbligatorio": False},
    "gruppo_societario_id": {"tipo": "testo", "obbligatorio": False},
    "codice_contratto_pubblico": {"tipo": "testo", "obbligatorio": False},
    "codice_subappalto": {"tipo": "testo", "obbligatorio": False},
    "sede_locale_codice": {"tipo": "testo", "obbligatorio": False},
    "giorni_apertura": {"tipo": "numero", "obbligatorio": False, "minimo": 1, "massimo": 7},
    "kg_materia_prima_settimana": {"tipo": "numero", "obbligatorio": False, "minimo": 0},
    "mezzi_agricoli": {"tipo": "numero", "obbligatorio": False, "minimo": 0},
    "mezzi": {"tipo": "numero", "obbligatorio": False, "minimo": 0},
    "_irregolare": {"tipo": "booleano", "obbligatorio": False},
}


class ErroreCSV(ValueError):
    """Errore di validazione, con messaggio destinato all'operatore."""


def _schema_globale() -> dict[str, dict[str, Any]]:
    schema = {k: dict(v) for k, v in _CAMPI_COMUNI.items()}
    schema.update({k: dict(v) for k, v in _CAMPI_EXTRA.items()})
    for settore in lista_settori():
        for campo, definizione in settore.get("campi", {}).items():
            precedente = schema.get(campo)
            nuova = dict(definizione)
            if precedente and precedente.get("tipo") != nuova.get("tipo"):
                raise RuntimeError(f"Campo ambiguo nel registro di schema: {campo}")
            schema[campo] = nuova
    return schema


def _converti_numero(testo: str, nome_campo: str, riga: int) -> int | float:
    normalizzato = testo.strip().replace(" ", "")
    if not normalizzato:
        raise ErroreCSV(f"Riga {riga}: il campo numerico '{nome_campo}' è vuoto.")
    # La virgola decimale è accettata se non viene usata anche come separatore migliaia.
    if "," in normalizzato and "." in normalizzato:
        raise ErroreCSV(f"Riga {riga}: formato numerico ambiguo in '{nome_campo}'. Usa un solo separatore decimale.")
    normalizzato = normalizzato.replace(",", ".")
    try:
        numero = float(normalizzato)
    except ValueError as exc:
        raise ErroreCSV(f"Riga {riga}: '{nome_campo}' deve essere numerico.") from exc
    if not math.isfinite(numero):
        raise ErroreCSV(f"Riga {riga}: '{nome_campo}' deve essere un numero finito.")
    minimo = None
    massimo = None
    # I limiti vengono applicati dal chiamante usando la definizione del campo.
    return int(numero) if numero.is_integer() else numero


def _converti(testo: str | None, nome_campo: str, definizione: dict[str, Any], riga: int) -> Any:
    if testo is None:
        testo = ""
    testo = testo.strip()
    tipo = definizione.get("tipo", "testo")
    obbligatorio = bool(definizione.get("obbligatorio", False))
    if testo == "":
        if obbligatorio:
            raise ErroreCSV(f"Riga {riga}: manca il campo obbligatorio '{nome_campo}'.")
        return None
    if tipo == "numero":
        numero = _converti_numero(testo, nome_campo, riga)
        minimo = definizione.get("minimo")
        massimo = definizione.get("massimo")
        if minimo is not None and numero < minimo:
            raise ErroreCSV(f"Riga {riga}: '{nome_campo}' non può essere inferiore a {minimo}.")
        if massimo is not None and numero > massimo:
            raise ErroreCSV(f"Riga {riga}: '{nome_campo}' non può essere superiore a {massimo}.")
        return numero
    if tipo == "booleano":
        valore = testo.casefold()
        if valore in {"true", "1", "si", "sì", "yes"}:
            return True
        if valore in {"false", "0", "no"}:
            return False
        raise ErroreCSV(f"Riga {riga}: '{nome_campo}' deve essere vero/falso.")
    if len(testo) > MAX_CAMPO_TESTO:
        raise ErroreCSV(f"Riga {riga}: '{nome_campo}' supera {MAX_CAMPO_TESTO} caratteri.")
    return testo


def carica_csv_da_bytes(contenuto: bytes) -> list[dict[str, Any]]:
    """Valida completamente un CSV prima di restituire i record.

    Non salva dati e non modifica lo stato applicativo; chi chiama può attivare il
    lotto soltanto dopo il completamento di tutti i controlli.
    """
    if not isinstance(contenuto, bytes):
        raise ErroreCSV("Il file caricato non è un contenuto binario valido.")
    if not contenuto:
        raise ErroreCSV("Il file CSV è vuoto.")
    if len(contenuto) > MAX_BYTES:
        raise ErroreCSV(f"Il file supera il limite di {MAX_BYTES // (1024 * 1024)} MiB.")
    try:
        testo = contenuto.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ErroreCSV("Codifica non valida: salva il file in UTF-8 e riprova.") from exc

    stream = io.StringIO(testo, newline="")
    lettore = csv.DictReader(stream, strict=True)
    intestazioni = lettore.fieldnames
    if not intestazioni:
        raise ErroreCSV("Il CSV deve contenere una riga di intestazione.")
    intestazioni = [str(x).strip() if x is not None else "" for x in intestazioni]
    if len(intestazioni) > MAX_COLONNE:
        raise ErroreCSV(f"Il CSV contiene troppe colonne (massimo {MAX_COLONNE}).")
    if any(not (_HEADER_RE.fullmatch(h) or h == "_irregolare") for h in intestazioni):
        raise ErroreCSV("Il CSV contiene intestazioni vuote o non valide. Usa nomi di campo ASCII senza spazi.")
    if len(set(intestazioni)) != len(intestazioni):
        raise ErroreCSV("Il CSV contiene intestazioni duplicate.")
    lettore.fieldnames = intestazioni
    mancanti = sorted(set(_CAMPI_COMUNI) - set(intestazioni))
    if mancanti:
        raise ErroreCSV("Mancano le colonne obbligatorie: " + ", ".join(mancanti) + ".")

    schema = _schema_globale()
    sconosciuti = sorted(set(intestazioni) - set(schema))
    if sconosciuti:
        raise ErroreCSV("Colonne non riconosciute dal catalogo dei dati: " + ", ".join(sconosciuti) + ". Configura prima il settore o il parametro corrispondente.")

    aziende: list[dict[str, Any]] = []
    identificativi: set[str] = set()
    try:
        for indice, raw in enumerate(lettore, start=2):
            if indice - 1 > MAX_RIGHE:
                raise ErroreCSV(f"Il CSV supera il limite di {MAX_RIGHE} righe dati.")
            if None in raw:
                raise ErroreCSV(f"Riga {indice}: contiene più valori delle colonne dichiarate.")
            settore_raw = str(raw.get("settore", "")).strip().casefold()
            settore_riga = ottieni_settore(settore_raw)
            if settore_riga is None:
                raise ErroreCSV(f"Riga {indice}: settore '{settore_raw}' non configurato o non disponibile per l'analisi.")
            campi_settore = settore_riga.get("campi", {})
            record: dict[str, Any] = {}
            for campo in intestazioni:
                definizione = dict(schema[campo])
                # I campi settoriali sono obbligatori solo per le righe del settore
                # che li utilizza; i CSV a schema largo contengono colonne vuote.
                if campo not in _CAMPI_COMUNI and campo not in _CAMPI_EXTRA and campo not in campi_settore:
                    definizione["obbligatorio"] = False
                elif campo in campi_settore:
                    definizione = dict(campi_settore[campo])
                record[campo] = _converti(raw.get(campo), campo, definizione, indice)
            record["settore"] = settore_raw
            azienda_id = record.get("id")
            if not isinstance(azienda_id, str) or not azienda_id:
                raise ErroreCSV(f"Riga {indice}: identificativo azienda non valido.")
            if azienda_id in identificativi:
                raise ErroreCSV(f"Riga {indice}: identificativo duplicato '{azienda_id}'.")
            identificativi.add(azienda_id)
            settore_id = record.get("settore")
            if record.get("tipo_commessa") not in (None, "") and record["tipo_commessa"] not in {"pubblico", "privato"}:
                raise ErroreCSV(f"Riga {indice}: 'tipo_commessa' deve essere 'pubblico' o 'privato'.")
            settore = ottieni_settore(settore_id)
            if settore is None:
                raise ErroreCSV(f"Riga {indice}: settore '{settore_id}' non configurato o non disponibile per l'analisi.")
            # Validazione legata al modulo dichiarato dal settore, non al nome del settore.
            if "screening_congruita_dm143" in settore.get("moduli", []) and record.get("categoria_opera") not in (None, ""):
                from app.normativa_edilizia import INDICI
                if record["categoria_opera"] not in INDICI:
                    raise ErroreCSV(f"Riga {indice}: 'categoria_opera' non riconosciuta. Usa uno dei codici ufficiali presenti nella guida del progetto.")
            for campo, definizione in settore.get("campi", {}).items():
                if definizione.get("obbligatorio") and record.get(campo) is None:
                    raise ErroreCSV(f"Riga {indice}: per il settore '{settore_id}' è obbligatorio '{campo}'.")
            almeno_uno = settore.get("campi_almeno_uno", [])
            if almeno_uno and not any((_numero_valido(record.get(c)) or 0) > 0 for c in almeno_uno):
                raise ErroreCSV(f"Riga {indice}: per il settore '{settore_id}' almeno uno tra {', '.join(almeno_uno)} deve essere maggiore di zero.")
            aziende.append(record)
    except csv.Error as exc:
        raise ErroreCSV("Struttura CSV non valida: controlla virgolette, separatori e righe incomplete.") from exc
    if not aziende:
        raise ErroreCSV("Il CSV non contiene righe dati.")
    return aziende


def _numero_valido(valore: Any) -> float | None:
    try:
        numero = float(valore)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def carica_csv(percorso: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Compatibilità con il vecchio ingresso da percorso, con limiti identici."""
    try:
        with open(percorso, "rb") as file:
            contenuto = file.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ErroreCSV("Impossibile leggere il file CSV selezionato.") from exc
    return carica_csv_da_bytes(contenuto)


def _proteggi_formula_csv(valore: Any) -> Any:
    if isinstance(valore, str):
        iniziale = valore.lstrip(" \t\r\n")[:1]
        if iniziale in {"=", "+", "-", "@"}:
            return "'" + valore
    return valore


def salva_csv(aziende: list[dict[str, Any]], percorso: str | os.PathLike[str]) -> None:
    if not aziende:
        raise ValueError("Non ci sono record da esportare.")
    if len(aziende) > MAX_RIGHE:
        raise ValueError(f"Il lotto supera il limite di {MAX_RIGHE} righe.")
    chiavi: list[str] = []
    for azienda in aziende:
        for chiave in azienda:
            if chiave != "analisi" and not chiave.startswith("_") and chiave not in chiavi:
                chiavi.append(chiave)
    destinazione = Path(percorso)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    fd, temporaneo = tempfile.mkstemp(prefix=".emersione_csv_", suffix=".tmp", dir=destinazione.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=chiavi, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            for azienda in aziende:
                writer.writerow({k: _proteggi_formula_csv(azienda.get(k)) for k in chiavi})
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporaneo, 0o640)
        os.replace(temporaneo, destinazione)
    finally:
        try:
            if os.path.exists(temporaneo):
                os.unlink(temporaneo)
        except OSError:
            pass


def esporta_csv_bytes(aziende: list[dict[str, Any]], *, includi_analisi: bool = True) -> bytes:
    """Esportazione con protezione dall'iniezione di formule; mai campi interni (prefisso _)."""
    if len(aziende) > MAX_RIGHE:
        raise ValueError(f"Il lotto supera il limite di {MAX_RIGHE} righe.")
    chiavi: list[str] = []
    for azienda in aziende:
        for chiave in azienda:
            if chiave != "analisi" and not chiave.startswith("_") and chiave not in chiavi:
                chiavi.append(chiave)
    extra = ["indice_tecnico", "esito_tecnico", "stato_metodologico", "robustezza", "numero_segnali"] if includi_analisi else []
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(chiavi + extra)
    for azienda in aziende:
        riga = [_proteggi_formula_csv("" if azienda.get(k) is None else azienda.get(k)) for k in chiavi]
        if includi_analisi:
            a = azienda.get("analisi") or {}
            riga += [a.get("punteggio") if a.get("punteggio") is not None else "",
                     a.get("livello", ""), a.get("stato_metodologico", ""),
                     (a.get("robustezza") or {}).get("stato", ""), len(a.get("segnali") or [])]
        writer.writerow(riga)
    return buffer.getvalue().encode("utf-8")
