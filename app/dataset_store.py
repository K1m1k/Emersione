"""Persistenza locale transazionale del lotto attivo.

Questa implementazione mononodo mantiene un solo lotto attivo, rendendo atomica
la sostituzione e permettendo il ripristino dopo un riavvio. Non sostituisce un
archivio istituzionale centralizzato con retention e audit approvati dall'ente.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_RECORDS = 25_000
MAX_ORIGINE = 500
VERSIONE_SCHEMA = 2
VERSIONE_MOTORE = "emersione-regole-dichiarative-v1"
DB_PATH = Path(os.environ.get(
    "EMERSIONE_DATASET_DB",
    str(Path(__file__).resolve().parents[1] / "dati" / "emersione_dataset.sqlite3"),
))
_SCHEMA_INIT: set[str] = set()
_SCHEMA_LOCK = threading.Lock()


class ErrorePersistenza(RuntimeError):
    """Il lotto non può essere letto o salvato in modo sicuro."""


def hash_configurazione() -> str:
    """Hash canonico delle sole definizioni che incidono sui calcoli."""
    try:
        from app import settori
        configurazione = json.loads(settori.PERCORSO_REGISTRO.read_text(encoding="utf-8"))
        rilevante = {
            "versione": configurazione.get("versione"),
            "settori": configurazione.get("settori"),
            "parametri": configurazione.get("parametri"),
        }
        canonico = json.dumps(rilevante, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ErrorePersistenza("Impossibile verificare la configurazione dei settori e dei parametri.") from exc
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = str(DB_PATH.resolve())
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0, isolation_level=None)
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        if key not in _SCHEMA_INIT:
            with _SCHEMA_LOCK:
                if key not in _SCHEMA_INIT:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("""CREATE TABLE IF NOT EXISTS lotto_attivo (
                        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                        lotto_id TEXT NOT NULL,
                        origine TEXT NOT NULL,
                        sintetico INTEGER NOT NULL CHECK(sintetico IN (0,1)),
                        numero_record INTEGER NOT NULL CHECK(numero_record > 0),
                        creato_il TEXT NOT NULL,
                        hash_origine TEXT,
                        hash_dataset TEXT NOT NULL DEFAULT '',
                        hash_configurazione TEXT NOT NULL DEFAULT '',
                        versione_schema INTEGER NOT NULL,
                        versione_motore TEXT NOT NULL
                    )""")
                    # Migrazione incrementale del database locale della versione precedente.
                    colonne = {riga[1] for riga in conn.execute("PRAGMA table_info(lotto_attivo)").fetchall()}
                    if "hash_dataset" not in colonne:
                        conn.execute("ALTER TABLE lotto_attivo ADD COLUMN hash_dataset TEXT NOT NULL DEFAULT ''")
                    if "hash_configurazione" not in colonne:
                        conn.execute("ALTER TABLE lotto_attivo ADD COLUMN hash_configurazione TEXT NOT NULL DEFAULT ''")
                    conn.execute("""CREATE TABLE IF NOT EXISTS record_attivi (
                        posizione INTEGER PRIMARY KEY,
                        record_json TEXT NOT NULL
                    )""")
                    try:
                        os.chmod(DB_PATH, 0o600)
                    except OSError:
                        pass
                    _SCHEMA_INIT.add(key)
        return conn
    except sqlite3.Error as exc:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        raise ErrorePersistenza("Archivio locale non disponibile.") from exc


def _serializza_record(aziende: list[dict[str, Any]]) -> list[str]:
    if not isinstance(aziende, list) or not aziende or len(aziende) > MAX_RECORDS:
        raise ErrorePersistenza(f"Il lotto deve contenere da 1 a {MAX_RECORDS} record.")
    serializzati: list[str] = []
    for indice, azienda in enumerate(aziende):
        if not isinstance(azienda, dict):
            raise ErrorePersistenza(f"Record {indice + 1} non valido.")
        try:
            serializzati.append(json.dumps(azienda, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")))
        except (TypeError, ValueError) as exc:
            raise ErrorePersistenza(f"Record {indice + 1} contiene dati non serializzabili o non finiti.") from exc
    return serializzati


def salva_attivo(
    aziende: list[dict[str, Any]],
    *,
    origine: str,
    sintetico: bool,
    hash_origine: str | None = None,
) -> dict[str, Any]:
    """Sostituisce il lotto attivo in una transazione atomica."""
    if not isinstance(origine, str) or not origine.strip() or len(origine) > MAX_ORIGINE:
        raise ErrorePersistenza("Descrizione di provenienza non valida.")
    if not isinstance(sintetico, bool):
        raise ErrorePersistenza("Il tipo di dataset deve essere esplicito.")
    if hash_origine is not None and (not isinstance(hash_origine, str) or len(hash_origine) != 64 or any(c not in "0123456789abcdef" for c in hash_origine.casefold())):
        raise ErrorePersistenza("Hash della fonte non valido.")

    serializzati = _serializza_record(aziende)
    lotto_id = secrets.token_hex(16)
    creato_il = datetime.now(timezone.utc).isoformat(timespec="seconds")
    hash_dataset = hashlib.sha256("\n".join(serializzati).encode("utf-8")).hexdigest()
    hash_config = hash_configurazione()
    hash_sorgente = hash_origine.casefold() if hash_origine is not None else None

    with closing(_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM record_attivi")
            conn.executemany(
                "INSERT INTO record_attivi(posizione, record_json) VALUES(?,?)",
                [(indice, contenuto) for indice, contenuto in enumerate(serializzati)],
            )
            conn.execute(
                """INSERT INTO lotto_attivo(singleton, lotto_id, origine, sintetico, numero_record,
                   creato_il, hash_origine, hash_dataset, hash_configurazione, versione_schema, versione_motore)
                   VALUES(1,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(singleton) DO UPDATE SET
                     lotto_id=excluded.lotto_id,
                     origine=excluded.origine,
                     sintetico=excluded.sintetico,
                     numero_record=excluded.numero_record,
                     creato_il=excluded.creato_il,
                     hash_origine=excluded.hash_origine,
                     hash_dataset=excluded.hash_dataset,
                     hash_configurazione=excluded.hash_configurazione,
                     versione_schema=excluded.versione_schema,
                     versione_motore=excluded.versione_motore""",
                (lotto_id, origine.strip(), int(sintetico), len(serializzati), creato_il,
                 hash_sorgente, hash_dataset, hash_config, VERSIONE_SCHEMA, VERSIONE_MOTORE),
            )
            conn.execute("COMMIT")
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            if isinstance(exc, ErrorePersistenza):
                raise
            raise ErrorePersistenza("Il lotto non è stato salvato; il lotto precedente resta attivo.") from exc

    return {
        "lotto_id": lotto_id,
        "origine": origine.strip(),
        "sintetico": sintetico,
        "numero_record": len(serializzati),
        "creato_il": creato_il,
        "hash_origine": hash_sorgente,
        "hash_dataset": hash_dataset,
        "hash_configurazione": hash_config,
        "versione_schema": VERSIONE_SCHEMA,
        "versione_motore": VERSIONE_MOTORE,
    }


def carica_attivo() -> dict[str, Any] | None:
    """Restituisce il lotto persistito; un archivio corrotto non diventa demo sintetica."""
    with closing(_conn()) as conn:
        metadata = conn.execute(
            """SELECT lotto_id, origine, sintetico, numero_record, creato_il, hash_origine,
                      hash_dataset, hash_configurazione, versione_schema, versione_motore
               FROM lotto_attivo WHERE singleton=1"""
        ).fetchone()
        if metadata is None:
            return None
        rows = conn.execute("SELECT posizione, record_json FROM record_attivi ORDER BY posizione").fetchall()

    try:
        if len(rows) != metadata[3] or not rows:
            raise ErrorePersistenza("L'archivio attivo presenta un numero di record incoerente.")
        aziende: list[dict[str, Any]] = []
        for expected_position, row in enumerate(rows):
            posizione, contenuto = row
            if posizione != expected_position:
                raise ErrorePersistenza("L'archivio attivo presenta posizioni mancanti o duplicate.")
            record = json.loads(contenuto)
            if not isinstance(record, dict):
                raise ErrorePersistenza("Un record persistito non è un oggetto valido.")
            aziende.append(record)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ErrorePersistenza("L'archivio attivo è corrotto o non leggibile.") from exc

    try:
        hash_attuale = hash_configurazione()
    except ErrorePersistenza:
        hash_attuale = ""
    hash_salvato = metadata[7] or ""
    return {
        "aziende": aziende,
        "metadati": {
            "lotto_id": metadata[0],
            "origine": metadata[1],
            "sintetico": bool(metadata[2]),
            "numero_record": metadata[3],
            "creato_il": metadata[4],
            "hash_origine": metadata[5],
            "hash_dataset": metadata[6],
            "hash_configurazione": hash_salvato,
            "configurazione_corrente": bool(hash_salvato) and hash_salvato == hash_attuale,
            "versione_schema": metadata[8],
            "versione_motore": metadata[9],
        },
    }
