import os, socket, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from app import osint

class _Response:
    status = 200
    headers = {"Content-Type": "text/html; charset=utf-8", "Content-Length": "100"}
    data = b'<html><head><title>Avviso pubblico</title><script>segreto</script></head><body><main><h1>Ricerca personale</h1><p>Testo di interesse documentale.</p></main></body></html>'
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, n=-1): return self.data[:n]
class _Opener:
    def open(self, req, timeout=None): return _Response()

class OsintTests(unittest.TestCase):
    def test_rifiuta_senza_allowlist_o_host_non_autorizzato(self):
        with patch.dict(os.environ, {"EMERSIONE_OSINT_ALLOWED_DOMAINS": ""}):
            with self.assertRaisesRegex(osint.ErroreOSINT, "Nessun dominio"):
                osint._valida_url("https://example.org/page")
        with patch.dict(os.environ, {"EMERSIONE_OSINT_ALLOWED_DOMAINS": "example.org"}):
            with self.assertRaisesRegex(osint.ErroreOSINT, "allowlist"):
                osint._valida_url("https://evil.example/page")
            with self.assertRaises(osint.ErroreOSINT):
                osint._valida_url("http://example.org/page")

    def test_acquisizione_pagina_con_hash_ed_esito_revisione(self):
        addr = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"EMERSIONE_OSINT_ALLOWED_DOMAINS": "example.org"}), \
             patch.object(osint, "DB_PATH", Path(tmp) / "osint.sqlite3"), \
             patch.object(osint.socket, "getaddrinfo", return_value=addr), \
             patch.object(osint.urllib.request, "build_opener", return_value=_Opener()):
            osint._READY.clear()
            observation = osint.acquisisci("https://example.org/report", utente="test-admin", motivazione="Verifica puntuale di un elemento documentale pubblico.")
            self.assertEqual(observation["titolo"], "Avviso pubblico")
            self.assertNotIn("segreto", observation["estratto"])
            self.assertEqual(observation["stato"], "da_verificare")
            osint.rivedi(observation["id"], "non_pertinente", "test-admin", "Il contenuto non è pertinente al caso esaminato.")
            self.assertEqual(osint.elenco()[0]["stato"], "non_pertinente")
            self.assertEqual(osint.elenco()[0]["nota_revisore"], "Il contenuto non è pertinente al caso esaminato.")

if __name__ == "__main__": unittest.main()
