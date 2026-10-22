import json
import os
import re
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

from app import sicurezza
from app.web.server import app


class SicurezzaTests(unittest.TestCase):
    def test_hash_password_roundtrip(self):
        hashed = sicurezza.crea_hash_password("Password corretta abbastanza lunga 2026!")
        self.assertTrue(sicurezza.verifica_hash_password("Password corretta abbastanza lunga 2026!", hashed))
        self.assertFalse(sicurezza.verifica_hash_password("password errata", hashed))

    def test_accesso_anonimo_reindirizzato(self):
        with patch.dict(os.environ, {"EMERSIONE_USERS_JSON": ""}):
            client = TestClient(app)
            res = client.get("/", follow_redirects=False)
            self.assertEqual(res.status_code, 303)
            self.assertTrue(res.headers["location"].startswith("/login"))

    def test_login_ruoli_e_csrf(self):
        password = "Password amministratore sufficientemente robusta 2026!"
        users = [{"username": "admin-test", "password_hash": sicurezza.crea_hash_password(password), "ruolo": "amministratore"},
                 {"username": "analista-test", "password_hash": sicurezza.crea_hash_password("Password analista abbastanza lunga 2026!"), "ruolo": "analista"}]
        with patch.dict(os.environ, {"EMERSIONE_USERS_JSON": json.dumps(users)}):
            client = TestClient(app)
            page = client.get("/login")
            token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            login = client.post("/login", data={"csrf_token": token, "username": "analista-test", "password": "Password analista abbastanza lunga 2026!", "next": "/"}, follow_redirects=False)
            self.assertEqual(login.status_code, 303)
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/carica").status_code, 403)
            self.assertEqual(client.get("/audit").status_code, 403)
            no_csrf = client.post("/ripristina", data={}, follow_redirects=False)
            self.assertEqual(no_csrf.status_code, 403)
            self.assertIn("x-content-type-options", {h.lower() for h in client.get("/").headers})

    def test_upload_non_autenticato_non_raggiunge_import(self):
        client = TestClient(app)
        res = client.post("/carica", data={}, follow_redirects=False)
        self.assertEqual(res.status_code, 303)


if __name__ == "__main__":
    unittest.main()
