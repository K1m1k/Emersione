"""Acquisizione protetta di documenti di riferimento e collegamenti dichiarati.

Il contenuto può essere sottoposto a estrazione testuale assistita; i candidati
sono solo indizi da verificare e non aggiornano automaticamente coefficienti.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app import settori

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
ESTENSIONI_AMMESSE = {".pdf", ".txt", ".csv", ".json"}
_STORAGE = Path(os.environ.get("EMERSIONE_DOCUMENTI_DIR", str(Path(__file__).resolve().parents[1] / "dati" / "documenti")))
_ID_RE = re.compile(r"^[a-f0-9]{32}$")


class ErroreDocumento(ValueError):
    pass


def _url_valido(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.username or parsed.password or len(url) > 1000:
        raise ErroreDocumento("URL di riferimento non valido.")
    return url


def _valida_contenuto(nome_file: str, contenuto: bytes) -> tuple[str, str]:
    if not isinstance(contenuto, bytes) or not contenuto:
        raise ErroreDocumento("Il documento è vuoto o non è un file valido.")
    if len(contenuto) > MAX_DOCUMENT_BYTES:
        raise ErroreDocumento(f"Il documento supera il limite di {MAX_DOCUMENT_BYTES // (1024 * 1024)} MiB.")
    estensione = Path(nome_file.replace("\\", "/").split("/")[-1]).suffix.casefold()
    if estensione not in ESTENSIONI_AMMESSE:
        raise ErroreDocumento("Formati ammessi: PDF, TXT, CSV e JSON. File Office e archivi compressi non sono ammessi in questa versione.")
    if estensione == ".pdf":
        if not contenuto.startswith(b"%PDF-"):
            raise ErroreDocumento("Il contenuto non presenta l'intestazione di un PDF valido.")
        mime = "application/pdf"
    else:
        try:
            testo = contenuto.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ErroreDocumento("I documenti testuali devono essere codificati in UTF-8.") from exc
        if "\x00" in testo:
            raise ErroreDocumento("Il documento testuale contiene caratteri binari non ammessi.")
        if estensione == ".json":
            try:
                json.loads(testo)
            except json.JSONDecodeError as exc:
                raise ErroreDocumento("Il file JSON non è sintatticamente valido.") from exc
        mime = {".txt": "text/plain", ".csv": "text/csv", ".json": "application/json"}[estensione]
    return estensione, mime


def aggiungi_documento(*, nome_file: str, contenuto: bytes, titolo: str, descrizione: str,
                       settore_id: str = "", parametro_id: str = "", url_fonte: str = "",
                       utente: str = "sconosciuto") -> dict:
    titolo = (titolo or "").strip()
    descrizione = (descrizione or "").strip()
    if not titolo or len(titolo) > 180:
        raise ErroreDocumento("Il titolo è obbligatorio e deve contenere al massimo 180 caratteri.")
    if len(descrizione) > 1000:
        raise ErroreDocumento("La descrizione supera 1000 caratteri.")
    estensione, mime = _valida_contenuto(nome_file, contenuto)
    url_fonte = _url_valido(url_fonte)
    # I documenti servono anche a settori in bozza o revisione: escluso solo l'archiviato.
    settore = settori.configurazione_settore(settore_id) if settore_id else None
    if settore is not None and settore.get("stato") == "archiviato":
        settore = None
    if settore_id and settore is None:
        raise ErroreDocumento("Il settore selezionato non è disponibile.")
    parametri = settori.catalogo_parametri()
    parametro = parametri.get(parametro_id) if parametro_id else None
    if parametro_id and parametro is None:
        raise ErroreDocumento("Il parametro selezionato non esiste.")
    if parametro and settore_id and parametro.get("ambito") not in {settore_id, "trasversale"}:
        raise ErroreDocumento("Il parametro non appartiene al settore selezionato.")

    identificativo = secrets.token_hex(16)
    file_key = identificativo + estensione
    _STORAGE.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(_STORAGE, 0o700)
    except OSError:
        pass
    percorso = _STORAGE / file_key
    digest = hashlib.sha256(contenuto).hexdigest()
    # La chiave generata dal server è l'unico nome usato sul filesystem.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(percorso, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contenuto)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            percorso.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    # L'estrazione è preliminare e non approva valori: salva solo candidati con
    # riferimenti testuali/pagina per facilitare la verifica umana.
    try:
        from app.estrazione_documenti import estrai
        dati_estratti = estrai(nome_file, contenuto)
    except Exception:
        dati_estratti = {"stato": "errore_estrazione", "candidati": [],
                         "nota": "Estrazione non completata; verificare il documento originale."}
    documento = {
        "id": identificativo,
        "titolo": titolo,
        "descrizione": descrizione,
        "nome_file_originale": Path(nome_file.replace("\\", "/").split("/")[-1]).name[:180],
        "file_key": file_key,
        "mime": mime,
        "dimensione_byte": len(contenuto),
        "sha256": digest,
        "url_fonte": url_fonte,
        "settore": settore_id or "",
        "parametro": parametro_id or "",
        "creato_da": (utente or "sconosciuto")[:100],
        "acquisito_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stato": "da_verificare",
        "estrazione": dati_estratti.get("stato", "errore_estrazione"),
        "estrazione_dati": dati_estratti,
        "nota": "File conservato con hash SHA-256. L'estrazione propone soltanto candidati; significato, fonte, periodo e applicabilità richiedono verifica umana.",
    }
    try:
        settori.registra_documento(documento)
    except Exception:
        try:
            percorso.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return documento


def percorso_documento(documento: dict) -> Path | None:
    doc_id = documento.get("id", "")
    file_key = documento.get("file_key", "")
    if not isinstance(doc_id, str) or not _ID_RE.fullmatch(doc_id):
        return None
    if not isinstance(file_key, str) or not re.fullmatch(rf"{doc_id}\.(pdf|txt|csv|json)", file_key):
        return None
    percorso = _STORAGE / file_key
    try:
        return percorso if percorso.is_file() and percorso.parent.resolve() == _STORAGE.resolve() else None
    except OSError:
        return None
