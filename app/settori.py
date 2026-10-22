"""Registro versionato di settori, parametri e riferimenti documentali.

Le formule usano una piccola DSL dichiarativa: non viene mai eseguito codice
arbitrario contenuto nella configurazione.
"""
from __future__ import annotations

import json
import math
import os
import re
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PERCORSO_REGISTRO = Path(os.environ.get(
    "EMERSIONE_REGISTRO",
    str(Path(__file__).resolve().parents[1] / "config" / "registro_emersione.json"),
))
_LOCK = threading.RLock()
_MAX_NODI_FORMULA = 128
_MAX_PROFONDITA_FORMULA = 16
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Natura del parametro (sezione 7): una soglia tecnica non va mai presentata come obbligo di legge.
NATURE_PARAMETRO = {
    "norma": "Parametro imposto da una norma",
    "statistico": "Parametro statistico derivato da dati ufficiali",
    "stima_tecnica": "Stima tecnica",
    "ipotesi_sperimentale": "Ipotesi sperimentale",
    "soglia_configurabile": "Soglia configurabile",
    "regola_interna": "Regola sviluppata internamente",
}
CAMPI_RIFERIMENTO = ("titolo_documento", "url", "riferimento", "data_pubblicazione", "data_accesso", "periodo_validita",
                     "territorio", "condizioni_uso", "responsabile_verifica")
RIFERIMENTO_OBBLIGATORIO_PER_VALIDARE = ("titolo_documento", "riferimento", "data_accesso", "periodo_validita", "territorio")


def _valida_riferimento(riferimento: Any) -> dict[str, str]:
    if riferimento is None:
        return {}
    if not isinstance(riferimento, dict):
        raise ErroreRegistro("Riferimento alla fonte non valido.")
    out = {}
    for campo in CAMPI_RIFERIMENTO:
        valore = str(riferimento.get(campo, "") or "").strip()
        if len(valore) > 500:
            raise ErroreRegistro(f"Il campo {campo} supera 500 caratteri.")
        if campo in {"data_pubblicazione", "data_accesso"} and valore and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valore):
            raise ErroreRegistro(f"Il campo {campo} deve avere formato AAAA-MM-GG.")
        if campo == "url" and valore:
            from urllib.parse import urlparse
            parsed = urlparse(valore)
            if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
                raise ErroreRegistro("L'URL della fonte deve essere HTTP(S) senza credenziali.")
        out[campo] = valore
    return out


_STATI_PARAMETRO = {"da_verificare", "sperimentale", "verificato", "approvato", "scaduto", "sostituito"}
# Ciclo di vita del settore (sezione 30.11). "sperimentale" è lo stato storico dei
# quattro settori iniziali ed equivale ad "approvata_sperimentazione".
_STATI_SETTORI = {
    "bozza", "in_revisione", "verificata_tecnicamente", "in_validazione_metodologica",
    "in_verifica_normativa", "approvata_sperimentazione", "sperimentale", "approvato",
    "sospeso", "archiviato",
}
STATI_SETTORI = frozenset(_STATI_SETTORI)
# Solo questi stati producono risultati nel lotto operativo; gli altri sono
# eseguibili esclusivamente in collaudo isolato.
STATI_ANALIZZABILI = frozenset({"sperimentale", "approvata_sperimentazione", "approvato"})
STATI_NON_MODIFICABILI = frozenset({"sospeso", "archiviato"})


class ErroreRegistro(ValueError):
    """Configurazione o richiesta di modifica non valida."""


def _numero_finito(valore: Any) -> bool:
    if isinstance(valore, bool) or not isinstance(valore, (int, float)):
        return False
    try:
        return math.isfinite(float(valore))
    except (OverflowError, TypeError, ValueError):
        return False


def _leggi() -> dict[str, Any]:
    try:
        contenuto = PERCORSO_REGISTRO.read_text(encoding="utf-8")
        if len(contenuto.encode("utf-8")) > 2_000_000:
            raise ErroreRegistro("Il registro supera la dimensione massima consentita.")
        dati = json.loads(contenuto)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Registro settori assente: {PERCORSO_REGISTRO}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Il registro settori/parametri contiene JSON non valido.") from exc
    if not isinstance(dati, dict) or dati.get("versione") != 1:
        raise RuntimeError("Versione o struttura del registro settori non supportata.")
    if not isinstance(dati.get("parametri"), dict) or not isinstance(dati.get("settori"), dict):
        raise RuntimeError("Registro settori/parametri incompleto.")
    if not isinstance(dati.setdefault("documenti", []), list):
        raise RuntimeError("Registro documentale non valido.")
    if not isinstance(dati.setdefault("relazioni", []), list):
        raise RuntimeError("Registro delle relazioni non valido.")
    return dati


def _scrivi_atomico(dati: dict[str, Any], *, autore: str = "sistema", motivo: str = "modifica del registro") -> None:
    """Salva l'intero registro con sostituzione atomica e permessi restrittivi.

    Prima della sostituzione la nuova versione viene registrata nello storico
    completo (app.versioni_registro): nessuna configurazione diventa attiva senza
    essere ricostruibile. Se lo storico non è scrivibile, il registro non cambia.
    """
    from app import versioni_registro
    if not versioni_registro.elenco(1) and PERCORSO_REGISTRO.exists():
        try:
            versioni_registro.registra(json.loads(PERCORSO_REGISTRO.read_text(encoding="utf-8")),
                                       autore="sistema", motivo="versione iniziale")
        except (OSError, json.JSONDecodeError):
            pass
    versioni_registro.registra(dati, autore=autore, motivo=motivo)
    PERCORSO_REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dati, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    fd, temporaneo = tempfile.mkstemp(prefix=".registro_emersione_", suffix=".tmp", dir=PERCORSO_REGISTRO.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporaneo, 0o640)
        os.replace(temporaneo, PERCORSO_REGISTRO)
        try:
            dir_fd = os.open(PERCORSO_REGISTRO.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        try:
            if os.path.exists(temporaneo):
                os.unlink(temporaneo)
        except OSError:
            pass


def lista_settori(includi_archiviati: bool = False) -> list[dict[str, Any]]:
    with _LOCK:
        settori = _leggi()["settori"]
        return [
            {"id": sid, **config}
            for sid, config in sorted(settori.items(), key=lambda item: item[1].get("nome", item[0]).casefold())
            if includi_archiviati or config.get("stato") != "archiviato"
        ]


def ottieni_settore(settore_id: str, solo_attivo: bool = False) -> dict[str, Any] | None:
    if not isinstance(settore_id, str):
        return None
    with _LOCK:
        settore = _leggi()["settori"].get(settore_id)
        if settore is None or settore.get("stato") in {"sospeso", "archiviato", "bozza"}:
            if settore is None or solo_attivo or settore.get("stato") in {"sospeso", "archiviato", "bozza"}:
                return None
        if solo_attivo and settore.get("stato") != "approvato":
            return None
        return dict(settore)


def configurazione_settore(settore_id: str) -> dict[str, Any] | None:
    """Configurazione del settore in qualunque stato (per gestione, collaudo e audit)."""
    if not isinstance(settore_id, str):
        return None
    with _LOCK:
        settore = _leggi()["settori"].get(settore_id)
        return json.loads(json.dumps(settore)) if isinstance(settore, dict) else None


def leggi_registro() -> dict[str, Any]:
    """Copia completa del registro (sola lettura)."""
    with _LOCK:
        return json.loads(json.dumps(_leggi()))


def salva_registro(dati: dict[str, Any], *, autore: str, motivo: str) -> None:
    """Sostituzione atomica del registro con registrazione nello storico (uso interno ai moduli di gestione)."""
    with _LOCK:
        _scrivi_atomico(dati, autore=autore, motivo=motivo)


def catalogo_parametri() -> dict[str, dict[str, Any]]:
    with _LOCK:
        return json.loads(json.dumps(_leggi()["parametri"]))


def lista_parametri() -> list[dict[str, Any]]:
    params = catalogo_parametri()
    return [{"id": pid, **p} for pid, p in sorted(params.items(), key=lambda item: item[1].get("nome", item[0]).casefold())]


def _valore_parametro(parametri: dict[str, Any], parametro_id: str, utilizzati: dict[str, dict[str, Any]]) -> float:
    parametro = parametri.get(parametro_id)
    if not isinstance(parametro, dict):
        raise ErroreRegistro(f"Parametro non definito: {parametro_id}")
    valore = parametro.get("valore")
    if isinstance(valore, bool) or not isinstance(valore, (int, float)) or not math.isfinite(float(valore)):
        raise ErroreRegistro(f"Valore non numerico o non finito per il parametro {parametro_id}.")
    utilizzati[parametro_id] = parametro
    return float(valore)


def valuta_formula(espressione: Any, record: dict[str, Any], parametri: dict[str, Any] | None = None) -> tuple[float, list[dict[str, Any]]]:
    """Valuta una formula dichiarativa limitata; niente eval/exec."""
    if parametri is None:
        parametri = catalogo_parametri()
    utilizzati: dict[str, dict[str, Any]] = {}
    contatore = [0]

    def calcola(expr: Any, profondita: int = 0) -> float:
        contatore[0] += 1
        if contatore[0] > _MAX_NODI_FORMULA or profondita > _MAX_PROFONDITA_FORMULA:
            raise ErroreRegistro("Formula troppo complessa.")
        if not isinstance(expr, dict):
            raise ErroreRegistro("Nodo formula non valido.")
        op = expr.get("op")
        if op == "campo":
            nome = expr.get("nome")
            if not isinstance(nome, str) or not _FIELD_RE.fullmatch(nome):
                raise ErroreRegistro("Riferimento a campo non valido nella formula.")
            valore = record.get(nome, expr.get("default"))
            if valore is None or valore == "":
                raise ErroreRegistro(f"Dato necessario mancante: {nome}")
            try:
                numero = float(valore)
            except (TypeError, ValueError) as exc:
                raise ErroreRegistro(f"Il campo {nome} non contiene un numero valido.") from exc
            if not math.isfinite(numero):
                raise ErroreRegistro(f"Il campo {nome} non contiene un numero finito.")
            return numero
        if op == "coefficiente":
            pid = expr.get("id")
            if not isinstance(pid, str) or not _ID_RE.fullmatch(pid):
                raise ErroreRegistro("Identificativo parametro non valido nella formula.")
            return _valore_parametro(parametri, pid, utilizzati)
        if op == "lookup_coefficiente":
            campo = expr.get("campo")
            if not isinstance(campo, str) or not _FIELD_RE.fullmatch(campo):
                raise ErroreRegistro("Campo di lookup non valido.")
            mappa = expr.get("mappa")
            if not isinstance(mappa, dict) or len(mappa) > 500:
                raise ErroreRegistro("Mappa di lookup non valida.")
            chiave = str(record.get(campo, "generico") or "generico").strip().casefold()
            pid = mappa.get(chiave, expr.get("predefinito"))
            if not isinstance(pid, str) or not _ID_RE.fullmatch(pid):
                raise ErroreRegistro("Parametro predefinito del lookup non valido.")
            return _valore_parametro(parametri, pid, utilizzati)
        if op in {"somma", "moltiplica"}:
            elementi = expr.get("elementi")
            if not isinstance(elementi, list) or not 1 <= len(elementi) <= 32:
                raise ErroreRegistro(f"Operazione {op} non valida.")
            valori = [calcola(x, profondita + 1) for x in elementi]
            risultato = sum(valori) if op == "somma" else math.prod(valori)
        elif op == "dividi":
            sinistra = calcola(expr.get("sinistra"), profondita + 1)
            destra = calcola(expr.get("destra"), profondita + 1)
            if destra == 0:
                raise ErroreRegistro("Divisione per zero nella formula.")
            risultato = sinistra / destra
        elif op == "costante":
            valore = expr.get("valore")
            if isinstance(valore, bool) or not isinstance(valore, (int, float)):
                raise ErroreRegistro("Costante numerica non valida.")
            risultato = float(valore)
        else:
            raise ErroreRegistro(f"Operazione formula non supportata: {op!r}")
        if not math.isfinite(risultato):
            raise ErroreRegistro("La formula produce un valore non finito.")
        return risultato

    risultato = calcola(espressione)
    if risultato < 0:
        raise ErroreRegistro("La formula produce un risultato negativo non valido.")
    dettaglio = [{"id": pid, **parametro} for pid, parametro in utilizzati.items()]
    return risultato, dettaglio


def descrizione_formula(espressione: Any, parametri: dict[str, Any] | None = None) -> str:
    """Descrive la formula senza eseguirla."""
    if parametri is None:
        parametri = catalogo_parametri()
    if not isinstance(espressione, dict):
        return "formula non descrivibile"
    op = espressione.get("op")
    if op == "campo":
        return str(espressione.get("nome", "campo"))
    if op == "coefficiente":
        pid = espressione.get("id", "?")
        return str(parametri.get(pid, {}).get("nome", pid))
    if op == "lookup_coefficiente":
        campo = espressione.get("campo", "campo")
        return f"coefficiente selezionato in base a {campo}"
    if op == "costante":
        return str(espressione.get("valore", "?"))
    if op in {"somma", "moltiplica"}:
        simbolo = " + " if op == "somma" else " × "
        return "(" + simbolo.join(descrizione_formula(x, parametri) for x in espressione.get("elementi", [])) + ")"
    if op == "dividi":
        return f"({descrizione_formula(espressione.get('sinistra'), parametri)} / {descrizione_formula(espressione.get('destra'), parametri)})"
    return "formula non descrivibile"


def _slug(testo: str) -> str:
    valore = testo.strip().casefold()
    valore = valore.replace("à", "a").replace("è", "e").replace("é", "e").replace("ì", "i").replace("ò", "o").replace("ù", "u")
    valore = re.sub(r"[^a-z0-9]+", "_", valore).strip("_")
    if not _ID_RE.fullmatch(valore) or len(valore) > 50:
        raise ErroreRegistro("Nome settore non valido: usa 2-50 caratteri alfanumerici e parole separate da spazi.")
    return valore


def crea_settore_semplice(*, nome: str, descrizione: str, campo: str, etichetta_campo: str,
                           unita_campo: str, metodo: str, valore_coefficiente: float,
                           nome_coefficiente: str, unita_coefficiente: str, fonte: str,
                           riferimento_url: str = "", autore: str = "sconosciuto",
                           dimensione_campo: dict[str, int] | None = None,
                           dimensione_coefficiente: dict[str, int] | None = None) -> str:
    """Crea un settore sperimentale configurabile senza codice eseguibile."""
    settore_id = _slug(nome)
    if not isinstance(descrizione, str) or not descrizione.strip() or len(descrizione) > 500:
        raise ErroreRegistro("Inserisci una descrizione di massimo 500 caratteri.")
    if not isinstance(campo, str) or not _FIELD_RE.fullmatch(campo):
        raise ErroreRegistro("Il nome del campo deve essere in formato snake_case e contenere solo lettere ASCII, numeri e underscore.")
    campi_riservati = {"id", "settore", "dipendenti_dichiarati", "costo_lavoro_per_addetto", "analisi", "ragione_sociale", "citta"}
    if campo in campi_riservati:
        raise ErroreRegistro("Il nome del campo è riservato al sistema.")
    if metodo not in {"ore_per_unita", "unita_per_addetto"}:
        raise ErroreRegistro("Metodo di stima non supportato.")
    try:
        coeff = float(valore_coefficiente)
    except (TypeError, ValueError) as exc:
        raise ErroreRegistro("Il coefficiente deve essere numerico.") from exc
    if not math.isfinite(coeff) or coeff <= 0 or coeff > 1e12:
        raise ErroreRegistro("Il coefficiente deve essere finito, maggiore di zero e non eccessivo.")
    if not nome.strip() or len(nome.strip()) > 80 or not etichetta_campo.strip() or len(etichetta_campo) > 100:
        raise ErroreRegistro("Nome settore o etichetta del campo non validi.")
    if not unita_campo.strip() or len(unita_campo) > 40 or not unita_coefficiente.strip() or len(unita_coefficiente) > 60:
        raise ErroreRegistro("Le unità di misura sono obbligatorie e devono essere brevi.")
    if not fonte.strip() or len(fonte.strip()) > 300:
        raise ErroreRegistro("La fonte o motivazione del coefficiente è obbligatoria.")
    if riferimento_url:
        from urllib.parse import urlparse
        parsed = urlparse(riferimento_url.strip())
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password:
            raise ErroreRegistro("Il riferimento deve essere un URL HTTP(S) valido, senza credenziali incorporate.")
        riferimento_url = riferimento_url.strip()
    parametro_id = f"custom_{settore_id}_coeff"
    with _LOCK:
        dati = _leggi()
        if settore_id in dati["settori"]:
            raise ErroreRegistro("Esiste già un settore con questo identificativo.")
        if parametro_id in dati["parametri"]:
            raise ErroreRegistro("Esiste già un parametro con questo identificativo.")
        param = {
            "nome": nome_coefficiente.strip(), "valore": coeff, "unita": unita_coefficiente.strip(),
            "fonte": fonte.strip(), "stato": "da_verificare", "tipo": "coefficiente",
            "ambito": settore_id, "descrizione": "Parametro personalizzato: verificare fonte, unità e applicabilità prima di qualsiasi utilizzo operativo.",
            "natura": "ipotesi_sperimentale", "riferimento_fonte": {c: "" for c in CAMPI_RIFERIMENTO},
        }
        if dimensione_coefficiente is not None:
            from app.unita import ErroreDimensione, valida_dimensione
            try:
                param["dimensione"] = valida_dimensione(dimensione_coefficiente)
            except ErroreDimensione as exc:
                raise ErroreRegistro(str(exc)) from exc
        dati["parametri"][parametro_id] = param
        if metodo == "ore_per_unita":
            formula = {"op": "dividi", "sinistra": {"op": "moltiplica", "elementi": [{"op": "campo", "nome": campo}, {"op": "coefficiente", "id": parametro_id}]}, "destra": {"op": "coefficiente", "id": "ore_annue_addetto"}}
        else:
            formula = {"op": "dividi", "sinistra": {"op": "campo", "nome": campo}, "destra": {"op": "coefficiente", "id": parametro_id}}
        dati["settori"][settore_id] = {
            "nome": nome.strip(), "descrizione": descrizione.strip(), "stato": "bozza",
            "controlli": [], "moduli": [],
            "campi": {campo: {"etichetta": etichetta_campo.strip(), "tipo": "numero", "obbligatorio": True, "unita": unita_campo.strip(), "minimo": 0}},
            "stima": formula, "campi_almeno_uno": [], "richiede_validazione": True,
            "versione_configurazione": 1,
            "metadati": {"creato_da_configurazione": True, "metodo": metodo},
            "creato_da": (autore or "sconosciuto")[:100],
            "creato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if riferimento_url:
            dati.setdefault("documenti", []).append({
                "id": f"ref_{settore_id}", "titolo": nome_coefficiente.strip(),
                "descrizione": "Riferimento dichiarato durante la creazione del settore.",
                "url_fonte": riferimento_url, "settore": settore_id, "parametro": parametro_id,
                "stato": "da_verificare", "estrazione": "non_eseguita", "tipo": "riferimento_esterno",
                "nota": "Riferimento registrato: il contenuto non è stato acquisito né verificato automaticamente.",
            })
        if dimensione_campo is not None:
            from app.unita import ErroreDimensione, valida_dimensione
            try:
                dati["settori"][settore_id]["campi"][campo]["dimensione"] = valida_dimensione(dimensione_campo)
            except ErroreDimensione as exc:
                raise ErroreRegistro(str(exc)) from exc
        # Validazione preventiva della formula contro il catalogo aggiornato.
        valuta_formula(formula, {campo: 1.0}, dati["parametri"])
        _scrivi_atomico(dati, autore=autore, motivo=f"Creazione del settore {settore_id} in bozza")
    return settore_id


def lista_documenti() -> list[dict[str, Any]]:
    with _LOCK:
        return json.loads(json.dumps(_leggi().get("documenti", [])))


def ottieni_documento(documento_id: str) -> dict[str, Any] | None:
    if not isinstance(documento_id, str):
        return None
    with _LOCK:
        for documento in _leggi().get("documenti", []):
            if documento.get("id") == documento_id:
                return dict(documento)
    return None


def registra_documento(documento: dict[str, Any]) -> None:
    """Registra metadati e relazioni in una sostituzione atomica del registro."""
    if not isinstance(documento, dict) or not isinstance(documento.get("id"), str):
        raise ErroreRegistro("Metadati documento non validi.")
    with _LOCK:
        dati = _leggi()
        if any(x.get("id") == documento["id"] for x in dati.get("documenti", [])):
            raise ErroreRegistro("Identificativo documento duplicato.")
        settore_id = documento.get("settore")
        if settore_id and settore_id not in dati["settori"]:
            raise ErroreRegistro("Il settore associato al documento non esiste.")
        parametro_id = documento.get("parametro")
        if parametro_id and parametro_id not in dati["parametri"]:
            raise ErroreRegistro("Il parametro associato al documento non esiste.")
        if parametro_id and settore_id:
            ambito = dati["parametri"][parametro_id].get("ambito")
            if ambito not in {settore_id, "trasversale"}:
                raise ErroreRegistro("Il parametro selezionato non appartiene al settore indicato.")
        dati.setdefault("documenti", []).append(documento)
        _scrivi_atomico(dati)

def crea_parametro(*, nome: str, valore: Any, unita: str, fonte: str,
                   ambito: str = "trasversale", descrizione: str = "",
                   autore: str = "sconosciuto", natura: str = "ipotesi_sperimentale") -> str:
    """Aggiunge un parametro numerico non validato, riutilizzabile nelle formule dichiarative."""
    parametro_nome = nome.strip() if isinstance(nome, str) else ""
    if not parametro_nome or len(parametro_nome) > 100:
        raise ErroreRegistro("Il nome del parametro è obbligatorio e deve contenere al massimo 100 caratteri.")
    if not isinstance(unita, str) or not unita.strip() or len(unita) > 60:
        raise ErroreRegistro("L'unità di misura è obbligatoria e deve contenere al massimo 60 caratteri.")
    if not isinstance(fonte, str) or not fonte.strip() or len(fonte) > 500:
        raise ErroreRegistro("La fonte o motivazione provvisoria è obbligatoria e deve contenere al massimo 500 caratteri.")
    if not isinstance(descrizione, str) or len(descrizione) > 500:
        raise ErroreRegistro("La descrizione non può superare 500 caratteri.")
    try:
        numero = float(valore)
    except (TypeError, ValueError) as exc:
        raise ErroreRegistro("Il valore del parametro deve essere numerico.") from exc
    if not math.isfinite(numero) or abs(numero) > 1e12:
        raise ErroreRegistro("Il valore deve essere finito e compreso tra -10^12 e 10^12.")
    if not isinstance(ambito, str) or not ambito.strip():
        raise ErroreRegistro("L'ambito del parametro non è valido.")
    parametro_id = f"custom_param_{_slug(parametro_nome)}"
    with _LOCK:
        dati = _leggi()
        if ambito != "trasversale" and ambito not in dati["settori"]:
            raise ErroreRegistro("Il settore selezionato per il parametro non esiste.")
        if parametro_id in dati["parametri"]:
            raise ErroreRegistro("Esiste già un parametro con questo identificativo; scegli un nome distinto.")
        dati["parametri"][parametro_id] = {
            "nome": parametro_nome,
            "valore": numero,
            "unita": unita.strip(),
            "fonte": fonte.strip(),
            "stato": "da_verificare",
            "tipo": "parametro_numerico",
            "ambito": ambito,
            "descrizione": descrizione.strip() or "Parametro aggiunto manualmente; verificare definizione, fonte, unità e applicabilità.",
            "versione": 1,
            "creato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "creato_da": (autore or "sconosciuto")[:100],
            "natura": natura if natura in NATURE_PARAMETRO else "ipotesi_sperimentale",
            "riferimento_fonte": {c: "" for c in CAMPI_RIFERIMENTO},
        }
        _scrivi_atomico(dati)
    return parametro_id


def _snapshot_parametro(parametro: dict[str, Any], *, autore: str, motivo: str) -> int:
    """Conserva un'istantanea del parametro prima di ogni modifica."""
    try:
        versione = int(parametro.get("versione", 1))
    except (TypeError, ValueError):
        versione = 1
    fotografia = {
        chiave: valore for chiave, valore in parametro.items()
        if chiave not in {"storico_versioni", "aggiornato_il", "aggiornato_da"}
    }
    storico = parametro.setdefault("storico_versioni", [])
    storico.append({
        "versione_precedente": versione,
        "registrata_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "autore": (autore or "sconosciuto")[:100],
        "motivo": motivo[:200],
        "valori_precedenti": fotografia,
    })
    parametro["storico_versioni"] = storico[-20:]
    parametro["versione"] = versione + 1
    parametro["aggiornato_il"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parametro["aggiornato_da"] = (autore or "sconosciuto")[:100]
    return versione + 1


def aggiorna_parametro(*, parametro_id: str, nome: str, valore: Any, unita: str,
                       fonte: str, descrizione: str = "", stato: str = "da_verificare",
                       documento_validazione: str = "", nota_validazione: str = "",
                       autore: str = "sconosciuto", natura: str | None = None,
                       riferimento_fonte: dict[str, Any] | None = None) -> int:
    """Versiona un parametro e registra evidenza/revisore per gli stati verificati."""
    if not isinstance(parametro_id, str) or not _ID_RE.fullmatch(parametro_id):
        raise ErroreRegistro("Identificativo parametro non valido.")
    nome = nome.strip() if isinstance(nome, str) else ""
    unita = unita.strip() if isinstance(unita, str) else ""
    fonte = fonte.strip() if isinstance(fonte, str) else ""
    descrizione = descrizione.strip() if isinstance(descrizione, str) else ""
    documento_validazione = documento_validazione.strip() if isinstance(documento_validazione, str) else ""
    nota_validazione = nota_validazione.strip() if isinstance(nota_validazione, str) else ""
    if not nome or len(nome) > 100:
        raise ErroreRegistro("Il nome del parametro è obbligatorio e deve avere al massimo 100 caratteri.")
    if not unita or len(unita) > 60:
        raise ErroreRegistro("L'unità di misura è obbligatoria e deve avere al massimo 60 caratteri.")
    if not fonte or len(fonte) > 500 or len(descrizione) > 500:
        raise ErroreRegistro("Fonte o descrizione non valida.")
    try:
        numero = float(valore)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ErroreRegistro("Il valore del parametro deve essere numerico.") from exc
    if not math.isfinite(numero) or abs(numero) > 1e12:
        raise ErroreRegistro("Il valore deve essere finito e compreso tra -10^12 e 10^12.")
    if stato not in _STATI_PARAMETRO:
        raise ErroreRegistro("Stato del parametro non supportato.")
    if len(nota_validazione) > 1000:
        raise ErroreRegistro("La nota di validazione supera 1000 caratteri.")
    if natura is not None and natura not in NATURE_PARAMETRO:
        raise ErroreRegistro("Natura del parametro non riconosciuta.")
    riferimento_nuovo = _valida_riferimento(riferimento_fonte)

    with _LOCK:
        dati = _leggi()
        parametro = dati["parametri"].get(parametro_id)
        if not isinstance(parametro, dict):
            raise ErroreRegistro("Parametro non trovato.")
        attuali = {
            "nome": parametro.get("nome"),
            "valore": parametro.get("valore"),
            "unita": parametro.get("unita"),
            "fonte": parametro.get("fonte"),
            "descrizione": parametro.get("descrizione", ""),
        }
        richiesti = {"nome": nome, "valore": numero, "unita": unita, "fonte": fonte, "descrizione": descrizione}
        modifiche_tecniche = any(attuali.get(chiave) != valore_nuovo for chiave, valore_nuovo in richiesti.items())
        if modifiche_tecniche and stato in {"verificato", "approvato"}:
            raise ErroreRegistro(
                "La modifica di valore o definizione crea una nuova revisione: salva prima il parametro come 'da_verificare' o 'sperimentale', quindi avvia una verifica separata."
            )

        natura_finale = natura if natura is not None else parametro.get("natura", "ipotesi_sperimentale")
        riferimento_finale = riferimento_nuovo if riferimento_fonte is not None else dict(parametro.get("riferimento_fonte") or {})
        riferimento_documento = None
        if stato in {"verificato", "approvato"}:
            mancanti = [c for c in RIFERIMENTO_OBBLIGATORIO_PER_VALIDARE if not str(riferimento_finale.get(c, "")).strip()]
            if mancanti:
                raise ErroreRegistro("Per verificare/approvare il parametro completa il riferimento alla fonte: " + ", ".join(mancanti) + ".")
            doc_id = documento_validazione
            nota = nota_validazione
            if fonte.casefold() in {"fonte da verificare", "da verificare", "non disponibile", "sconosciuta"}:
                raise ErroreRegistro("Non puoi verificare/approvare un parametro lasciando la fonte come segnaposto.")
            if not doc_id or not nota or len(nota) < 20:
                raise ErroreRegistro("Per verificare/approvare occorrono un documento registrato e una nota motivata di almeno 20 caratteri.")
            riferimento_documento = next((
                d for d in dati.get("documenti", [])
                if isinstance(d, dict) and d.get("id") == doc_id
            ), None)
            if riferimento_documento is None or not riferimento_documento.get("file_key") or not riferimento_documento.get("sha256"):
                raise ErroreRegistro("La validazione richiede un documento caricato, conservato e identificato tramite SHA-256.")
            relazione_documentale = (
                riferimento_documento.get("parametro") == parametro_id
                or any(
                    isinstance(r, dict)
                    and r.get("sorgente_tipo") == "documento"
                    and r.get("sorgente_id") == doc_id
                    and r.get("destinazione_tipo") == "parametro"
                    and r.get("destinazione_id") == parametro_id
                    and r.get("tipo") in {"supporta", "definisce", "deriva_da", "documenta", "integra"}
                    for r in dati.get("relazioni", [])
                )
            )
            if not relazione_documentale:
                raise ErroreRegistro("Il documento deve essere associato al parametro o collegato da una relazione documentale esplicita.")

        nuovo_stato = stato
        campi_nuovi = {**richiesti, "stato": nuovo_stato}
        modifiche = any(parametro.get(k) != v for k, v in campi_nuovi.items())
        modifiche = modifiche or parametro.get("natura") != natura_finale or (parametro.get("riferimento_fonte") or {}) != riferimento_finale
        if stato in {"verificato", "approvato"}:
            modifiche = modifiche or parametro.get("documento_validazione") != documento_validazione
            modifiche = modifiche or parametro.get("nota_validazione") != nota_validazione.strip()
        if not modifiche:
            raise ErroreRegistro("Non è stata indicata alcuna modifica.")

        motivo = "Aggiornamento del parametro" if modifiche_tecniche else f"Cambio stato in {stato}"
        versione = _snapshot_parametro(parametro, autore=autore, motivo=motivo)
        parametro.update(richiesti)
        parametro["stato"] = nuovo_stato
        parametro["natura"] = natura_finale
        parametro["riferimento_fonte"] = riferimento_finale
        if nuovo_stato in {"verificato", "approvato"}:
            parametro["documento_validazione"] = documento_validazione.strip()
            parametro["nota_validazione"] = nota_validazione.strip()
            parametro["validato_da"] = (autore or "sconosciuto")[:100]
            parametro["validato_il"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        else:
            for chiave in ("documento_validazione", "nota_validazione", "validato_da", "validato_il"):
                parametro.pop(chiave, None)
        riaperti: list[str] = []
        if modifiche_tecniche:
            # Una modifica di valore/definizione non deve alterare in silenzio i
            # risultati: i settori che ne dipendono tornano in revisione (sez. 30.4, 30.9).
            for sid, cfg in dati["settori"].items():
                if cfg.get("stato") in STATI_ANALIZZABILI | {"verificata_tecnicamente", "in_validazione_metodologica", "in_verifica_normativa"} \
                        and parametro_id in parametri_usati_da_settore(cfg):
                    cfg["stato"] = "in_revisione"
                    cfg["motivo_revisione"] = f"Parametro {parametro_id} modificato alla versione {versione}"
                    riaperti.append(sid)
        _scrivi_atomico(dati, autore=autore, motivo=f"{motivo}: {parametro_id}" + (f"; settori riaperti: {', '.join(riaperti)}" if riaperti else ""))
        return versione


PARAMETRI_MOTORE = frozenset({"scarto_manodopera_attenzione", "scarto_manodopera_grave", "costo_addetto_scarto"})


def parametri_usati_da_settore(settore: dict[str, Any]) -> set[str]:
    """Parametri referenziati da formula, lookup e controlli del settore, più le soglie del motore."""
    usati: set[str] = set(PARAMETRI_MOTORE)

    def visita(nodo: Any) -> None:
        if not isinstance(nodo, dict):
            return
        op = nodo.get("op")
        if op == "coefficiente" and isinstance(nodo.get("id"), str):
            usati.add(nodo["id"])
        elif op == "lookup_coefficiente":
            for pid in [nodo.get("predefinito"), *dict(nodo.get("mappa") or {}).values()]:
                if isinstance(pid, str):
                    usati.add(pid)
        for figlio in nodo.get("elementi", []) or []:
            visita(figlio)
        visita(nodo.get("sinistra"))
        visita(nodo.get("destra"))

    visita(settore.get("stima"))
    for controllo in settore.get("controlli", []) or []:
        if isinstance(controllo, dict) and isinstance(controllo.get("coefficiente"), str):
            usati.add(controllo["coefficiente"])
    return usati


def _snapshot_settore(settore: dict[str, Any], *, autore: str, motivo: str) -> None:
    """Registra la versione precedente prima di una modifica metodologica."""
    versione = settore.get("versione_configurazione", 1)
    try:
        versione = int(versione)
    except (TypeError, ValueError):
        versione = 1
    fotografia = {
        chiave: valore for chiave, valore in settore.items()
        if chiave not in {"storico_configurazioni", "aggiornato_il", "aggiornato_da"}
    }
    storico = settore.setdefault("storico_configurazioni", [])
    storico.append({
        "versione_precedente": versione,
        "registrata_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "autore": (autore or "sconosciuto")[:100],
        "motivo": motivo[:200],
        "configurazione_precedente": fotografia,
    })
    # Limita la dimensione del registro per non far crescere indefinitamente il JSON.
    settore["storico_configurazioni"] = storico[-20:]
    settore["versione_configurazione"] = versione + 1
    settore["aggiornato_il"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    settore["aggiornato_da"] = (autore or "sconosciuto")[:100]
    # Una modifica tecnica riapre la verifica: non conserva mai uno stato approvato.
    # Una bozza resta bozza finché non viene sottoposta a revisione.
    if settore.get("stato") != "bozza":
        settore["stato"] = "in_revisione"


def aggiungi_campo_settore(*, settore_id: str, campo: str, etichetta: str,
                           unita: str, obbligatorio: bool = True,
                           minimo: Any = None, massimo: Any = None,
                           autore: str = "sconosciuto") -> str:
    """Aggiunge un campo numerico a un settore e riapre la revisione metodologica."""
    if not isinstance(settore_id, str) or not _ID_RE.fullmatch(settore_id):
        raise ErroreRegistro("Identificativo settore non valido.")
    if not isinstance(campo, str) or not _FIELD_RE.fullmatch(campo):
        raise ErroreRegistro("Il nome del campo deve usare snake_case ASCII.")
    campi_riservati = {
        "id", "settore", "dipendenti_dichiarati", "costo_lavoro_per_addetto",
        "analisi", "ragione_sociale", "citta", "dpi_acquistati", "valore_opera",
        "costo_manodopera_dichiarato", "_irregolare",
    }
    if campo in campi_riservati:
        raise ErroreRegistro("Il nome del campo è riservato al sistema.")
    if not isinstance(etichetta, str) or not etichetta.strip() or len(etichetta) > 100:
        raise ErroreRegistro("L'etichetta è obbligatoria e deve avere al massimo 100 caratteri.")
    if not isinstance(unita, str) or not unita.strip() or len(unita) > 60:
        raise ErroreRegistro("L'unità di misura è obbligatoria e deve avere al massimo 60 caratteri.")
    if not isinstance(obbligatorio, bool):
        raise ErroreRegistro("Il flag del campo obbligatorio non è valido.")
    def limite_numero(valore: Any, nome: str) -> float | None:
        if valore is None or valore == "":
            return None
        try:
            numero = float(valore)
        except (TypeError, ValueError) as exc:
            raise ErroreRegistro(f"Il limite {nome} deve essere numerico.") from exc
        if not math.isfinite(numero) or abs(numero) > 1e12:
            raise ErroreRegistro(f"Il limite {nome} non è valido.")
        return numero
    minimo_num = limite_numero(minimo, "minimo")
    massimo_num = limite_numero(massimo, "massimo")
    if minimo_num is not None and massimo_num is not None and minimo_num > massimo_num:
        raise ErroreRegistro("Il valore minimo non può superare il massimo.")
    with _LOCK:
        dati = _leggi()
        settore = dati["settori"].get(settore_id)
        if settore is None or settore.get("stato") in STATI_NON_MODIFICABILI:
            raise ErroreRegistro("Il settore non esiste o non può essere modificato nello stato corrente.")
        campi = settore.setdefault("campi", {})
        if campo in campi:
            raise ErroreRegistro("Il campo esiste già nel settore.")
        _snapshot_settore(settore, autore=autore, motivo=f"Aggiunta del campo {campo}")
        definizione = {
            "etichetta": etichetta.strip(), "tipo": "numero", "obbligatorio": obbligatorio,
            "unita": unita.strip(),
        }
        if minimo_num is not None:
            definizione["minimo"] = minimo_num
        if massimo_num is not None:
            definizione["massimo"] = massimo_num
        campi[campo] = definizione
        _scrivi_atomico(dati)
    return campo


def valida_formula_settore(settore_id: str, formula: Any, *, registro: dict[str, Any] | None = None) -> dict[str, Any]:
    """Valida staticamente una formula DSL e la restituisce in forma JSON sicura."""
    try:
        serializzata = json.dumps(formula, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(serializzata.encode("utf-8")) > 16_384:
            raise ErroreRegistro("La formula supera la dimensione massima di 16 KiB.")
        formula_canonica = json.loads(serializzata)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, ErroreRegistro):
            raise
        raise ErroreRegistro("La formula deve essere JSON valido, non eccessivamente annidato e con valori numerici finiti.") from exc

    with _LOCK:
        dati = registro if registro is not None else _leggi()
        settore = dati["settori"].get(settore_id)
        if settore is None or (registro is None and settore.get("stato") in STATI_NON_MODIFICABILI):
            raise ErroreRegistro("Il settore non esiste o non può essere configurato nello stato corrente.")
        campi = settore.get("campi", {})
        parametri = dati["parametri"]

    visitati = [0]
    def controlla(nodo: Any, profondita: int = 0) -> None:
        visitati[0] += 1
        if visitati[0] > _MAX_NODI_FORMULA or profondita > _MAX_PROFONDITA_FORMULA:
            raise ErroreRegistro("Formula troppo complessa: supera i limiti di nodi o profondità.")
        if not isinstance(nodo, dict) or not isinstance(nodo.get("op"), str):
            raise ErroreRegistro("Ogni elemento della formula deve essere un oggetto con operazione dichiarata.")
        op = nodo["op"]
        if op == "campo":
            if set(nodo) - {"op", "nome", "default"} or not isinstance(nodo.get("nome"), str):
                raise ErroreRegistro("Riferimento a campo malformato.")
            nome_campo = nodo["nome"]
            definizione = campi.get(nome_campo)
            if not isinstance(definizione, dict) or definizione.get("tipo") != "numero":
                raise ErroreRegistro(f"Il campo '{nome_campo}' non è un campo numerico configurato per questo settore.")
            if "default" in nodo:
                valore_default = nodo["default"]
                if not _numero_finito(valore_default):
                    raise ErroreRegistro(f"Valore predefinito non valido per il campo '{nome_campo}'.")
            return
        if op == "coefficiente":
            if set(nodo) != {"op", "id"} or not isinstance(nodo.get("id"), str):
                raise ErroreRegistro("Riferimento a parametro malformato.")
            pid = nodo["id"]
            parametro = parametri.get(pid)
            if not _ID_RE.fullmatch(pid) or not isinstance(parametro, dict):
                raise ErroreRegistro(f"Parametro non configurato: {pid}.")
            if parametro.get("ambito") not in {settore_id, "trasversale"}:
                raise ErroreRegistro(f"Il parametro '{pid}' appartiene a un ambito diverso dal settore.")
            return
        if op == "lookup_coefficiente":
            if set(nodo) != {"op", "campo", "mappa", "predefinito"}:
                raise ErroreRegistro("Lookup malformato: sono richiesti campo, mappa e parametro predefinito.")
            nome_campo = nodo.get("campo")
            if not isinstance(nome_campo, str) or nome_campo not in campi:
                raise ErroreRegistro("Il campo di lookup non appartiene al settore configurato.")
            mappa = nodo.get("mappa")
            if not isinstance(mappa, dict) or len(mappa) > 500:
                raise ErroreRegistro("La mappa di lookup deve contenere al massimo 500 voci.")
            def controlla_pid(pid: Any) -> None:
                if not isinstance(pid, str) or not _ID_RE.fullmatch(pid):
                    raise ErroreRegistro("La mappa di lookup contiene un parametro non valido.")
                parametro = parametri.get(pid)
                if not isinstance(parametro, dict) or parametro.get("ambito") not in {settore_id, "trasversale"}:
                    raise ErroreRegistro(f"Parametro di lookup non disponibile per il settore: {pid}.")
            controlla_pid(nodo["predefinito"])
            viste_chiavi: set[str] = set()
            for chiave, pid in mappa.items():
                if not isinstance(chiave, str) or not chiave.strip() or len(chiave) > 100:
                    raise ErroreRegistro("Chiave di lookup non valida.")
                chiave_normalizzata = chiave.strip().casefold()
                if chiave_normalizzata in viste_chiavi:
                    raise ErroreRegistro("La mappa di lookup contiene chiavi duplicate ignorando maiuscole/minuscole.")
                viste_chiavi.add(chiave_normalizzata)
                controlla_pid(pid)
            return
        if op in {"somma", "moltiplica"}:
            if set(nodo) != {"op", "elementi"}:
                raise ErroreRegistro(f"Operazione {op} con struttura non valida.")
            elementi = nodo.get("elementi")
            if not isinstance(elementi, list) or not 1 <= len(elementi) <= 32:
                raise ErroreRegistro(f"Operazione {op} deve contenere da 1 a 32 elementi.")
            for elemento in elementi:
                controlla(elemento, profondita + 1)
            return
        if op == "dividi":
            if set(nodo) != {"op", "sinistra", "destra"}:
                raise ErroreRegistro("Divisione con struttura non valida.")
            controlla(nodo["sinistra"], profondita + 1)
            controlla(nodo["destra"], profondita + 1)
            return
        if op == "costante":
            if set(nodo) != {"op", "valore"}:
                raise ErroreRegistro("Costante con struttura non valida.")
            valore = nodo.get("valore")
            if not _numero_finito(valore) or float(valore) < 0:
                raise ErroreRegistro("La costante deve essere un numero finito non negativo.")
            return
        raise ErroreRegistro(f"Operazione formula non supportata: {op}.")

    controlla(formula_canonica)
    return formula_canonica


def aggiorna_formula_settore(*, settore_id: str, formula: Any, autore: str = "sconosciuto") -> int:
    """Aggiorna una formula dichiarativa, conserva la versione precedente e riapre la revisione."""
    # Tenere lo stesso lock durante validazione e scrittura evita che un'altra
    # modifica cambi i campi/parametri fra il controllo e il commit.
    with _LOCK:
        formula_canonica = valida_formula_settore(settore_id, formula)
        dati = _leggi()
        settore = dati["settori"].get(settore_id)
        if settore is None:
            raise ErroreRegistro("Settore non trovato.")
        _snapshot_settore(settore, autore=autore, motivo="Aggiornamento della formula di stima")
        settore["stima"] = formula_canonica
        _scrivi_atomico(dati)
        return settore["versione_configurazione"]


def _id_entita_valido(tipo: str, identificativo: str) -> bool:
    if tipo in {"settore", "parametro"}:
        return bool(_ID_RE.fullmatch(identificativo))
    if tipo == "documento":
        # I documenti caricati hanno UUID esadecimale (possono iniziare con una cifra);
        # i riferimenti esterni sintetici usano il prefisso ref_.
        return bool(re.fullmatch(r"(?:[a-f0-9]{32}|ref_[a-z0-9_]{2,59})", identificativo))
    return False


def _esiste_entita(dati: dict[str, Any], tipo: str, identificativo: str) -> bool:
    if tipo == "settore":
        return identificativo in dati["settori"]
    if tipo == "parametro":
        return identificativo in dati["parametri"]
    if tipo == "documento":
        return any(isinstance(doc, dict) and doc.get("id") == identificativo for doc in dati.get("documenti", []))
    return False


_TIPI_RELAZIONE = {
    "documenta", "supporta", "definisce", "applicabile_a", "deriva_da",
    "aggiorna", "correla_con", "contraddice", "sostituisce", "integra",
}


# Relazioni di derivazione/sostituzione: un ciclo renderebbe indeterminata la
# provenienza (A deriva da B che deriva da A) e va rifiutato (sezione 30.6).
_TIPI_ACICLICI = {"deriva_da", "sostituisce", "aggiorna", "definisce"}


def _crea_ciclo(relazioni: list[dict[str, Any]], tipo: str, origine: str, destinazione: str) -> bool:
    archi: dict[str, set[str]] = {}
    for r in relazioni:
        if isinstance(r, dict) and r.get("tipo") in _TIPI_ACICLICI:
            archi.setdefault(f"{r.get('sorgente_tipo')}:{r.get('sorgente_id')}", set()).add(
                f"{r.get('destinazione_tipo')}:{r.get('destinazione_id')}")
    # aggiungere origine→destinazione crea un ciclo se destinazione raggiunge già origine
    da_visitare, visti = [destinazione], set()
    while da_visitare:
        nodo = da_visitare.pop()
        if nodo == origine:
            return True
        if nodo in visti:
            continue
        visti.add(nodo)
        da_visitare.extend(archi.get(nodo, ()))
    return False


def registra_relazione(*, sorgente_tipo: str, sorgente_id: str, tipo: str,
                        destinazione_tipo: str, destinazione_id: str,
                        descrizione: str = "", utente: str = "sconosciuto") -> dict[str, Any]:
    """Registra una relazione documentale/metodologica non ancora validata."""
    tipi_entita = {"settore", "parametro", "documento"}
    if sorgente_tipo not in tipi_entita or destinazione_tipo not in tipi_entita:
        raise ErroreRegistro("Tipo di entità della relazione non supportato.")
    if not isinstance(sorgente_id, str) or not isinstance(destinazione_id, str):
        raise ErroreRegistro("Identificativi della relazione non validi.")
    if not _id_entita_valido(sorgente_tipo, sorgente_id) or not _id_entita_valido(destinazione_tipo, destinazione_id):
        raise ErroreRegistro("Identificativi della relazione non validi.")
    if tipo not in _TIPI_RELAZIONE:
        raise ErroreRegistro("Tipo di relazione non supportato.")
    if sorgente_tipo == destinazione_tipo and sorgente_id == destinazione_id:
        raise ErroreRegistro("Una relazione non può collegare un elemento a sé stesso.")
    if not isinstance(descrizione, str) or len(descrizione) > 1000:
        raise ErroreRegistro("La nota della relazione supera 1000 caratteri.")
    identificativo = secrets.token_hex(16)
    relazione = {
        "id": identificativo,
        "sorgente_tipo": sorgente_tipo,
        "sorgente_id": sorgente_id,
        "tipo": tipo,
        "destinazione_tipo": destinazione_tipo,
        "destinazione_id": destinazione_id,
        "descrizione": descrizione.strip(),
        "creato_da": (utente or "sconosciuto")[:100],
        "creato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stato": "da_verificare",
    }
    with _LOCK:
        dati = _leggi()
        if not _esiste_entita(dati, sorgente_tipo, sorgente_id):
            raise ErroreRegistro("L'elemento di origine della relazione non esiste.")
        if not _esiste_entita(dati, destinazione_tipo, destinazione_id):
            raise ErroreRegistro("L'elemento di destinazione della relazione non esiste.")
        duplicata = any(
            r.get("sorgente_tipo") == sorgente_tipo and r.get("sorgente_id") == sorgente_id
            and r.get("tipo") == tipo and r.get("destinazione_tipo") == destinazione_tipo
            and r.get("destinazione_id") == destinazione_id
            for r in dati.get("relazioni", []) if isinstance(r, dict)
        )
        if duplicata:
            raise ErroreRegistro("Questa relazione è già registrata.")
        if tipo in _TIPI_ACICLICI and _crea_ciclo(dati.get("relazioni", []), tipo,
                                                   f"{sorgente_tipo}:{sorgente_id}", f"{destinazione_tipo}:{destinazione_id}"):
            raise ErroreRegistro(f"La relazione '{tipo}' creerebbe un ciclo di dipendenze non ammesso.")
        dati.setdefault("relazioni", []).append(relazione)
        _scrivi_atomico(dati)
    return dict(relazione)


def lista_relazioni() -> list[dict[str, Any]]:
    with _LOCK:
        relazioni = _leggi().get("relazioni", [])
        return json.loads(json.dumps(relazioni, ensure_ascii=False))

