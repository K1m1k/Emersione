"""Motore v3.1 (dati mancanti, intervalli, unità, robustezza, controlli dichiarativi) e metriche."""
import copy
import unittest

from app import settori, unita
from app.dati_sintetici import genera_aziende
from app.motore import valutazione
from app.motore.analisi import analizza


def edile(**kw):
    d = {"id": "E", "settore": "edilizia", "dipendenti_dichiarati": 10, "costo_lavoro_per_addetto": 20000,
         "mc_getto": 100, "mq_solaio": 100, "valore_opera": 100000, "costo_manodopera_dichiarato": 20000, "dpi_acquistati": 10}
    d.update(kw)
    return d


def run(record):
    return analizza([copy.deepcopy(record)])[0]["analisi"]


class DatiMancantiTests(unittest.TestCase):
    def test_nessuna_quantita_alternativa_non_diventa_nessuna_anomalia(self):
        an = run(edile(mc_getto=None, mq_solaio=None))
        self.assertEqual(an["livello"], "non_valutabile")
        self.assertIsNone(an["punteggio"])
        self.assertIn("nessuna quantità", an["formula"])

    def test_valori_fuori_intervallo_non_valutabili(self):
        for campo, valore in (("mc_getto", -5), ("mq_solaio", "abc")):
            with self.subTest(campo=campo):
                self.assertEqual(run(edile(**{campo: valore}))["livello"], "non_valutabile")

    def test_dpi_e_costo_manodopera_assenti_non_generano_segnali(self):
        d = edile()
        del d["dpi_acquistati"], d["costo_manodopera_dichiarato"]
        an = run(d)
        self.assertNotIn("dpi", [s["tipo"] for s in an["segnali"]])
        self.assertIsNone(an["incidenza_manodopera_descrittiva"])

    def test_righe_sporche_non_fermano_il_lotto(self):
        lotto = [edile(id="1"), {"id": "2"}, {}, {"id": "3", "settore": "ristorazione", "dipendenti_dichiarati": "x"}, "non un dict"]
        out = analizza(lotto)
        self.assertEqual(len(out), 5)
        self.assertEqual(out[1]["analisi"]["livello"], "non_valutabile")


class ControlliDichiarativiTests(unittest.TestCase):
    def test_nucleo_senza_regole_per_nome_di_settore(self):
        import inspect
        from app.motore import analisi
        sorgente = inspect.getsource(analisi)
        for nome in ("agricoltura", "edilizia", "ristorazione", "logistica"):
            self.assertNotIn(f'"{nome}"', sorgente, nome)

    def test_controllo_dpi_e_modulo_dichiarati_nel_registro(self):
        cfg = settori.configurazione_settore("edilizia")
        self.assertEqual([c["id"] for c in cfg["controlli"]], ["dpi", "incidenza_manodopera"])
        self.assertEqual(cfg["moduli"], ["screening_congruita_dm143"])
        an = run(edile(dpi_acquistati=2, categoria_opera="OG1_NUOVA_CIVILE", tipo_commessa="pubblico"))
        self.assertIn("dpi", [s["tipo"] for s in an["segnali"]])
        self.assertIsNotNone(an["pre_screening_congruita_edilizia"])
        self.assertIsNone(run({"id": "R", "settore": "ristorazione", "dipendenti_dichiarati": 3,
                               "coperti_giorno_stimati": 100})["pre_screening_congruita_edilizia"])


class UnitaTests(unittest.TestCase):
    def test_settori_iniziali_dimensionalmente_coerenti(self):
        registro = settori.leggi_registro()
        for sid, cfg in registro["settori"].items():
            with self.subTest(settore=sid):
                esito = unita.verifica_stima_addetti(cfg["stima"], cfg["campi"], registro["parametri"])
                self.assertEqual(esito["esito"], "compatibile", esito)

    def test_rileva_somma_incompatibile_e_dimensione_errata(self):
        campi = {"a": {"dimensione": {"m2": 1}}, "b": {"dimensione": {"ora": 1}}}
        somma = {"op": "somma", "elementi": [{"op": "campo", "nome": "a"}, {"op": "campo", "nome": "b"}]}
        self.assertEqual(unita.verifica_stima_addetti(somma, campi, {})["esito"], "incompatibile")
        self.assertEqual(unita.verifica_stima_addetti({"op": "campo", "nome": "b"}, campi, {})["esito"], "incompatibile")
        self.assertEqual(unita.verifica_stima_addetti({"op": "campo", "nome": "c"}, campi, {})["esito"], "non_verificabile")
        with self.assertRaises(unita.ErroreDimensione):
            unita.valida_dimensione({"parsec": 1})


class RobustezzaTests(unittest.TestCase):
    def test_robustezza_calcolata_e_instabilita_dichiarata(self):
        out = analizza(genera_aziende(500, seme=42))
        stati = {a["analisi"]["robustezza"]["stato"] for a in out}
        self.assertLessEqual(stati, {"stabile", "instabile", "non_calcolata"})
        instabile = next(a for a in out if a["analisi"]["robustezza"]["stato"] == "instabile")
        self.assertGreater(len(instabile["analisi"]["robustezza"]["livelli_osservati"]), 1)
        self.assertTrue(any("sensibile ai parametri" in l for l in instabile["analisi"]["limitazioni"]))

    def test_caso_vicino_alla_soglia_e_instabile(self):
        # ristorazione: 250 coperti / 25 = 10 attesi; 7 dichiarati → scarto 30%, esattamente la soglia di attenzione
        an = run({"id": "R", "settore": "ristorazione", "dipendenti_dichiarati": 7, "coperti_giorno_stimati": 250})
        self.assertEqual(an["robustezza"]["stato"], "instabile")
        self.assertEqual(an["robustezza"]["parametri_sensibili"], ["ristorazione_coperti_addetto"])


class ValutazioneTests(unittest.TestCase):
    def az(self, i, p):
        return {"id": i, "analisi": {"punteggio": p}}

    def test_senza_etichette_nessuna_metrica(self):
        m = valutazione.valuta_motore([self.az("a", 80)], {}, None)
        self.assertFalse(m["valutabile"])
        self.assertNotIn("precisione", m)

    def test_etichette_estratte_e_separate(self):
        dati = [{"id": "1", "_irregolare": "False"}, {"id": "2", "_irregolare": True}, {"id": "2", "_irregolare": False}]
        et = valutazione.estrai_etichette(dati, "_irregolare")
        self.assertEqual(et, {"1": False})    # id duplicato escluso; "False" stringa non diventa vero
        self.assertTrue(all("_irregolare" not in d for d in dati))

    def test_metriche_e_intervalli(self):
        aziende = [self.az("a", 80), self.az("b", 80), self.az("c", 10), self.az("d", 10), self.az("e", None)]
        m = valutazione.valuta_motore(aziende, {"a": True, "b": False, "c": False, "d": True, "e": True}, "sintetiche")
        self.assertEqual(m["matrice"], {"veri_positivi": 1, "falsi_positivi": 1, "veri_negativi": 1, "falsi_negativi": 1})
        self.assertEqual(m["esclusi_non_valutabili"], 1)
        self.assertEqual(m["precisione"]["valore"], 0.5)
        lo, hi = m["precisione"]["ic95"]
        self.assertTrue(0 <= lo < 0.5 < hi <= 1)
        self.assertIn("Test sintetico", m["avviso"])

    def test_wilson_valori_noti(self):
        self.assertEqual(valutazione.intervallo_wilson(50, 100), (0.404, 0.596))
        self.assertIsNone(valutazione.intervallo_wilson(0, 0))

    def test_metriche_sintetiche_complete(self):
        grezzi = genera_aziende(500, seme=42)
        et = valutazione.estrai_etichette(grezzi, "_irregolare")
        m = valutazione.valuta_motore(analizza(grezzi), et, "sintetiche")
        self.assertEqual(m["casi_valutati"], 500)
        self.assertEqual(m["classi"]["irregolari"] + m["classi"]["regolari"], 500)
        for chiave in ("precisione", "richiamo", "specificita", "tasso_falsi_positivi", "tasso_falsi_negativi"):
            self.assertIsNotNone(m[chiave]["ic95"], chiave)


if __name__ == "__main__":
    unittest.main()
