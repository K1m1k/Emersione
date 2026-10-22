"""Connettori di acquisizione per fonti aperte ufficiali.

I payload acquisiti sono conservati come artefatti grezzi con metadati e hash.
Non vengono inseriti automaticamente nel dataset analitico: il mapping e la
valutazione di pertinenza richiedono un passaggio esplicito e tracciato.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 15
USER_AGENT = "Emersione/0.3 (acquisizione documentata di open data; contatto da configurare)"

INAIL_ENDPOINTS = {
    "infortuni_mensili": "https://dati.inail.it/api/OpenData/DatiConCadenzaMensileInfortuni",
    "infortuni_semestrali": "https://dati.inail.it/api/OpenData/DatiConCadenzaSemestraleInfortuni",
    "malattie_professionali_mensili_protocollo": "https://dati.inail.it/api/OpenData/DatiMensiliMalattieProfessionaliDataProt",
    "malattie_professionali_semestrali_protocollo": "https://dati.inail.it/api/OpenData/DatiSemestraliMalattieProfessionaliDataProt",
    "malattie_professionali_semestrali_definizione": "https://dati.inail.it/api/OpenData/DatiSemestraliMalattieProfessionaliDataDec",
}

ISTAT_ALLOWED_HOSTS = {"esploradati.istat.it", "sdmx.istat.it"}
ANAC_ALLOWED_HOSTS = {"dati.anticorruzione.it"}
ISTAT_ALLOWED_PREFIXES = ("/HVD/", "/hvd/", "/SDMXWS/", "/sdmxws/")
ANAC_ALLOWED_PREFIXES = ("/opendata/",)


class ErroreAcquisizione(ValueError):
    """Acquisizione negata o non riuscita in modo controllato."""


@dataclass(frozen=True)
class PayloadFonte:
    chiave: str
    url: str
    acquisito_il: str
    status_http: int
    content_type: str
    dimensione_byte: int
    sha256: str
    contenuto: bytes
    metadati: dict[str, Any]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # I redirect vengono rifiutati per evitare che una fonte ufficiale conduca
        # l'acquisizione verso un host o protocollo non approvato.
        return None


def _valida_url(url: str, host_ammessi: set[str], prefissi: tuple[str, ...]) -> urllib.parse.ParseResult:
    if not isinstance(url, str) or len(url) > 2000:
        raise ErroreAcquisizione("URL assente o troppo lungo.")
    try:
        parsed = urllib.parse.urlparse(url.strip())
        port = parsed.port
    except ValueError as exc:
        raise ErroreAcquisizione("URL non valido.") from exc
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (parsed.scheme != "https" or host not in host_ammessi or parsed.username or parsed.password
            or port not in (None, 443) or parsed.fragment or not parsed.path.startswith(prefissi)):
        raise ErroreAcquisizione("URL non consentito: usare HTTPS e un endpoint ufficiale ammesso dal connettore.")
    return parsed


def _parametri_validi(parametri: dict[str, Any] | None) -> dict[str, str]:
    if parametri is None:
        return {}
    if not isinstance(parametri, dict) or len(parametri) > 30:
        raise ErroreAcquisizione("Parametri di query non validi.")
    risultato: dict[str, str] = {}
    for chiave, valore in parametri.items():
        if not isinstance(chiave, str) or not chiave.strip() or len(chiave) > 100:
            raise ErroreAcquisizione("Nome parametro di query non valido.")
        if isinstance(valore, (dict, list, tuple)) or valore is None:
            raise ErroreAcquisizione(f"Valore query non valido per '{chiave}'.")
        testo = str(valore)
        if len(testo) > 300 or any(ord(c) < 32 for c in testo):
            raise ErroreAcquisizione(f"Valore query troppo lungo o non valido per '{chiave}'.")
        risultato[chiave.strip()] = testo
    return risultato


# Limiti di frequenza lato client per host. ISTAT dichiara un massimo di 5
# richieste al minuto per indirizzo IP, con blocco di 1-2 giorni se superato
# (pagina ufficiale "SDMX web services", verificata il 2026-10-22): si resta
# sotto la soglia con margine. Il limite è per processo: con più processi va
# usato un limitatore condiviso.
LIMITI_FREQUENZA: dict[str, tuple[int, float]] = {
    "esploradati.istat.it": (4, 60.0),
    "sdmx.istat.it": (4, 60.0),
    "dati.anticorruzione.it": (30, 60.0),
    "dati.inail.it": (30, 60.0),
}
_STORICO_RICHIESTE: dict[str, list[float]] = {}
_LOCK_FREQUENZA = __import__("threading").Lock()


def _controlla_frequenza(host: str) -> None:
    import time
    limite = LIMITI_FREQUENZA.get(host)
    if not limite:
        return
    massimo, finestra = limite
    adesso = time.monotonic()
    with _LOCK_FREQUENZA:
        recenti = [t for t in _STORICO_RICHIESTE.get(host, []) if adesso - t < finestra]
        if len(recenti) >= massimo:
            attesa = int(finestra - (adesso - recenti[0])) + 1
            _STORICO_RICHIESTE[host] = recenti
            raise ErroreAcquisizione(
                f"Limite di frequenza per {host} raggiunto ({massimo} richieste ogni {int(finestra)} s): riprovare tra {attesa} s. "
                "Il limite protegge dal blocco imposto dalla fonte.")
        recenti.append(adesso)
        _STORICO_RICHIESTE[host] = recenti


def _fetch(chiave: str, url: str, host_ammessi: set[str], prefissi: tuple[str, ...],
           parametri: dict[str, Any] | None = None) -> PayloadFonte:
    parsed = _valida_url(url, host_ammessi, prefissi)
    _controlla_frequenza((parsed.hostname or "").casefold().rstrip("."))
    query = _parametri_validi(parametri)
    url_finale = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=False) if query else parsed.query))
    # Risoluzione DNS usata come ulteriore barriera: l'host resta anche vincolato
    # a una allowlist di host ufficiali e non viene accettato input URL arbitrario.
    try:
        indirizzi = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ErroreAcquisizione("Impossibile risolvere l'host della fonte.") from exc
    if not indirizzi:
        raise ErroreAcquisizione("La fonte non risolve verso un indirizzo valido.")
    for record in indirizzi:
        try:
            ip = ipaddress.ip_address(record[4][0])
        except (ValueError, IndexError) as exc:
            raise ErroreAcquisizione("La fonte ha risolto verso un indirizzo non valido.") from exc
        if not ip.is_global:
            raise ErroreAcquisizione("La fonte risolve verso un indirizzo IP non pubblico.")
    richiesta = urllib.request.Request(url_finale, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/csv, text/plain, application/xml, application/octet-stream, */*;q=0.2",
        "Accept-Encoding": "identity",
    }, method="GET")
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(richiesta, timeout=TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 200))
            if status < 200 or status >= 300:
                raise ErroreAcquisizione(f"La fonte ha restituito HTTP {status}.")
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_BYTES:
                        raise ErroreAcquisizione(f"La risposta supera il limite di {MAX_BYTES // (1024 * 1024)} MiB.")
                except ValueError as exc:
                    raise ErroreAcquisizione("Content-Length non valido restituito dalla fonte.") from exc
            contenuto = response.read(MAX_BYTES + 1)
            content_type = (response.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].strip().casefold()
    except urllib.error.HTTPError as exc:
        if exc.code in {301, 302, 303, 307, 308}:
            raise ErroreAcquisizione("La fonte ha richiesto un redirect; è stato rifiutato per sicurezza. Usa l'URL finale ufficiale.") from exc
        raise ErroreAcquisizione(f"La fonte ha restituito HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise ErroreAcquisizione("Connessione alla fonte non riuscita.") from exc
    except TimeoutError as exc:
        raise ErroreAcquisizione("Timeout durante l'acquisizione della fonte.") from exc
    if len(contenuto) > MAX_BYTES:
        raise ErroreAcquisizione(f"La risposta supera il limite di {MAX_BYTES // (1024 * 1024)} MiB.")
    if not contenuto:
        raise ErroreAcquisizione("La fonte ha restituito una risposta vuota.")
    # Rifiuta pagine di errore HTML per evitare di archiviarle come dataset.
    if content_type in {"text/html", "application/xhtml+xml"}:
        raise ErroreAcquisizione("La fonte ha restituito HTML invece di un dataset. Verifica l'endpoint.")
    return PayloadFonte(
        chiave=chiave, url=url_finale, acquisito_il=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        status_http=status, content_type=content_type, dimensione_byte=len(contenuto),
        sha256=hashlib.sha256(contenuto).hexdigest(), contenuto=contenuto,
        metadati={"timeout_secondi": TIMEOUT_SECONDS, "limite_byte": MAX_BYTES},
    )


def acquisisci_inail(dataset: str, parametri: dict[str, Any] | None = None) -> PayloadFonte:
    """Acquisisce una delle Open API INAIL pubblicate ufficialmente."""
    url = INAIL_ENDPOINTS.get(dataset)
    if not url:
        raise ErroreAcquisizione("Dataset INAIL non riconosciuto.")
    return _fetch(f"inail:{dataset}", url, {"dati.inail.it"}, ("/api/OpenData/",), parametri)


def acquisisci_istat(url: str, parametri: dict[str, Any] | None = None) -> PayloadFonte:
    """Acquisisce da un endpoint SDMX ISTAT esplicitamente selezionato.

    Il dataflow e la chiave SDMX devono provenire dalla documentazione ufficiale
    del dataset scelto; il connettore non presume un dataflow universale.
    """
    return _fetch("istat:sdmx", url, ISTAT_ALLOWED_HOSTS, ISTAT_ALLOWED_PREFIXES, parametri)


def acquisisci_anac(url: str) -> PayloadFonte:
    """Scarica un URL di dataset/risorsa dal portale Open Data ANAC.

    Il portale pubblica risorse distinte per dataset: si richiede l'URL diretto
    della risorsa individuata nel catalogo ufficiale, non si inventa un endpoint.
    """
    return _fetch("anac:opendata", url, ANAC_ALLOWED_HOSTS, ANAC_ALLOWED_PREFIXES)


def prova_parsabilita(payload: PayloadFonte) -> dict[str, Any]:
    """Controlli sintattici limitati: nessun mapping semantico o uso nel punteggio."""
    import csv
    import io
    import re

    ct = payload.content_type.casefold()
    raw = payload.contenuto
    stripped = raw.lstrip()
    formato = "binario"
    note = "Payload conservato grezzo; mapping analitico non eseguito."
    if "json" in ct or stripped.startswith((b"{", b"[")):
        try:
            dato = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ErroreAcquisizione("La fonte dichiara o sembra JSON ma la risposta non è JSON valido.") from exc
        formato = "json"
        note = f"JSON valido; radice {type(dato).__name__}. Non collegato automaticamente al punteggio."
    elif "xml" in ct or stripped.startswith(b"<"):
        # Controllo DTD/entity anche per XML UTF-16 con byte NUL intercalati.
        try:
            if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or raw[:100].count(b"\x00") > 5:
                xml_testo = raw.decode("utf-16")
            else:
                xml_testo = raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ErroreAcquisizione("Codifica XML non supportata o non valida.") from exc
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", xml_testo, flags=re.IGNORECASE):
            raise ErroreAcquisizione("XML con DTD/entity non ammessi.")
        try:
            import xml.etree.ElementTree as ET
            ET.fromstring(raw)
        except Exception as exc:
            raise ErroreAcquisizione("La risposta XML non è ben formata.") from exc
        formato = "xml"
        note = "XML ben formato; struttura SDMX e semantica non ancora mappate al modello Emersione."
    elif "csv" in ct or "text/plain" in ct or stripped.count(b",") >= 2 or stripped.count(b";") >= 2:
        try:
            testo = raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ErroreAcquisizione("La risposta CSV/testuale non è UTF-8 valida.") from exc
        try:
            try:
                dialect = csv.Sniffer().sniff(testo[:8192], delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            lettore = csv.reader(io.StringIO(testo, newline=""), dialect=dialect, strict=True)
            numero_righe = 0
            numero_colonne = 0
            for riga_num, riga in enumerate(lettore, start=1):
                if len(riga) > 500:
                    raise ErroreAcquisizione("CSV con oltre 500 colonne: verificare il dataset prima dell'archiviazione.")
                if any(len(cella) > 1_000_000 for cella in riga):
                    raise ErroreAcquisizione("CSV con una cella eccessivamente lunga.")
                if riga and any(cella.strip() for cella in riga):
                    numero_righe += 1
                    numero_colonne = max(numero_colonne, len(riga))
                if riga_num > 500_000:
                    raise ErroreAcquisizione("CSV con oltre 500.000 righe: usare una procedura di acquisizione a lotti.")
        except csv.Error as exc:
            raise ErroreAcquisizione("CSV non sintatticamente valido.") from exc
        if numero_righe == 0 or numero_colonne == 0:
            raise ErroreAcquisizione("CSV privo di righe contenenti dati.")
        formato = "csv"
        note = f"CSV leggibile: {numero_righe} righe non vuote e fino a {numero_colonne} colonne. Schema, licenza e semantica restano da validare."
    return {"formato": formato, "nota": note}
