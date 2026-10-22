import csv
import io
import unittest
from pathlib import Path

from app.connettori.csv_import import ErroreCSV, carica_csv_da_bytes, salva_csv

ROOT = Path(__file__).resolve().parents[1]


class ImportCSVTests(unittest.TestCase):
    def test_esempio_sintetico_valido(self):
        content = (ROOT / "dati" / "esempio_sintetico.csv").read_bytes()
        rows = carica_csv_da_bytes(content)
        self.assertEqual(len(rows), 50)
        self.assertTrue(all(isinstance(row["dipendenti_dichiarati"], (int, float)) for row in rows))

    def test_costo_lavoro_facoltativo(self):
        data = b"id,settore,dipendenti_dichiarati,ettari,coltura\nA1,agricoltura,2,4,pomodoro\n"
        rows = carica_csv_da_bytes(data)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("costo_lavoro_per_addetto", rows[0])

    def test_rifiuta_identificativi_duplicati(self):
        data = b"id,settore,dipendenti_dichiarati,costo_lavoro_per_addetto,ettari,coltura\nA1,agricoltura,2,12000,4,pomodoro\nA1,agricoltura,3,14000,6,uva\n"
        with self.assertRaisesRegex(ErroreCSV, "duplicato"):
            carica_csv_da_bytes(data)

    def test_rifiuta_settore_sconosciuto(self):
        data = b"id,settore,dipendenti_dichiarati,costo_lavoro_per_addetto\nA1,settore_inesistente,2,12000\n"
        with self.assertRaisesRegex(ErroreCSV, "non configurato"):
            carica_csv_da_bytes(data)

    def test_rifiuta_numero_infinito_e_valore_negativo(self):
        data = b"id,settore,dipendenti_dichiarati,costo_lavoro_per_addetto,ettari,coltura\nA1,agricoltura,2,12000,inf,pomodoro\n"
        with self.assertRaisesRegex(ErroreCSV, "finito"):
            carica_csv_da_bytes(data)
        data = b"id,settore,dipendenti_dichiarati,costo_lavoro_per_addetto,ettari,coltura\nA1,agricoltura,2,12000,-1,pomodoro\n"
        with self.assertRaisesRegex(ErroreCSV, "inferiore"):
            carica_csv_da_bytes(data)

    def test_esportazione_protegge_formula_csv(self):
        with __import__('tempfile').TemporaryDirectory() as temp:
            output = Path(temp) / "export.csv"
            salva_csv([{"id": "=HYPERLINK(\"http://evil\")", "settore": "agricoltura", "dipendenti_dichiarati": 2}], output)
            with output.open(encoding="utf-8", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertTrue(row["id"].startswith("'="))

    def test_rifiuta_file_oltre_dimensione(self):
        with self.assertRaisesRegex(ErroreCSV, "supera il limite"):
            carica_csv_da_bytes(b"x" * (5 * 1024 * 1024 + 1))


if __name__ == "__main__":
    unittest.main()
