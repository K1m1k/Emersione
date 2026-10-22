"""Archivio locale dei payload acquisiti da fonti ufficiali, con hash e metadati."""
from __future__ import annotations
import json
import os
import secrets
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any
from app.connettori.fonti_live import PayloadFonte, prova_parsabilita

DB_PATH = Path(os.environ.get("EMERSIONE_FONTI_DB", str(Path(__file__).resolve().parents[1] / "dati" / "emersione_fonti.sqlite3")))
_LOCK = threading.Lock()
_READY: set[str] = set()

class ErroreArchivioFonte(RuntimeError):
    pass

def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = str(DB_PATH.resolve())
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    if key not in _READY:
        with _LOCK:
            if key not in _READY:
                conn.execute("""CREATE TABLE IF NOT EXISTS acquisizioni_fonti (
                    id TEXT PRIMARY KEY, chiave TEXT NOT NULL, url TEXT NOT NULL,
                    acquisito_il TEXT NOT NULL, status_http INTEGER NOT NULL,
                    content_type TEXT NOT NULL, dimensione_byte INTEGER NOT NULL,
                    sha256 TEXT NOT NULL, formato TEXT NOT NULL, nota TEXT NOT NULL,
                    metadati_json TEXT NOT NULL, contenuto BLOB NOT NULL)""")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_fonti_data ON acquisizioni_fonti(acquisito_il DESC)")
                conn.commit()
                try: os.chmod(DB_PATH, 0o600)
                except OSError: pass
                _READY.add(key)
    return conn

def salva(payload: PayloadFonte) -> dict[str, Any]:
    analisi = prova_parsabilita(payload)
    identificativo = secrets.token_hex(16)
    try:
        with closing(_conn()) as conn:
            conn.execute("INSERT INTO acquisizioni_fonti VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                identificativo, payload.chiave, payload.url, payload.acquisito_il,
                payload.status_http, payload.content_type, payload.dimensione_byte,
                payload.sha256, analisi["formato"], analisi["nota"],
                json.dumps(payload.metadati, ensure_ascii=False), sqlite3.Binary(payload.contenuto)))
            conn.commit()
    except sqlite3.Error as exc:
        raise ErroreArchivioFonte("Acquisizione ricevuta ma non è stato possibile archiviarla in modo persistente.") from exc
    return {"id": identificativo, "chiave": payload.chiave, "url": payload.url,
        "acquisito_il": payload.acquisito_il, "status_http": payload.status_http,
        "content_type": payload.content_type, "dimensione_byte": payload.dimensione_byte,
        "sha256": payload.sha256, **analisi}

def elenco(limite: int = 50) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite), 100))
    with closing(_conn()) as conn:
        rows = conn.execute("SELECT id,chiave,url,acquisito_il,status_http,content_type,dimensione_byte,sha256,formato,nota FROM acquisizioni_fonti ORDER BY acquisito_il DESC LIMIT ?", (limite,)).fetchall()
    return [dict(r) for r in rows]

def contenuto(identificativo: str) -> tuple[dict[str, Any], bytes] | None:
    if not isinstance(identificativo, str) or len(identificativo) != 32 or any(c not in "0123456789abcdef" for c in identificativo):
        return None
    with closing(_conn()) as conn:
        row = conn.execute("SELECT id,chiave,content_type,sha256,contenuto FROM acquisizioni_fonti WHERE id=?", (identificativo,)).fetchone()
    if not row:
        return None
    import hashlib
    raw = bytes(row["contenuto"])
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise ErroreArchivioFonte("Integrità del payload non verificata: hash non corrispondente.")
    return ({"id": row["id"], "chiave": row["chiave"], "content_type": row["content_type"], "sha256": row["sha256"]}, raw)
