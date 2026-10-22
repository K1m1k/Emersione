"""Collaudo di estensibilità (sezione 30.15) con un settore non previsto: servizi di pulizia.

Il flusso completo: creazione, parametri, documento come fonte, estrazione di
proposte non applicate, relazioni, collaudo, approvazioni con separazione dei
compiti, analisi riproducibile, impatto, storico e ripristino. Ogni scenario
numerato della sezione 30.15 è indicato nel commento corrispondente.
"""
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import (ciclo_settori, collaudo_settori, db_operativo, dipendenze, documenti, estrazione_documenti,
                 settori, versioni_registro)
from app.dati_sintetici import genera_aziende
from app.motore.analisi import analizza

BASELINE_SINTETICO = "cb82abafdc0c46d5342615b2dcd233f1d8f6f05427e36ae7524eb81a830119bf"


def impronta_risultati(aziende):
    snap = [{"id": a["id"], "p": a["analisi"]["punteggio"], "l": a["analisi"]["livello"],
             "s": sorted((s["tipo"], s["gravita"]) for s in a["analisi"]["segnali"]),
             "att": a["analisi"]["addetti_attesi"]} for a in aziende]
    return hashlib.sha256(json.dumps(snap, sort_keys=True).encode()).hexdigest()


class EstensibilitaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        radice = Path(self.tmp.name)
        registro = radice / "registro_emersione.json"
        shutil.copyfile(settori.PERCORSO_REGISTRO, registro)
        for p in (patch.object(settori, "PERCORSO_REGISTRO", registro),
                  patch.object(db_operativo, "DB_PATH", radice / "operativo.sqlite3"),
                  patch.object(documenti, "_STORAGE", radice / "documenti")):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def _crea_pulizie(self):
        return settori.crea_settore_semplice(
            nome="Servizi di pulizia", descrizione="Settore dimostrativo per il collaudo di estensibilità; coefficienti non validati.",
            campo="mq_puliti_giorno", etichetta_campo="Superficie pulita al giorno", unita_campo="m²/giorno",
            metodo="unita_per_addetto", valore_coefficiente=1200, nome_coefficiente="Superficie pulita da un addetto al giorno",
            unita_coefficiente="m²/(addetto·giorno)", fonte="Valore dimostrativo da verificare", autore="analista_config",
            dimensione_campo={"m2": 1, "giorno": -1}, dimensione_coefficiente={"m2": 1, "addetto": -1, "giorno": -1},
        )

    def test_flusso_completo_settore_pulizie(self):
        prima = impronta_risultati(analizza(genera_aziende(500, seme=42)))
        self.assertEqual(prima, BASELINE_SINTETICO)
        hash_config_iniziale = hashlib.sha256(json.dumps(
            {k: settori.leggi_registro()[k] for k in ("versione", "settori", "parametri")},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

        # 1. nuovo settore senza modificare il nucleo; nasce in bozza
        sid = self._crea_pulizie()
        self.assertEqual(sid, "servizi_di_pulizia")
        self.assertEqual(settori.configurazione_settore(sid)["stato"], "bozza")
        # 2. nuovi parametri senza nuove colonne di database (registro dichiarativo)
        pid = settori.crea_parametro(nome="Giorni lavorativi annui pulizie", valore=250, unita="giorni/anno",
                                     fonte="Ipotesi dimostrativa", ambito=sid, autore="analista_config")
        self.assertIn(pid, settori.catalogo_parametri())
        # 3. riuso di un parametro esistente (soglie del motore) senza duplicarlo
        self.assertIn("scarto_manodopera_grave", settori.parametri_usati_da_settore(settori.configurazione_settore(sid)))

        # 4. documento importato e registrato come fonte
        doc = documenti.aggiungi_documento(
            nome_file="capitolato_pulizie.txt",
            contenuto="Capitolato di prova. Produttività di riferimento: 1100 m2 per addetto al giorno. Art. 5.".encode(),
            titolo="Capitolato dimostrativo pulizie", descrizione="Documento di prova per il collaudo.",
            settore_id=sid, parametro_id=f"custom_{sid}_coeff", utente="analista_config")
        self.assertTrue(doc["sha256"])
        # 5. valori estratti dal documento restano proposte non applicate
        estratti = estrazione_documenti.estrai("capitolato_pulizie.txt", "Produttività: 1100 m2 per addetto al giorno.".encode())
        self.assertTrue(any(c["valore_testuale"] == "1100" and c["stato"] == "da_verificare" for c in estratti["candidati"]))
        self.assertEqual(settori.catalogo_parametri()[f"custom_{sid}_coeff"]["valore"], 1200)
        # 6. relazioni esplicite documento → parametro, e niente cicli di derivazione
        settori.registra_relazione(sorgente_tipo="documento", sorgente_id=doc["id"], tipo="supporta",
                                   destinazione_tipo="parametro", destinazione_id=f"custom_{sid}_coeff", utente="analista_config")
        settori.registra_relazione(sorgente_tipo="parametro", sorgente_id=pid, tipo="deriva_da",
                                   destinazione_tipo="documento", destinazione_id=doc["id"], utente="analista_config")
        settori.registra_relazione(sorgente_tipo="documento", sorgente_id=doc["id"], tipo="deriva_da",
                                   destinazione_tipo="parametro", destinazione_id=f"custom_{sid}_coeff", utente="analista_config")
        with self.assertRaisesRegex(settori.ErroreRegistro, "ciclo"):
            settori.registra_relazione(sorgente_tipo="parametro", sorgente_id=f"custom_{sid}_coeff", tipo="deriva_da",
                                       destinazione_tipo="parametro", destinazione_id=pid, utente="analista_config")

        # 8. test senza attivazione: in bozza non produce risultati operativi, in collaudo sì
        record = {"id": "PUL-1", "settore": sid, "dipendenti_dichiarati": 2, "mq_puliti_giorno": 12000}
        self.assertEqual(analizza([dict(record)])[0]["analisi"]["livello"], "non_valutabile")
        in_prova = analizza([dict(record)], settori_in_collaudo={sid})[0]["analisi"]
        self.assertAlmostEqual(in_prova["addetti_attesi"], 10.0)
        self.assertEqual(in_prova["stato_metodologico"], "collaudo")

        # 9. attivazione solo dopo collaudo e approvazioni
        with self.assertRaises(ciclo_settori.ErroreTransizione):
            ciclo_settori.esegui_transizione(sid, "verificata_tecnicamente", utente="admin", ruolo="amministratore",
                                             motivazione="Tentativo senza revisione")
        ciclo_settori.esegui_transizione(sid, "in_revisione", utente="analista_config", ruolo="responsabile_dati",
                                         motivazione="Configurazione completa, si chiede revisione")
        with self.assertRaisesRegex(ciclo_settori.ErroreTransizione, "Collaudo automatico non ancora eseguito"):
            ciclo_settori.esegui_transizione(sid, "verificata_tecnicamente", utente="admin", ruolo="amministratore",
                                             motivazione="Manca il collaudo")
        collaudo = collaudo_settori.collauda(sid, utente="admin")
        self.assertTrue(collaudo["superato"], collaudo["controlli"])
        unita = next(c for c in collaudo["controlli"] if c["controllo"] == "unita_di_misura")
        self.assertEqual(unita["esito"], "superato")
        ciclo_settori.esegui_transizione(sid, "verificata_tecnicamente", utente="admin", ruolo="amministratore",
                                         motivazione="Collaudo superato su tutti i casi")
        ciclo_settori.esegui_transizione(sid, "in_validazione_metodologica", utente="rev", ruolo="revisore",
                                         motivazione="Avvio validazione metodologica")
        with self.assertRaisesRegex(ciclo_settori.ErroreTransizione, "Separazione dei compiti"):
            ciclo_settori.esegui_transizione(sid, "approvata_sperimentazione", utente="analista_config", ruolo="revisore",
                                             motivazione="Auto-approvazione non ammessa dall'autore")
        ciclo_settori.esegui_transizione(sid, "approvata_sperimentazione", utente="rev", ruolo="revisore",
                                         motivazione="Approvato per la sola sperimentazione su dati sintetici")
        with self.assertRaisesRegex(ciclo_settori.ErroreTransizione, "Parametri non verificati"):
            ciclo_settori.esegui_transizione(sid, "approvato", utente="rev", ruolo="revisore",
                                             motivazione="Tentativo di approvazione per l'uso previsto", evidenza=doc["id"])
        self.assertEqual(settori.ottieni_settore(sid)["stato"], "approvata_sperimentazione")

        # analisi riproducibile e risultati degli altri settori invariati (12)
        campione = genera_aziende(500, seme=42)
        dopo = analizza(copy.deepcopy(campione))
        self.assertEqual(impronta_risultati(dopo), BASELINE_SINTETICO)
        r1 = analizza([dict(record)])[0]["analisi"]
        r2 = analizza([dict(record)])[0]["analisi"]
        self.assertEqual(r1, r2)
        # 10 attesi, 2 dichiarati: scarto 80% → segnale grave (50 punti) → livello "medio"
        self.assertEqual(r1["livello"], "medio")
        self.assertEqual([(x["tipo"], x["gravita"]) for x in r1["segnali"]], [("manodopera", "grave")])
        self.assertEqual(r1["stato_metodologico"], "sperimentale")

        # 11. analisi che dipendono da un parametro + 13. ricostruzione della configurazione storica
        hash_config = hashlib.sha256(json.dumps(
            {k: settori.leggi_registro()[k] for k in ("versione", "settori", "parametri")},
            ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        esecuzione = db_operativo.registra_esecuzione(
            analizza([dict(record)]), utente="analista", motivo="collaudo", versione_motore=r1["versione_motore"],
            hash_configurazione=hash_config, hash_dataset=None, origine="test", sintetico=True)
        impatto = dipendenze.impatto_parametro(f"custom_{sid}_coeff")
        self.assertIn(esecuzione, impatto["esecuzioni_storiche"])
        self.assertEqual([s["id"] for s in impatto["settori"]], [sid])
        storica = versioni_registro.configurazione_settore_storica(hash_config, sid)
        self.assertEqual(storica["settore"]["stato"], "approvata_sperimentazione")
        self.assertEqual(storica["parametri"][f"custom_{sid}_coeff"]["valore"], 1200)
        self.assertNotEqual(hash_config, hash_config_iniziale)

        # modifica del coefficiente: il settore torna in revisione (nessun effetto silenzioso)
        param = settori.catalogo_parametri()[f"custom_{sid}_coeff"]
        settori.aggiorna_parametro(parametro_id=f"custom_{sid}_coeff", nome=param["nome"], valore=1100, unita=param["unita"],
                                   fonte="Capitolato dimostrativo, art. 5", descrizione="", autore="analista_config")
        self.assertEqual(settori.configurazione_settore(sid)["stato"], "in_revisione")
        self.assertEqual(analizza([dict(record)])[0]["analisi"]["livello"], "non_valutabile")
        # l'analisi storica resta quella registrata
        self.assertEqual(db_operativo.risultato_storico(esecuzione, "PUL-1")["livello"], "medio")

        # 10. sospensione e ripristino di una versione senza perdere lo storico
        ciclo_settori.esegui_transizione(sid, "sospeso", utente="admin", ruolo="amministratore", motivazione="Sospensione di prova")
        versioni = ciclo_settori.storico_versioni_settore(sid)
        self.assertGreaterEqual(len(versioni), 5)
        approvata = next(v for v in versioni if v["stato"] == "approvata_sperimentazione")
        differenze = ciclo_settori.confronta_versioni(sid, approvata["progressivo"], versioni[0]["progressivo"])
        self.assertTrue(any(d["percorso"] == "stato" for d in differenze))
        numero_versioni_prima = len(versioni_registro.elenco(5000))
        ciclo_settori.ripristina_versione(sid, approvata["progressivo"], utente="admin", ruolo="amministratore",
                                          motivazione="Ripristino della configurazione approvata")
        self.assertEqual(settori.configurazione_settore(sid)["stato"], "in_revisione")
        self.assertGreater(len(versioni_registro.elenco(5000)), numero_versioni_prima)

        # 14. il non valutabile è esplicito; 15. nessun numero fisso di settori
        for i in range(3):
            settori.crea_settore_semplice(
                nome=f"Settore prova {i}", descrizione="Prova di numerosità.", campo=f"quantita_{i}",
                etichetta_campo="Quantità", unita_campo="unità/anno", metodo="ore_per_unita", valore_coefficiente=1,
                nome_coefficiente="Ore per unità", unita_coefficiente="ore/unità", fonte="prova")
        self.assertEqual(len(settori.lista_settori(includi_archiviati=True)), 8)  # 4 iniziali + pulizie + 3

    def test_collaudo_rileva_unita_incompatibili_e_riferimenti_mancanti(self):
        # 7. dipendenze mancanti e unità incompatibili
        sid = self._crea_pulizie()
        registro = settori.leggi_registro()
        registro["settori"][sid]["campi"]["mq_puliti_giorno"]["dimensione"] = {"m2": 1}   # manca il /giorno
        risultato = collaudo_settori.collauda(sid, registro=registro, salva=False)
        self.assertFalse(risultato["superato"])
        self.assertEqual(next(c for c in risultato["controlli"] if c["controllo"] == "unita_di_misura")["esito"], "fallito")
        registro = settori.leggi_registro()
        registro["settori"][sid]["stima"]["destra"]["id"] = "parametro_inesistente"
        risultato = collaudo_settori.collauda(sid, registro=registro, salva=False)
        self.assertFalse(risultato["superato"])
        mappa = dipendenze.mappa_completa()
        self.assertEqual(mappa["riferimenti_irrisolti"], [])

    def test_quattro_settori_iniziali_superano_il_collaudo(self):
        for sid in ("agricoltura", "edilizia", "ristorazione", "logistica"):
            with self.subTest(settore=sid):
                risultato = collaudo_settori.collauda(sid, salva=False)
                self.assertTrue(risultato["superato"], [c for c in risultato["controlli"] if c["esito"] == "fallito"])

    def test_parametri_non_usati_sono_dichiarati(self):
        registro = settori.leggi_registro()
        non_usati = set(dipendenze.mappa_completa()["parametri_non_usati"])
        for pid in non_usati:
            self.assertIs(registro["parametri"][pid].get("in_uso"), False, pid)
            self.assertTrue(registro["parametri"][pid].get("nota_utilizzo"), pid)


if __name__ == "__main__":
    unittest.main()
