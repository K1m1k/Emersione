import math, unittest
from app import normativa_edilizia as norma

class NormativaEdiliziaTests(unittest.TestCase):
    def test_tabella_ufficiale_completa_e_screening_separato(self):
        self.assertEqual(len(norma.INDICI), 17)
        risultato = norma.verifica_preliminare(categoria="OG1_NUOVA_CIVILE", valore_opera=100000,
            costo_manodopera=14280, tipo_commessa="pubblico")
        self.assertEqual(risultato["stato"], "pari_o_superiore_all_indice")
        self.assertAlmostEqual(risultato["indice_minimo_tabellare"], 0.1428)
        sotto = norma.verifica_preliminare(categoria="OG1_NUOVA_CIVILE", valore_opera=100000,
            costo_manodopera=14279, tipo_commessa="pubblico")
        self.assertEqual(sotto["stato"], "sotto_indice_tabellare")
        self.assertIn("Non è attestazione", sotto["nota"])

    def test_non_valutabile_e_soglia_lavori_privati(self):
        incompleto = norma.verifica_preliminare(categoria="OG1_NUOVA_CIVILE", valore_opera=float("nan"),
            costo_manodopera=10, tipo_commessa="pubblico")
        self.assertEqual(incompleto["stato"], "non_valutabile")
        privato = norma.verifica_preliminare(categoria="OG1_NUOVA_CIVILE", valore_opera=69999,
            costo_manodopera=10000, tipo_commessa="privato")
        self.assertEqual(privato["stato"], "fuori_soglia_privati_dm143")

if __name__ == "__main__": unittest.main()
