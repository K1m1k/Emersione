"""Interfaccia web v3.1: matrice ruoli, pratiche, relazioni verificabili, esportazioni, audit, accessibilità."""
import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from starlette.testclient import TestClient

from app import (audit, dataset_store, db_operativo, documenti, fonti_mapping, fonti_store, grafo, osint, sessioni,
                 sicurezza, settori)
from app.web import server

PASSWORD = "Password di test sufficientemente robusta 2026!"
RUOLI = sorted(sicurezza.RUOLI)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = Path(self.tmp.name)
        self.vecchio_stato = copy.deepcopy(server.STATO)
        registro = r / "registro_emersione.json"
        shutil.copyfile(settori.PERCORSO_REGISTRO, registro)
        hash_pw = sicurezza.crea_hash_password(PASSWORD)
        self.utenti = [{"username": f"u-{ruolo}", "password_hash": hash_pw, "ruolo": ruolo} for ruolo in RUOLI]
        self.env = patch.dict(os.environ, {"EMERSIONE_ENV": "development",
                                           "EMERSIONE_USERS_JSON": json.dumps(self.utenti)})
        for p in (patch.object(settori, "PERCORSO_REGISTRO", registro),
                  patch.object(sessioni, "DB_PATH", r / "sessioni.sqlite3"),
                  patch.object(dataset_store, "DB_PATH", r / "dataset.sqlite3"),
                  patch.object(db_operativo, "DB_PATH", r / "operativo.sqlite3"),
                  patch.object(audit, "PERCORSO_LOG", r / "audit.jsonl"),
                  patch.object(documenti, "_STORAGE", r / "documenti"),
                  patch.object(fonti_store, "DB_PATH", r / "fonti.sqlite3"),
                  patch.object(fonti_mapping, "DB_PATH", r / "mappature.sqlite3"),
                  patch.object(osint, "DB_PATH", r / "osint.sqlite3"),
                  patch.object(grafo, "DB_PATH", r / "grafo.sqlite3"),
                  self.env):
            p.start()
            self.addCleanup(p.stop)
        server._carica_sintetici(persisti=False)
        self.addCleanup(self._ripristina)
        self.clienti = {}

    def _ripristina(self):
        for c in self.clienti.values():
            c.close()
        server.STATO.clear()
        server.STATO.update(self.vecchio_stato)
        self.tmp.cleanup()

    def cliente(self, ruolo):
        if ruolo not in self.clienti:
            c = TestClient(server.app)
            pagina = c.get("/login")
            token = re.search(r'name="csrf_token" value="([^"]+)"', pagina.text).group(1)
            r = c.post("/login", data={"csrf_token": token, "username": f"u-{ruolo}", "password": PASSWORD, "next": "/"},
                       follow_redirects=False)
            self.assertEqual(r.status_code, 303, ruolo)
            self.clienti[ruolo] = c
        return self.clienti[ruolo]

    def csrf(self, cliente, url="/"):
        return re.search(r'name="csrf_token" value="([^"]+)"', cliente.get(url).text).group(1)


class MatriceRuoliTests(Base):
    PAGINE = {
        "/": "consulta_elenco", "/azienda/AZ00000": "consulta_scheda", "/fonti": "consulta_fonti",
        "/fonti/catalogo": "catalogo_fonti", "/valutazione": "valutazione", "/carica": "importa_dati",
        "/audit": "audit", "/settori": "consulta_settori", "/settori/edilizia/gestione": "consulta_settori",
        "/documenti": "consulta_documenti", "/osint": "osint_consulta", "/grafo": "grafo_consulta",
        "/esecuzioni": "esecuzioni", "/pratiche": "pratiche_consulta", "/dipendenze": "dipendenze",
        "/esporta.csv": "esporta_dati", "/audit/esporta.csv": "esporta_audit",
    }

    def test_ogni_pagina_rispetta_la_matrice(self):
        for ruolo in RUOLI:
            c = self.cliente(ruolo)
            for url, permesso in self.PAGINE.items():
                with self.subTest(ruolo=ruolo, url=url):
                    atteso = 200 if ruolo in sicurezza.ruoli_per(permesso) else 403
                    self.assertEqual(c.get(url).status_code, atteso)

    def test_nessun_privilegio_di_validazione_all_amministratore(self):
        self.assertNotIn("amministratore", sicurezza.ruoli_per("valida_parametri"))
        self.assertNotIn("amministratore", sicurezza.ruoli_per("decidi_collegamenti"))
        self.assertEqual(sicurezza.ruoli_per("permesso_inesistente"), set())

    def test_menu_mostra_solo_le_voci_permesse(self):
        testo = self.cliente("consultazione").get("/").text
        self.assertIn('href="/pratiche"', testo)
        for voce in ('href="/audit"', 'href="/carica"', 'href="/settori"', 'href="/grafo"'):
            self.assertNotIn(voce, testo)

    def test_auditor_non_vede_schede_aziendali_ma_esporta_audit(self):
        c = self.cliente("auditor")
        self.assertEqual(c.get("/azienda/AZ00000").status_code, 403)
        r = c.get("/audit/esporta.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("# integrita", r.text)
        self.assertTrue(any(e["azione"] == "esportazione_audit" for e in audit.leggi(50)))


class SessioniEIdentitaTests(Base):
    def test_account_rimosso_perde_subito_l_accesso(self):
        c = self.cliente("analista")
        self.assertEqual(c.get("/").status_code, 200)
        rimasti = [u for u in self.utenti if u["ruolo"] != "analista"]
        with patch.dict(os.environ, {"EMERSIONE_USERS_JSON": json.dumps(rimasti)}):
            r = c.get("/", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["location"].startswith("/login"))

    def test_cambio_di_ruolo_applicato_alla_richiesta_successiva(self):
        c = self.cliente("amministratore")
        self.assertEqual(c.get("/audit").status_code, 200)
        cambiati = [dict(u, ruolo="consultazione") if u["ruolo"] == "amministratore" else u for u in self.utenti]
        with patch.dict(os.environ, {"EMERSIONE_USERS_JSON": json.dumps(cambiati)}):
            self.assertEqual(c.get("/audit").status_code, 403)

    def test_identificativo_di_correlazione_in_header_e_audit(self):
        r = self.cliente("analista").get("/azienda/AZ00001")
        rid = r.headers.get("x-request-id")
        self.assertRegex(rid or "", r"^[0-9a-f]{16}$")
        evento = next(e for e in audit.leggi(20) if e["azione"] == "consultazione_scheda")
        self.assertEqual(evento["request_id"], rid)


class PraticheERelazioniTests(Base):
    def test_pratica_relazione_e_verifica_integrita(self):
        c = self.cliente("analista")
        token = self.csrf(c, "/azienda/AZ00001")
        r = c.post("/pratiche/crea", data={"csrf_token": token, "azienda_id": "AZ00001",
                                            "finalita": "Approfondimento sulla coerenza tra produzione e addetti",
                                            "ambito": "Dati dichiarati nel lotto dimostrativo"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        pratica_id = r.headers["location"].rsplit("/", 1)[1]
        pagina = c.get(f"/pratiche/{pratica_id}")
        self.assertIn("Analisi alla data della pratica", pagina.text)
        esecuzione = server.STATO["esecuzione_id"]
        self.assertIsNotNone(esecuzione)

        pdf = c.get(f"/azienda/AZ00001/report.pdf?pratica={pratica_id}")
        self.assertEqual(pdf.status_code, 200)
        impronta = hashlib.sha256(pdf.content).hexdigest()
        verifica = c.get(f"/report/verifica?sha256={impronta}")
        self.assertIn("Corrispondenza trovata", verifica.text)
        self.assertIn(pratica_id, verifica.text)
        alterato = hashlib.sha256(pdf.content + b"x").hexdigest()
        self.assertIn("Nessuna corrispondenza", c.get(f"/report/verifica?sha256={alterato}").text)
        self.assertEqual(c.get("/report/verifica?sha256=nonvalido").status_code, 400)

        # pratica di un'altra azienda non utilizzabile per la relazione
        self.assertEqual(c.get(f"/azienda/AZ00002/report.pdf?pratica={pratica_id}").status_code, 404)

        token = self.csrf(c, f"/pratiche/{pratica_id}")
        self.assertEqual(c.post(f"/pratiche/{pratica_id}/evento", data={"csrf_token": token, "nota": "Esame avviato",
                                                                          "nuovo_stato": "in_approfondimento"},
                                follow_redirects=False).status_code, 303)
        self.assertEqual(c.post(f"/pratiche/{pratica_id}/evento", data={"nota": "senza token"}).status_code, 400)
        self.assertEqual(self.cliente("consultazione").post(f"/pratiche/{pratica_id}/evento", data={
            "csrf_token": self.csrf(self.cliente("consultazione"), "/pratiche"), "nota": "non autorizzato"}).status_code, 403)

    def test_pdf_contiene_le_sezioni_richieste(self):
        from pypdf import PdfReader
        import io
        c = self.cliente("analista")
        pdf = c.get("/azienda/AZ00001/report.pdf")
        testo = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
        for voce in ("Identificativo relazione", "Finalità dichiarata", "Operatore e ruolo", "Robustezza",
                     "Dati mancanti", "Natura delle informazioni", "Versione del documento", "Pagina 1"):
            self.assertIn(voce, testo, voce)

    def test_esportazione_csv_protetta(self):
        server.STATO["aziende"][0]["ragione_sociale"] = "=HYPERLINK(\"http://x\")"
        r = self.cliente("analista").get("/esporta.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("'=HYPERLINK", r.text)
        self.assertNotIn("_irregolare", r.text)
        self.assertIn("robustezza", r.text.splitlines()[0])


class ImportazioneTests(Base):
    PROV = {"conferente": "Ente di prova", "titolare": "Ente di prova", "finalita": "Collaudo del flusso di importazione",
            "autorizzazione": "Nota prot. 1/2026 (fittizia)", "data_ricezione": "2026-10-01", "condizioni_uso": "Solo collaudo"}
    CSV = b"id,settore,dipendenti_dichiarati,coperti_giorno_stimati\nR1,ristorazione,2,300\nR2,ristorazione,12,300\n"

    def _anteprima(self, c, **prov):
        dati = {"csrf_token": self.csrf(c, "/carica"), **self.PROV, **prov}
        r = c.post("/carica", data=dati, files={"file": ("lotto.csv", self.CSV, "text/csv")})
        self.assertEqual(r.status_code, 200, r.text[:300])
        return r, re.search(r'name="token" value="([^"]+)"', r.text).group(1)

    def test_fallimento_del_salvataggio_lascia_il_lotto_precedente(self):
        c = self.cliente("responsabile_dati")
        prima = server.STATO["aziende"]
        r, token = self._anteprima(c)
        with patch.object(dataset_store, "salva_attivo", side_effect=OSError("disco pieno")):
            esito = c.post("/carica/conferma", data={"csrf_token": self.csrf(c, "/carica"), "token": token})
        self.assertEqual(esito.status_code, 500)
        self.assertNotIn("disco pieno", esito.text)
        self.assertIs(server.STATO["aziende"], prima)
        self.assertTrue(server.STATO["dataset_sintetico"])

    def test_autorizzazione_scaduta_blocca_relazioni_esportazioni_pratiche(self):
        c = self.cliente("responsabile_dati")
        _, token = self._anteprima(c, data_ricezione="2020-01-01", scadenza_autorizzazione="2020-12-31")
        self.assertEqual(c.post("/carica/conferma", data={"csrf_token": self.csrf(c, "/carica"), "token": token}).status_code, 200)
        analista = self.cliente("analista")
        self.assertIn("autorizzazione dichiarata per il lotto attivo è scaduta", analista.get("/").text)
        self.assertEqual(analista.get("/azienda/R1/report.pdf").status_code, 409)
        self.assertEqual(analista.get("/esporta.csv").status_code, 409)
        r = analista.post("/pratiche/crea", data={"csrf_token": self.csrf(analista, "/azienda/R1"), "azienda_id": "R1",
                                                   "finalita": "Finalità sufficientemente lunga", "ambito": "Ambito di prova"})
        self.assertEqual(r.status_code, 409)

    def test_revoca_del_lotto(self):
        c = self.cliente("responsabile_dati")
        _, token = self._anteprima(c)
        c.post("/carica/conferma", data={"csrf_token": self.csrf(c, "/carica"), "token": token})
        lotto = server.STATO["lotto_id"]
        self.assertFalse(server.STATO["dataset_sintetico"])
        r = c.post("/lotto/revoca", data={"csrf_token": self.csrf(c, "/carica"), "motivo": "Il conferente ha segnalato dati errati"},
                   follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertTrue(server.STATO["dataset_sintetico"])
        from app import provenienza
        self.assertEqual(provenienza.per_lotto(lotto)["stato"], "revocato")

    def test_etichette_nel_file_non_arrivano_al_motore(self):
        c = self.cliente("responsabile_dati")
        csv = b"id,settore,dipendenti_dichiarati,coperti_giorno_stimati,_irregolare\nR1,ristorazione,2,300,true\n"
        r = c.post("/carica", data={"csrf_token": self.csrf(c, "/carica"), **self.PROV}, files={"file": ("l.csv", csv, "text/csv")})
        self.assertEqual(r.status_code, 200, r.text[:300])
        token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)
        c.post("/carica/conferma", data={"csrf_token": self.csrf(c, "/carica"), "token": token})
        self.assertNotIn("_irregolare", server.STATO["aziende"][0])


class SettoriWebTests(Base):
    def test_pagina_gestione_spiega_cosa_manca(self):
        testo = self.cliente("revisore").get("/settori/edilizia/gestione").text
        self.assertIn("Parametri non verificati/approvati", testo)
        self.assertIn("Collaudo automatico non ancora eseguito", testo)

    def test_collaudo_e_transizione_via_web_con_csrf(self):
        admin = self.cliente("amministratore")
        self.assertEqual(admin.post("/settori/edilizia/collaudo", data={}).status_code, 400)
        r = admin.post("/settori/edilizia/collaudo", data={"csrf_token": self.csrf(admin, "/settori/edilizia/gestione")})
        self.assertIn("Collaudo superato", r.text)
        r = admin.post("/settori/edilizia/transizione", data={
            "csrf_token": self.csrf(admin, "/settori/edilizia/gestione"), "a_stato": "approvato", "motivazione": "x" * 30})
        self.assertEqual(r.status_code, 400)        # l'amministratore non approva
        self.assertEqual(self.cliente("analista").post("/settori/edilizia/collaudo", data={
            "csrf_token": self.csrf(self.cliente("analista"))}).status_code, 403)

    def test_impatto_parametro(self):
        testo = self.cliente("revisore").get("/dipendenze?tipo=parametro&id=ore_annue_addetto").text
        self.assertIn("Agricoltura", testo)
        self.assertIn("Edilizia", testo)
        self.assertNotIn("Ristorazione</a>", testo)


class RegressioneSchedeTests(Base):
    def test_tutte_le_schede_e_relazioni_si_aprono(self):
        # Difetto della v3: le schede edilizie con dati incompleti per lo screening D.M. 143 davano errore 500.
        c = self.cliente("analista")
        errori = [a["id"] for a in server.STATO["aziende"] if c.get(f"/azienda/{a['id']}").status_code != 200]
        self.assertEqual(errori, [])
        edili = [a["id"] for a in server.STATO["aziende"] if a.get("settore") == "edilizia"][:5]
        for az_id in edili:
            self.assertEqual(c.get(f"/azienda/{az_id}/report.pdf").status_code, 200, az_id)


class ValutazioneEMonitoraggioTests(Base):
    def test_metriche_per_gruppo_e_ricerca(self):
        c = self.cliente("analista")
        testo = c.get("/valutazione").text
        for voce in ("Prestazioni per settore", "Prestazioni per territorio", "Prestazioni per dimensione", "Wilson"):
            self.assertIn(voce, testo)
        trovato = c.get("/?q=AZ00007").text
        self.assertIn("AZ00007", trovato)
        self.assertIn("1 record nel filtro corrente", trovato)

    def test_pagina_prestazioni_per_amministratore(self):
        self.cliente("amministratore").get("/")
        testo = self.cliente("amministratore").get("/prestazioni").text
        self.assertIn("<code>/</code>", testo)
        self.assertEqual(self.cliente("analista").get("/prestazioni").status_code, 403)


class _Moduli(HTMLParser):
    def __init__(self):
        super().__init__()
        self.campi, self.etichette, self.lang, self.skip = [], set(), None, False
        self._dentro_label = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        if tag == "a" and a.get("href") == "#contenuto":
            self.skip = True
        if tag == "label":
            self._dentro_label += 1
            if a.get("for"):
                self.etichette.add(a["for"])
        if tag in {"input", "select", "textarea"} and a.get("type") not in {"hidden", "submit"}:
            self.campi.append((a.get("id"), a.get("name"), self._dentro_label > 0, a.get("aria-label")))

    def handle_endtag(self, tag):
        if tag == "label":
            self._dentro_label -= 1


class AccessibilitaTests(Base):
    def test_campi_etichettati_lingua_e_salto_al_contenuto(self):
        pagine = ["/", "/azienda/AZ00001", "/fonti", "/fonti/catalogo", "/carica", "/settori", "/settori/edilizia/gestione",
                  "/documenti", "/osint", "/grafo", "/pratiche", "/dipendenze", "/esecuzioni", "/report/verifica",
                  "/valutazione", "/audit"]
        c = self.cliente("amministratore")
        for url in pagine:
            with self.subTest(url=url):
                p = _Moduli()
                p.feed(c.get(url).text)
                self.assertEqual(p.lang, "it")
                self.assertTrue(p.skip)
                senza = [(i, n) for i, n, in_label, aria in p.campi if not (in_label or aria or (i and i in p.etichette))]
                self.assertEqual(senza, [], f"campi senza etichetta in {url}")

    def test_stati_non_solo_colore(self):
        testo = self.cliente("analista").get("/").text
        self.assertRegex(testo, r'class="badge (alto|medio|basso|nessuno)">(alto|medio|basso|nessuno)')


if __name__ == "__main__":
    unittest.main()
