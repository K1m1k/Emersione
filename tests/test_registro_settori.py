import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import settori
from app.motore.analisi import analizza, valuta_motore
from app.dati_sintetici import genera_aziende


class RegistroSettoriTests(unittest.TestCase):
    def test_formula_uses_whitelisted_operations(self):
        params = {"coeff": {"valore": 2.5, "nome": "Coefficiente", "stato": "da_verificare"}}
        formula = {"op": "dividi", "sinistra": {"op": "moltiplica", "elementi": [
            {"op": "campo", "nome": "quantita"}, {"op": "coefficiente", "id": "coeff"}
        ]}, "destra": {"op": "costante", "valore": 5}}
        value, used = settori.valuta_formula(formula, {"quantita": 10}, params)
        self.assertEqual(value, 5.0)
        self.assertEqual(used[0]["id"], "coeff")
        with self.assertRaises(settori.ErroreRegistro):
            settori.valuta_formula({"op": "eval", "code": "__import__('os').system('id')"}, {}, params)

    def test_creazione_dinamica_settore_e_parametro(self):
        origine = settori.PERCORSO_REGISTRO
        with tempfile.TemporaryDirectory() as temp:
            destinazione = Path(temp) / "registro.json"
            shutil.copyfile(origine, destinazione)
            with patch.object(settori, "PERCORSO_REGISTRO", destinazione):
                sid = settori.crea_settore_semplice(
                    nome="Pesca industriale", descrizione="Prova sintetica non validata.",
                    campo="tonnellate_annue", etichetta_campo="Tonnellate annue", unita_campo="t/anno",
                    metodo="ore_per_unita", valore_coefficiente=2, nome_coefficiente="Ore per tonnellata",
                    unita_coefficiente="ore/t", fonte="Fonte sperimentale da verificare",
                )
                # Un settore nuovo nasce in bozza: esiste nel registro ma non è attivo.
                self.assertIsNone(settori.ottieni_settore(sid))
                config = settori.configurazione_settore(sid)
                self.assertIsNotNone(config)
                self.assertEqual(config["stato"], "bozza")
                value, used = settori.valuta_formula(config["stima"], {"tonnellate_annue": 800}, settori.catalogo_parametri())
                self.assertEqual(value, 1.0)
                self.assertEqual(used[0]["stato"], "da_verificare")
                record = {
                    "id": "TEST-PESCA-1", "settore": sid,
                    "dipendenti_dichiarati": 1, "costo_lavoro_per_addetto": None,
                    "tonnellate_annue": 800,
                }
                # Nel lotto operativo una bozza non produce risultati...
                operativo = analizza([dict(record)])[0]["analisi"]
                self.assertEqual(operativo["livello"], "non_valutabile")
                # ...ma è eseguibile in collaudo isolato, con esito marcato come tale.
                risultato = analizza([dict(record)], settori_in_collaudo={sid})[0]["analisi"]
                self.assertAlmostEqual(risultato["addetti_attesi"], 1.0)
                self.assertEqual(risultato["stato_metodologico"], "collaudo")
                saved = json.loads(destinazione.read_text(encoding="utf-8"))
                self.assertIn(sid, saved["settori"])

    def test_campi_aggiuntivi_formula_multi_parametro_e_versionamento(self):
        origine = settori.PERCORSO_REGISTRO
        with tempfile.TemporaryDirectory() as temp:
            destinazione = Path(temp) / "registro.json"
            shutil.copyfile(origine, destinazione)
            with patch.object(settori, "PERCORSO_REGISTRO", destinazione):
                sid = settori.crea_settore_semplice(
                    nome="Pesca industriale", descrizione="Prova sintetica non validata.",
                    campo="tonnellate_annue", etichetta_campo="Tonnellate annue", unita_campo="t/anno",
                    metodo="ore_per_unita", valore_coefficiente=2, nome_coefficiente="Ore per tonnellata",
                    unita_coefficiente="ore/t", fonte="Fonte sperimentale da verificare",
                )
                settori.aggiungi_campo_settore(
                    settore_id=sid, campo="ore_macchina_anno", etichetta="Ore macchina annue",
                    unita="ore/anno", obbligatorio=True, minimo=0, autore="tester",
                )
                formula = {
                    "op": "dividi",
                    "sinistra": {"op": "somma", "elementi": [
                        {"op": "moltiplica", "elementi": [
                            {"op": "campo", "nome": "tonnellate_annue"},
                            {"op": "coefficiente", "id": f"custom_{sid}_coeff"},
                        ]},
                        {"op": "campo", "nome": "ore_macchina_anno"},
                    ]},
                    "destra": {"op": "coefficiente", "id": "ore_annue_addetto"},
                }
                versione = settori.aggiorna_formula_settore(settore_id=sid, formula=formula, autore="tester")
                config = settori.configurazione_settore(sid)
                self.assertEqual(versione, 3)
                self.assertEqual(config["stato"], "bozza")  # una bozza modificata resta bozza
                self.assertEqual(len(config["storico_configurazioni"]), 2)
                valore, usati = settori.valuta_formula(config["stima"], {
                    "tonnellate_annue": 800, "ore_macchina_anno": 100,
                }, settori.catalogo_parametri())
                self.assertAlmostEqual(valore, 1.0625)
                self.assertEqual({p["id"] for p in usati}, {f"custom_{sid}_coeff", "ore_annue_addetto"})
                with self.assertRaisesRegex(settori.ErroreRegistro, "non è un campo numerico"):
                    settori.valida_formula_settore(sid, {"op": "campo", "nome": "campo_inesistente"})
                with self.assertRaisesRegex(settori.ErroreRegistro, "ambito diverso"):
                    settori.valida_formula_settore(sid, {"op": "coefficiente", "id": "ristorazione_coperti_addetto"})
                with self.assertRaises(settori.ErroreRegistro):
                    settori.valida_formula_settore(sid, {"op": "eval", "code": "__import__('os').system('id')"})

    def test_parametri_documenti_e_relazioni_versionabili(self):
        origine = settori.PERCORSO_REGISTRO
        with tempfile.TemporaryDirectory() as temp:
            destinazione = Path(temp) / "registro.json"
            shutil.copyfile(origine, destinazione)
            with patch.object(settori, "PERCORSO_REGISTRO", destinazione):
                parametro_id = settori.crea_parametro(
                    nome="Umidità del terreno", valore=31.5, unita="percento",
                    fonte="Documento dimostrativo da verificare", ambito="agricoltura",
                )
                documento_id = "0" * 32  # UUID che inizia con cifra: caso valido.
                settori.registra_documento({
                    "id": documento_id, "titolo": "Scheda tecnica dimostrativa",
                    "descrizione": "Non valida", "settore": "agricoltura",
                    "parametro": parametro_id, "stato": "da_verificare",
                })
                relazione = settori.registra_relazione(
                    sorgente_tipo="documento", sorgente_id=documento_id,
                    tipo="supporta", destinazione_tipo="parametro",
                    destinazione_id=parametro_id, descrizione="Dato nella sezione 2.",
                    utente="tester",
                )
                self.assertEqual(relazione["stato"], "da_verificare")
                self.assertEqual(len(settori.lista_relazioni()), 1)
                with self.assertRaisesRegex(settori.ErroreRegistro, "già registrata"):
                    settori.registra_relazione(
                        sorgente_tipo="documento", sorgente_id=documento_id,
                        tipo="supporta", destinazione_tipo="parametro",
                        destinazione_id=parametro_id, descrizione="Duplicato",
                    )

    def test_parametro_versionato_e_approvazione_con_documento_tracciato(self):
        origine = settori.PERCORSO_REGISTRO
        with tempfile.TemporaryDirectory() as temp:
            destinazione = Path(temp) / "registro.json"
            shutil.copyfile(origine, destinazione)
            with patch.object(settori, "PERCORSO_REGISTRO", destinazione):
                parametro_id = "agri_ore_ha_pomodoro"
                documento_id = "a" * 32
                settori.registra_documento({
                    "id": documento_id, "titolo": "Tabella tecnica verificata",
                    "descrizione": "Documento conservato per test del flusso di verifica.",
                    "settore": "agricoltura", "parametro": parametro_id,
                    "file_key": "documento-test.pdf", "sha256": "b" * 64,
                    "stato": "da_verificare",
                })
                with self.assertRaisesRegex(settori.ErroreRegistro, "nuova revisione"):
                    settori.aggiorna_parametro(
                        parametro_id=parametro_id, nome="Ore per ettaro di pomodoro", valore=451,
                        unita="ore/(ha·anno)", fonte="Tabella tecnica acquisita, pagina 14",
                        descrizione="Valore aggiornato in attesa di nuova verifica.", stato="approvato",
                        documento_validazione=documento_id,
                        nota_validazione="Confronto con la tabella tecnica e verifica delle unità.",
                        autore="responsabile-test",
                    )
                versione = settori.aggiorna_parametro(
                    parametro_id=parametro_id, nome="Ore per ettaro di pomodoro", valore=451,
                    unita="ore/(ha·anno)", fonte="Tabella tecnica acquisita, pagina 14",
                    descrizione="Valore aggiornato in attesa di nuova verifica.", stato="da_verificare",
                    autore="responsabile-test",
                )
                self.assertEqual(versione, 2)
                # Senza riferimento completo alla fonte (sezione 7) l'approvazione è rifiutata.
                with self.assertRaisesRegex(settori.ErroreRegistro, "riferimento alla fonte"):
                    settori.aggiorna_parametro(
                        parametro_id=parametro_id, nome="Ore per ettaro di pomodoro", valore=451,
                        unita="ore/(ha·anno)", fonte="Tabella tecnica acquisita, pagina 14",
                        descrizione="Valore aggiornato in attesa di nuova verifica.", stato="approvato",
                        documento_validazione=documento_id,
                        nota_validazione="Confronto con la tabella tecnica e verifica delle unità.",
                        autore="responsabile-test",
                    )
                versione = settori.aggiorna_parametro(
                    parametro_id=parametro_id, nome="Ore per ettaro di pomodoro", valore=451,
                    unita="ore/(ha·anno)", fonte="Tabella tecnica acquisita, pagina 14",
                    descrizione="Valore aggiornato in attesa di nuova verifica.", stato="approvato",
                    documento_validazione=documento_id,
                    nota_validazione="Confronto con la tabella tecnica e verifica delle unità.",
                    autore="responsabile-test", natura="stima_tecnica",
                    riferimento_fonte={"titolo_documento": "Tabella tecnica di prova", "riferimento": "pag. 14, tab. 3",
                                       "data_accesso": "2026-10-22", "periodo_validita": "2026", "territorio": "Italia (prova)"},
                )
                self.assertEqual(versione, 3)
                self.assertEqual(settori.catalogo_parametri()[parametro_id]["natura"], "stima_tecnica")
                aggiornato = settori.catalogo_parametri()[parametro_id]
                self.assertEqual(aggiornato["stato"], "approvato")
                self.assertEqual(aggiornato["validato_da"], "responsabile-test")
                self.assertEqual(aggiornato["documento_validazione"], documento_id)
                self.assertEqual(len(aggiornato["storico_versioni"]), 2)

    def test_dataset_sintetico_metriche_con_etichetta(self):
        data = analizza(genera_aziende(500, seme=42))
        metriche = valuta_motore(data)
        self.assertEqual(metriche["aziende_totali"], 500)
        self.assertAlmostEqual(metriche["precisione"], 0.919)
        self.assertAlmostEqual(metriche["recupero"], 0.836)

    def test_metriche_non_calcolate_senza_etichette(self):
        data = analizza(genera_aziende(10, seme=42))
        for row in data:
            row.pop("_irregolare", None)
        self.assertIsNone(valuta_motore(data))

    def test_record_senza_dati_minimi_non_dice_punteggio_zero(self):
        data = [{"id": "T1", "settore": "agricoltura", "costo_lavoro_per_addetto": None,
                 "dipendenti_dichiarati": 2, "ettari": None, "coltura": "pomodoro"}]
        result = analizza(data)[0]["analisi"]
        self.assertIsNone(result["punteggio"])
        self.assertEqual(result["livello"], "non_valutabile")


if __name__ == "__main__":
    unittest.main()
