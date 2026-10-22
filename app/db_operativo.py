"""Archivio operativo SQLite con migrazioni versionate.

Contiene i dati che devono sopravvivere al riavvio e restare ricostruibili:
  - esecuzioni del motore e risultati per azienda (analisi storiche);
  - collaudi automatici e approvazioni dei settori;
  - pratiche di approfondimento e loro eventi.

Le migrazioni sono applicate in ordine e registrate in PRAGMA user_version.
Ogni migrazione viene eseguita in una transazione: se fallisce lo schema resta
alla versione precedente. Baseline mononodo: per un impiego istituzionale va
valutato PostgreSQL con le stesse tabelle (vedi docs/B_ARCHITETTURA.md).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get(
    "EMERSIONE_OPERATIVO_DB",
    str(Path(__file__).resolve().parents[1] / "dati" / "emersione_operativo.sqlite3"),
))
_LOCK = threading.RLock()
_INIZIALIZZATI: set[str] = set()


class ErroreDB(RuntimeError):
    pass


MIGRAZIONI: list[tuple[int, str, str]] = [
    (1, "Schema iniziale: esecuzioni del motore e risultati per azienda", """
        CREATE TABLE esecuzioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eseguita_il TEXT NOT NULL,
            utente TEXT NOT NULL,
            motivo TEXT NOT NULL,
            versione_motore TEXT NOT NULL,
            hash_configurazione TEXT NOT NULL,
            hash_dataset TEXT,
            origine TEXT NOT NULL,
            sintetico INTEGER NOT NULL CHECK (sintetico IN (0,1)),
            numero_record INTEGER NOT NULL CHECK (numero_record >= 0),
            riepilogo TEXT NOT NULL
        );
        CREATE INDEX idx_esecuzioni_data ON esecuzioni(eseguita_il);
        CREATE TABLE risultati (
            esecuzione_id INTEGER NOT NULL REFERENCES esecuzioni(id) ON DELETE CASCADE,
            azienda_id TEXT NOT NULL,
            settore TEXT,
            punteggio REAL,
            livello TEXT NOT NULL,
            analisi TEXT NOT NULL,
            PRIMARY KEY (esecuzione_id, azienda_id)
        );
        CREATE INDEX idx_risultati_azienda ON risultati(azienda_id);
    """),
    (2, "Collaudi e approvazioni dei settori", """
        CREATE TABLE collaudi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            settore_id TEXT NOT NULL,
            hash_settore TEXT NOT NULL,
            eseguito_il TEXT NOT NULL,
            utente TEXT NOT NULL,
            superato INTEGER NOT NULL CHECK (superato IN (0,1)),
            risultato TEXT NOT NULL
        );
        CREATE INDEX idx_collaudi_settore ON collaudi(settore_id, id);
        CREATE TABLE transizioni_settore (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            settore_id TEXT NOT NULL,
            da_stato TEXT NOT NULL,
            a_stato TEXT NOT NULL,
            utente TEXT NOT NULL,
            ruolo TEXT NOT NULL,
            motivazione TEXT NOT NULL,
            evidenza TEXT,
            hash_settore TEXT NOT NULL,
            collaudo_id INTEGER REFERENCES collaudi(id),
            registrata_il TEXT NOT NULL
        );
        CREATE INDEX idx_transizioni_settore ON transizioni_settore(settore_id, id);
    """),
    (3, "Pratiche di approfondimento", """
        CREATE TABLE pratiche (
            id TEXT PRIMARY KEY,
            azienda_id TEXT NOT NULL,
            esecuzione_id INTEGER REFERENCES esecuzioni(id),
            finalita TEXT NOT NULL,
            ambito TEXT NOT NULL,
            stato TEXT NOT NULL,
            creata_da TEXT NOT NULL,
            creata_il TEXT NOT NULL,
            aggiornata_il TEXT NOT NULL,
            assegnata_a TEXT
        );
        CREATE INDEX idx_pratiche_azienda ON pratiche(azienda_id);
        CREATE TABLE pratiche_eventi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pratica_id TEXT NOT NULL REFERENCES pratiche(id) ON DELETE CASCADE,
            quando TEXT NOT NULL,
            utente TEXT NOT NULL,
            tipo TEXT NOT NULL,
            nota TEXT NOT NULL
        );
        CREATE INDEX idx_pratiche_eventi ON pratiche_eventi(pratica_id, id);
    """),
    (4, "Registro delle relazioni PDF generate (verifica d'integrità)", """
        CREATE TABLE report_generati (
            id TEXT PRIMARY KEY,
            generato_il TEXT NOT NULL,
            utente TEXT NOT NULL,
            ruolo TEXT NOT NULL,
            azienda_id TEXT NOT NULL,
            pratica_id TEXT REFERENCES pratiche(id),
            esecuzione_id INTEGER REFERENCES esecuzioni(id),
            sha256 TEXT NOT NULL,
            byte INTEGER NOT NULL
        );
        CREATE INDEX idx_report_sha ON report_generati(sha256);
    """),
    (5, "Catalogo dei dataset scoperti e proposte di collegamento ai parametri", """
        CREATE TABLE catalogo_dataset (
            fonte TEXT NOT NULL,
            identificativo TEXT NOT NULL,
            nome TEXT NOT NULL,
            descrizione TEXT NOT NULL,
            url_dati TEXT,
            licenza TEXT,
            scoperto_il TEXT NOT NULL,
            hash_catalogo TEXT NOT NULL,
            PRIMARY KEY (fonte, identificativo)
        );
        CREATE TABLE proposte_parametri (
            id TEXT PRIMARY KEY,
            parametro_id TEXT NOT NULL,
            valore_proposto REAL NOT NULL,
            unita_osservazioni TEXT NOT NULL,
            unita_parametro TEXT NOT NULL,
            unita_compatibili INTEGER NOT NULL CHECK (unita_compatibili IN (0,1)),
            mappatura_id TEXT NOT NULL,
            filtro TEXT NOT NULL,
            statistica TEXT NOT NULL,
            numero_osservazioni INTEGER NOT NULL,
            provenienza TEXT NOT NULL,
            stato TEXT NOT NULL CHECK (stato IN ('proposta','applicata','respinta')),
            creata_da TEXT NOT NULL,
            creata_il TEXT NOT NULL,
            decisa_da TEXT,
            decisa_il TEXT,
            nota_decisione TEXT
        );
        CREATE INDEX idx_proposte_parametro ON proposte_parametri(parametro_id, stato);
    """),
    (6, "Provenienza dei lotti importati (sezioni 10 e 13)", """
        CREATE TABLE provenienza_lotti (
            lotto_id TEXT PRIMARY KEY,
            file TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            conferente TEXT NOT NULL,
            titolare TEXT NOT NULL,
            finalita TEXT NOT NULL,
            autorizzazione TEXT NOT NULL,
            data_ricezione TEXT NOT NULL,
            scadenza_autorizzazione TEXT,
            condizioni_uso TEXT NOT NULL,
            caricato_da TEXT NOT NULL,
            caricato_il TEXT NOT NULL,
            stato TEXT NOT NULL CHECK (stato IN ('attivo','sostituito','revocato')),
            revocato_da TEXT,
            revocato_il TEXT,
            motivo_revoca TEXT
        );
    """),
]

VERSIONE_SCHEMA = MIGRAZIONI[-1][0]


def adesso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _apri(percorso: Path) -> sqlite3.Connection:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(percorso, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=FULL")
    try:
        os.chmod(percorso, 0o600)
    except OSError:
        pass
    return conn


def versione_schema(percorso: Path | None = None) -> int:
    percorso = percorso or DB_PATH
    if not percorso.exists():
        return 0
    with closing(_apri(percorso)) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def applica_migrazioni(percorso: Path | None = None) -> list[int]:
    """Applica le migrazioni mancanti; restituisce le versioni applicate."""
    percorso = percorso or DB_PATH
    applicate: list[int] = []
    with _LOCK, closing(_apri(percorso)) as conn:
        attuale = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if attuale > VERSIONE_SCHEMA:
            raise ErroreDB(f"Schema del database ({attuale}) più recente del software ({VERSIONE_SCHEMA}): aggiornare il software.")
        for numero, _descrizione, sql in MIGRAZIONI:
            if numero <= attuale:
                continue
            conn.execute("BEGIN IMMEDIATE")
            try:
                for istruzione in [s.strip() for s in sql.split(";") if s.strip()]:
                    conn.execute(istruzione)
                conn.execute(f"PRAGMA user_version={int(numero)}")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            applicate.append(numero)
    return applicate


def connessione() -> sqlite3.Connection:
    chiave = str(DB_PATH.resolve())
    if chiave not in _INIZIALIZZATI or not DB_PATH.exists():
        applica_migrazioni(DB_PATH)
        _INIZIALIZZATI.add(chiave)
    return _apri(DB_PATH)


# ---------------------------------------------------------------------------
# Esecuzioni del motore
# ---------------------------------------------------------------------------

def _riepilogo(aziende: list[dict[str, Any]]) -> dict[str, Any]:
    livelli: dict[str, int] = {}
    settori: dict[str, int] = {}
    for a in aziende:
        livello = (a.get("analisi") or {}).get("livello", "non_valutabile")
        livelli[livello] = livelli.get(livello, 0) + 1
        s = str(a.get("settore", ""))
        settori[s] = settori.get(s, 0) + 1
    return {"livelli": livelli, "settori": settori}


def registra_esecuzione(aziende: list[dict[str, Any]], *, utente: str, motivo: str,
                        versione_motore: str, hash_configurazione: str,
                        hash_dataset: str | None, origine: str, sintetico: bool) -> int:
    """Salva l'esecuzione e i risultati di ogni azienda in una sola transazione.

    Le etichette di valutazione non vengono mai salvate nei risultati.
    """
    with _LOCK, closing(connessione()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cur = conn.execute(
                """INSERT INTO esecuzioni(eseguita_il, utente, motivo, versione_motore, hash_configurazione,
                   hash_dataset, origine, sintetico, numero_record, riepilogo) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (adesso(), utente[:100], motivo[:200], versione_motore, hash_configurazione,
                 hash_dataset, origine[:500], 1 if sintetico else 0, len(aziende),
                 json.dumps(_riepilogo(aziende), ensure_ascii=False)),
            )
            esecuzione_id = int(cur.lastrowid)
            conn.executemany(
                "INSERT INTO risultati(esecuzione_id, azienda_id, settore, punteggio, livello, analisi) VALUES (?,?,?,?,?,?)",
                [
                    (esecuzione_id, str(a.get("id")), a.get("settore"),
                     (a.get("analisi") or {}).get("punteggio"),
                     (a.get("analisi") or {}).get("livello", "non_valutabile"),
                     json.dumps(a.get("analisi") or {}, ensure_ascii=False, default=str))
                    for a in aziende if a.get("id") is not None
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return esecuzione_id


def elenco_esecuzioni(limite: int = 50) -> list[dict[str, Any]]:
    with closing(connessione()) as conn:
        righe = conn.execute("SELECT * FROM esecuzioni ORDER BY id DESC LIMIT ?", (int(limite),)).fetchall()
    out = []
    for r in righe:
        d = dict(r)
        d["riepilogo"] = json.loads(d["riepilogo"])
        out.append(d)
    return out


def ottieni_esecuzione(esecuzione_id: int) -> dict[str, Any] | None:
    with closing(connessione()) as conn:
        r = conn.execute("SELECT * FROM esecuzioni WHERE id=?", (int(esecuzione_id),)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["riepilogo"] = json.loads(d["riepilogo"])
    return d


def risultato_storico(esecuzione_id: int, azienda_id: str) -> dict[str, Any] | None:
    with closing(connessione()) as conn:
        r = conn.execute("SELECT analisi FROM risultati WHERE esecuzione_id=? AND azienda_id=?",
                         (int(esecuzione_id), azienda_id)).fetchone()
    return json.loads(r["analisi"]) if r else None


def storico_azienda(azienda_id: str, limite: int = 20) -> list[dict[str, Any]]:
    with closing(connessione()) as conn:
        righe = conn.execute(
            """SELECT e.id, e.eseguita_il, e.hash_configurazione, e.versione_motore, r.punteggio, r.livello
               FROM risultati r JOIN esecuzioni e ON e.id = r.esecuzione_id
               WHERE r.azienda_id=? ORDER BY e.id DESC LIMIT ?""",
            (azienda_id, int(limite)),
        ).fetchall()
    return [dict(r) for r in righe]


def esecuzioni_con_configurazione(hash_configurazione: str) -> list[int]:
    with closing(connessione()) as conn:
        return [int(r[0]) for r in conn.execute(
            "SELECT id FROM esecuzioni WHERE hash_configurazione=? ORDER BY id", (hash_configurazione,))]


def esecuzioni_che_usano_parametro(parametro_id: str, limite: int = 1000) -> list[int]:
    """Esecuzioni in cui il parametro è comparso nella formula di almeno un'azienda."""
    modello = f'%"id": "{parametro_id}"%'
    with closing(connessione()) as conn:
        return [int(r[0]) for r in conn.execute(
            "SELECT DISTINCT esecuzione_id FROM risultati WHERE analisi LIKE ? ORDER BY esecuzione_id DESC LIMIT ?",
            (modello, int(limite)))]


# ---------------------------------------------------------------------------
# Relazioni PDF generate
# ---------------------------------------------------------------------------

def registra_report(*, report_id: str, utente: str, ruolo: str, azienda_id: str, pratica_id: str | None,
                    esecuzione_id: int | None, sha256: str, byte: int) -> None:
    with closing(connessione()) as conn:
        conn.execute(
            """INSERT INTO report_generati(id, generato_il, utente, ruolo, azienda_id, pratica_id, esecuzione_id, sha256, byte)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (report_id, adesso(), utente[:100], ruolo, azienda_id, pratica_id, esecuzione_id, sha256, int(byte)))


def verifica_report(sha256: str) -> dict[str, Any] | None:
    """Indica se un PDF con questo hash è stato generato da questa istanza (non ne attesta il contenuto)."""
    with closing(connessione()) as conn:
        r = conn.execute("SELECT * FROM report_generati WHERE sha256=? ORDER BY generato_il DESC LIMIT 1", (sha256,)).fetchone()
    return dict(r) if r else None
