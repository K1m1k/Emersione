"""Registro eventi JSON Lines con catena hash locale per rilevare modifiche.

La catena hash rileva molte alterazioni/interruzioni interne, ma non garantisce
immutabilità e non rileva con certezza la rimozione della coda senza un ancoraggio
esterno. Per produzione istituzionale è richiesto un audit centralizzato con
controlli di accesso, retention e verifica indipendente.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import contextvars
import threading
from pathlib import Path
from typing import Any
from collections import deque

PERCORSO_LOG = Path(os.environ.get(
    "EMERSIONE_AUDIT_PATH",
    str(Path(__file__).resolve().parents[1] / "dati" / "audit.jsonl"),
))
_LOCK = threading.Lock()
# Identificativo di correlazione della richiesta corrente, impostato dal middleware web.
CORRELAZIONE: contextvars.ContextVar[str] = contextvars.ContextVar("emersione_correlazione", default="")
_MAX_DETTAGLIO = 500
_MAX_META = 200

# Include solo metadati operativi sicuri e brevi: mai password, token, cookie,
# contenuto integrale dei documenti o record aziendali.
_METADATI_AMMESSI = {
    "esito", "ruolo", "risorsa", "request_id", "sha256", "byte", "host",
    "motivo", "stato", "tipo", "numero_record", "formato", "codice_http",
}


def _canonico(evento: dict[str, Any]) -> bytes:
    return json.dumps(evento, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _ultimo_hash() -> str:
    """Trova l'ultimo hash registrato senza leggere l'intero file in memoria."""
    if not PERCORSO_LOG.exists():
        return ""
    try:
        with PERCORSO_LOG.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            posizione = stream.tell()
            if posizione == 0:
                return ""
            # Una riga evento è limitata dalla allowlist e dal dettaglio massimo.
            # Scansiona al massimo 64 KiB per trovare la coda utile.
            dimensione = min(posizione, 64 * 1024)
            stream.seek(posizione - dimensione)
            righe = stream.read(dimensione).splitlines()
        for riga in reversed(righe):
            if not riga.strip():
                continue
            try:
                evento = json.loads(riga.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return ""
            hash_evento = evento.get("hash_evento") if isinstance(evento, dict) else None
            if isinstance(hash_evento, str) and len(hash_evento) == 64:
                return hash_evento
            # Riga legacy JSON/TSV: non ha hash, ma può precedere la nuova catena.
            return ""
    except OSError:
        return ""
    return ""


def registra(utente: str, azione: str, dettaglio: str = "", **metadati: Any) -> None:
    """Registra evento firmato da hash-chain; identità sempre passata dal server."""
    nome_utente = str(utente or "sconosciuto")[:100]
    nome_azione = str(azione or "azione_non_specificata")[:100]
    testo = str(dettaglio or "")[:_MAX_DETTAGLIO]
    evento: dict[str, Any] = {
        "quando": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
        "utente": nome_utente,
        "azione": nome_azione,
        "dettaglio": testo,
    }
    if "request_id" not in metadati and CORRELAZIONE.get():
        metadati["request_id"] = CORRELAZIONE.get()
    for chiave in _METADATI_AMMESSI:
        valore = metadati.get(chiave)
        if isinstance(valore, (str, int, float, bool)) and len(str(valore)) <= _MAX_META:
            evento[chiave] = valore
    PERCORSO_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd = os.open(PERCORSO_LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o640)
        try:
            try:
                os.fchmod(fd, 0o640)
            except OSError:
                pass
            # Il lock interprocesso è disponibile su Unix. Il lock thread protegge
            # anche l'esecuzione in ambienti in cui fcntl non è presente.
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            except ImportError:
                fcntl = None
            evento["hash_precedente"] = _ultimo_hash()
            evento["hash_evento"] = hashlib.sha256(_canonico(evento)).hexdigest()
            riga = (_canonico(evento) + b"\n")
            os.write(fd, riga)
            os.fsync(fd)
        finally:
            try:
                if 'fcntl' in locals() and fcntl is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except (OSError, UnboundLocalError):
                pass
            os.close(fd)


def verifica_integrita(percorso: Path | None = None) -> dict[str, Any]:
    """Verifica gli hash memorizzati. Non è una prova di immutabilità assoluta."""
    PERCORSO = percorso or PERCORSO_LOG
    if not PERCORSO.exists():
        return {"valida": True, "eventi_verificati": 0, "eventi_legacy": 0, "errori": [], "nota": "Registro non ancora creato."}
    errori: list[dict[str, Any]] = []
    verificati = 0
    legacy = 0
    hash_precedente = ""
    ultimo_linea_hashata = None
    try:
        with PERCORSO.open("r", encoding="utf-8") as stream:
            for numero, riga in enumerate(stream, start=1):
                if not riga.strip():
                    continue
                try:
                    evento = json.loads(riga)
                except json.JSONDecodeError:
                    legacy += 1
                    # Le righe legacy/illeggibili non si considerano verificate.
                    continue
                if not isinstance(evento, dict) or "hash_evento" not in evento:
                    legacy += 1
                    continue
                hash_evento = evento.get("hash_evento")
                prev = evento.get("hash_precedente", "")
                senza_hash = dict(evento)
                senza_hash.pop("hash_evento", None)
                calcolato = hashlib.sha256(_canonico(senza_hash)).hexdigest()
                if prev != hash_precedente:
                    errori.append({"riga": numero, "motivo": "collegamento al precedente non valido"})
                if not isinstance(hash_evento, str) or hash_evento != calcolato:
                    errori.append({"riga": numero, "motivo": "hash evento non valido"})
                hash_precedente = hash_evento if isinstance(hash_evento, str) else ""
                verificati += 1
                ultimo_linea_hashata = numero
    except OSError:
        return {"valida": False, "eventi_verificati": verificati, "eventi_legacy": legacy,
                "errori": [{"riga": 0, "motivo": "registro non leggibile"}], "nota": "Verifica non completata."}
    return {
        "valida": not errori,
        "eventi_verificati": verificati,
        "eventi_legacy": legacy,
        "errori": errori[:100],
        "ultima_riga_hashata": ultimo_linea_hashata,
        "ultimo_hash": hash_precedente,
        "nota": "La verifica rileva modifiche ai record collegati; non garantisce la rilevazione della rimozione della coda senza un hash ancorato esternamente.",
    }


def leggi(ultime: int = 200) -> list[dict[str, Any]]:
    if isinstance(ultime, bool) or not isinstance(ultime, int):
        raise ValueError("Il numero di eventi deve essere un intero.")
    ultime = min(ultime, 10_000)
    if ultime < 1 or not PERCORSO_LOG.exists():
        return []
    try:
        with PERCORSO_LOG.open("r", encoding="utf-8") as stream:
            righe = list(deque(stream, maxlen=ultime))
    except OSError:
        return []
    voci: list[dict[str, Any]] = []
    for riga in reversed(righe):
        try:
            dato = json.loads(riga)
            if isinstance(dato, dict) and all(k in dato for k in ("quando", "utente", "azione")):
                voci.append(dato)
                continue
        except (json.JSONDecodeError, TypeError):
            pass
        parti = riga.rstrip("\n").split("\t", 3)
        if len(parti) >= 3:
            voci.append({"quando": parti[0], "utente": parti[1], "azione": parti[2],
                         "dettaglio": parti[3] if len(parti) > 3 else ""})
    return voci


# ---------------------------------------------------------------------------
# Ancoraggio esterno e rotazione (sezione 17)
# ---------------------------------------------------------------------------

def ancoraggio() -> dict[str, Any]:
    """Punto di controllo da conservare FUORI dal sistema (es. protocollo, e-mail all'auditor,
    archivio separato). Permette di rilevare la rimozione della coda del registro."""
    esito = verifica_integrita()
    return {
        "creato_il": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "registro": str(PERCORSO_LOG.name),
        "eventi_verificati": esito["eventi_verificati"],
        "ultimo_hash": esito.get("ultimo_hash", ""),
        "catena_valida": esito["valida"],
    }


def verifica_ancoraggio(punto: dict[str, Any]) -> dict[str, Any]:
    """Controlla che l'evento ancorato sia ancora presente nella posizione attesa."""
    atteso, n = str(punto.get("ultimo_hash", "")), int(punto.get("eventi_verificati", 0))
    if not atteso or n <= 0:
        return {"esito": "non_verificabile", "motivo": "Punto di ancoraggio vuoto."}
    contatore = 0
    try:
        with PERCORSO_LOG.open("r", encoding="utf-8") as stream:
            for riga in stream:
                try:
                    evento = json.loads(riga)
                except json.JSONDecodeError:
                    continue
                if isinstance(evento, dict) and "hash_evento" in evento:
                    contatore += 1
                    if contatore == n:
                        ok = evento.get("hash_evento") == atteso
                        return {"esito": "conforme" if ok else "difforme",
                                "motivo": "Evento ancorato presente." if ok else "L'evento in posizione ancorata è diverso."}
    except OSError:
        return {"esito": "non_verificabile", "motivo": "Registro non leggibile."}
    return {"esito": "difforme", "motivo": f"Il registro contiene {contatore} eventi verificabili, meno dei {n} ancorati: possibile rimozione della coda."}


def ruota(cartella_archivio: Path) -> dict[str, Any]:
    """Archivia il segmento corrente e apre un nuovo segmento collegato al precedente.

    Il primo evento del nuovo segmento riporta (campo sha256) l'ultimo hash del
    segmento archiviato, così la catena resta ricostruibile tra i segmenti.
    """
    import shutil
    esito = verifica_integrita()
    if not PERCORSO_LOG.exists():
        raise FileNotFoundError("Registro inesistente.")
    cartella_archivio.mkdir(parents=True, exist_ok=True)
    nome = f"audit-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    destinazione = cartella_archivio / nome
    with _LOCK:
        shutil.copy2(PERCORSO_LOG, destinazione)
        impronta = hashlib.sha256(destinazione.read_bytes()).hexdigest()
        os.replace(PERCORSO_LOG, PERCORSO_LOG.with_suffix(".ruotato.tmp"))
        os.unlink(PERCORSO_LOG.with_suffix(".ruotato.tmp"))
    registra("sistema", "apertura_segmento_audit", f"segmento precedente {nome}", sha256=esito.get("ultimo_hash", ""),
             stato="catena precedente valida" if esito["valida"] else "catena precedente NON valida")
    return {"archivio": str(destinazione), "sha256_archivio": impronta, "eventi_archiviati": esito["eventi_verificati"],
            "ultimo_hash_segmento": esito.get("ultimo_hash", "")}
