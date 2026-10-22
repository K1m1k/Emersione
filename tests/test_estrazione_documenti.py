import unittest
from app.estrazione_documenti import estrai

class EstrazioneDocumentiTests(unittest.TestCase):
    def test_candidati_numerici_e_normativi_non_approvati(self):
        raw = "Per la nuova edilizia civile è riportato un indice del 14,28%. Riferimento D.M. 143/2021."
        risultato = estrai("riferimento.txt", raw.encode())
        self.assertEqual(risultato["stato"], "candidati_estratti")
        self.assertTrue(any(c["tipo"] == "riferimento_normativo_candidato" for c in risultato["candidati"]))
        self.assertTrue(all(c["stato"] == "da_verificare" for c in risultato["candidati"]))
        self.assertIn("Nessun valore è approvato", risultato["nota"])

if __name__ == "__main__": unittest.main()


class RegressioneNumeriTests(unittest.TestCase):
    def test_numeri_non_troncati(self):
        from app import estrazione_documenti as e
        casi = {"1100 m2": ("1100", "m2"), "1.234,56 euro": ("1.234,56", "euro"), "14,28%": ("14,28", "%"),
                "2.000 ore/ettaro": ("2.000", "ore/ettaro"), "valore 1100.": ("1100", None)}
        for testo, atteso in casi.items():
            with self.subTest(testo=testo):
                candidati = [(c["valore_testuale"], c["unita_testuale"]) for c in e.estrai("a.txt", testo.encode())["candidati"]
                             if c["tipo"] == "valore_numerico_candidato"]
                self.assertIn(atteso, candidati)
                self.assertFalse(any(v != atteso[0] and atteso[0].startswith(v) for v, _ in candidati), candidati)
