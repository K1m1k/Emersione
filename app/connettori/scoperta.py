"""Scoperta dei dataset pubblici e catalogo locale (sezione 12).

ISTAT — elenco dei dataflow dal servizio SDMX 2.1 REST ufficiale:
  base https://esploradati.istat.it/SDMXWS/rest, agenzia IT1 (verificati il
  2026-10-22 sulla pagina ISTAT "SDMX web services" e sulla documentazione del
  pacchetto istatR). Il percorso /dataflow/IT1 segue lo standard SDMX 2.1 REST.
  Stato: implementato e collaudato con risposte simulate; la risposta reale va
  verificata in rete prima dell'uso (vedi docs/H_LIMITI_NOTI.md).

ANAC — il portale pubblica pagine di dataset (es. /opendata/dataset/cup) ma in
  fase di sviluppo non è stata trovata documentazione ufficiale di un'API di
  catalogo. Il connettore usa l'interfaccia CKAN "package_search" SOLO se
  l'amministratore imposta EMERSIONE_ANAC_CATALOGO_API dopo averne verificato
  l'esistenza; altrimenti lo stato è "non_configurato" e la scoperta non avviene.

La scoperta registra metadati nel catalogo: non scarica dati, non li collega
alle formule e non modifica parametri. Il collegamento passa da mappatura,
revisione e proposta approvata (app.collegamento_semantico).
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import xml.etree.ElementTree as ET
from contextlib import closing
from typing import Any, Callable

from app import db_operativo
from app.connettori import fonti_live

ISTAT_BASE = "https://esploradati.istat.it/SDMXWS/rest"
ISTAT_AGENZIA = "IT1"
MAX_VOCI = 5000


class ErroreScoperta(ValueError):
    pass


def stato_connettori() -> list[dict[str, str]]:
    anac = os.environ.get("EMERSIONE_ANAC_CATALOGO_API", "").strip()
    return [
        {"fonte": "istat", "stato": "operativo_da_verificare_live",
         "endpoint": f"{ISTAT_BASE}/dataflow/{ISTAT_AGENZIA}",
         "nota": "Limite ISTAT: 5 richieste/minuto per IP; il client si ferma a 4."},
        {"fonte": "anac", "stato": "configurato_da_verificare" if anac else "non_configurato",
         "endpoint": anac or "-",
         "nota": "Impostare EMERSIONE_ANAC_CATALOGO_API solo dopo aver verificato l'API di catalogo ufficiale."},
    ]


def _tag(elemento: ET.Element) -> str:
    return elemento.tag.rsplit("}", 1)[-1]


def analizza_dataflow_sdmx(contenuto: bytes) -> list[dict[str, str]]:
    """Estrae id, versione e nome (preferibilmente italiano) dei dataflow da SDMX-ML 2.1."""
    if b"<!DOCTYPE" in contenuto[:2048].upper() or b"<!ENTITY" in contenuto.upper():
        raise ErroreScoperta("XML con DTD/entità non ammesso.")
    try:
        radice = ET.fromstring(contenuto)
    except ET.ParseError as exc:
        raise ErroreScoperta("Risposta SDMX non è XML valido.") from exc
    voci = []
    for el in radice.iter():
        if _tag(el) != "Dataflow" or not el.get("id"):
            continue
        nomi = {}
        for figlio in el:
            if _tag(figlio) == "Name":
                lingua = figlio.get("{http://www.w3.org/XML/1998/namespace}lang", "")
                nomi[lingua] = (figlio.text or "").strip()
        voci.append({
            "identificativo": f"{el.get('agencyID', ISTAT_AGENZIA)}:{el.get('id')}({el.get('version', '')})",
            "nome": (nomi.get("it") or nomi.get("en") or next(iter(nomi.values()), el.get("id")))[:500],
            "descrizione": (nomi.get("en") or "")[:500],
            "url_dati": f"{ISTAT_BASE}/data/{el.get('id')}",
        })
        if len(voci) >= MAX_VOCI:
            break
    return voci


def _salva(fonte: str, voci: list[dict[str, str]], hash_catalogo: str, licenza: str) -> int:
    with closing(db_operativo.connessione()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for v in voci:
                conn.execute(
                    """INSERT INTO catalogo_dataset(fonte, identificativo, nome, descrizione, url_dati, licenza, scoperto_il, hash_catalogo)
                       VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(fonte, identificativo) DO UPDATE SET nome=excluded.nome, descrizione=excluded.descrizione,
                       url_dati=excluded.url_dati, scoperto_il=excluded.scoperto_il, hash_catalogo=excluded.hash_catalogo""",
                    (fonte, v["identificativo"], v["nome"], v.get("descrizione", ""), v.get("url_dati"), licenza,
                     db_operativo.adesso(), hash_catalogo))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return len(voci)


def scopri_istat(fetch: Callable[..., Any] | None = None) -> dict[str, Any]:
    fetch = fetch or fonti_live._fetch
    payload = fetch("istat:catalogo", f"{ISTAT_BASE}/dataflow/{ISTAT_AGENZIA}", fonti_live.ISTAT_ALLOWED_HOSTS,
                    fonti_live.ISTAT_ALLOWED_PREFIXES)
    voci = analizza_dataflow_sdmx(payload.contenuto)
    n = _salva("istat", voci, payload.sha256, "da verificare sulle condizioni d'uso ISTAT")
    return {"fonte": "istat", "voci": n, "sha256": payload.sha256, "url": payload.url}


def analizza_ckan(contenuto: bytes) -> list[dict[str, str]]:
    try:
        dato = json.loads(contenuto.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErroreScoperta("Risposta di catalogo non è JSON valido.") from exc
    risultati = ((dato or {}).get("result") or {}).get("results") if isinstance(dato, dict) else None
    if not isinstance(risultati, list):
        raise ErroreScoperta("Struttura di catalogo non riconosciuta (atteso result.results).")
    voci = []
    for r in risultati[:MAX_VOCI]:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        risorse = [x.get("url") for x in r.get("resources", []) if isinstance(x, dict) and isinstance(x.get("url"), str)]
        ammesse = [u for u in risorse if (urllib.parse.urlparse(u).hostname or "") in fonti_live.ANAC_ALLOWED_HOSTS
                   and urllib.parse.urlparse(u).scheme == "https"]
        voci.append({"identificativo": str(r["name"])[:200], "nome": str(r.get("title") or r["name"])[:500],
                     "descrizione": str(r.get("notes") or "")[:500], "url_dati": ammesse[0] if ammesse else None,
                     "licenza": str(r.get("license_title") or r.get("license_id") or "non indicata")[:200]})
    return voci


def scopri_anac(testo: str, fetch: Callable[..., Any] | None = None) -> dict[str, Any]:
    base = os.environ.get("EMERSIONE_ANAC_CATALOGO_API", "").strip()
    if not base:
        raise ErroreScoperta("Connettore di catalogo ANAC non configurato (EMERSIONE_ANAC_CATALOGO_API).")
    if not isinstance(testo, str) or not testo.strip() or len(testo) > 100:
        raise ErroreScoperta("Indicare un termine di ricerca di massimo 100 caratteri.")
    fetch = fetch or fonti_live._fetch
    payload = fetch("anac:catalogo", base, fonti_live.ANAC_ALLOWED_HOSTS, fonti_live.ANAC_ALLOWED_PREFIXES,
                    {"q": testo.strip(), "rows": "100"})
    voci = analizza_ckan(payload.contenuto)
    licenze = {v.pop("licenza") for v in voci} or {"non indicata"}
    n = _salva("anac", voci, payload.sha256, ", ".join(sorted(licenze))[:200])
    return {"fonte": "anac", "voci": n, "sha256": payload.sha256, "url": payload.url}


def cerca_catalogo(testo: str = "", fonte: str = "", limite: int = 100) -> list[dict[str, Any]]:
    condizioni, valori = [], []
    if fonte:
        condizioni.append("fonte=?")
        valori.append(fonte)
    for parola in (testo or "").split()[:5]:
        condizioni.append("(nome LIKE ? OR descrizione LIKE ? OR identificativo LIKE ?)")
        valori += [f"%{parola}%"] * 3
    sql = "SELECT * FROM catalogo_dataset" + (" WHERE " + " AND ".join(condizioni) if condizioni else "") + " ORDER BY fonte, nome LIMIT ?"
    with closing(db_operativo.connessione()) as conn:
        return [dict(r) for r in conn.execute(sql, (*valori, int(limite)))]


def hash_testo(contenuto: bytes) -> str:
    return hashlib.sha256(contenuto).hexdigest()
