"""Isola l'intera suite dai dati reali del progetto.

unittest carica i moduli di test in ordine alfabetico: questo modulo viene
importato per primo e, PRIMA che il codice dell'applicazione sia importato,
indirizza ogni archivio (database, audit, documenti, registro) verso una
cartella temporanea. Nessun test scrive in dati/ o config/ del progetto.
"""
import atexit
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_RADICE = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="emersione-test-"))
atexit.register(shutil.rmtree, _TMP, True)
shutil.copyfile(_RADICE / "config" / "registro_emersione.json", _TMP / "registro_emersione.json")
for variabile, nome in {
    "EMERSIONE_REGISTRO": "registro_emersione.json",
    "EMERSIONE_SESSION_DB": "sessioni.sqlite3",
    "EMERSIONE_DATASET_DB": "dataset.sqlite3",
    "EMERSIONE_OPERATIVO_DB": "operativo.sqlite3",
    "EMERSIONE_FONTI_DB": "fonti.sqlite3",
    "EMERSIONE_MAPPATURE_DB": "mappature.sqlite3",
    "EMERSIONE_OSINT_DB": "osint.sqlite3",
    "EMERSIONE_GRAFO_DB": "grafo.sqlite3",
    "EMERSIONE_AUDIT_PATH": "audit.jsonl",
    "EMERSIONE_DOCUMENTI_DIR": "documenti",
}.items():
    os.environ[variabile] = str(_TMP / nome)


class IsolamentoTests(unittest.TestCase):
    def test_percorsi_fuori_dal_progetto(self):
        from app import (audit, dataset_store, db_operativo, documenti, fonti_mapping, fonti_store, grafo, osint,
                         sessioni, settori)
        for percorso in (settori.PERCORSO_REGISTRO, sessioni.DB_PATH, dataset_store.DB_PATH, db_operativo.DB_PATH,
                         fonti_store.DB_PATH, fonti_mapping.DB_PATH, osint.DB_PATH, grafo.DB_PATH,
                         audit.PERCORSO_LOG, documenti._STORAGE):
            self.assertNotIn(str(_RADICE / "dati"), str(percorso))
            self.assertNotIn(str(_RADICE / "config"), str(percorso))
