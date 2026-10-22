import copy
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from app import audit, dataset_store, db_operativo, documenti, sicurezza, sessioni, settori, fonti_store, fonti_mapping, osint, grafo
from app.web import server


class WebIntegrationTests(unittest.TestCase):
    password = "Password di test sufficientemente robusta 2026!"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.old_state = copy.deepcopy(server.STATO)

        registry_copy = root / "registro_emersione.json"
        shutil.copyfile(settori.PERCORSO_REGISTRO, registry_copy)
        self.patches = [
            patch.object(settori, "PERCORSO_REGISTRO", registry_copy),
            patch.object(sessioni, "DB_PATH", root / "sessioni.sqlite3"),
            patch.object(dataset_store, "DB_PATH", root / "dataset.sqlite3"),
            patch.object(audit, "PERCORSO_LOG", root / "audit.jsonl"),
            patch.object(documenti, "_STORAGE", root / "documenti"),
            patch.object(fonti_store, "DB_PATH", root / "fonti.sqlite3"),
            patch.object(fonti_mapping, "DB_PATH", root / "fonti_mapping.sqlite3"),
            patch.object(osint, "DB_PATH", root / "osint.sqlite3"),
            patch.object(grafo, "DB_PATH", root / "grafo.sqlite3"),
            patch.object(db_operativo, "DB_PATH", root / "operativo.sqlite3"),
            patch.dict(__import__("os").environ, {
                "EMERSIONE_ENV": "development",
                "EMERSIONE_SESSION_SECRET": "test-session-secret-value-with-at-least-48-bytes",
                "EMERSIONE_USERS_JSON": json.dumps([{
                    "username": "admin-test",
                    "password_hash": sicurezza.crea_hash_password(self.password),
                    "ruolo": "amministratore",
                }, {
                    "username": "revisore-test",
                    "password_hash": sicurezza.crea_hash_password(self.password),
                    "ruolo": "revisore",
                }]),
            }),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self._restore_state)
        self._login()

    def _restore_state(self):
        server.STATO.clear()
        server.STATO.update(self.old_state)
        self.temporary.cleanup()

    def _csrf(self, response):
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        self.assertIsNotNone(match, "Token CSRF non presente nella pagina.")
        return match.group(1)

    def _cliente_revisore(self):
        cliente = TestClient(server.app)
        self.addCleanup(cliente.close)
        self._login(cliente, "revisore-test")
        return cliente

    def _login(self, cliente=None, username="admin-test"):
        cliente = cliente or self.client
        page = cliente.get("/login")
        token = self._csrf(page)
        response = cliente.post("/login", data={
            "csrf_token": token,
            "username": username,
            "password": self.password,
            "next": "/",
        }, follow_redirects=False) if cliente is self.client else cliente.post("/login", data={
            "csrf_token": token, "username": username, "password": self.password, "next": "/",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

    def test_pagine_protette_renderizzano_e_non_vengono_cacheate(self):
        urls = ["/", "/fonti", "/valutazione", "/carica", "/settori", "/documenti", "/osint", "/grafo", "/audit", "/azienda/AZ00000"]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get("cache-control"), "no-store")
                self.assertIn("x-content-type-options", response.headers)

    def test_crea_settore_parametro_documento_relazione_e_import_dinamico(self):
        page = self.client.get("/settori")
        token = self._csrf(page)
        response = self.client.post("/settori/crea", data={
            "csrf_token": token,
            "nome": "Energia Rinnovabile",
            "descrizione": "Settore dimostrativo sperimentale.",
            "campo": "energia_annua_mwh",
            "etichetta_campo": "Energia prodotta annua",
            "unita_campo": "MWh/anno",
            "metodo": "ore_per_unita",
            "valore_coefficiente": "2",
            "nome_coefficiente": "Ore per MWh",
            "unita_coefficiente": "ore/MWh",
            "fonte": "Parametro sperimentale da verificare",
            "riferimento_url": "",
        })
        self.assertEqual(response.status_code, 200, response.text)
        settore_id = "energia_rinnovabile"
        self.assertIsNone(settori.ottieni_settore(settore_id))  # bozza: non attivo
        self.assertEqual(settori.configurazione_settore(settore_id)["stato"], "bozza")

        token = self._csrf(response)
        response = self.client.post("/settori/campi/aggiungi", data={
            "csrf_token": token,
            "settore_id": settore_id,
            "campo": "ore_macchina_anno",
            "etichetta": "Ore macchina annue",
            "unita": "ore/anno",
            "obbligatorio": "on",
            "minimo": "0",
            "massimo": "1000000",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("ore_macchina_anno", settori.configurazione_settore(settore_id)["campi"])

        formula = {
            "op": "dividi",
            "sinistra": {"op": "somma", "elementi": [
                {"op": "moltiplica", "elementi": [
                    {"op": "campo", "nome": "energia_annua_mwh"},
                    {"op": "coefficiente", "id": "custom_energia_rinnovabile_coeff"},
                ]},
                {"op": "campo", "nome": "ore_macchina_anno"},
            ]},
            "destra": {"op": "coefficiente", "id": "ore_annue_addetto"},
        }
        response = self.client.post("/settori/formula", data={
            "csrf_token": self._csrf(response),
            "settore_id": settore_id,
            "formula_json": json.dumps(formula),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(settori.configurazione_settore(settore_id)["versione_configurazione"], 3)
        self.assertEqual(settori.configurazione_settore(settore_id)["stato"], "bozza")
        self.assertFalse(server.STATO["configurazione_corrente"])
        self.assertIn("Formula salvata", response.text)

        token = self._csrf(response)
        response = self.client.post("/settori/parametri/crea", data={
            "csrf_token": token,
            "nome": "Fattore di prova",
            "valore": "1.25",
            "unita": "unità/MWh",
            "ambito": settore_id,
            "fonte": "Riferimento provvisorio non validato",
            "descrizione": "Parametro aggiuntivo per test integrazione.",
        })
        self.assertEqual(response.status_code, 200, response.text)
        parametro_id = "custom_param_fattore_di_prova"
        self.assertIn(parametro_id, settori.catalogo_parametri())
        self.assertFalse(server.STATO["configurazione_corrente"])
        self.assertIn("configurazione di settori o parametri è cambiata", self.client.get("/").text)
        report_obsoleto = self.client.get("/azienda/AZ00000/report.pdf")
        self.assertEqual(report_obsoleto.status_code, 409)
        self.assertIn("configurazione è cambiata", report_obsoleto.text)
        recalcolo_page = self.client.get("/")
        recalcolo = self.client.post("/ricalcola", data={"csrf_token": self._csrf(recalcolo_page)}, follow_redirects=False)
        self.assertEqual(recalcolo.status_code, 303)
        self.assertTrue(server.STATO["configurazione_corrente"])

        page = self.client.get("/documenti")
        token = self._csrf(page)
        response = self.client.post("/documenti/carica", data={
            "csrf_token": token,
            "titolo": "Scheda di riferimento test",
            "descrizione": "Documento di prova; contenuto non validato.",
            "settore": settore_id,
            "parametro": parametro_id,
            "url_fonte": "https://example.org/scheda",
        }, files={"file": ("scheda.txt", b"Parametro dimostrativo = 1.25", "text/plain")})
        self.assertEqual(response.status_code, 200, response.text)
        documento = next(d for d in settori.lista_documenti() if d.get("titolo") == "Scheda di riferimento test")
        download = self.client.get(f"/documenti/{documento['id']}/download")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, b"Parametro dimostrativo = 1.25")

        page = self.client.get("/documenti")
        token = self._csrf(page)
        response = self.client.post("/relazioni/crea", data={
            "csrf_token": token,
            "sorgente": f"documento:{documento['id']}",
            "tipo": "supporta",
            "destinazione": f"parametro:{parametro_id}",
            "descrizione": "Il documento riporta il parametro alla sezione di prova.",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(settori.lista_relazioni()), 1)

        # Prima si crea una revisione tecnica non validata; l'approvazione
        # successiva deve essere un'operazione separata e tracciabile.
        page = self.client.get("/settori")
        response = self.client.post("/settori/parametri/aggiorna", data={
            "csrf_token": self._csrf(page),
            "parametro_id": parametro_id,
            "nome": "Fattore di prova",
            "valore": "1.25",
            "unita": "unità/MWh",
            "fonte": "Scheda tecnica caricata e sottoposta a verifica",
            "descrizione": "Parametro dimostrativo collegato al documento di test.",
            "stato": "da_verificare",
            "documento_validazione": "",
            "nota_validazione": "",
        })
        self.assertEqual(response.status_code, 200, response.text)
        parametro_revisionato = settori.catalogo_parametri()[parametro_id]
        self.assertEqual(parametro_revisionato["versione"], 2)
        self.assertEqual(parametro_revisionato["stato"], "da_verificare")

        # L'amministratore non può dichiarare approvato un parametro: serve il revisore.
        page = self.client.get("/settori")
        negato = self.client.post("/settori/parametri/aggiorna", data={
            "csrf_token": self._csrf(page), "parametro_id": parametro_id, "nome": "Fattore di prova",
            "valore": "1.25", "unita": "unità/MWh", "fonte": "Scheda tecnica caricata e sottoposta a verifica",
            "descrizione": "Parametro dimostrativo collegato al documento di test.", "stato": "approvato",
            "documento_validazione": documento["id"], "nota_validazione": "Verificato il riferimento e confrontata l'unità di misura.",
        })
        self.assertEqual(negato.status_code, 403)
        revisore = self._cliente_revisore()
        page = revisore.get("/settori")
        response = revisore.post("/settori/parametri/aggiorna", data={
            "csrf_token": self._csrf(page),
            "parametro_id": parametro_id,
            "nome": "Fattore di prova",
            "valore": "1.25",
            "unita": "unità/MWh",
            "fonte": "Scheda tecnica caricata e sottoposta a verifica",
            "descrizione": "Parametro dimostrativo collegato al documento di test.",
            "stato": "approvato",
            "documento_validazione": documento["id"],
            "nota_validazione": "Verificato il riferimento e confrontata l'unità di misura.",
            "natura": "stima_tecnica",
            "rf_titolo_documento": "Scheda di riferimento test", "rf_riferimento": "riga 1",
            "rf_data_accesso": "2026-10-22", "rf_periodo_validita": "2026", "rf_territorio": "Italia (prova)",
        })
        self.assertEqual(response.status_code, 200, response.text)
        parametro_aggiornato = settori.catalogo_parametri()[parametro_id]
        self.assertEqual(parametro_aggiornato["versione"], 3)
        self.assertEqual(parametro_aggiornato["stato"], "approvato")
        self.assertEqual(parametro_aggiornato["validato_da"], "revisore-test")

        # Ciclo di vita: bozza -> revisione -> collaudo -> verifica tecnica -> validazione -> approvazione
        # per la sperimentazione da parte di un revisore diverso dall'autore.
        gestione = f"/settori/{settore_id}/gestione"
        def passa(cliente, a_stato, motivazione="Passaggio di prova con motivazione completa."):
            pagina = cliente.get(gestione)
            return cliente.post(f"/settori/{settore_id}/transizione", data={
                "csrf_token": self._csrf(pagina), "a_stato": a_stato, "motivazione": motivazione}, follow_redirects=False)
        self.assertEqual(passa(self.client, "in_revisione").status_code, 303)
        prematuro = passa(self.client, "verificata_tecnicamente")
        self.assertEqual(prematuro.status_code, 400)
        self.assertIn("Collaudo automatico non ancora eseguito", prematuro.text)
        pagina = self.client.get(gestione)
        collaudo = self.client.post(f"/settori/{settore_id}/collaudo", data={"csrf_token": self._csrf(pagina)})
        self.assertEqual(collaudo.status_code, 200, collaudo.text[:300])
        self.assertIn("Collaudo superato", collaudo.text)
        self.assertEqual(passa(self.client, "verificata_tecnicamente").status_code, 303)
        self.assertEqual(passa(revisore, "in_validazione_metodologica").status_code, 303)
        self.assertEqual(passa(revisore, "approvata_sperimentazione").status_code, 303)
        self.assertEqual(settori.ottieni_settore(settore_id)["stato"], "approvata_sperimentazione")

        page = self.client.get("/carica")
        token = self._csrf(page)
        csv_content = (
            "id,settore,dipendenti_dichiarati,energia_annua_mwh,ore_macchina_anno\n"
            f"TEST-ER-1,{settore_id},1,800,100\n"
        ).encode("utf-8")
        provenienza_lotto = {"conferente": "Ente di prova", "titolare": "Ente di prova", "finalita": "Collaudo del flusso",
                             "autorizzazione": "Nota prot. 1/2026 (fittizia)", "data_ricezione": "2026-10-01",
                             "condizioni_uso": "Solo collaudo, cancellazione a fine prova"}
        senza_provenienza = self.client.post("/carica", data={"csrf_token": token}, files={"file": ("energia.csv", csv_content, "text/csv")})
        self.assertEqual(senza_provenienza.status_code, 400)
        response = self.client.post("/carica", data={"csrf_token": token, **provenienza_lotto}, files={
            "file": ("energia.csv", csv_content, "text/csv"),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(server.STATO["dataset_sintetico"])          # anteprima: il lotto attivo non cambia
        self.assertIn("Conferma e attiva il lotto", response.text)
        conferma_token = re.search(r'name="token" value="([^"]+)"', response.text).group(1)
        self.assertEqual(self.client.post("/carica/conferma", data={"csrf_token": self._csrf(response), "token": "sbagliato"}).status_code, 409)
        response = self.client.post("/carica/conferma", data={"csrf_token": self._csrf(response), "token": conferma_token})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(server.STATO["dataset_sintetico"])
        self.assertEqual(server.STATO["provenienza"]["conferente"], "Ente di prova")
        self.assertEqual(server.STATO["aziende"][0]["settore"], settore_id)
        self.assertAlmostEqual(server.STATO["aziende"][0]["analisi"]["addetti_attesi"], 1.06)
        self.assertTrue(server.STATO["lotto_id"])
        persisted = dataset_store.carica_attivo()
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["metadati"]["lotto_id"], server.STATO["lotto_id"])
        metrics_page = self.client.get("/valutazione")
        self.assertIn("Metriche non disponibili", metrics_page.text)

        report = self.client.get("/azienda/TEST-ER-1/report.pdf")
        self.assertEqual(report.status_code, 200, report.text[:200])
        self.assertEqual(report.headers.get("content-type"), "application/pdf")
        self.assertTrue(report.content.startswith(b"%PDF-"))
        self.assertEqual(report.headers.get("cache-control"), "no-store")
        self.assertTrue(any(e.get("azione") == "generazione_report_pdf" for e in audit.leggi(100)))

    def test_acquisizione_fonte_pubblica_archivia_payload_e_hash(self):
        from app.connettori.fonti_live import PayloadFonte
        raw = b'{"records":[{"anno":2025}]}'
        payload = PayloadFonte(
            chiave="inail:test", url="https://dati.inail.it/api/OpenData/test",
            acquisito_il="2026-10-22T00:00:00+00:00", status_http=200,
            content_type="application/json", dimensione_byte=len(raw),
            sha256=__import__("hashlib").sha256(raw).hexdigest(), contenuto=raw,
            metadati={"test": True},
        )
        with patch.object(server.fonti_live, "acquisisci_inail", return_value=payload):
            page = self.client.get("/fonti")
            response = self.client.post("/fonti/acquisisci", data={
                "csrf_token": self._csrf(page), "tipo": "inail",
                "dataset_inail": "infortuni_mensili", "parametri": "",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Acquisizione archiviata", response.text)
        archivio = fonti_store.elenco(10)
        self.assertEqual(len(archivio), 1)
        self.assertEqual(archivio[0]["sha256"], payload.sha256)
        downloaded = self.client.get(f"/fonti/{archivio[0]['id']}/scarica")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, raw)
        self.assertEqual(downloaded.headers.get("cache-control"), "no-store")


    def test_mapping_fonte_normalizza_osservazioni_e_non_tocca_punteggi(self):
        from app.connettori.fonti_live import PayloadFonte
        raw = b"anno;regione;coltura;ore\n2025;Lazio;pomodoro;1.234,5\n2024;Umbria;pomodoro;980,25\n"
        payload = PayloadFonte(
            chiave="test:csv", url="https://dati.inail.it/api/OpenData/test.csv",
            acquisito_il="2026-10-22T00:00:00+00:00", status_http=200,
            content_type="text/csv", dimensione_byte=len(raw),
            sha256=__import__("hashlib").sha256(raw).hexdigest(), contenuto=raw,
            metadati={"test": True},
        )
        saved = fonti_store.salva(payload)
        page = self.client.get(f"/fonti/{saved['id']}/mappatura")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("1.234,5", page.text)
        response = self.client.post("/fonti/mappatura/crea", data={
            "csrf_token": self._csrf(page), "acquisizione_id": saved["id"],
            "settore_id": "agricoltura", "parametro_id": "agri_ore_ha_pomodoro",
            "campo_valore": "ore", "campo_periodo": "anno", "campo_territorio": "regione",
            "campo_categoria": "coltura", "campo_unita": "", "unita_fissa": "ore/ettaro",
            "formato_numero": "virgola",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        self.assertTrue(response.headers["location"].startswith("/fonti/mappature/"))
        mapping_id = response.headers["location"].rsplit("/", 1)[-1]
        detail = self.client.get(response.headers["location"])
        self.assertEqual(detail.status_code, 200, detail.text)
        rows = fonti_mapping.osservazioni(mapping_id)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["valore"], 1234.5)
        self.assertEqual(rows[0]["territorio"], "Lazio")
        self.assertEqual(rows[0]["stato"], "da_verificare")
        self.assertIn("non sono attualmente utilizzate automaticamente nel punteggio", detail.text)
        reviewed = self.client.post("/fonti/mappatura/revisiona", data={
            "csrf_token": self._csrf(detail), "mapping_id": mapping_id,
            "stato": "mapping_verificato",
            "nota": "Colonne, unità e trasformazione numerica controllate sul payload originale.",
        }, follow_redirects=False)
        self.assertEqual(reviewed.status_code, 303)
        self.assertTrue(all(r["stato"] == "mapping_verificato" for r in fonti_mapping.osservazioni(mapping_id)))

    def test_grafo_relazione_documentata_e_revisione_via_interfaccia(self):
        aziende = server.STATO["aziende"]
        self.assertGreaterEqual(len(aziende), 2)
        origine = str(aziende[0]["id"])
        destinazione = str(aziende[1]["id"])
        page = self.client.get("/grafo")
        response = self.client.post("/grafo/aggiungi", data={
            "csrf_token": self._csrf(page), "origine_id": origine,
            "destinazione_id": destinazione, "tipo": "subappalto_documentato",
            "evidenza": "Il contratto e il documento allegato descrivono il subappalto tra queste imprese.",
            "url_fonte": "https://example.org/contratto", "riferimento_documento": "",
        })
        self.assertEqual(response.status_code, 200, response.text)
        relazioni = grafo.elenco(10)
        self.assertEqual(len(relazioni), 1)
        self.assertEqual(relazioni[0]["stato"], "da_verificare")
        self.assertIn("non costituisce prova di illecito", response.text)
        ident = relazioni[0]["id"]
        page = self.client.get("/grafo")
        response = self.client.post("/grafo/revisiona", data={
            "csrf_token": self._csrf(page), "id": ident,
            "stato": "confermata_documentalmente",
            "nota": "Il riferimento è stato confrontato con la fonte primaria disponibile.",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(grafo.elenco(10)[0]["stato"], "confermata_documentalmente")


if __name__ == "__main__":
    unittest.main()
