"""Archivio operativo, migrazioni, pratiche, relazioni PDF, backup, audit e sessioni."""
import json
from contextlib import closing
import os
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app import audit, backup, db_operativo, documenti, pratiche, sessioni, settori
from app.dati_sintetici import genera_aziende
from app.motore.analisi import analizza


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.radice = Path(self.tmp.name)
        registro = self.radice / "config" / "registro_emersione.json"
        registro.parent.mkdir()
        shutil.copyfile(settori.PERCORSO_REGISTRO, registro)
        for p in (patch.object(settori, "PERCORSO_REGISTRO", registro),
                  patch.object(db_operativo, "DB_PATH", self.radice / "dati" / "operativo.sqlite3"),
                  patch.object(audit, "PERCORSO_LOG", self.radice / "dati" / "audit.jsonl"),
                  patch.object(sessioni, "DB_PATH", self.radice / "dati" / "sessioni.sqlite3"),
                  patch.object(documenti, "_STORAGE", self.radice / "dati" / "documenti")):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)


class MigrazioniTests(Base):
    def test_migrazioni_idempotenti_e_versione(self):
        self.assertEqual(db_operativo.applica_migrazioni(), list(range(1, db_operativo.VERSIONE_SCHEMA + 1)))
        self.assertEqual(db_operativo.applica_migrazioni(), [])
        self.assertEqual(db_operativo.versione_schema(), db_operativo.VERSIONE_SCHEMA)

    def test_schema_piu_recente_rifiutato(self):
        db_operativo.applica_migrazioni()
        with closing(sqlite3.connect(db_operativo.DB_PATH)) as c:
            c.execute("PRAGMA user_version=99")
        with self.assertRaises(db_operativo.ErroreDB):
            db_operativo.applica_migrazioni()

    def test_migrazione_fallita_non_lascia_schema_parziale(self):
        originali = list(db_operativo.MIGRAZIONI)
        rotta = originali[:1] + [(2, "rotta", "CREATE TABLE ok_temp (x INTEGER); CREATE TABLE ok_temp (y INTEGER)")]
        with patch.object(db_operativo, "MIGRAZIONI", rotta), patch.object(db_operativo, "VERSIONE_SCHEMA", 2):
            with self.assertRaises(sqlite3.Error):
                db_operativo.applica_migrazioni()
        self.assertEqual(db_operativo.versione_schema(), 1)
        with closing(sqlite3.connect(db_operativo.DB_PATH)) as c:
            self.assertIsNone(c.execute("SELECT name FROM sqlite_master WHERE name='ok_temp'").fetchone())


class EsecuzioniPraticheTests(Base):
    def test_esecuzione_conserva_risultati_senza_etichette(self):
        aziende = analizza(genera_aziende(20, seme=3))
        eid = db_operativo.registra_esecuzione(aziende, utente="u", motivo="test", versione_motore="v", hash_configurazione="h",
                                               hash_dataset=None, origine="sintetico", sintetico=True)
        e = db_operativo.ottieni_esecuzione(eid)
        self.assertEqual(e["numero_record"], 20)
        storico = db_operativo.risultato_storico(eid, aziende[0]["id"])
        self.assertEqual(storico["punteggio"], aziende[0]["analisi"]["punteggio"])
        with closing(sqlite3.connect(db_operativo.DB_PATH)) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM risultati WHERE analisi LIKE '%_irregolare%'").fetchone()[0], 0)

    def test_ciclo_pratica(self):
        pid = pratiche.crea(azienda_id="AZ1", esecuzione_id=None, finalita="Verifica di coerenza dei dati dichiarati",
                            ambito="Annualità 2025", utente="analista")
        with self.assertRaises(pratiche.ErrorePratica):
            pratiche.aggiungi_evento(pid, utente="analista", nota="Salto non consentito", nuovo_stato="trasmessa")
        pratiche.aggiungi_evento(pid, utente="analista", nota="Avvio approfondimento", nuovo_stato="in_approfondimento")
        pratiche.aggiungi_evento(pid, utente="analista", nota="Fascicolo inoltrato all'ufficio", nuovo_stato="trasmessa")
        p = pratiche.ottieni(pid)
        self.assertEqual(p["stato"], "trasmessa")
        self.assertEqual([e["tipo"] for e in p["eventi"]], ["creazione", "stato:aperta→in_approfondimento", "stato:in_approfondimento→trasmessa"])
        self.assertEqual(p["transizioni"], [])
        with self.assertRaises(pratiche.ErrorePratica):
            pratiche.crea(azienda_id="AZ1", esecuzione_id=None, finalita="corta", ambito="x", utente="a")

    def test_registro_relazioni_pdf(self):
        db_operativo.registra_report(report_id="REL-1", utente="a", ruolo="analista", azienda_id="AZ1", pratica_id=None,
                                     esecuzione_id=None, sha256="a" * 64, byte=10)
        self.assertEqual(db_operativo.verifica_report("a" * 64)["id"], "REL-1")
        self.assertIsNone(db_operativo.verifica_report("b" * 64))


class AuditTests(Base):
    def test_ancoraggio_rileva_rimozione_della_coda(self):
        for i in range(6):
            audit.registra("u", "azione", f"evento {i}")
        punto = audit.ancoraggio()
        self.assertEqual(audit.verifica_ancoraggio(punto)["esito"], "conforme")
        righe = audit.PERCORSO_LOG.read_text(encoding="utf-8").splitlines(keepends=True)
        audit.PERCORSO_LOG.write_text("".join(righe[:-2]), encoding="utf-8")
        self.assertTrue(audit.verifica_integrita()["valida"])          # la catena residua è coerente...
        self.assertEqual(audit.verifica_ancoraggio(punto)["esito"], "difforme")   # ...ma l'ancoraggio lo rileva

    def test_rotazione_mantiene_il_collegamento(self):
        for i in range(3):
            audit.registra("u", "azione", f"evento {i}")
        ultimo = audit.verifica_integrita()["ultimo_hash"]
        esito = audit.ruota(self.radice / "archivio")
        self.assertTrue(Path(esito["archivio"]).exists())
        self.assertTrue(audit.verifica_integrita(Path(esito["archivio"]))["valida"])
        primo = json.loads(audit.PERCORSO_LOG.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(primo["azione"], "apertura_segmento_audit")
        self.assertEqual(primo["sha256"], ultimo)

    def test_correlazione_e_metadati_non_ammessi(self):
        token = audit.CORRELAZIONE.set("abc123")
        try:
            audit.registra("u", "azione", "x", password="segreto", esito="ok")
        finally:
            audit.CORRELAZIONE.reset(token)
        evento = json.loads(audit.PERCORSO_LOG.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(evento["request_id"], "abc123")
        self.assertNotIn("password", evento)

    def test_scritture_concorrenti(self):
        thread = [threading.Thread(target=lambda: [audit.registra("u", "a", "x") for _ in range(20)]) for _ in range(5)]
        [t.start() for t in thread]
        [t.join() for t in thread]
        esito = audit.verifica_integrita()
        self.assertTrue(esito["valida"], esito["errori"][:3])
        self.assertEqual(esito["eventi_verificati"], 100)


class SessioniTests(Base):
    def test_revoca_per_utente_e_totale(self):
        sessioni.crea("s1", "mario")
        sessioni.crea("s2", "mario")
        sessioni.crea("s3", "lucia")
        self.assertEqual(sessioni.revoca_utente("mario"), 2)
        self.assertFalse(sessioni.valida("s1", "mario"))
        self.assertTrue(sessioni.valida("s3", "lucia"))
        self.assertEqual(sessioni.revoca_tutte(), 1)
        self.assertEqual(sessioni.attive(), [])


class BackupTests(Base):
    def test_backup_verifica_ripristino_e_manomissione(self):
        db_operativo.registra_esecuzione(analizza(genera_aziende(5, seme=1)), utente="u", motivo="m", versione_motore="v",
                                         hash_configurazione="h", hash_dataset=None, origine="o", sintetico=True)
        audit.registra("u", "prima_del_backup", "")
        documenti._STORAGE.mkdir(parents=True, exist_ok=True)
        (documenti._STORAGE / "doc.txt").write_text("contenuto", encoding="utf-8")
        archivio = backup.crea(self.radice / "backup")
        esito = backup.verifica(archivio)
        self.assertTrue(esito["valido"], esito["errori"])

        with self.assertRaises(FileExistsError):
            backup.ripristina(archivio)
        # perdita di dati, poi ripristino
        os.remove(db_operativo.DB_PATH)
        audit.registra("u", "dopo_il_backup", "")
        risultato = backup.ripristina(archivio, forza=True)
        self.assertIn("dati/emersione_operativo.sqlite3", risultato["ripristinati"])
        self.assertEqual(len(db_operativo.elenco_esecuzioni()), 1)
        self.assertNotIn("dopo_il_backup", audit.PERCORSO_LOG.read_text(encoding="utf-8"))
        self.assertTrue(list(audit.PERCORSO_LOG.parent.glob("audit.jsonl.pre-ripristino-*")))
        self.assertEqual((documenti._STORAGE / "doc.txt").read_text(encoding="utf-8"), "contenuto")

        # archivio manomesso: rifiutato
        manomesso = self.radice / "manomesso.tar.gz"
        with tarfile.open(archivio, "r:gz") as src, tarfile.open(manomesso, "w:gz") as dst:
            for m in src.getmembers():
                dati = src.extractfile(m).read() if m.isfile() else None
                if m.name == "config/registro_emersione.json":
                    dati = dati.replace(b'"valore": 1600', b'"valore": 1700')
                    m.size = len(dati)
                import io
                dst.addfile(m, io.BytesIO(dati) if dati is not None else None)
        self.assertFalse(backup.verifica(manomesso)["valido"])
        with self.assertRaises(ValueError):
            backup.ripristina(manomesso, forza=True)

    def test_archivio_con_percorsi_pericolosi_rifiutato(self):
        pericoloso = self.radice / "p.tar.gz"
        import io
        with tarfile.open(pericoloso, "w:gz") as t:
            info = tarfile.TarInfo("../fuori.txt")
            info.size = 1
            t.addfile(info, io.BytesIO(b"x"))
        with self.assertRaises(ValueError):
            backup.verifica(pericoloso)


if __name__ == "__main__":
    unittest.main()
