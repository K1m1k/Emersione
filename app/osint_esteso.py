"""OSINT su più pagine e verifica incrociata (sezione 14).

Raccolta limitata e controllata, non un crawler generico:
  - parte da un URL su un dominio in allowlist e segue solo collegamenti dello
    STESSO host, entro un numero massimo di pagine e una profondità massima;
  - rispetta robots.txt (se robots.txt non è leggibile per errore, si ferma);
  - una richiesta al secondo al massimo, nessun redirect, nessuna autenticazione,
    nessun aggiramento di paywall o misure tecniche;
  - ogni pagina è conservata con URL, hash, data e motivazione, stato "da_verificare".

La verifica incrociata conta in quante fonti INDIPENDENTI (domini registrabili
diversi, contenuti non identici) compare un'affermazione. Più fonti non rendono
vera una notizia: il risultato è "riscontrata in N fonti", da valutare da un operatore.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from contextlib import closing
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Callable

from app import osint

MAX_PAGINE = 20
MAX_PROFONDITA = 2
PAUSA_SECONDI = 1.0
USER_AGENT = "Emersione-OSINT/0.4 (raccolta limitata su domini autorizzati; rispetta robots.txt)"


class _Collegamenti(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.href: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for nome, valore in attrs:
                if nome == "href" and valore and len(self.href) < 500:
                    self.href.append(valore)


def _scarica(url: str) -> tuple[int, str, bytes]:
    """Download di una singola risorsa con le stesse regole del modulo OSINT puntuale."""
    p = osint._valida_url(url)
    richiesta = urllib.request.Request(p.geturl(), headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity",
                                                            "Accept": "text/html, text/plain, application/xhtml+xml;q=0.9"})
    opener = urllib.request.build_opener(osint._NoRedirect())
    try:
        with opener.open(richiesta, timeout=12) as r:
            ct = (r.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
            raw = r.read(osint.MAX_BYTES + 1)
            return int(getattr(r, "status", 200)), ct, raw
    except urllib.error.HTTPError as exc:
        return exc.code, "", b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise osint.ErroreOSINT("Connessione alla fonte non riuscita.") from exc


def _robots(host: str, scarica: Callable[[str], tuple[int, str, bytes]]) -> urllib.robotparser.RobotFileParser:
    rp = urllib.robotparser.RobotFileParser()
    stato, _ct, raw = scarica(f"https://{host}/robots.txt")
    if stato == 404 or stato == 410:
        rp.parse([])            # nessuna regola pubblicata: accesso consentito per convenzione
    elif 200 <= stato < 300:
        rp.parse(raw.decode("utf-8", errors="replace").splitlines())
    else:
        raise osint.ErroreOSINT(f"robots.txt non leggibile (HTTP {stato}): raccolta non avviata per prudenza.")
    return rp


def _salva_pagina(url: str, host: str, ct: str, raw: bytes, *, utente: str, motivazione: str, raccolta_id: str) -> dict[str, Any]:
    testo = raw.decode("utf-8", errors="replace")
    estrattore = osint._EstrattoreHTML()
    estrattore.feed(testo)
    titolo = re.sub(r"\s+", " ", " ".join(estrattore.titolo)).strip()[:300] or host
    estratto = re.sub(r"\s+", " ", " ".join(estrattore.testi)).strip()[:osint.MAX_TEXT]
    ident = secrets.token_hex(16)
    adesso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = hashlib.sha256(raw).hexdigest()
    with closing(osint._conn()) as conn:
        conn.execute("""INSERT INTO osservazioni_osint
            (id,url,host,titolo,estratto,sha256,content_type,acquisito_il,acquisito_da,motivazione,stato,byte_originali,contenuto_originale)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ident, url, host, titolo, estratto, sha, ct, adesso, utente[:100],
             f"{motivazione} [raccolta {raccolta_id}]", "da_verificare", len(raw), sqlite3.Binary(raw)))
        conn.commit()
    return {"id": ident, "url": url, "titolo": titolo, "sha256": sha}


def raccogli(url_iniziale: str, *, utente: str, motivazione: str, max_pagine: int = 10, profondita: int = 1,
             scarica: Callable[[str], tuple[int, str, bytes]] | None = None, pausa: float = PAUSA_SECONDI) -> dict[str, Any]:
    motivazione = (motivazione or "").strip()
    if len(motivazione) < 15 or len(motivazione) > 1000:
        raise osint.ErroreOSINT("Indica una motivazione specifica (15–1000 caratteri).")
    max_pagine = max(1, min(int(max_pagine), MAX_PAGINE))
    profondita = max(0, min(int(profondita), MAX_PROFONDITA))
    scarica = scarica or _scarica
    partenza = osint._valida_url(url_iniziale)
    host = (partenza.hostname or "").casefold()
    rp = _robots(host, scarica)
    raccolta_id = secrets.token_hex(6)
    coda: list[tuple[str, int]] = [(partenza.geturl(), 0)]
    visti: set[str] = set()
    salvate, saltate = [], []
    while coda and len(salvate) < max_pagine:
        url, livello = coda.pop(0)
        if url in visti:
            continue
        visti.add(url)
        if not rp.can_fetch(USER_AGENT, url):
            saltate.append({"url": url, "motivo": "escluso da robots.txt"})
            continue
        if salvate or saltate:
            time.sleep(pausa)
        try:
            osint._valida_url(url)
            stato, ct, raw = scarica(url)
        except osint.ErroreOSINT as exc:
            saltate.append({"url": url, "motivo": str(exc)})
            continue
        if not 200 <= stato < 300 or ct not in {"text/html", "application/xhtml+xml", "text/plain"} or len(raw) > osint.MAX_BYTES or not raw:
            saltate.append({"url": url, "motivo": f"risposta non utilizzabile (HTTP {stato}, {ct or 'tipo ignoto'})"})
            continue
        salvate.append(_salva_pagina(url, host, ct, raw, utente=utente, motivazione=motivazione, raccolta_id=raccolta_id))
        if livello < profondita and ct != "text/plain":
            parser = _Collegamenti()
            parser.feed(raw.decode("utf-8", errors="replace"))
            for href in parser.href:
                assoluto = urllib.parse.urljoin(url, href)
                p = urllib.parse.urlparse(assoluto)
                if p.scheme == "https" and (p.hostname or "").casefold() == host and not p.username:
                    pulito = urllib.parse.urlunparse(p._replace(fragment=""))
                    if pulito not in visti:
                        coda.append((pulito, livello + 1))
    return {"raccolta_id": raccolta_id, "host": host, "pagine_salvate": salvate, "saltate": saltate[:100],
            "nota": "Pagine conservate come fonti da verificare; nessuna valutazione automatica di attendibilità."}


def _dominio_registrabile(host: str) -> str:
    # Approssimazione: ultimi due livelli (es. comune.roma.it → roma.it). Non gestisce
    # tutti i suffissi pubblici: la valutazione di indipendenza resta all'operatore.
    parti = (host or "").casefold().split(".")
    return ".".join(parti[-2:]) if len(parti) >= 2 else host


def verifica_incrociata(affermazione: str, limite: int = 500) -> dict[str, Any]:
    termini = [t for t in re.split(r"\s+", (affermazione or "").strip()) if len(t) > 2][:8]
    if not termini:
        raise osint.ErroreOSINT("Indicare un'affermazione o termini di almeno 3 caratteri.")
    with closing(osint._conn()) as conn:
        righe = conn.execute("SELECT id,url,host,titolo,estratto,sha256,stato,acquisito_il FROM osservazioni_osint ORDER BY acquisito_il DESC LIMIT ?",
                             (int(limite),)).fetchall()
    corrispondenze = []
    for r in righe:
        testo = (r["estratto"] or "").casefold()
        if all(t.casefold() in testo for t in termini):
            corrispondenze.append(dict(r))
    domini: dict[str, list[dict[str, Any]]] = {}
    for c in corrispondenze:
        domini.setdefault(_dominio_registrabile(c["host"]), []).append(c)
    hash_visti: dict[str, str] = {}
    duplicati = []
    for c in corrispondenze:
        if c["sha256"] in hash_visti and hash_visti[c["sha256"]] != c["host"]:
            duplicati.append(c["url"])
        hash_visti.setdefault(c["sha256"], c["host"])
    indipendenti = len(domini)
    esito = ("non_riscontrata" if indipendenti == 0 else "fonte_singola" if indipendenti == 1
             else "riscontrata_in_piu_fonti")
    return {
        "termini": termini, "esito": esito, "fonti_indipendenti": indipendenti,
        "confermate_da_revisione": sum(1 for c in corrispondenze if c["stato"] == "confermato_documentale"),
        "contestate": sum(1 for c in corrispondenze if c["stato"] == "contestato"),
        "domini": {d: [x["url"] for x in v][:10] for d, v in domini.items()},
        "contenuti_identici_su_host_diversi": duplicati[:20],
        "nota": "Il riscontro in più fonti non prova un fatto: indica dove cercare conferme documentali.",
    }
