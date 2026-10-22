"""Autenticazione locale a fail-closed e controlli di autorizzazione.

Per un deployment istituzionale è preferibile integrare l'IdP ufficiale (OIDC/SAML).
Questo modulo è una baseline locale: non sostituisce una verifica di sicurezza indipendente.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import threading
from collections import deque
from typing import Any

# Ruoli (sezione 16). "consultazione" corrisponde a ispettore/operatore consultante.
# Nessun privilegio amministrativo è assegnato per impostazione predefinita.
RUOLI = {"amministratore", "responsabile_dati", "analista", "consultazione", "auditor", "revisore"}
DESCRIZIONE_RUOLI = {
    "amministratore": "Amministratore tecnico: configurazione, import, ricalcolo, gestione settori (non valida parametri né approva settori).",
    "responsabile_dati": "Responsabile dei dati e delle fonti: import, acquisizione fonti, documenti, proposta di settori e parametri.",
    "analista": "Analista autorizzato: consultazione, report, pratiche, esportazioni, OSINT e grafo (inserimento).",
    "consultazione": "Ispettore o operatore consultante: consultazione di elenco, schede e pratiche.",
    "auditor": "Auditor: registro accessi, esecuzioni, configurazioni; nessun accesso alle schede aziendali.",
    "revisore": "Responsabile della revisione: valida parametri, approva o respinge settori, revisiona OSINT e grafo.",
}
_TUTTI = frozenset(RUOLI)
# Matrice ruoli/permessi da validare con l'ente destinatario.
PERMESSI: dict[str, frozenset[str]] = {
    "consulta_elenco": _TUTTI,
    "consulta_scheda": _TUTTI - {"auditor"},
    "genera_report": frozenset({"amministratore", "analista"}),
    "consulta_fonti": _TUTTI,
    "acquisisci_fonti": frozenset({"amministratore", "responsabile_dati"}),
    "consulta_mappature": frozenset({"amministratore", "responsabile_dati", "analista", "auditor", "revisore"}),
    "crea_mappature": frozenset({"amministratore", "responsabile_dati"}),
    "revisiona_mappature": frozenset({"amministratore", "revisore"}),
    "scarica_fonti": frozenset({"amministratore", "responsabile_dati", "analista", "auditor"}),
    "valutazione": _TUTTI - {"auditor"},
    "importa_dati": frozenset({"amministratore", "responsabile_dati"}),
    "ricalcola": frozenset({"amministratore"}),
    "ripristina_demo": frozenset({"amministratore"}),
    "audit": frozenset({"amministratore", "auditor"}),
    "consulta_settori": frozenset({"amministratore", "responsabile_dati", "revisore", "auditor"}),
    "configura_settori": frozenset({"amministratore", "responsabile_dati"}),
    "modifica_formule": frozenset({"amministratore"}),
    "valida_parametri": frozenset({"revisore"}),
    "consulta_documenti": frozenset({"amministratore", "responsabile_dati", "revisore", "auditor"}),
    "gestione_documenti": frozenset({"amministratore", "responsabile_dati"}),
    "osint_consulta": frozenset({"amministratore", "analista", "auditor", "revisore"}),
    "osint_acquisisci": frozenset({"amministratore", "responsabile_dati", "analista"}),
    "osint_revisiona": frozenset({"amministratore", "revisore"}),
    "grafo_consulta": frozenset({"amministratore", "analista", "auditor", "revisore"}),
    "grafo_aggiungi": frozenset({"amministratore", "analista"}),
    "grafo_revisiona": frozenset({"amministratore", "revisore"}),
    "grafo_riservato": frozenset({"amministratore", "analista", "revisore"}),
    "catalogo_fonti": frozenset({"amministratore", "responsabile_dati", "analista", "revisore", "auditor"}),
    "proponi_collegamenti": frozenset({"amministratore", "responsabile_dati"}),
    "decidi_collegamenti": frozenset({"revisore"}),
    "esporta_dati": frozenset({"amministratore", "analista"}),
    "pratiche_consulta": frozenset({"amministratore", "analista", "consultazione", "revisore", "auditor"}),
    "pratiche_gestisci": frozenset({"amministratore", "analista"}),
    "settori_collaudo": frozenset({"amministratore", "responsabile_dati", "revisore"}),
    "settori_transizione": frozenset({"amministratore", "responsabile_dati", "revisore"}),
    "settori_ripristino": frozenset({"amministratore"}),
    "esecuzioni": frozenset({"amministratore", "analista", "revisore", "auditor"}),
    "dipendenze": frozenset({"amministratore", "responsabile_dati", "revisore", "auditor"}),
    "esporta_audit": frozenset({"auditor", "amministratore"}),
}


def ruoli_per(permesso: str) -> set[str]:
    """Ruoli ammessi per un permesso; un permesso sconosciuto non è concesso a nessuno."""
    return set(PERMESSI.get(permesso, frozenset()))
_ITERAZIONI_MINIME = 600_000
_LOGIN_ATTEMPI = 5
_LOGIN_FINESTRA = 15 * 60
_LOGIN_BLOCCO = 15 * 60
_TENTATIVI: dict[str, deque[float]] = {}
_BLOCCHI: dict[str, float] = {}
_LOCK_TENTATIVI = threading.Lock()
_MAX_CHIAVI_RATE_LIMIT = 10_000


class ErroreConfigurazioneSicurezza(RuntimeError):
    pass


def crea_hash_password(password: str, iterazioni: int = _ITERAZIONI_MINIME) -> str:
    if not isinstance(password, str) or len(password) < 14 or len(password) > 1024:
        raise ValueError("La password deve contenere almeno 14 caratteri e non superare 1024 caratteri.")
    if iterazioni < _ITERAZIONI_MINIME or iterazioni > 2_000_000:
        raise ValueError("Numero di iterazioni non consentito.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterazioni, dklen=32)
    return "pbkdf2_sha256${}${}${}".format(
        iterazioni,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def verifica_hash_password(password: str, valore_hash: str) -> bool:
    try:
        algoritmo, raw_iterazioni, raw_salt, raw_digest = valore_hash.split("$", 3)
        iterazioni = int(raw_iterazioni)
        if algoritmo != "pbkdf2_sha256" or not (_ITERAZIONI_MINIME <= iterazioni <= 2_000_000):
            return False
        salt = base64.urlsafe_b64decode(raw_salt + "=" * (-len(raw_salt) % 4))
        atteso = base64.urlsafe_b64decode(raw_digest + "=" * (-len(raw_digest) % 4))
        if not 16 <= len(salt) <= 64 or len(atteso) != 32:
            return False
        calcolato = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterazioni, dklen=32)
        return hmac.compare_digest(calcolato, atteso)
    except (ValueError, TypeError, AttributeError):
        return False


def utenti_configurati() -> dict[str, dict[str, str]]:
    raw = os.environ.get("EMERSIONE_USERS_JSON", "").strip()
    if not raw:
        return {}
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ErroreConfigurazioneSicurezza("EMERSIONE_USERS_JSON non contiene JSON valido.") from exc
    if not isinstance(entries, list) or len(entries) > 500:
        raise ErroreConfigurazioneSicurezza("EMERSIONE_USERS_JSON deve essere una lista di massimo 500 utenti.")
    utenti: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ErroreConfigurazioneSicurezza("Configurazione utente non valida.")
        username = entry.get("username")
        password_hash = entry.get("password_hash")
        ruolo = entry.get("ruolo")
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9._@-]{3,100}", username):
            raise ErroreConfigurazioneSicurezza("Nome utente non valido.")
        if username in utenti:
            raise ErroreConfigurazioneSicurezza("Nomi utente duplicati nella configurazione.")
        if not _hash_strutturalmente_valido(password_hash):
            raise ErroreConfigurazioneSicurezza(f"Hash password non valido per l'utente {username}.")
        if not isinstance(ruolo, str) or ruolo not in RUOLI:
            raise ErroreConfigurazioneSicurezza(f"Ruolo non valido per l'utente {username}.")
        utenti[username] = {"username": username, "password_hash": password_hash, "ruolo": ruolo}
    return utenti


def _hash_strutturalmente_valido(valore: Any) -> bool:
    if not isinstance(valore, str):
        return False
    try:
        algoritmo, raw_iterazioni, raw_salt, raw_digest = valore.split("$", 3)
        iterazioni = int(raw_iterazioni)
        salt = base64.urlsafe_b64decode(raw_salt + "=" * (-len(raw_salt) % 4))
        digest = base64.urlsafe_b64decode(raw_digest + "=" * (-len(raw_digest) % 4))
        return algoritmo == "pbkdf2_sha256" and _ITERAZIONI_MINIME <= iterazioni <= 2_000_000 and len(salt) >= 16 and len(digest) == 32
    except (ValueError, TypeError):
        return False


def verifica_credenziali(username: str, password: str) -> dict[str, str] | None:
    utenti = utenti_configurati()
    utente = utenti.get(username)
    if utente is None:
        # Riduce differenze temporali macroscopiche per username inesistenti.
        hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), b"emersione-dummy-salt", _ITERAZIONI_MINIME, dklen=32)
        return None
    if not verifica_hash_password(password, utente["password_hash"]):
        return None
    return {"username": utente["username"], "ruolo": utente["ruolo"]}


def _pulisci_rate_limit(adesso: float) -> None:
    """Mantiene il contatore locale limitato anche con chiavi/IP in rotazione."""
    for chiave, scadenza in list(_BLOCCHI.items()):
        if scadenza <= adesso:
            _BLOCCHI.pop(chiave, None)
    for chiave, coda in list(_TENTATIVI.items()):
        while coda and adesso - coda[0] > _LOGIN_FINESTRA:
            coda.popleft()
        if not coda and chiave not in _BLOCCHI:
            _TENTATIVI.pop(chiave, None)
    while len(_TENTATIVI) > _MAX_CHIAVI_RATE_LIMIT:
        chiave = next(iter(_TENTATIVI))
        _TENTATIVI.pop(chiave, None)
    while len(_BLOCCHI) > _MAX_CHIAVI_RATE_LIMIT:
        chiave = min(_BLOCCHI, key=_BLOCCHI.get)
        _BLOCCHI.pop(chiave, None)
    # La rimozione locale dei contatori non sostituisce un rate limiter condiviso.


def tentativi_bloccati(chiave: str) -> bool:
    adesso = time.monotonic()
    with _LOCK_TENTATIVI:
        _pulisci_rate_limit(adesso)
        if _BLOCCHI.get(chiave, 0.0) > adesso:
            return True
        coda = _TENTATIVI.get(chiave)
        if coda is not None:
            while coda and adesso - coda[0] > _LOGIN_FINESTRA:
                coda.popleft()
            if not coda:
                _TENTATIVI.pop(chiave, None)
        return False


def registra_login_fallito(chiave: str) -> None:
    adesso = time.monotonic()
    with _LOCK_TENTATIVI:
        _pulisci_rate_limit(adesso)
        coda = _TENTATIVI.setdefault(chiave, deque())
        while coda and adesso - coda[0] > _LOGIN_FINESTRA:
            coda.popleft()
        coda.append(adesso)
        if len(coda) >= _LOGIN_ATTEMPI:
            _BLOCCHI[chiave] = adesso + _LOGIN_BLOCCO
            coda.clear()
        _pulisci_rate_limit(adesso)


def registra_login_riuscito(chiave: str) -> None:
    with _LOCK_TENTATIVI:
        _TENTATIVI.pop(chiave, None)
        _BLOCCHI.pop(chiave, None)
        _pulisci_rate_limit(time.monotonic())


def valida_token_csrf(session: dict[str, Any], token: Any) -> bool:
    atteso = session.get("csrf_token")
    return isinstance(atteso, str) and isinstance(token, str) and hmac.compare_digest(atteso, token)


def token_csrf(session: dict[str, Any]) -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str) or len(token) < 32:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def verifica_configurazione_produzione() -> None:
    ambiente = os.environ.get("EMERSIONE_ENV", "development").strip().casefold()
    if ambiente not in {"development", "test", "production"}:
        raise ErroreConfigurazioneSicurezza("EMERSIONE_ENV deve essere development, test o production.")
    if ambiente == "production":
        secret = os.environ.get("EMERSIONE_SESSION_SECRET", "")
        if len(secret.encode("utf-8")) < 32:
            raise ErroreConfigurazioneSicurezza("In produzione EMERSIONE_SESSION_SECRET deve contenere almeno 32 byte.")
        if not utenti_configurati():
            raise ErroreConfigurazioneSicurezza("In produzione è obbligatorio configurare EMERSIONE_USERS_JSON o integrare un provider di identità.")


def ambiente_produzione() -> bool:
    return os.environ.get("EMERSIONE_ENV", "development").strip().casefold() == "production"
