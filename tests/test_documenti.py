import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import documenti, settori


class DocumentiTests(unittest.TestCase):
    def test_documento_registrato_con_hash_e_relazione(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            path_registro = temp / "registro.json"
            shutil.copyfile(settori.PERCORSO_REGISTRO, path_registro)
            archivio = temp / "documenti"
            with patch.object(settori, "PERCORSO_REGISTRO", path_registro), patch.object(documenti, "_STORAGE", archivio):
                doc = documenti.aggiungi_documento(
                    nome_file="nota.txt", contenuto="Documento di prova non validato.\n".encode(),
                    titolo="Nota tecnica", descrizione="Campione per test", settore_id="agricoltura",
                    parametro_id="agri_ore_ha_pomodoro", url_fonte="https://example.org/documento",
                    utente="tester",
                )
                self.assertEqual(doc["stato"], "da_verificare")
                self.assertIn(doc["estrazione"], {"candidati_estratti", "nessun_candidato_rilevato"})
                self.assertIn("candidati", doc["estrazione_dati"])
                self.assertEqual(len(doc["sha256"]), 64)
                self.assertIn(doc["id"], [x["id"] for x in settori.lista_documenti()])
                percorso = documenti.percorso_documento(doc)
                self.assertIsNotNone(percorso)
                self.assertEqual(percorso.read_text(encoding="utf-8"), "Documento di prova non validato.\n")

    def test_rifiuta_pdf_senza_header(self):
        with self.assertRaisesRegex(documenti.ErroreDocumento, "intestazione"):
            documenti._valida_contenuto("file.pdf", b"non e un pdf")

    def test_rifiuta_url_con_schema_non_http(self):
        with self.assertRaisesRegex(documenti.ErroreDocumento, "URL"):
            documenti.aggiungi_documento(
                nome_file="a.txt", contenuto=b"x", titolo="test", descrizione="", url_fonte="file:///etc/passwd",
            )


if __name__ == "__main__":
    unittest.main()
