"""Collaudo automatico di un settore prima dell'attivazione (sezione 30.10).

Il collaudo è eseguito in ambiente isolato: usa una copia del registro e dati di
prova generati dalla definizione del settore; non tocca il lotto operativo.

Superare il collaudo significa che il software si comporta come previsto sui
casi provati. NON è una validazione scientifica o giuridica della metodologia.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from typing import Any

from app import db_operativo, moduli_settore, settori, unita
from app.dati_sintetici import genera_aziende

CAMPI_BASE = {"dipendenti_dichiarati", "costo_lavoro_per_addetto"}


def hash_settore(settore_id: str, registro: dict[str, Any] | None = None) -> str:
    """Hash degli elementi che determinano i calcoli del settore (non dello stato)."""
    dati = registro if registro is not None else settori.leggi_registro()
    settore = dati["settori"].get(settore_id)
    if settore is None:
        raise settori.ErroreRegistro("Settore non trovato.")
    parametri = dati["parametri"]
    usati = sorted(settori.parametri_usati_da_settore(settore))
    rilevante = {
        "campi": settore.get("campi"),
        "stima": settore.get("stima"),
        "campi_almeno_uno": settore.get("campi_almeno_uno"),
        "controlli": settore.get("controlli", []),
        "moduli": settore.get("moduli", []),
        "parametri": {pid: {k: parametri.get(pid, {}).get(k) for k in ("valore", "unita", "dimensione")} for pid in usati},
    }
    canonico = json.dumps(rilevante, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _esito(nome: str, esito: str, dettaglio: str) -> dict[str, str]:
    return {"controllo": nome, "esito": esito, "dettaglio": dettaglio}


def _valore_tipico(definizione: dict[str, Any]) -> float:
    minimo = definizione.get("minimo")
    massimo = definizione.get("massimo")
    if isinstance(minimo, (int, float)) and isinstance(massimo, (int, float)):
        return (minimo + massimo) / 2 or 1.0
    if isinstance(minimo, (int, float)) and minimo > 0:
        return float(minimo) * 10
    return 100.0


def dataset_di_prova(settore_id: str, settore: dict[str, Any]) -> list[dict[str, Any]]:
    """Casi normali, limite, incompleti ed errati generati dalla definizione del settore."""
    campi = settore.get("campi", {})
    base: dict[str, Any] = {"settore": settore_id, "dipendenti_dichiarati": 5, "costo_lavoro_per_addetto": 20000}
    lookup_campi = {}

    def trova_lookup(nodo: Any) -> None:
        if isinstance(nodo, dict):
            if nodo.get("op") == "lookup_coefficiente":
                chiavi = list(dict(nodo.get("mappa") or {}).keys())
                lookup_campi[nodo.get("campo")] = chiavi[0] if chiavi else "generico"
            for figlio in nodo.get("elementi", []) or []:
                trova_lookup(figlio)
            trova_lookup(nodo.get("sinistra"))
            trova_lookup(nodo.get("destra"))

    trova_lookup(settore.get("stima"))
    for campo, definizione in campi.items():
        if campo in lookup_campi:
            base[campo] = lookup_campi[campo]
        elif isinstance(definizione, dict) and definizione.get("tipo") == "numero":
            base[campo] = _valore_tipico(definizione)
    casi: list[dict[str, Any]] = []

    def caso(tipo: str, atteso: str, **modifiche: Any) -> None:
        record = dict(base)
        for k, v in modifiche.items():
            if v is _RIMUOVI:
                record.pop(k, None)
            else:
                record[k] = v
        record["id"] = f"COLLAUDO-{len(casi) + 1:03d}"
        record["_caso"] = {"tipo": tipo, "atteso": atteso}
        casi.append(record)

    caso("normale", "valutabile")
    caso("limite_zero_dipendenti", "valutabile", dipendenti_dichiarati=0)
    caso("limite_molti_dipendenti", "valutabile", dipendenti_dichiarati=10_000)
    numerici = [c for c, d in campi.items() if isinstance(d, dict) and d.get("tipo") == "numero" and c in base]
    for c in numerici:
        caso(f"limite_valore_elevato_{c}", "qualsiasi", **{c: 1e9})
    obbligatori = [c for c, d in campi.items() if isinstance(d, dict) and d.get("obbligatorio")]
    for c in obbligatori:
        caso(f"incompleto_{c}", "non_valutabile", **{c: _RIMUOVI})
    almeno_uno = settore.get("campi_almeno_uno") or []
    if almeno_uno:
        caso("incompleto_tutti_alternativi", "non_valutabile", **{c: _RIMUOVI for c in almeno_uno})
    caso("incompleto_dipendenti", "non_valutabile", dipendenti_dichiarati=_RIMUOVI)
    caso("errato_dipendenti_testo", "non_valutabile", dipendenti_dichiarati="dieci")
    caso("errato_dipendenti_negativi", "non_valutabile", dipendenti_dichiarati=-3)
    for c in numerici:
        caso(f"errato_testo_{c}", "non_valutabile", **{c: "abc"})
        caso(f"errato_nan_{c}", "non_valutabile", **{c: float("nan")})
        if isinstance(campi[c].get("minimo"), (int, float)):
            caso(f"errato_sotto_minimo_{c}", "non_valutabile", **{c: campi[c]["minimo"] - 1})
    return casi


class _Rimuovi:
    pass


_RIMUOVI = _Rimuovi()


def _senza_caso(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k != "_caso"} for r in records]


def collauda(settore_id: str, *, utente: str = "sistema", registro: dict[str, Any] | None = None,
             salva: bool = True) -> dict[str, Any]:
    from app.motore.analisi import analizza

    dati = copy.deepcopy(registro if registro is not None else settori.leggi_registro())
    settore = dati["settori"].get(settore_id)
    if settore is None:
        raise settori.ErroreRegistro("Settore non trovato.")
    parametri = dati["parametri"]
    esiti: list[dict[str, str]] = []

    # 1. Struttura dei campi
    problemi = []
    for campo, d in (settore.get("campi") or {}).items():
        if not isinstance(d, dict) or d.get("tipo") not in {"numero", "testo"}:
            problemi.append(f"{campo}: tipo non valido")
        elif d.get("tipo") == "numero" and not str(d.get("unita") or "").strip():
            problemi.append(f"{campo}: unità di misura assente")
    esiti.append(_esito("struttura_campi", "fallito" if problemi else "superato", "; ".join(problemi) or "tipi e unità presenti"))

    # 2. Validità statica della formula e riferimenti
    try:
        settori.valida_formula_settore(settore_id, settore.get("stima"), registro=dati)
        esiti.append(_esito("formula", "superato", "struttura, campi e parametri risolti"))
    except settori.ErroreRegistro as exc:
        esiti.append(_esito("formula", "fallito", str(exc)))

    # 3. Parametri: esistenza e valori finiti
    usati = settori.parametri_usati_da_settore(settore)
    mancanti = [pid for pid in usati if pid not in parametri]
    non_finiti = [pid for pid in usati if pid in parametri and not (isinstance(parametri[pid].get("valore"), (int, float))
                  and not isinstance(parametri[pid].get("valore"), bool) and math.isfinite(float(parametri[pid]["valore"])))]
    esiti.append(_esito("riferimenti_parametri", "fallito" if (mancanti or non_finiti) else "superato",
                        (f"mancanti: {mancanti}; " if mancanti else "") + (f"non numerici: {non_finiti}" if non_finiti else "")
                        or f"{len(usati)} parametri risolti"))

    # 4. Controlli aggiuntivi e moduli
    problemi = []
    for c in settore.get("controlli", []) or []:
        if c.get("tipo") not in {"rapporto_minimo", "rapporto_descrittivo"}:
            problemi.append(f"controllo {c.get('id')}: tipo non supportato")
        if c.get("tipo") == "rapporto_minimo" and c.get("coefficiente") not in parametri:
            problemi.append(f"controllo {c.get('id')}: coefficiente inesistente")
    for m in settore.get("moduli", []) or []:
        if m not in moduli_settore.MODULI:
            problemi.append(f"modulo non registrato: {m}")
    esiti.append(_esito("controlli_e_moduli", "fallito" if problemi else "superato", "; ".join(problemi) or "riferimenti validi"))

    # 5. Compatibilità dimensionale
    dim = unita.verifica_stima_addetti(settore.get("stima"), settore.get("campi") or {}, parametri)
    esiti.append(_esito(
        "unita_di_misura",
        {"compatibile": "superato", "incompatibile": "fallito"}.get(dim["esito"], "avviso"),
        dim["dimensione"] and f"dimensione risultante: {dim['dimensione']}" if dim["esito"] == "compatibile"
        else "; ".join(dim["problemi"]) or dim["esito"]))

    # 6. Casi di prova (normali, limite, incompleti, errati)
    casi = dataset_di_prova(settore_id, settore)
    catalogo = (dati["settori"], parametri)
    errori_casi = []
    try:
        risultati = analizza(copy.deepcopy(_senza_caso(casi)), catalogo=catalogo, settori_in_collaudo={settore_id})
    except Exception as exc:  # il collaudo deve registrare il fallimento, non interrompersi
        risultati = []
        errori_casi.append(f"eccezione del motore: {type(exc).__name__}")
    for caso, risultato in zip(casi, risultati):
        atteso = caso["_caso"]["atteso"]
        livello = risultato["analisi"]["livello"]
        if atteso == "valutabile" and livello == "non_valutabile":
            errori_casi.append(f"{caso['_caso']['tipo']}: atteso valutabile, ottenuto non valutabile")
        if atteso == "non_valutabile" and livello != "non_valutabile":
            errori_casi.append(f"{caso['_caso']['tipo']}: atteso non valutabile, ottenuto {livello}")
        p = risultato["analisi"]["punteggio"]
        if p is not None and not (isinstance(p, (int, float)) and 0 <= p <= 100):
            errori_casi.append(f"{caso['_caso']['tipo']}: punteggio fuori intervallo")
    esiti.append(_esito("casi_di_prova", "fallito" if errori_casi else "superato",
                        "; ".join(errori_casi[:10]) or f"{len(casi)} casi coerenti con l'atteso"))

    # 7. Riproducibilità
    try:
        r1 = analizza(copy.deepcopy(_senza_caso(casi)), catalogo=catalogo, settori_in_collaudo={settore_id})
        r2 = analizza(copy.deepcopy(_senza_caso(casi)), catalogo=catalogo, settori_in_collaudo={settore_id})
        uguali = json.dumps([x["analisi"] for x in r1], sort_keys=True, default=str) == json.dumps([x["analisi"] for x in r2], sort_keys=True, default=str)
    except Exception:
        uguali = False
    esiti.append(_esito("riproducibilita", "superato" if uguali else "fallito", "due esecuzioni identiche" if uguali else "risultati diversi o errore"))

    # 8. Spiegazioni e tracciabilità
    normale = next((r for r, c in zip(risultati, casi) if c["_caso"]["tipo"] == "normale"), None)
    if normale and "non descrivibile" not in normale["analisi"].get("formula", "") and normale["analisi"].get("parametri_formula"):
        senza_fonte = [p["id"] for p in normale["analisi"]["parametri_formula"]
                       if str(p.get("fonte", "")).strip().casefold() in {"", "fonte da verificare", "da verificare"}]
        esiti.append(_esito("spiegazione_e_tracciabilita", "avviso" if senza_fonte else "superato",
                            f"parametri senza fonte verificata: {senza_fonte}" if senza_fonte else "spiegazione e fonti presenti"))
    else:
        esiti.append(_esito("spiegazione_e_tracciabilita", "fallito", "spiegazione o parametri usati assenti nel caso normale"))

    # 9. Non interferenza con gli altri settori
    try:
        campione = genera_aziende(200, seme=7)
        for a in campione:
            a.pop("_irregolare", None)
        con = analizza(copy.deepcopy(campione), catalogo=catalogo)
        senza_settori = {k: v for k, v in dati["settori"].items() if k != settore_id}
        senza = analizza(copy.deepcopy(campione), catalogo=(senza_settori, parametri))
        diversi = [a["id"] for a, b in zip(con, senza) if a.get("settore") != settore_id
                   and json.dumps(a["analisi"], sort_keys=True, default=str) != json.dumps(b["analisi"], sort_keys=True, default=str)]
        esiti.append(_esito("non_interferenza", "fallito" if diversi else "superato",
                            f"risultati di altri settori alterati: {diversi[:5]}" if diversi else "altri settori invariati"))
    except Exception as exc:
        esiti.append(_esito("non_interferenza", "fallito", f"errore: {type(exc).__name__}"))

    superato = all(e["esito"] != "fallito" for e in esiti)
    risultato = {
        "settore_id": settore_id,
        "hash_settore": hash_settore(settore_id, dati),
        "superato": superato,
        "casi_eseguiti": len(casi),
        "controlli": esiti,
        "nota": "Il collaudo verifica il comportamento del software sui casi provati; non è una validazione scientifica o normativa.",
    }
    if salva:
        from contextlib import closing
        with closing(db_operativo.connessione()) as conn:
            cur = conn.execute(
                "INSERT INTO collaudi(settore_id, hash_settore, eseguito_il, utente, superato, risultato) VALUES (?,?,?,?,?,?)",
                (settore_id, risultato["hash_settore"], db_operativo.adesso(), utente[:100], 1 if superato else 0,
                 json.dumps(risultato, ensure_ascii=False)),
            )
            risultato["collaudo_id"] = int(cur.lastrowid)
    return risultato


def ultimo_collaudo(settore_id: str) -> dict[str, Any] | None:
    from contextlib import closing
    with closing(db_operativo.connessione()) as conn:
        r = conn.execute("SELECT id, eseguito_il, utente, superato, hash_settore, risultato FROM collaudi WHERE settore_id=? ORDER BY id DESC LIMIT 1",
                         (settore_id,)).fetchone()
    if not r:
        return None
    d = json.loads(r["risultato"])
    d.update({"collaudo_id": r["id"], "eseguito_il": r["eseguito_il"], "utente": r["utente"]})
    return d
