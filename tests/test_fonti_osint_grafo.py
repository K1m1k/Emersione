"""Scoperta dataset, limite di frequenza ISTAT, proposte di collegamento, OSINT su più pagine, grafo OCDS."""
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import collegamento_semantico, db_operativo, fonti_mapping, fonti_store, grafo, osint, osint_esteso, settori
from app.connettori import fonti_live, scoperta
from app.connettori.fonti_live import PayloadFonte

SDMX = b"""<?xml version="1.0" encoding="UTF-8"?>
<message:Structure xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
 xmlns:structure="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure"
 xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common">
 <message:Structures><structure:Dataflows>
  <structure:Dataflow id="150_908" agencyID="IT1" version="1.0">
   <common:Name xml:lang="it">Occupati per settore di attivita economica</common:Name>
   <common:Name xml:lang="en">Employed persons by economic activity</common:Name>
  </structure:Dataflow>
  <structure:Dataflow id="101_1015" agencyID="IT1" version="1.2">
   <common:Name xml:lang="it">Coltivazioni: superfici e produzione</common:Name>
  </structure:Dataflow>
 </structure:Dataflows></message:Structures></message:Structure>"""


def payload(chiave, url, contenuto, ct="application/xml"):
    return PayloadFonte(chiave=chiave, url=url, acquisito_il="2026-10-22T00:00:00+00:00", status_http=200, content_type=ct,
                        dimensione_byte=len(contenuto), sha256=hashlib.sha256(contenuto).hexdigest(), contenuto=contenuto,
                        metadati={})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        r = Path(self.tmp.name)
        registro = r / "registro_emersione.json"
        shutil.copyfile(settori.PERCORSO_REGISTRO, registro)
        for p in (patch.object(settori, "PERCORSO_REGISTRO", registro),
                  patch.object(db_operativo, "DB_PATH", r / "operativo.sqlite3"),
                  patch.object(fonti_store, "DB_PATH", r / "fonti.sqlite3"),
                  patch.object(fonti_mapping, "DB_PATH", r / "mappature.sqlite3"),
                  patch.object(osint, "DB_PATH", r / "osint.sqlite3"),
                  patch.object(grafo, "DB_PATH", r / "grafo.sqlite3")):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)


class FrequenzaTests(unittest.TestCase):
    def test_limite_istat_sotto_la_soglia_ufficiale(self):
        fonti_live._STORICO_RICHIESTE.clear()
        massimo, finestra = fonti_live.LIMITI_FREQUENZA["esploradati.istat.it"]
        self.assertLess(massimo, 5)          # ISTAT: 5 richieste/minuto per IP
        self.assertEqual(finestra, 60.0)
        for _ in range(massimo):
            fonti_live._controlla_frequenza("esploradati.istat.it")
        with self.assertRaisesRegex(fonti_live.ErroreAcquisizione, "Limite di frequenza"):
            fonti_live._controlla_frequenza("esploradati.istat.it")
        fonti_live._controlla_frequenza("host.non.limitato.example")
        fonti_live._STORICO_RICHIESTE.clear()


class ScopertaTests(Base):
    def test_dataflow_istat_nel_catalogo(self):
        chiamate = []

        def fetch(chiave, url, host, prefissi, parametri=None):
            chiamate.append(url)
            fonti_live._valida_url(url, host, prefissi)      # l'URL rispetta le regole del connettore
            return payload(chiave, url, SDMX)
        esito = scoperta.scopri_istat(fetch)
        self.assertEqual(chiamate, ["https://esploradati.istat.it/SDMXWS/rest/dataflow/IT1"])
        self.assertEqual(esito["voci"], 2)
        trovate = scoperta.cerca_catalogo("occupati")
        self.assertEqual(len(trovate), 1)
        self.assertEqual(trovate[0]["nome"], "Occupati per settore di attivita economica")
        self.assertTrue(trovate[0]["url_dati"].endswith("/data/150_908"))

    def test_xml_con_entita_rifiutato(self):
        with self.assertRaises(scoperta.ErroreScoperta):
            scoperta.analizza_dataflow_sdmx(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>')

    def test_anac_non_configurato_non_scopre(self):
        with patch.dict(os.environ, {"EMERSIONE_ANAC_CATALOGO_API": ""}):
            with self.assertRaisesRegex(scoperta.ErroreScoperta, "non configurato"):
                scoperta.scopri_anac("appalti")
            self.assertEqual(next(c for c in scoperta.stato_connettori() if c["fonte"] == "anac")["stato"], "non_configurato")

    def test_anac_configurato_accetta_solo_risorse_ufficiali(self):
        risposta = json.dumps({"result": {"results": [
            {"name": "cig-2025", "title": "CIG 2025", "license_title": "CC BY 4.0", "resources": [
                {"url": "https://evil.example/x.csv"}, {"url": "https://dati.anticorruzione.it/opendata/download/cig.zip"}]},
            {"name": "senza-risorse", "title": "Senza risorse", "resources": []}]}}).encode()
        with patch.dict(os.environ, {"EMERSIONE_ANAC_CATALOGO_API": "https://dati.anticorruzione.it/opendata/api/verificata"}):
            esito = scoperta.scopri_anac("cig", lambda *a, **k: payload("anac", a[1], risposta, "application/json"))
        self.assertEqual(esito["voci"], 2)
        voci = {v["identificativo"]: v for v in scoperta.cerca_catalogo(fonte="anac")}
        self.assertEqual(voci["cig-2025"]["url_dati"], "https://dati.anticorruzione.it/opendata/download/cig.zip")
        self.assertIsNone(voci["senza-risorse"]["url_dati"])


class CollegamentoTests(Base):
    def _mappatura_verificata(self, unita="ore/anno"):
        csv = f"anno,valore,unita\n2023,1580,{unita}\n2024,1620,{unita}\n".encode()
        acq = fonti_store.salva(payload("istat:test", "https://esploradati.istat.it/SDMXWS/rest/data/X", csv, "text/csv"))
        m = fonti_mapping.crea_mappatura(acquisizione_id=acq["id"], settore_id="agricoltura", parametro_id="ore_annue_addetto",
                                         campo_valore="valore", campo_periodo="anno", campo_unita="unita", utente="dati")
        return m

    def test_proposta_richiede_mappatura_verificata_e_revisore_diverso(self):
        m = self._mappatura_verificata()
        with self.assertRaisesRegex(collegamento_semantico.ErroreCollegamento, "mapping_verificato"):
            collegamento_semantico.proponi(mapping_id=m["id"], parametro_id="ore_annue_addetto", statistica="mediana", utente="dati")
        fonti_mapping.revisiona(m["id"], stato="mapping_verificato", nota="Colonne e unità controllate sul dataset.", revisore="rev")
        with self.assertRaisesRegex(collegamento_semantico.ErroreCollegamento, "2 osservazioni"):
            collegamento_semantico.proponi(mapping_id=m["id"], parametro_id="ore_annue_addetto", statistica="valore_unico", utente="dati")
        prop = collegamento_semantico.proponi(mapping_id=m["id"], parametro_id="ore_annue_addetto", statistica="mediana", utente="dati")
        self.assertEqual(prop["valore_proposto"], 1600)
        self.assertTrue(prop["unita_compatibili"])
        self.assertEqual(settori.catalogo_parametri()["ore_annue_addetto"]["valore"], 1600)   # nulla applicato
        with self.assertRaisesRegex(collegamento_semantico.ErroreCollegamento, "Solo il revisore"):
            collegamento_semantico.decidi(prop["id"], decisione="applicata", utente="admin", ruolo="amministratore", nota="x" * 25)
        with self.assertRaisesRegex(collegamento_semantico.ErroreCollegamento, "Separazione"):
            collegamento_semantico.decidi(prop["id"], decisione="applicata", utente="dati", ruolo="revisore", nota="x" * 25)
        esito = collegamento_semantico.decidi(prop["id"], decisione="applicata", utente="rev", ruolo="revisore",
                                              nota="Mediana 2023-2024 coerente con la definizione del parametro.")
        param = settori.catalogo_parametri()["ore_annue_addetto"]
        self.assertEqual(param["stato"], "da_verificare")
        self.assertIn(prop["id"], param["fonte"])
        self.assertEqual(esito["versione_parametro"], param["versione"])
        # solo i settori che usano il parametro tornano in revisione; gli altri restano invariati
        stati = {s["id"]: s["stato"] for s in settori.lista_settori()}
        self.assertEqual(stati, {"agricoltura": "in_revisione", "edilizia": "in_revisione",
                                 "ristorazione": "sperimentale", "logistica": "sperimentale"})

    def test_unita_diverse_non_applicabili(self):
        m = self._mappatura_verificata(unita="ore/mese")
        fonti_mapping.revisiona(m["id"], stato="mapping_verificato", nota="Colonne controllate; unità mensile.", revisore="rev")
        prop = collegamento_semantico.proponi(mapping_id=m["id"], parametro_id="ore_annue_addetto", statistica="media",
                                              utente="dati", periodo="2024")
        self.assertFalse(prop["unita_compatibili"])
        with self.assertRaisesRegex(collegamento_semantico.ErroreCollegamento, "conversione"):
            collegamento_semantico.decidi(prop["id"], decisione="applicata", utente="rev", ruolo="revisore", nota="x" * 25)

    def test_suggerimenti_lessicali(self):
        s = collegamento_semantico.suggerisci_parametri(["ore annue addetto"], "ore/anno")
        self.assertEqual(s[0]["parametro_id"], "ore_annue_addetto")
        self.assertIn("non verificato", s[0]["nota"])


class OsintEstesoTests(Base):
    def _sito(self, robots=b"User-agent: *\nDisallow: /privato\n"):
        pagine = {
            "https://fonte.example.it/robots.txt": (200, "text/plain", robots),
            "https://fonte.example.it/": (200, "text/html", b'<html><title>Home</title><body><p>Ditta Alfa assume braccianti</p>'
                                         b'<a href="/a">a</a><a href="/privato/x">p</a><a href="https://altro.example/z">z</a>'
                                         b'<a href="/a#frammento">a2</a></body></html>'),
            "https://fonte.example.it/a": (200, "text/html", b"<html><title>A</title><body><p>Ditta Alfa cantiere</p><a href='/b'>b</a></body></html>"),
            "https://fonte.example.it/b": (200, "text/html", b"<html><body><p>profondita due</p></body></html>"),
        }
        visitati = []

        def scarica(url):
            visitati.append(url)
            return pagine.get(url, (404, "", b""))
        return scarica, visitati

    def test_raccolta_limitata_stesso_host_e_robots(self):
        scarica, visitati = self._sito()
        with patch.dict(os.environ, {"EMERSIONE_OSINT_ALLOWED_DOMAINS": "fonte.example.it"}), \
                patch.object(osint, "_valida_url", side_effect=lambda u: __import__("urllib.parse").parse.urlparse(u)):
            esito = osint_esteso.raccogli("https://fonte.example.it/", utente="analista", motivazione="Verifica annunci di lavoro pubblici",
                                          max_pagine=10, profondita=1, scarica=scarica, pausa=0)
        salvate = [p["url"] for p in esito["pagine_salvate"]]
        self.assertEqual(salvate, ["https://fonte.example.it/", "https://fonte.example.it/a"])   # profondità 1: /b escluso
        self.assertIn({"url": "https://fonte.example.it/privato/x", "motivo": "escluso da robots.txt"}, esito["saltate"])
        self.assertFalse(any("altro.example" in u for u in visitati))
        self.assertEqual({o["stato"] for o in osint.elenco()}, {"da_verificare"})

    def test_robots_illeggibile_blocca(self):
        def scarica(url):
            return (500, "", b"")
        with patch.object(osint, "_valida_url", side_effect=lambda u: __import__("urllib.parse").parse.urlparse(u)):
            with self.assertRaisesRegex(osint.ErroreOSINT, "robots.txt"):
                osint_esteso.raccogli("https://fonte.example.it/", utente="a", motivazione="Motivazione sufficiente qui",
                                      scarica=scarica, pausa=0)

    def test_limiti_massimi_imposti(self):
        scarica, _ = self._sito(robots=b"")
        with patch.object(osint, "_valida_url", side_effect=lambda u: __import__("urllib.parse").parse.urlparse(u)):
            esito = osint_esteso.raccogli("https://fonte.example.it/", utente="a", motivazione="Motivazione sufficiente qui",
                                          max_pagine=1000, profondita=99, scarica=scarica, pausa=0)
        self.assertLessEqual(len(esito["pagine_salvate"]), osint_esteso.MAX_PAGINE)

    def test_verifica_incrociata(self):
        scarica, _ = self._sito(robots=b"")
        with patch.object(osint, "_valida_url", side_effect=lambda u: __import__("urllib.parse").parse.urlparse(u)):
            osint_esteso.raccogli("https://fonte.example.it/", utente="a", motivazione="Motivazione sufficiente qui",
                                  max_pagine=2, profondita=1, scarica=scarica, pausa=0)
        r = osint_esteso.verifica_incrociata("Ditta Alfa")
        self.assertEqual(r["esito"], "fonte_singola")     # due pagine ma un solo dominio
        self.assertEqual(r["fonti_indipendenti"], 1)
        self.assertEqual(osint_esteso.verifica_incrociata("inesistente parola")["esito"], "non_riscontrata")


class GrafoTests(Base):
    def test_periodo_di_validita_e_riservatezza(self):
        base = dict(tipo="partecipazione_societaria", evidenza="Visura con partecipazione del 40% registrata in archivio.",
                    url_fonte="https://example.org/visura", utente="analista")
        grafo.aggiungi_relazione(origine_id="A", destinazione_id="B", valido_dal="2020-01-01", valido_al="2022-12-31", **base)
        grafo.aggiungi_relazione(origine_id="A", destinazione_id="C", riservatezza="riservata", **base)
        self.assertEqual(len(grafo.elenco(alla_data="2021-06-01")), 2)
        self.assertEqual(len(grafo.elenco(alla_data="2024-01-01")), 1)
        self.assertEqual([r["destinazione_id"] for r in grafo.elenco(includi_riservate=False)], ["B"])
        with self.assertRaises(grafo.ErroreGrafo):
            grafo.aggiungi_relazione(origine_id="A", destinazione_id="D", valido_dal="2022-01-01", valido_al="2021-01-01", **base)

    def test_suggerimenti_ocds_solo_per_identificativo_esatto(self):
        ocds = {"releases": [{"ocid": "ocds-x-1", "parties": [
            {"id": "P1", "identifier": {"id": "01234567890"}}, {"id": "P2", "identifier": {"id": "IT 098 765 43210"}},
            {"id": "P3", "name": "Alfa S.r.l.", "identifier": {"id": "55555555555"}}],
            "awards": [{"id": "aw1", "suppliers": [{"id": "P1"}, {"id": "P2"}, {"id": "P3"}]}]}]}
        aziende = [{"id": "AZ1", "partita_iva": "01234567890"}, {"id": "AZ2", "partita_iva": "IT09876543210"},
                   {"id": "AZ3", "ragione_sociale": "Alfa S.r.l."}]
        s = grafo.suggerimenti_da_ocds(json.dumps(ocds).encode(), aziende, url_fonte="https://dati.anticorruzione.it/opendata/x")
        self.assertEqual([(x["origine_id"], x["destinazione_id"]) for x in s], [("AZ1", "AZ2")])   # mai per nome
        self.assertEqual(s[0]["stato"], "candidato_non_verificato")
        self.assertEqual(grafo.elenco(), [])                                                      # nulla salvato


if __name__ == "__main__":
    unittest.main()
