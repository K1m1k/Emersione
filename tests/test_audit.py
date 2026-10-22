import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import audit


class AuditTests(unittest.TestCase):
    def test_hash_chain_valida_e_metadati_operativi_registrati(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(audit, "PERCORSO_LOG", Path(tmp) / "audit.jsonl"):
            audit.registra("operatore", "acquisizione", "dataset", esito="ok", sha256="a" * 64, byte=1234, motivo="non deve essere perso")
            audit.registra("operatore", "download", "fonte", esito="ok", request_id="ab12")
            risultato = audit.verifica_integrita()
            self.assertTrue(risultato["valida"], risultato)
            self.assertEqual(risultato["eventi_verificati"], 2)
            voci = audit.leggi(10)
            self.assertEqual(voci[0]["azione"], "download")
            self.assertEqual(voci[1]["sha256"], "a" * 64)
            self.assertEqual(voci[1]["byte"], 1234)
            self.assertEqual(voci[1]["motivo"], "non deve essere perso")

    def test_hash_chain_rileva_modifica_del_record(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(audit, "PERCORSO_LOG", Path(tmp) / "audit.jsonl"):
            audit.registra("operatore", "consultazione", "primo evento", esito="ok")
            audit.registra("operatore", "esportazione", "secondo evento", esito="ok")
            righe = audit.PERCORSO_LOG.read_text(encoding="utf-8").splitlines()
            record = json.loads(righe[0])
            record["dettaglio"] = "evento alterato"
            righe[0] = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            audit.PERCORSO_LOG.write_text("\n".join(righe) + "\n", encoding="utf-8")
            risultato = audit.verifica_integrita()
            self.assertFalse(risultato["valida"])
            self.assertTrue(risultato["errori"])


if __name__ == "__main__":
    unittest.main()
