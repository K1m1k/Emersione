import hashlib
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.connettori import fonti_live
from app import fonti_store

class _Response:
    status = 200
    headers = {"Content-Type": "application/json; charset=utf-8", "Content-Length": "17"}
    def __init__(self, data=b'{"records": [1]}'):
        self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, n=-1): return self.data[:n]

class _Opener:
    def open(self, request, timeout=None):
        self.request = request
        return _Response()

class FontiLiveTests(unittest.TestCase):
    def test_endpoint_inail_conosciuto_e_allowlist(self):
        self.assertIn("infortuni_mensili", fonti_live.INAIL_ENDPOINTS)
        with self.assertRaises(fonti_live.ErroreAcquisizione):
            fonti_live.acquisisci_istat("https://example.org/HVD/rest/data/foo")
        with self.assertRaises(fonti_live.ErroreAcquisizione):
            fonti_live.acquisisci_anac("https://dati.anticorruzione.it.evil.example/opendata/file.csv")
        with self.assertRaises(fonti_live.ErroreAcquisizione):
            fonti_live.acquisisci_inail("dataset-non-esistente")

    def test_acquisizione_inail_validata_e_archiviabile(self):
        addr = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "fonti.sqlite3"
            with patch.object(fonti_live.socket, "getaddrinfo", return_value=addr), \
                 patch.object(fonti_live.urllib.request, "build_opener", return_value=_Opener()), \
                 patch.object(fonti_store, "DB_PATH", db):
                fonti_store._READY.clear()
                payload = fonti_live.acquisisci_inail("infortuni_mensili", {"Regione": "Lazio"})
                self.assertEqual(payload.status_http, 200)
                self.assertEqual(payload.sha256, hashlib.sha256(payload.contenuto).hexdigest())
                saved = fonti_store.salva(payload)
                self.assertEqual(saved["formato"], "json")
                result = fonti_store.contenuto(saved["id"])
                self.assertIsNotNone(result)
                self.assertEqual(result[1], payload.contenuto)

    def test_parser_csv_strutturato_e_xml_con_virgole(self):
        raw_csv = b"anno;regione;valore\n2025;Lazio;12\n"
        csv_payload = fonti_live.PayloadFonte("test", "https://dati.inail.it/api/OpenData/x", "now", 200,
            "text/csv", len(raw_csv), hashlib.sha256(raw_csv).hexdigest(), raw_csv, {})
        parsed_csv = fonti_live.prova_parsabilita(csv_payload)
        self.assertEqual(parsed_csv["formato"], "csv")
        self.assertIn("2 righe", parsed_csv["nota"])

        raw_xml = b'<?xml version="1.0"?><root><v>uno, due, tre</v></root>'
        xml_payload = fonti_live.PayloadFonte("test", "https://sdmx.istat.it/HVD/x", "now", 200,
            "application/xml", len(raw_xml), hashlib.sha256(raw_xml).hexdigest(), raw_xml, {})
        self.assertEqual(fonti_live.prova_parsabilita(xml_payload)["formato"], "xml")

    def test_parser_rifiuta_xml_con_doctype_anche_in_utf16(self):
        raw = '<?xml version="1.0"?><!DOCTYPE root [<!ENTITY x "bad">]><root>&x;</root>'.encode("utf-16")
        payload = fonti_live.PayloadFonte("test", "https://sdmx.istat.it/HVD/x", "now", 200,
            "application/xml", len(raw), hashlib.sha256(raw).hexdigest(), raw, {})
        with self.assertRaisesRegex(fonti_live.ErroreAcquisizione, "DTD/entity"):
            fonti_live.prova_parsabilita(payload)

    def test_rifiuta_dns_non_pubblico_e_json_malformato(self):
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch.object(fonti_live.socket, "getaddrinfo", return_value=private):
            with self.assertRaisesRegex(fonti_live.ErroreAcquisizione, "non pubblico"):
                fonti_live.acquisisci_inail("infortuni_mensili")
        payload = fonti_live.PayloadFonte("test", "https://dati.inail.it/api/OpenData/x", "now", 200,
            "application/json", 3, hashlib.sha256(b"bad").hexdigest(), b"bad", {})
        with self.assertRaises(fonti_live.ErroreAcquisizione):
            fonti_live.prova_parsabilita(payload)

if __name__ == "__main__": unittest.main()
