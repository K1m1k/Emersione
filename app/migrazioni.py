"""Stato e applicazione delle migrazioni dei database locali.

Uso (dalla cartella del progetto):
    python -m app.migrazioni stato
    python -m app.migrazioni applica

Gli altri archivi SQLite del prototipo (sessioni, lotto attivo, fonti, OSINT,
grafo) creano le proprie tabelle in modo idempotente all'apertura; l'archivio
operativo usa migrazioni numerate e registrate in PRAGMA user_version.
"""
from __future__ import annotations

import sys

from app import db_operativo


def main(argv: list[str]) -> int:
    comando = argv[0] if argv else "stato"
    if comando == "stato":
        attuale = db_operativo.versione_schema()
        print(f"Archivio operativo: {db_operativo.DB_PATH}")
        print(f"Versione schema: {attuale} (software: {db_operativo.VERSIONE_SCHEMA})")
        for numero, descrizione, _ in db_operativo.MIGRAZIONI:
            print(f"  [{'x' if numero <= attuale else ' '}] {numero}: {descrizione}")
        return 0
    if comando == "applica":
        applicate = db_operativo.applica_migrazioni()
        print("Nessuna migrazione da applicare." if not applicate else f"Applicate: {applicate}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
