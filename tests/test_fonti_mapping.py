import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import fonti_mapping, fonti_store
from app.connettori.fonti_live import PayloadFonte


class FontiMappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            patch.object(fonti_store, "DB_PATH", root / "fonti.sqlite3"),
            patch.object(fonti_mapping, "DB_PATH", root / "mapping.sqlite3"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        fonti_store._READY.clear()
        fonti_mapping._READY.clear()

    def _payload(self, raw):
        return PayloadFonte("test:csv", "https://example.org/dataset.csv", "2026-10-22T00:00:00+00:00",
            200, "text/csv", len(raw), hashlib.sha256(raw).hexdigest(), raw, {})

    def test_normalizza_con_provenienza_e_blocca_duplicazione(self):
        raw = b"anno;regione;valore\n2025;Lazio;1.234,5\n2024;Umbria;980,25\n"
        acquired = fonti_store.salva(self._payload(raw))
        preview = fonti_mapping.anteprima(acquired["id"])
        self.assertEqual(preview["formato"], "csv")
        self.assertEqual(preview["numero_righe"], 2)
        m = fonti_mapping.crea_mappatura(acquisizione_id=acquired["id"], settore_id="agricoltura",
            parametro_id="agri_ore_ha_pomodoro", campo_valore="valore", campo_periodo="anno",
            campo_territorio="regione", unita_fissa="ore/ettaro", formato_numero="virgola", utente="admin")
        rows = fonti_mapping.osservazioni(m["id"])
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["valore"], 1234.5)
        self.assertEqual(rows[0]["hash_fonte"], acquired["sha256"])
        with self.assertRaisesRegex(fonti_mapping.ErroreMappatura, "già importati"):
            fonti_mapping.crea_mappatura(acquisizione_id=acquired["id"], settore_id="agricoltura",
                parametro_id="agri_ore_ha_pomodoro", campo_valore="valore", campo_periodo="anno",
                campo_territorio="regione", unita_fissa="ore/ettaro", formato_numero="virgola", utente="admin")

    def test_rifiuta_dataset_parzialmente_invalido_senza_scrivere(self):
        raw = b"anno;valore\n2025;12,5\n2024;ND\n"
        acquired = fonti_store.salva(self._payload(raw))
        with self.assertRaisesRegex(fonti_mapping.ErroreMappatura, "Mapping non salvato"):
            fonti_mapping.crea_mappatura(acquisizione_id=acquired["id"], settore_id="agricoltura",
                parametro_id="agri_ore_ha_pomodoro", campo_valore="valore", campo_periodo="anno",
                unita_fissa="ore/ettaro", formato_numero="virgola", utente="admin")
        self.assertEqual(fonti_mapping.elenco(), [])


if __name__ == "__main__":
    unittest.main()
