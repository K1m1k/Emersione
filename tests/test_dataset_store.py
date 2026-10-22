import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import dataset_store


class DatasetStoreTests(unittest.TestCase):
    def test_persistenza_e_ripristino_lotto_attivo(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "dataset.sqlite3"
            with patch.object(dataset_store, "DB_PATH", db):
                rows = [{"id": "T1", "settore": "agricoltura", "analisi": {"punteggio": None}}]
                metadata = dataset_store.salva_attivo(rows, origine="dataset sintetico di test", sintetico=True)
                loaded = dataset_store.carica_attivo()
                self.assertEqual(loaded["aziende"], rows)
                self.assertEqual(loaded["metadati"]["lotto_id"], metadata["lotto_id"])
                self.assertTrue(loaded["metadati"]["sintetico"])

    def test_salvataggio_invalido_non_sostituisce_lotto_precedente(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "dataset.sqlite3"
            with patch.object(dataset_store, "DB_PATH", db):
                originale = [{"id": "T1", "valore": 3}]
                dataset_store.salva_attivo(originale, origine="lotto valido", sintetico=False)
                with self.assertRaises(dataset_store.ErrorePersistenza):
                    dataset_store.salva_attivo([{"id": "T2", "valore": float("nan")}], origine="lotto errato", sintetico=False)
                loaded = dataset_store.carica_attivo()
                self.assertEqual(loaded["aziende"], originale)
                self.assertEqual(loaded["metadati"]["origine"], "lotto valido")


if __name__ == "__main__":
    unittest.main()
