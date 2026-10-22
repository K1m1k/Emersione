import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from app import grafo

class GrafoTests(unittest.TestCase):
    def test_relazione_documentata_restando_da_verificare(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(grafo, "DB_PATH", Path(tmp) / "grafo.sqlite3"):
            grafo._READY.clear()
            r = grafo.aggiungi_relazione(origine_id="AZ01", destinazione_id="AZ02", tipo="subappalto_documentato",
                evidenza="Il documento indica esplicitamente un rapporto di subappalto tra le due imprese.",
                url_fonte="https://example.org/doc", dataset_hash="a" * 64, utente="tester")
            self.assertEqual(r["stato"], "da_verificare")
            self.assertEqual(len(r["hash_evidenza"]), 64)
            self.assertEqual(len(grafo.elenco()), 1)
            grafo.revisiona(r["id"], stato="confermata_documentalmente", nota="Contenuto confrontato con la fonte e verificato dal revisore.", revisore="revisore")
            self.assertEqual(grafo.elenco()[0]["stato"], "confermata_documentalmente")

    def test_suggerimenti_da_identificativi_esatti_non_sono_relazioni_confermate(self):
        records = [
            {"id": "AZ01", "ragione_sociale": "Alfa", "gruppo_societario_id": "GRUPPO-77"},
            {"id": "AZ02", "ragione_sociale": "Beta", "gruppo_societario_id": "GRUPPO-77"},
            {"id": "AZ03", "ragione_sociale": "Gamma", "gruppo_societario_id": "n/a"},
        ]
        candidati = grafo.suggerimenti_da_record(records)
        self.assertEqual(len(candidati), 1)
        self.assertEqual(candidati[0]["stato"], "candidato_non_verificato")
        self.assertEqual(grafo.elenco(), [])

    def test_rifiuta_relazione_senza_evidenza_o_fonte(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(grafo, "DB_PATH", Path(tmp) / "grafo.sqlite3"):
            grafo._READY.clear()
            with self.assertRaises(grafo.ErroreGrafo):
                grafo.aggiungi_relazione(origine_id="A", destinazione_id="B", tipo="altro_documentato", evidenza="Testo evidente e sufficiente da conservare.", utente="tester")
            with self.assertRaises(grafo.ErroreGrafo):
                grafo.aggiungi_relazione(origine_id="A", destinazione_id="A", tipo="altro_documentato", evidenza="Testo evidente e sufficiente da conservare.", url_fonte="https://example.org", utente="tester")

if __name__ == "__main__": unittest.main()
