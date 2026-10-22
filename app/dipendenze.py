"""Mappa delle dipendenze e analisi d'impatto (sezione 30.9).

Prima di modificare o disattivare un parametro, un documento o un settore,
l'interfaccia mostra quali elementi ne dipendono, quali analisi storiche lo
hanno usato, quali collaudi vanno ripetuti e quali approvazioni servono.
"""
from __future__ import annotations

from contextlib import closing
from typing import Any

from app import db_operativo, settori


def _relazioni_di(tipo: str, identificativo: str, registro: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in registro.get("relazioni", []) if isinstance(r, dict) and (
        (r.get("sorgente_tipo") == tipo and r.get("sorgente_id") == identificativo)
        or (r.get("destinazione_tipo") == tipo and r.get("destinazione_id") == identificativo))]


def impatto_parametro(parametro_id: str) -> dict[str, Any]:
    registro = settori.leggi_registro()
    if parametro_id not in registro["parametri"]:
        raise settori.ErroreRegistro("Parametro non trovato.")
    settori_interessati = [
        {"id": sid, "nome": cfg.get("nome", sid), "stato": cfg.get("stato")}
        for sid, cfg in registro["settori"].items() if parametro_id in settori.parametri_usati_da_settore(cfg)
    ]
    globale = parametro_id in settori.PARAMETRI_MOTORE
    documenti = [d for d in registro.get("documenti", []) if isinstance(d, dict) and d.get("parametro") == parametro_id]
    try:
        esecuzioni = db_operativo.esecuzioni_che_usano_parametro(parametro_id, 200)
    except Exception:
        esecuzioni = []
    approvati = [s["id"] for s in settori_interessati if s["stato"] in settori.STATI_ANALIZZABILI]
    return {
        "tipo": "parametro", "id": parametro_id,
        "parametro_globale_del_motore": globale,
        "settori": settori_interessati,
        "documenti": [{"id": d.get("id"), "titolo": d.get("titolo")} for d in documenti],
        "relazioni": _relazioni_di("parametro", parametro_id, registro),
        "esecuzioni_storiche": esecuzioni,
        "analisi_future": "Cambieranno i risultati dei settori elencati" + (" e di tutti i settori (soglia del motore)" if globale else ""),
        "test_da_rieseguire": [f"collaudo del settore {s['id']}" for s in settori_interessati],
        "approvazioni_richieste": (
            [f"Il settore {sid} tornerà 'in_revisione' e richiederà nuovo collaudo e approvazione." for sid in approvati]
            or ["Nessun settore attivo interessato."]),
        "nota_storico": "Le analisi storiche non vengono ricalcolate: restano associate alla configurazione con cui sono state prodotte.",
    }


def impatto_settore(settore_id: str) -> dict[str, Any]:
    registro = settori.leggi_registro()
    cfg = registro["settori"].get(settore_id)
    if cfg is None:
        raise settori.ErroreRegistro("Settore non trovato.")
    usati = sorted(settori.parametri_usati_da_settore(cfg))
    condivisi = [pid for pid in usati if any(
        pid in settori.parametri_usati_da_settore(altro) for sid, altro in registro["settori"].items() if sid != settore_id)]
    with closing(db_operativo.connessione()) as conn:
        esecuzioni = [int(r[0]) for r in conn.execute(
            "SELECT DISTINCT esecuzione_id FROM risultati WHERE settore=? ORDER BY esecuzione_id DESC LIMIT 200", (settore_id,))]
        pratiche = conn.execute(
            "SELECT COUNT(*) FROM pratiche p JOIN risultati r ON r.azienda_id=p.azienda_id AND r.esecuzione_id=p.esecuzione_id WHERE r.settore=?",
            (settore_id,)).fetchone()[0]
    return {
        "tipo": "settore", "id": settore_id, "stato": cfg.get("stato"),
        "parametri_usati": usati,
        "parametri_condivisi_con_altri_settori": condivisi,
        "moduli": cfg.get("moduli", []),
        "documenti": [{"id": d.get("id"), "titolo": d.get("titolo")} for d in registro.get("documenti", [])
                      if isinstance(d, dict) and d.get("settore") == settore_id],
        "relazioni": _relazioni_di("settore", settore_id, registro),
        "esecuzioni_storiche": esecuzioni,
        "pratiche_collegate": int(pratiche),
        "test_da_rieseguire": [f"collaudo del settore {settore_id}"],
        "approvazioni_richieste": ["Ogni modifica riporta il settore in revisione: servono nuovo collaudo e approvazioni."],
    }


def impatto_documento(documento_id: str) -> dict[str, Any]:
    registro = settori.leggi_registro()
    doc = next((d for d in registro.get("documenti", []) if isinstance(d, dict) and d.get("id") == documento_id), None)
    if doc is None:
        raise settori.ErroreRegistro("Documento non trovato.")
    relazioni = _relazioni_di("documento", documento_id, registro)
    parametri = {doc.get("parametro")} | {r["destinazione_id"] for r in relazioni if r.get("destinazione_tipo") == "parametro"}
    parametri.discard(None)
    validati = [pid for pid, p in registro["parametri"].items() if p.get("documento_validazione") == documento_id]
    settori_interessati = sorted({sid for sid, cfg in registro["settori"].items()
                                  if parametri & settori.parametri_usati_da_settore(cfg)} | ({doc["settore"]} if doc.get("settore") else set()))
    return {
        "tipo": "documento", "id": documento_id, "titolo": doc.get("titolo"),
        "parametri_collegati": sorted(parametri),
        "parametri_validati_con_questo_documento": validati,
        "settori": settori_interessati,
        "relazioni": relazioni,
        "conseguenza_se_obsoleto": "I parametri validati con questo documento vanno riportati 'da_verificare' e i settori interessati in revisione.",
    }


def mappa_completa() -> dict[str, Any]:
    """Grafo esplicito documento → parametro → settore usato dalla pagina delle dipendenze."""
    registro = settori.leggi_registro()
    archi = []
    for sid, cfg in registro["settori"].items():
        for pid in sorted(settori.parametri_usati_da_settore(cfg)):
            if pid in registro["parametri"]:
                archi.append({"da": f"parametro:{pid}", "a": f"settore:{sid}", "tipo": "usato_da"})
            else:
                archi.append({"da": f"parametro:{pid}", "a": f"settore:{sid}", "tipo": "riferimento_irrisolto"})
    for d in registro.get("documenti", []):
        if isinstance(d, dict) and d.get("parametro"):
            archi.append({"da": f"documento:{d.get('id')}", "a": f"parametro:{d['parametro']}", "tipo": "associato"})
    for r in registro.get("relazioni", []):
        if isinstance(r, dict):
            archi.append({"da": f"{r.get('sorgente_tipo')}:{r.get('sorgente_id')}",
                          "a": f"{r.get('destinazione_tipo')}:{r.get('destinazione_id')}", "tipo": r.get("tipo")})
    irrisolti = [a for a in archi if a["tipo"] == "riferimento_irrisolto"]
    non_usati = sorted(pid for pid in registro["parametri"]
                       if not any(a["da"] == f"parametro:{pid}" and a["tipo"] == "usato_da" for a in archi))
    return {"archi": archi, "riferimenti_irrisolti": irrisolti, "parametri_non_usati": non_usati}
