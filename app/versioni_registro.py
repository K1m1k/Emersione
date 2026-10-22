"""Storico completo e non troncato delle versioni del registro settori/parametri.

Ogni salvataggio del registro conserva qui una copia integrale, identificata
dall'hash SHA-256 del contenuto canonico. L'archivio sta accanto al registro
(stessa cartella) perché ne è la storia: backup e ripristino li trattano insieme.
Lo storico non viene mai riscritto: il ripristino di una versione crea una nuova
versione, non cancella le successive.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def percorso() -> Path:
    from app import settori
    return Path(settori.PERCORSO_REGISTRO).with_name("registro_versioni.sqlite3")


def _conn() -> sqlite3.Connection:
    p = percorso()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("""CREATE TABLE IF NOT EXISTS versioni (
        progressivo INTEGER PRIMARY KEY AUTOINCREMENT,
        hash TEXT NOT NULL,
        registrata_il TEXT NOT NULL,
        autore TEXT NOT NULL,
        motivo TEXT NOT NULL,
        contenuto TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_versioni_hash ON versioni(hash)")
    try:
        os.chmod(p, 0o640)
    except OSError:
        pass
    return conn


def hash_registro(dati: dict[str, Any]) -> str:
    canonico = json.dumps(dati, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def registra(dati: dict[str, Any], *, autore: str = "sistema", motivo: str = "salvataggio registro") -> str:
    """Aggiunge una versione se diversa dall'ultima registrata."""
    h = hash_registro(dati)
    with closing(_conn()) as conn:
        ultima = conn.execute("SELECT hash FROM versioni ORDER BY progressivo DESC LIMIT 1").fetchone()
        if ultima is None or ultima["hash"] != h:
            conn.execute(
                "INSERT INTO versioni(hash, registrata_il, autore, motivo, contenuto) VALUES (?,?,?,?,?)",
                (h, datetime.now(timezone.utc).isoformat(timespec="seconds"), str(autore)[:100], str(motivo)[:200],
                 json.dumps(dati, ensure_ascii=False, sort_keys=True)),
            )
    return h


def elenco(limite: int = 200) -> list[dict[str, Any]]:
    with closing(_conn()) as conn:
        righe = conn.execute(
            "SELECT progressivo, hash, registrata_il, autore, motivo FROM versioni ORDER BY progressivo DESC LIMIT ?",
            (int(limite),)).fetchall()
    return [dict(r) for r in righe]


def leggi(progressivo: int) -> dict[str, Any] | None:
    with closing(_conn()) as conn:
        r = conn.execute("SELECT contenuto FROM versioni WHERE progressivo=?", (int(progressivo),)).fetchone()
    return json.loads(r["contenuto"]) if r else None


def leggi_per_hash(h: str) -> dict[str, Any] | None:
    with closing(_conn()) as conn:
        r = conn.execute("SELECT contenuto FROM versioni WHERE hash=? ORDER BY progressivo DESC LIMIT 1", (h,)).fetchone()
    return json.loads(r["contenuto"]) if r else None


def configurazione_settore_storica(hash_configurazione: str, settore_id: str) -> dict[str, Any] | None:
    """Ricostruisce settore e parametri usati da un'analisi a partire dall'hash di configurazione
    registrato nell'esecuzione (hash su versione+settori+parametri)."""
    with closing(_conn()) as conn:
        righe = conn.execute("SELECT contenuto FROM versioni ORDER BY progressivo DESC").fetchall()
    for r in righe:
        dati = json.loads(r["contenuto"])
        rilevante = {"versione": dati.get("versione"), "settori": dati.get("settori"), "parametri": dati.get("parametri")}
        canonico = json.dumps(rilevante, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
        if hashlib.sha256(canonico.encode("utf-8")).hexdigest() == hash_configurazione:
            settore = (dati.get("settori") or {}).get(settore_id)
            return {"settore": settore, "parametri": dati.get("parametri")} if settore else None
    return None
