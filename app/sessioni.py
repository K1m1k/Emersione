"""Registro locale delle sessioni con revoca server-side.

SQLite è usato come baseline mononodo. Un deployment distribuito deve usare uno
store condiviso supportato dall'ente e una gestione centralizzata delle sessioni.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path

DB_PATH = Path(os.environ.get(
    "EMERSIONE_SESSION_DB",
    str(Path(__file__).resolve().parents[1] / "dati" / "sessioni.sqlite3"),
))
_TTL_DEFAULT = 8 * 60 * 60


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessioni (
        session_hash TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        creata INTEGER NOT NULL,
        scadenza INTEGER NOT NULL,
        revocata INTEGER
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessioni_username ON sessioni(username)")
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass
    return conn


def _hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


def crea(session_id: str, username: str, ttl: int = _TTL_DEFAULT) -> None:
    if not session_id or not username or ttl < 60 or ttl > 24 * 60 * 60:
        raise ValueError("Parametri di sessione non validi.")
    adesso = int(time.time())
    with closing(_conn()) as conn:
        conn.execute("DELETE FROM sessioni WHERE scadenza < ? OR revocata IS NOT NULL", (adesso - 86400,))
        conn.execute(
            "INSERT INTO sessioni(session_hash, username, creata, scadenza, revocata) VALUES(?,?,?,?,NULL)",
            (_hash(session_id), username, adesso, adesso + ttl),
        )


def valida(session_id: str | None, username: str | None) -> bool:
    if not session_id or not username:
        return False
    adesso = int(time.time())
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT 1 FROM sessioni WHERE session_hash=? AND username=? AND scadenza>? AND revocata IS NULL",
            (_hash(session_id), username, adesso),
        ).fetchone()
    return row is not None


def revoca(session_id: str | None) -> None:
    if not session_id:
        return
    with closing(_conn()) as conn:
        conn.execute("UPDATE sessioni SET revocata=? WHERE session_hash=? AND revocata IS NULL", (int(time.time()), _hash(session_id)))


def revoca_utente(username: str) -> int:
    """Revoca tutte le sessioni attive di un utente (es. account compromesso o ruolo cambiato)."""
    with closing(_conn()) as conn:
        cur = conn.execute("UPDATE sessioni SET revocata=? WHERE username=? AND revocata IS NULL", (int(time.time()), username))
        return cur.rowcount


def revoca_tutte() -> int:
    with closing(_conn()) as conn:
        cur = conn.execute("UPDATE sessioni SET revocata=? WHERE revocata IS NULL", (int(time.time()),))
        return cur.rowcount


def attive() -> list[dict]:
    adesso = int(time.time())
    with closing(_conn()) as conn:
        righe = conn.execute(
            "SELECT username, COUNT(*), MAX(creata), MAX(scadenza) FROM sessioni WHERE revocata IS NULL AND scadenza>? GROUP BY username",
            (adesso,)).fetchall()
    return [{"username": r[0], "sessioni": r[1], "ultima_creazione": r[2], "scadenza_massima": r[3]} for r in righe]
