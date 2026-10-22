"""Acquisizione puntuale di fonti web aperte, su host autorizzati dall'ente.

Non esegue crawling ricorsivo né assegna giudizi di attendibilità/illecito. Il
contenuto acquisito è una fonte da verificare; redirect e URL fuori allowlist
sono rifiutati per ridurre il rischio SSRF.
"""
from __future__ import annotations
import hashlib
import html
import ipaddress
import os
import re
import socket
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("EMERSIONE_OSINT_DB", str(Path(__file__).resolve().parents[1] / "dati" / "emersione_osint.sqlite3")))
MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 120_000
_LOCK = threading.Lock()
_READY: set[str] = set()

class ErroreOSINT(ValueError):
    pass

class _EstrattoreHTML(HTMLParser):
    SALTA = {"script", "style", "noscript", "svg", "canvas", "iframe", "nav", "footer", "form", "header"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.testi: list[str] = []
        self.titolo: list[str] = []
        self.in_titolo = False
    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        if tag == "title": self.in_titolo = True
    def handle_endtag(self, tag):
        if tag == "title": self.in_titolo = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i] == tag:
                del self.stack[i:]
                break
    def handle_data(self, data):
        val = re.sub(r"\s+", " ", data).strip()
        if not val: return
        if self.in_titolo:
            self.titolo.append(val)
        if not any(t in self.SALTA for t in self.stack) and len(" ".join(self.testi)) < MAX_TEXT:
            self.testi.append(val)


def domini_autorizzati() -> list[str]:
    valori = os.environ.get("EMERSIONE_OSINT_ALLOWED_DOMAINS", "")
    output: list[str] = []
    for valore in valori.split(","):
        host = valore.strip().casefold().rstrip(".")
        if host and re.fullmatch(r"[a-z0-9.-]{1,253}", host) and ".." not in host and not host.startswith("."):
            output.append(host)
    return sorted(set(output))


def _host_autorizzato(host: str, domini: list[str]) -> bool:
    host = host.casefold().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domini)


def _valida_url(url: str) -> urllib.parse.ParseResult:
    if not isinstance(url, str) or len(url) > 2000:
        raise ErroreOSINT("URL assente o troppo lungo.")
    try:
        p = urllib.parse.urlparse(url.strip())
        port = p.port
    except ValueError as exc:
        raise ErroreOSINT("URL non valido.") from exc
    host = (p.hostname or "").casefold().rstrip(".")
    if p.scheme != "https" or not host or p.username or p.password or port not in (None, 443) or p.fragment:
        raise ErroreOSINT("Sono ammessi soltanto URL HTTPS pubblici senza credenziali o frammenti.")
    domini = domini_autorizzati()
    if not domini:
        raise ErroreOSINT("Nessun dominio OSINT è autorizzato. Configura EMERSIONE_OSINT_ALLOWED_DOMAINS dopo la verifica della fonte.")
    if not _host_autorizzato(host, domini):
        raise ErroreOSINT("Dominio non presente nell'allowlist OSINT dell'ente.")
    try:
        risolti = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ErroreOSINT("Il dominio della fonte non è risolvibile.") from exc
    if not risolti:
        raise ErroreOSINT("Il dominio della fonte non ha indirizzi risolti.")
    for record in risolti:
        try:
            ip = ipaddress.ip_address(record[4][0])
        except ValueError as exc:
            raise ErroreOSINT("Il dominio ha restituito un indirizzo IP non valido.") from exc
        if not ip.is_global:
            raise ErroreOSINT("Dominio risolto verso un indirizzo non pubblico; acquisizione bloccata.")
    return p

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = str(DB_PATH.resolve())
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    if key not in _READY:
        with _LOCK:
            if key not in _READY:
                conn.execute("""CREATE TABLE IF NOT EXISTS osservazioni_osint(
                    id TEXT PRIMARY KEY, url TEXT NOT NULL, host TEXT NOT NULL, titolo TEXT NOT NULL,
                    estratto TEXT NOT NULL, sha256 TEXT NOT NULL, content_type TEXT NOT NULL,
                    acquisito_il TEXT NOT NULL, acquisito_da TEXT NOT NULL, motivazione TEXT NOT NULL,
                    stato TEXT NOT NULL, byte_originali INTEGER NOT NULL, contenuto_originale BLOB NOT NULL,
                    nota_revisore TEXT NOT NULL DEFAULT '', revisionato_da TEXT NOT NULL DEFAULT '',
                    revisionato_il TEXT NOT NULL DEFAULT '')""")
                colonne = {r[1] for r in conn.execute("PRAGMA table_info(osservazioni_osint)").fetchall()}
                for nome in ("nota_revisore", "revisionato_da", "revisionato_il"):
                    if nome not in colonne:
                        conn.execute(f"ALTER TABLE osservazioni_osint ADD COLUMN {nome} TEXT NOT NULL DEFAULT ''")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_osint_data ON osservazioni_osint(acquisito_il DESC)")
                conn.commit()
                try: os.chmod(DB_PATH, 0o600)
                except OSError: pass
                _READY.add(key)
    return conn


def acquisisci(url: str, *, utente: str, motivazione: str) -> dict[str, Any]:
    motivazione = (motivazione or "").strip()
    if not isinstance(utente, str) or not utente.strip() or len(utente) > 100:
        raise ErroreOSINT("Identità dell'operatore non valida.")
    if len(motivazione) < 15 or len(motivazione) > 1000:
        raise ErroreOSINT("Indica una motivazione specifica (15–1000 caratteri).")
    p = _valida_url(url)
    richiesta = urllib.request.Request(p.geturl(), headers={
        "User-Agent": "Emersione-OSINT/0.3 (single-page evidence collection)",
        "Accept": "text/html, text/plain, application/xhtml+xml;q=0.9",
        "Accept-Encoding": "identity",
    }, method="GET")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(richiesta, timeout=12) as risposta:
            status = int(getattr(risposta, "status", 200))
            content_type = (risposta.headers.get("Content-Type") or "").split(";", 1)[0].strip().casefold()
            length = risposta.headers.get("Content-Length")
            if length and int(length) > MAX_BYTES:
                raise ErroreOSINT("La pagina supera il limite di 2 MiB.")
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise ErroreOSINT("Formato non supportato: sono accettate solo pagine HTML/XHTML o testo semplice.")
            raw = risposta.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            raise ErroreOSINT("Redirect rifiutato. Verifica il dominio di destinazione e inserisci direttamente l'URL finale autorizzato.") from exc
        raise ErroreOSINT(f"La fonte ha restituito HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise ErroreOSINT("Connessione alla fonte non riuscita.") from exc
    except (TimeoutError, OSError) as exc:
        raise ErroreOSINT("Timeout o errore durante l'acquisizione.") from exc
    if len(raw) > MAX_BYTES:
        raise ErroreOSINT("La pagina supera il limite di 2 MiB.")
    try:
        testo = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError:
        try: testo = raw.decode("latin-1", errors="strict")
        except UnicodeDecodeError as exc: raise ErroreOSINT("Codifica della pagina non supportata.") from exc
    if content_type in {"text/html", "application/xhtml+xml"}:
        estrattore = _EstrattoreHTML()
        try: estrattore.feed(testo)
        except Exception as exc: raise ErroreOSINT("HTML non interpretabile in modo sicuro.") from exc
        titolo = re.sub(r"\s+", " ", " ".join(estrattore.titolo)).strip()[:300]
        estratto = re.sub(r"\s+", " ", " ".join(estrattore.testi)).strip()[:MAX_TEXT]
    else:
        titolo = p.hostname or "Fonte testuale"
        estratto = re.sub(r"\s+", " ", html.unescape(testo)).strip()[:MAX_TEXT]
    if not estratto:
        raise ErroreOSINT("Nessun testo utilizzabile è stato estratto dalla fonte.")
    import secrets
    ident = secrets.token_hex(16)
    acquired = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = hashlib.sha256(raw).hexdigest()
    with closing(_conn()) as conn:
        conn.execute("""INSERT INTO osservazioni_osint
            (id,url,host,titolo,estratto,sha256,content_type,acquisito_il,acquisito_da,motivazione,stato,byte_originali,contenuto_originale)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            ident, p.geturl(), p.hostname or "", titolo, estratto, sha, content_type,
            acquired, utente[:100], motivazione, "da_verificare", len(raw), sqlite3.Binary(raw)))
        conn.commit()
    return {"id": ident, "url": p.geturl(), "host": p.hostname, "titolo": titolo,
            "estratto": estratto, "sha256": sha, "content_type": content_type,
            "acquisito_il": acquired, "acquisito_da": utente[:100], "motivazione": motivazione,
            "stato": "da_verificare", "byte_originali": len(raw)}


def elenco(limite: int = 100) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite), 200))
    with closing(_conn()) as conn:
        righe = conn.execute("SELECT id,url,host,titolo,estratto,sha256,content_type,acquisito_il,acquisito_da,motivazione,stato,byte_originali,nota_revisore,revisionato_da,revisionato_il FROM osservazioni_osint ORDER BY acquisito_il DESC LIMIT ?", (limite,)).fetchall()
    return [dict(r) for r in righe]


def rivedi(identificativo: str, stato: str, revisore: str, nota: str) -> None:
    if stato not in {"confermato_documentale", "non_pertinente", "contestato", "da_verificare"}:
        raise ErroreOSINT("Stato di revisione non valido.")
    if not isinstance(identificativo, str) or not re.fullmatch(r"[a-f0-9]{32}", identificativo):
        raise ErroreOSINT("Identificativo osservazione non valido.")
    if not nota.strip() or len(nota) < 10 or len(nota) > 1000:
        raise ErroreOSINT("La revisione richiede una nota da 10 a 1000 caratteri.")
    if not isinstance(revisore, str) or not revisore.strip() or len(revisore) > 100:
        raise ErroreOSINT("Identità del revisore non valida.")
    with closing(_conn()) as conn:
        cur = conn.execute("UPDATE osservazioni_osint SET stato=?,nota_revisore=?,revisionato_da=?,revisionato_il=? WHERE id=?",
            (stato, nota.strip(), revisore.strip(), datetime.now(timezone.utc).isoformat(timespec="seconds"), identificativo))
        conn.commit()
        if cur.rowcount != 1:
            raise ErroreOSINT("Osservazione non trovata.")
