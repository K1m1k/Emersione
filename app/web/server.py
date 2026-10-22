"""Applicazione web Emersione.

La modalità predefinita non preconfigura credenziali: le pagine restano protette
finché gli account non sono configurati. In produzione è obbligatoria una chiave
sessione robusta e un elenco di account o, preferibilmente, un IdP istituzionale.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from urllib.parse import quote

from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from app.dati_sintetici import genera_aziende
from app.motore.analisi import VERSIONE_MOTORE, analizza
from app.motore import valutazione as valutazione_motore
from app.report import ErroreReport, genera_relazione_azienda
from app.connettori import registro, csv_import, fonti_live
from app import audit, sicurezza, settori, sessioni, documenti, dataset_store, fonti_store, fonti_mapping, osint, grafo
from app import ciclo_settori, collaudo_settori, collegamento_semantico, db_operativo, dipendenze, osint_esteso, pratiche, provenienza, versioni_registro
from app.connettori import scoperta

BASE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(BASE, "..", "..", ".."))
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))
MAX_UPLOAD_BYTES = csv_import.MAX_BYTES

# Stato transitorio della demo. Prima dell'uso istituzionale, lo stato operativo
# deve essere spostato su archivio persistente e transazionale.
STATO = {
    "aziende": [],
    "origine": "dati sintetici (500 aziende, seme 42)",
    "dataset_sintetico": True,
    "lotto_id": None,
    "hash_origine": None,
    "hash_dataset": None,
    "hash_configurazione": None,
    "configurazione_corrente": True,
    "esecuzione_id": None,
    "provenienza": None,
}

ORIGINE_SINTETICA = "dati sintetici (500 aziende, seme 42)"


def _etichette_sintetiche() -> dict:
    """Etichette di riferimento del dataset dimostrativo, tenute separate dai dati analizzati."""
    return valutazione_motore.estrai_etichette(genera_aziende(500, seme=42), "_irregolare")


def _carica_sintetici(*, persisti: bool = False) -> None:
    grezzi = genera_aziende(500, seme=42)
    # Le etichette escono dai record prima dell'analisi: il motore non le riceve mai.
    valutazione_motore.estrai_etichette(grezzi, "_irregolare")
    az = analizza(grezzi)
    origine = ORIGINE_SINTETICA
    metadati = dataset_store.salva_attivo(az, origine=origine, sintetico=True) if persisti else None
    hash_config = metadati["hash_configurazione"] if metadati else dataset_store.hash_configurazione()
    STATO.update({
        "aziende": az,
        "origine": origine,
        "dataset_sintetico": True,
        "lotto_id": metadati["lotto_id"] if metadati else None,
        "hash_origine": metadati["hash_origine"] if metadati else None,
        "hash_dataset": metadati["hash_dataset"] if metadati else None,
        "hash_configurazione": hash_config,
        "configurazione_corrente": True,
        "esecuzione_id": None,
        "provenienza": None,
    })


def _registra_esecuzione(utente: str, motivo: str) -> int:
    """Registra l'esecuzione corrente e i risultati per azienda nell'archivio operativo."""
    esecuzione_id = db_operativo.registra_esecuzione(
        STATO["aziende"], utente=utente, motivo=motivo, versione_motore=VERSIONE_MOTORE,
        hash_configurazione=STATO.get("hash_configurazione") or dataset_store.hash_configurazione(),
        hash_dataset=STATO.get("hash_dataset"), origine=STATO["origine"], sintetico=bool(STATO["dataset_sintetico"]),
    )
    STATO["esecuzione_id"] = esecuzione_id
    return esecuzione_id


def _assicura_esecuzione(utente: str) -> int:
    if STATO.get("esecuzione_id") is None:
        return _registra_esecuzione(utente, "registrazione del lotto attivo al primo utilizzo operativo")
    return int(STATO["esecuzione_id"])


def _inizializza_dataset() -> None:
    salvato = dataset_store.carica_attivo()
    if salvato is None:
        _carica_sintetici(persisti=False)
        return
    meta = salvato["metadati"]
    STATO.update({
        "aziende": salvato["aziende"],
        "origine": meta["origine"],
        "dataset_sintetico": meta["sintetico"],
        "lotto_id": meta["lotto_id"],
        "hash_origine": meta["hash_origine"],
        "hash_dataset": meta["hash_dataset"],
        "hash_configurazione": meta["hash_configurazione"],
        "configurazione_corrente": meta["configurazione_corrente"],
        "esecuzione_id": None,
    })
    try:
        STATO["provenienza"] = None if meta["sintetico"] else provenienza.per_lotto(meta["lotto_id"])
    except Exception:
        STATO["provenienza"] = None


def _utente(request) -> str:
    utente = request.session.get("utente") or {}
    return str(utente.get("username", "sconosciuto"))


def _ruolo(request) -> str:
    utente = request.session.get("utente") or {}
    return str(utente.get("ruolo", ""))


def _context(request, **extra):
    utente = request.session.get("utente")
    ruolo = str((utente or {}).get("ruolo", "")) if isinstance(utente, dict) else ""
    return {
        "utente": utente,
        "puo": {permesso: ruolo in ruoli for permesso, ruoli in sicurezza.PERMESSI.items()},
        "csrf_token": sicurezza.token_csrf(request.session),
        "configurazione_corrente": STATO.get("configurazione_corrente", True),
        "autorizzazione_scaduta": provenienza.scaduta(STATO.get("provenienza")),
        "nature_parametro": settori.NATURE_PARAMETRO,
        **extra,
    }


def _accesso_negato(request, ruoli: set[str]) -> Response | None:
    utente = request.session.get("utente")
    if not isinstance(utente, dict) or not utente.get("username") or not utente.get("ruolo") or not sessioni.valida(request.session.get("sid"), utente.get("username")):
        request.session.clear()
        destinazione = request.url.path
        if request.url.query:
            destinazione += "?" + request.url.query
        return RedirectResponse("/login?next=" + quote(destinazione, safe="/=?&"), status_code=303)
    # Ruolo e abilitazione sono riletti dalla configurazione a ogni richiesta: un
    # account rimosso o con ruolo cambiato non conserva i privilegi della sessione.
    attuale = sicurezza.utenti_configurati().get(utente.get("username"))
    if attuale is None:
        sessioni.revoca(request.session.get("sid"))
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    if attuale["ruolo"] != utente.get("ruolo"):
        utente = {"username": attuale["username"], "ruolo": attuale["ruolo"]}
        request.session["utente"] = utente
    if utente.get("ruolo") not in ruoli:
        audit.registra(_utente(request), "accesso_negato", request.url.path, esito="negato", ruolo=str(utente.get("ruolo", "")))
        return PlainTextResponse("Accesso negato: il ruolo corrente non è autorizzato.", status_code=403)
    return None


def _csrf_valido(request, form) -> bool:
    return sicurezza.valida_token_csrf(request.session, form.get("csrf_token"))


class IntestazioniSicurezzaMiddleware:
    """Aggiunge intestazioni di sicurezza di base a tutte le risposte HTTP."""
    def __init__(self, app, **kwargs):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_con_intestazioni(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                esistenti = {k.lower() for k, _ in headers}
                aggiunte = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                    (b"cache-control", b"no-store"),
                    (b"pragma", b"no-cache"),
                    (b"content-security-policy", b"default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"),
                ]
                if sicurezza.ambiente_produzione():
                    aggiunte.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                for nome, valore in aggiunte:
                    if nome not in esistenti:
                        headers.append((nome, valore))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_con_intestazioni)


# Monitoraggio essenziale delle prestazioni (sezione 23): per percorso normalizzato,
# numero di richieste, errori, tempo medio e massimo. In memoria, per processo.
PRESTAZIONI: dict[str, dict] = {}
SOGLIA_LENTA_SECONDI = 2.0


def _percorso_normalizzato(path: str) -> str:
    import re as _re
    path = _re.sub(r"/(AZ|PR-|REL-)?[A-Za-z0-9_.-]{6,}(?=/|$)", "/{id}", path)
    return path[:80]


def _registra_prestazione(path: str, codice: int, durata: float) -> None:
    chiave = _percorso_normalizzato(path)
    voce = PRESTAZIONI.setdefault(chiave, {"richieste": 0, "errori_5xx": 0, "totale_s": 0.0, "massimo_s": 0.0, "lente": 0})
    voce["richieste"] += 1
    voce["totale_s"] += durata
    voce["massimo_s"] = max(voce["massimo_s"], durata)
    if codice >= 500:
        voce["errori_5xx"] += 1
    if durata > SOGLIA_LENTA_SECONDI:
        voce["lente"] += 1
    if len(PRESTAZIONI) > 500:
        PRESTAZIONI.pop(next(iter(PRESTAZIONI)))


class CorrelazioneMiddleware:
    """Assegna un identificativo di correlazione a ogni richiesta (header X-Request-ID e audit)."""
    def __init__(self, app, **kwargs):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        identificativo = secrets.token_hex(8)
        token = audit.CORRELAZIONE.set(identificativo)
        import time as _t
        inizio = _t.perf_counter()
        stato_risposta = {"codice": 0}

        async def send_con_id(message):
            if message["type"] == "http.response.start":
                stato_risposta["codice"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", identificativo.encode()))
                message["headers"] = headers
            await send(message)
        try:
            await self.app(scope, receive, send_con_id)
        finally:
            audit.CORRELAZIONE.reset(token)
            _registra_prestazione(scope.get("path", ""), stato_risposta["codice"], _t.perf_counter() - inizio)


class LimiteDimensioneRichiestaMiddleware:
    """Limita il corpo HTTP della rotta di upload anche in assenza di Content-Length."""
    def __init__(self, app, max_bytes: int = MAX_UPLOAD_BYTES + 128 * 1024):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = scope.get("path")
        if path == "/carica":
            limite_corpo = csv_import.MAX_BYTES + 128 * 1024
        elif path == "/documenti/carica":
            limite_corpo = documenti.MAX_DOCUMENT_BYTES + 128 * 1024
        else:
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                if int(raw_length) > limite_corpo:
                    await _risposta_413(send)
                    return
            except ValueError:
                await _risposta_413(send)
                return
        messaggi = []
        totale = 0
        while True:
            messaggio = await receive()
            if messaggio["type"] == "http.disconnect":
                return
            if messaggio["type"] != "http.request":
                continue
            corpo = messaggio.get("body", b"")
            totale += len(corpo)
            if totale > limite_corpo:
                await _risposta_413(send)
                return
            messaggi.append(messaggio)
            if not messaggio.get("more_body", False):
                break
        indice = 0

        async def receive_riprodotto():
            nonlocal indice
            if indice < len(messaggi):
                msg = messaggi[indice]
                indice += 1
                return msg
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, receive_riprodotto, send)


async def _risposta_413(send):
    corpo = b"Richiesta troppo grande."
    await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(corpo)).encode())]})
    await send({"type": "http.response.body", "body": corpo})


async def login_form(request):
    errore = request.query_params.get("errore") == "configurazione"
    return templates.TemplateResponse(request, "login.html", _context(
        request,
        errore="Autenticazione non configurata. L'amministratore tecnico deve configurare gli account prima di usare la piattaforma." if errore else None,
        auth_configurata=bool(sicurezza.utenti_configurati()),
    ))


async def login_post(request):
    form = await request.form()
    if not _csrf_valido(request, form):
        audit.registra("anonimo", "login_csrf_rifiutato", "", esito="negato")
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina di accesso.", status_code=400)
    if not sicurezza.utenti_configurati():
        return RedirectResponse("/login?errore=configurazione", status_code=303)
    client_ip = request.client.host if request.client else "sconosciuto"
    # IP usato soltanto per limitazione temporanea; non viene assunto come identità.
    if sicurezza.tentativi_bloccati(client_ip):
        audit.registra("anonimo", "login_bloccato", "", esito="bloccato")
        return templates.TemplateResponse(request, "login.html", _context(request, errore="Troppi tentativi. Attendi prima di riprovare.", auth_configurata=True), status_code=429)
    username_valore = form.get("username", "")
    password_valore = form.get("password", "")
    if not isinstance(username_valore, str) or not isinstance(password_valore, str) or len(username_valore) > 100 or len(password_valore) > 1024:
        username = ""
        password = ""
        utente = None
    else:
        username = username_valore
        password = password_valore
        utente = sicurezza.verifica_credenziali(username, password)
    if utente is None:
        sicurezza.registra_login_fallito(client_ip)
        audit.registra("anonimo", "login_fallito", "", esito="negato")
        return templates.TemplateResponse(request, "login.html", _context(request, errore="Credenziali non valide.", auth_configurata=True), status_code=401)
    sicurezza.registra_login_riuscito(client_ip)
    request.session.clear()
    request.session["utente"] = utente
    session_id = secrets.token_urlsafe(32)
    sessioni.crea(session_id, utente["username"])
    request.session["sid"] = session_id
    sicurezza.token_csrf(request.session)
    audit.registra(utente["username"], "login_riuscito", "", esito="ok", ruolo=utente["ruolo"])
    destinazione = str(form.get("next", "/"))
    if not destinazione.startswith("/") or destinazione.startswith("//") or "\\" in destinazione:
        destinazione = "/"
    return RedirectResponse(destinazione, status_code=303)


async def logout(request):
    if not request.session.get("utente"):
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    username = _utente(request)
    sessioni.revoca(request.session.get("sid"))
    audit.registra(username, "logout", "", esito="ok")
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


async def home(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("consulta_elenco"))
    if denied:
        return denied
    settore_filtro = request.query_params.get("settore", "")
    livello = request.query_params.get("livello", "")
    aziende = STATO["aziende"]
    if settore_filtro:
        aziende = [a for a in aziende if a.get("settore") == settore_filtro]
    if livello:
        aziende = [a for a in aziende if a.get("analisi", {}).get("livello") == livello]
    ricerca = request.query_params.get("q", "").strip()[:100]
    if ricerca:
        termine = ricerca.casefold()
        aziende = [a for a in aziende if termine in str(a.get("id", "")).casefold()
                   or termine in str(a.get("ragione_sociale", "")).casefold() or termine in str(a.get("citta", "")).casefold()]
    aziende = sorted(aziende, key=lambda a: a.get("analisi", {}).get("punteggio") if isinstance(a.get("analisi", {}).get("punteggio"), (int, float)) else -1, reverse=True)
    settori_presenti = sorted({a.get("settore", "") for a in STATO["aziende"] if a.get("settore")})
    audit.registra(_utente(request), "consultazione_classifica", "", esito="ok")
    return templates.TemplateResponse(request, "home.html", _context(request, **{
        "aziende": aziende[:200], "totale": len(aziende), "settori": settori_presenti,
        "settore_sel": settore_filtro, "livello_sel": livello, "origine": STATO["origine"], "ricerca": ricerca,
        "stato_sintetico": STATO["dataset_sintetico"],
    }))


async def dettaglio(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("consulta_scheda"))
    if denied:
        return denied
    az_id = request.path_params["az_id"]
    azienda = next((a for a in STATO["aziende"] if a.get("id") == az_id), None)
    audit.registra(_utente(request), "consultazione_scheda", az_id, esito="ok" if azienda else "non_trovato")
    if azienda is None:
        return PlainTextResponse("Azienda non trovata.", status_code=404)
    try:
        storico = db_operativo.storico_azienda(az_id)
        pratiche_azienda = pratiche.elenco(50, azienda_id=az_id)
    except Exception:
        storico, pratiche_azienda = [], []
    return templates.TemplateResponse(request, "azienda.html", _context(
        request, az=azienda, storico=storico, pratiche_azienda=pratiche_azienda))


async def report_azienda(request):
    """Esporta una relazione sperimentale solo a utenti autorizzati e su analisi attuali."""
    denied = _accesso_negato(request, sicurezza.ruoli_per("genera_report"))
    if denied:
        return denied
    bloccato = _blocco_autorizzazione(request, "generazione_report_pdf")
    if bloccato:
        return bloccato
    az_id = request.path_params["az_id"]
    azienda = next((a for a in STATO["aziende"] if a.get("id") == az_id), None)
    if azienda is None:
        audit.registra(_utente(request), "generazione_report_pdf", az_id, esito="non_trovato")
        return PlainTextResponse("Azienda non trovata.", status_code=404)
    if not STATO.get("configurazione_corrente", False):
        audit.registra(_utente(request), "generazione_report_pdf", az_id, esito="bloccato_configurazione_obsoleta")
        return PlainTextResponse(
            "Report non generato: la configurazione è cambiata. Un amministratore deve ricalcolare il lotto attivo.",
            status_code=409,
        )
    try:
        settore = settori.configurazione_settore(str(azienda.get("settore", ""))) or {}
        metadati = {
            "lotto_id": STATO.get("lotto_id"),
            "hash_origine": STATO.get("hash_origine"),
            "hash_dataset": STATO.get("hash_dataset"),
            "hash_configurazione": STATO.get("hash_configurazione"),
            "configurazione_corrente": STATO.get("configurazione_corrente", False),
        }
        pratica = None
        pratica_id = request.query_params.get("pratica", "")
        if pratica_id:
            pratica = pratiche.ottieni(pratica_id)
            if pratica is None or pratica["azienda_id"] != az_id:
                return PlainTextResponse("Pratica non trovata per questa azienda.", status_code=404)
        esecuzione_id = _assicura_esecuzione(_utente(request))
        report_id = "REL-" + secrets.token_hex(8).upper()
        contesto = {"report_id": report_id, "versione_documento": "1", "esecuzione_id": esecuzione_id,
                    "pratica": pratica, "operatore": _utente(request), "ruolo": _ruolo(request)}
        pdf = genera_relazione_azienda(azienda, metadati_lotto=metadati, configurazione_settore=settore, contesto=contesto)
        impronta = hashlib.sha256(pdf).hexdigest()
        db_operativo.registra_report(report_id=report_id, utente=_utente(request), ruolo=_ruolo(request), azienda_id=az_id,
                                     pratica_id=pratica["id"] if pratica else None, esecuzione_id=esecuzione_id,
                                     sha256=impronta, byte=len(pdf))
    except ErroreReport as exc:
        audit.registra(_utente(request), "generazione_report_pdf", az_id, esito="rifiutato", motivo=str(exc)[:160])
        return PlainTextResponse(str(exc), status_code=409)
    except Exception:
        audit.registra(_utente(request), "generazione_report_pdf", az_id, esito="errore_interno")
        return PlainTextResponse("Report non generato per un errore interno.", status_code=500)
    import re
    nome_sicuro = re.sub(r"[^A-Za-z0-9_-]", "_", az_id)[:80] or "azienda"
    audit.registra(_utente(request), "generazione_report_pdf", az_id, esito="ok", request_id=report_id, sha256=impronta)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="emersione-{nome_sicuro}.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def fonti(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("consulta_fonti"))
    if denied:
        return denied
    audit.registra(_utente(request), "consultazione_fonti", "", esito="ok")
    try:
        acquisizioni = fonti_store.elenco(50)
    except Exception:
        acquisizioni = []
    return templates.TemplateResponse(request, "fonti.html", _context(
        request, fonti=registro.per_categoria(), acquisizioni=acquisizioni,
        esito=request.query_params.get("esito", ""), domini_osint=osint.domini_autorizzati()))


def _parametri_query_form(testo: str) -> dict[str, str]:
    if not isinstance(testo, str) or len(testo) > 5000:
        raise fonti_live.ErroreAcquisizione("Parametri troppo lunghi.")
    risultati = {}
    for riga_num, riga in enumerate(testo.splitlines(), start=1):
        riga = riga.strip()
        if not riga or riga.startswith("#"):
            continue
        if "=" not in riga:
            raise fonti_live.ErroreAcquisizione(f"Riga parametri {riga_num}: usa chiave=valore.")
        chiave, valore = riga.split("=", 1)
        chiave, valore = chiave.strip(), valore.strip()
        if chiave in risultati:
            raise fonti_live.ErroreAcquisizione(f"Parametro duplicato: {chiave}.")
        risultati[chiave] = valore
    return risultati


async def fonti_acquisisci(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("acquisisci_fonti"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=12)
    except Exception:
        return PlainTextResponse("Modulo di acquisizione non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    tipo = str(form.get("tipo", "")).strip()
    try:
        if tipo == "inail":
            dataset = str(form.get("dataset_inail", ""))
            parametri = _parametri_query_form(str(form.get("parametri", "")))
            payload = await asyncio.to_thread(fonti_live.acquisisci_inail, dataset, parametri)
        elif tipo == "istat":
            url = str(form.get("url_istat", "")).strip()
            parametri = _parametri_query_form(str(form.get("parametri", "")))
            payload = await asyncio.to_thread(fonti_live.acquisisci_istat, url, parametri)
        elif tipo == "anac":
            url = str(form.get("url_anac", "")).strip()
            payload = await asyncio.to_thread(fonti_live.acquisisci_anac, url)
        else:
            raise fonti_live.ErroreAcquisizione("Tipo di fonte non riconosciuto.")
        risultato = fonti_store.salva(payload)
        audit.registra(_utente(request), "acquisizione_fonte_pubblica", risultato["chiave"], esito="ok",
                       sha256=risultato["sha256"], byte=risultato["dimensione_byte"])
        acquisizioni = fonti_store.elenco(50)
        return templates.TemplateResponse(request, "fonti.html", _context(request,
            fonti=registro.per_categoria(), acquisizioni=acquisizioni,
            esito=f"Acquisizione archiviata (ID {risultato['id']}). Formato rilevato: {risultato['formato']}. {risultato['nota']}",
            domini_osint=osint.domini_autorizzati()))
    except (fonti_live.ErroreAcquisizione, fonti_store.ErroreArchivioFonte, ValueError) as exc:
        audit.registra(_utente(request), "acquisizione_fonte_pubblica", tipo or "sconosciuta", esito="rifiutato", motivo=str(exc)[:160])
        return templates.TemplateResponse(request, "fonti.html", _context(request,
            fonti=registro.per_categoria(), acquisizioni=fonti_store.elenco(50),
            esito=str(exc), domini_osint=osint.domini_autorizzati()), status_code=400)
    except Exception:
        audit.registra(_utente(request), "acquisizione_fonte_pubblica", tipo or "sconosciuta", esito="errore_interno")
        return templates.TemplateResponse(request, "fonti.html", _context(request,
            fonti=registro.per_categoria(), acquisizioni=fonti_store.elenco(50),
            esito="Acquisizione non completata per un errore interno. Verificare rete, configurazione e log autorizzato.",
            domini_osint=osint.domini_autorizzati()), status_code=500)


def _contesto_fonti_mappatura(request, anteprima=None, esito=None, stato_code=200, mapping=None, righe=None):
    return _context(request,
        anteprima=anteprima, esito=esito, mapping=mapping, righe=righe or [],
        settori=settori.lista_settori(), parametri=settori.lista_parametri(),
        mappature=fonti_mapping.elenco(100), stato_code=stato_code)


async def fonti_mappatura_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("consulta_mappature"))
    if denied:
        return denied
    fetch_id = request.path_params.get("fetch_id", "")
    try:
        anteprima = fonti_mapping.anteprima(fetch_id)
    except fonti_mapping.ErroreMappatura as exc:
        return PlainTextResponse(str(exc), status_code=400)
    audit.registra(_utente(request), "anteprima_mapping_fonte", fetch_id, esito="ok", sha256=anteprima["hash_fonte"])
    return templates.TemplateResponse(request, "fonti_mappatura.html", _contesto_fonti_mappatura(request, anteprima=anteprima))


async def fonti_mappatura_crea(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("crea_mappature"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=16, max_part_size=32 * 1024)
    except Exception:
        return PlainTextResponse("Modulo mapping non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica il modulo.", status_code=400)
    fetch_id = str(form.get("acquisizione_id", ""))
    try:
        mapping = fonti_mapping.crea_mappatura(
            acquisizione_id=fetch_id, settore_id=str(form.get("settore_id", "")),
            parametro_id=str(form.get("parametro_id", "")), campo_valore=str(form.get("campo_valore", "")),
            campo_periodo=str(form.get("campo_periodo", "")), campo_territorio=str(form.get("campo_territorio", "")),
            campo_categoria=str(form.get("campo_categoria", "")), campo_unita=str(form.get("campo_unita", "")),
            unita_fissa=str(form.get("unita_fissa", "")), formato_numero=str(form.get("formato_numero", "automatico")),
            utente=_utente(request))
        audit.registra(_utente(request), "normalizzazione_fonte", mapping["id"], esito="ok",
                       sha256=mapping["hash_fonte"], numero_record=mapping["numero_righe"], ruolo=_ruolo(request))
        return RedirectResponse(f"/fonti/mappature/{mapping['id']}", status_code=303)
    except fonti_mapping.ErroreMappatura as exc:
        audit.registra(_utente(request), "normalizzazione_fonte", fetch_id, esito="rifiutato", motivo=str(exc)[:160])
        try:
            anteprima = fonti_mapping.anteprima(fetch_id)
            return templates.TemplateResponse(request, "fonti_mappatura.html",
                _contesto_fonti_mappatura(request, anteprima=anteprima, esito=str(exc)), status_code=400)
        except fonti_mapping.ErroreMappatura:
            return PlainTextResponse(str(exc), status_code=400)
    except Exception:
        audit.registra(_utente(request), "normalizzazione_fonte", fetch_id, esito="errore_interno")
        return PlainTextResponse("Mapping non salvato. La transazione è stata annullata.", status_code=500)


async def fonti_mappatura_dettaglio(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("consulta_mappature"))
    if denied:
        return denied
    mapping_id = request.path_params.get("mapping_id", "")
    mapping = next((m for m in fonti_mapping.elenco(200) if m["id"] == mapping_id), None)
    if mapping is None:
        return PlainTextResponse("Mapping non trovato.", status_code=404)
    righe = fonti_mapping.osservazioni(mapping_id, 200)
    audit.registra(_utente(request), "consultazione_osservazioni_riferimento", mapping_id, esito="ok")
    return templates.TemplateResponse(request, "fonti_mappatura_dettaglio.html",
        _contesto_fonti_mappatura(request, mapping=mapping, righe=righe))


async def fonti_mappatura_revisiona(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("revisiona_mappature"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=8, max_part_size=16 * 1024)
    except Exception:
        return PlainTextResponse("Modulo revisione mapping non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica il modulo.", status_code=400)
    mapping_id = str(form.get("mapping_id", ""))
    try:
        fonti_mapping.revisiona(mapping_id, stato=str(form.get("stato", "")),
            nota=str(form.get("nota", "")), revisore=_utente(request))
        audit.registra(_utente(request), "revisione_mapping_fonte", mapping_id, esito="ok", stato=str(form.get("stato", "")))
        return RedirectResponse(f"/fonti/mappature/{mapping_id}", status_code=303)
    except fonti_mapping.ErroreMappatura as exc:
        audit.registra(_utente(request), "revisione_mapping_fonte", mapping_id, esito="rifiutato", motivo=str(exc)[:160])
        return PlainTextResponse(str(exc), status_code=400)


async def fonti_scarica(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("scarica_fonti"))
    if denied:
        return denied
    try:
        trovato = fonti_store.contenuto(request.path_params.get("fetch_id", ""))
        if trovato is None:
            return PlainTextResponse("Payload non trovato.", status_code=404)
        meta, contenuto = trovato
        audit.registra(_utente(request), "download_payload_fonte", meta["id"], esito="ok", sha256=meta["sha256"])
        return Response(contenuto, media_type=meta["content_type"], headers={
            "Content-Disposition": f'attachment; filename="emersione-fonte-{meta["id"]}.{"json" if "json" in meta["content_type"] else "csv" if "csv" in meta["content_type"] else "dat"}"',
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    except fonti_store.ErroreArchivioFonte:
        audit.registra(_utente(request), "download_payload_fonte", request.path_params.get("fetch_id", ""), esito="integrita_fallita")
        return PlainTextResponse("Integrità del payload non verificata.", status_code=409)


async def valutazione(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("valutazione"))
    if denied:
        return denied
    # Mai calcolare o mostrare metriche di validazione per dati senza etichette
    # di riferimento. Il dataset sintetico è l'unica eccezione dimostrativa.
    sintetico_standard = STATO["dataset_sintetico"] and STATO["origine"] == ORIGINE_SINTETICA
    etichette = _etichette_sintetiche() if sintetico_standard else {}
    tipo = "sintetiche" if etichette else None
    metriche = valutazione_motore.valuta_motore(STATO["aziende"], etichette, tipo)
    gruppi = {}
    if metriche.get("valutabile"):
        gruppi = {
            "Settore": valutazione_motore.per_gruppo(STATO["aziende"], etichette, tipo, lambda a: a.get("settore")),
            "Territorio": valutazione_motore.per_gruppo(STATO["aziende"], etichette, tipo, lambda a: a.get("citta")),
            "Dimensione": valutazione_motore.per_gruppo(STATO["aziende"], etichette, tipo, valutazione_motore.classe_dimensionale),
        }
    audit.registra(_utente(request), "consultazione_valutazione", "", esito="ok")
    return templates.TemplateResponse(request, "valutazione.html", _context(request, m=metriche, gruppi=gruppi, origine=STATO["origine"], dataset_sintetico=STATO["dataset_sintetico"]))


STAGING: dict[str, dict] = {}
STAGING_SECONDI = 30 * 60


def _pulisci_staging():
    import time as _t
    for token in [t for t, v in STAGING.items() if _t.time() - v["creato"] > STAGING_SECONDI]:
        STAGING.pop(token, None)


def _staging_utente(utente: str):
    _pulisci_staging()
    return next(((t, v) for t, v in STAGING.items() if v["utente"] == utente), (None, None))


def _anteprima(aziende):
    per_settore, per_livello = {}, {}
    for a in aziende:
        per_settore[a.get("settore")] = per_settore.get(a.get("settore"), 0) + 1
        livello = a["analisi"]["livello"]
        per_livello[livello] = per_livello.get(livello, 0) + 1
    return {"per_settore": per_settore, "per_livello": per_livello, "primi": aziende[:10], "totale": len(aziende)}


def _contesto_carica(request, **extra):
    token, staging = _staging_utente(_utente(request))
    base = {"esito": None, "token": token, "staging": staging, "anteprima": _anteprima(staging["aziende"]) if staging else None,
            "provenienza_attiva": STATO.get("provenienza"), "storico_lotti": provenienza.elenco(20), "dati_form": {}}
    base.update(extra)
    return _context(request, **base)


async def carica_form(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("importa_dati"))
    if denied:
        return denied
    return templates.TemplateResponse(request, "carica.html", _contesto_carica(request))


async def carica_post(request):
    """Fase 1: validazione e anteprima. Il lotto attivo NON cambia."""
    denied = _accesso_negato(request, sicurezza.ruoli_per("importa_dati"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=1, max_fields=16, max_part_size=MAX_UPLOAD_BYTES)
    except Exception:
        return templates.TemplateResponse(request, "carica.html", _contesto_carica(request, esito="Richiesta multipart non valida o troppo complessa."), status_code=400)
    try:
        if not _csrf_valido(request, form):
            return PlainTextResponse("Richiesta non valida. Ricarica il modulo.", status_code=400)
        dati_form = {k: str(form.get(k, ""))[:500] for k in (*provenienza.CAMPI, "scadenza_autorizzazione")}
        try:
            prov = provenienza.valida(dati_form)
        except provenienza.ErroreProvenienza as exc:
            return templates.TemplateResponse(request, "carica.html", _contesto_carica(request, esito=str(exc), dati_form=dati_form), status_code=400)
        upload = form.get("file")
        if upload is None or not getattr(upload, "filename", ""):
            return templates.TemplateResponse(request, "carica.html", _contesto_carica(request, esito="Seleziona un file CSV.", dati_form=dati_form), status_code=400)
        filename = str(upload.filename).replace("\\", "/").split("/")[-1][:120]
        if not filename.casefold().endswith(".csv"):
            return templates.TemplateResponse(request, "carica.html", _contesto_carica(request, esito="È consentito soltanto un file con estensione .csv.", dati_form=dati_form), status_code=400)
        contenuto = await upload.read(MAX_UPLOAD_BYTES + 1)
        digest = hashlib.sha256(contenuto).hexdigest()
        try:
            aziende_importate = csv_import.carica_csv_da_bytes(contenuto)
            # Etichette eventualmente presenti nel file: separate dai dati e non usate dal motore.
            valutazione_motore.estrai_etichette(aziende_importate, "_irregolare")
            aziende_analizzate = analizza(aziende_importate)
        except csv_import.ErroreCSV as exc:
            audit.registra(_utente(request), "import_csv_anteprima", filename, esito="rifiutato", sha256=digest, motivo=str(exc)[:180])
            return templates.TemplateResponse(request, "carica.html", _contesto_carica(request, esito=str(exc), dati_form=dati_form), status_code=400)
        except Exception:
            audit.registra(_utente(request), "import_csv_anteprima", filename, esito="errore_interno", sha256=digest)
            return templates.TemplateResponse(request, "carica.html", _contesto_carica(request, esito="Validazione non completata per un errore interno. Il dataset attivo non è stato modificato.", dati_form=dati_form), status_code=500)
        import time as _t
        for t in [t for t, v in STAGING.items() if v["utente"] == _utente(request)]:
            STAGING.pop(t, None)
        token = secrets.token_urlsafe(24)
        STAGING[token] = {"utente": _utente(request), "creato": _t.time(), "aziende": aziende_analizzate,
                          "filename": filename, "sha256": digest, "provenienza": prov}
        audit.registra(_utente(request), "import_csv_anteprima", filename, esito="ok", sha256=digest, numero_record=len(aziende_analizzate))
        return templates.TemplateResponse(request, "carica.html", _contesto_carica(
            request, esito="File valido. Controlla l'anteprima e conferma per sostituire il lotto attivo."))
    finally:
        await form.close()


async def carica_conferma(request):
    """Fase 2: conferma esplicita; sostituzione transazionale del lotto attivo."""
    denied = _accesso_negato(request, sicurezza.ruoli_per("importa_dati"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    token, staging = _staging_utente(_utente(request))
    if staging is None or not secrets.compare_digest(str(form.get("token", "")), token or ""):
        return PlainTextResponse("Anteprima scaduta o non valida: ripetere il caricamento.", status_code=409)
    aziende_analizzate = staging["aziende"]
    filename = staging["filename"]
    origine = f"CSV importato: {filename} ({len(aziende_analizzate)} record; conferente dichiarato: {staging['provenienza']['conferente']})"
    try:
        # Salvataggio transazionale prima dell'aggiornamento dello stato condiviso:
        # se fallisce, il lotto in memoria resta quello precedente.
        metadati = dataset_store.salva_attivo(aziende_analizzate, origine=origine, sintetico=False, hash_origine=staging["sha256"])
        provenienza.registra(lotto_id=metadati["lotto_id"], file=filename, sha256=staging["sha256"],
                             dati=staging["provenienza"], utente=_utente(request))
    except Exception:
        audit.registra(_utente(request), "import_csv", filename, esito="errore_interno", sha256=staging["sha256"])
        return templates.TemplateResponse(request, "carica.html", _contesto_carica(request, esito="Importazione non completata per un errore interno. Il dataset attivo non è stato sostituito."), status_code=500)
    STATO.update({
        "aziende": aziende_analizzate, "origine": origine, "dataset_sintetico": False,
        "lotto_id": metadati["lotto_id"], "hash_origine": metadati["hash_origine"], "hash_dataset": metadati["hash_dataset"],
        "hash_configurazione": metadati["hash_configurazione"], "configurazione_corrente": True,
        "provenienza": provenienza.per_lotto(metadati["lotto_id"]),
    })
    STAGING.pop(token, None)
    esecuzione_id = _registra_esecuzione(_utente(request), f"import CSV {filename}")
    audit.registra(_utente(request), "import_csv", filename, esito="ok", ruolo=_ruolo(request), sha256=staging["sha256"],
                   numero_record=len(aziende_analizzate), stato=f"lotto {metadati['lotto_id']} esecuzione {esecuzione_id}")
    return templates.TemplateResponse(request, "carica.html", _contesto_carica(
        request, esito=f"Importazione completata: {len(aziende_analizzate)} record attivi. Le metriche sintetiche non sono applicabili a questo lotto."))


async def carica_annulla(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("importa_dati"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    token, staging = _staging_utente(_utente(request))
    if staging:
        STAGING.pop(token, None)
        audit.registra(_utente(request), "import_csv_annullato", staging["filename"], esito="ok")
    return RedirectResponse("/carica", status_code=303)


async def lotto_revoca(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("importa_dati"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    lotto_id = STATO.get("lotto_id")
    try:
        if STATO.get("dataset_sintetico") or not lotto_id:
            raise provenienza.ErroreProvenienza("Il lotto attivo è dimostrativo: nulla da revocare.")
        provenienza.revoca(lotto_id, utente=_utente(request), motivo=str(form.get("motivo", "")))
    except provenienza.ErroreProvenienza as exc:
        return templates.TemplateResponse(request, "carica.html", _contesto_carica(request, esito=str(exc)), status_code=400)
    _carica_sintetici(persisti=True)
    _registra_esecuzione(_utente(request), f"revoca del lotto {lotto_id}: ripristino dimostrativo")
    audit.registra(_utente(request), "revoca_lotto", str(lotto_id), esito="ok", ruolo=_ruolo(request), motivo=str(form.get("motivo", ""))[:180])
    return RedirectResponse("/carica", status_code=303)


def _blocco_autorizzazione(request, operazione: str):
    """Con autorizzazione del lotto scaduta, relazioni, esportazioni e nuove pratiche sono sospese."""
    if provenienza.scaduta(STATO.get("provenienza")):
        audit.registra(_utente(request), operazione, "", esito="bloccato_autorizzazione_scaduta")
        return PlainTextResponse("Operazione sospesa: l'autorizzazione dichiarata per il lotto attivo è scaduta. "
                                 "Rinnovarla con un nuovo caricamento o revocare il lotto.", status_code=409)
    return None


async def ricalcola(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("ricalcola"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=5)
    except Exception:
        return PlainTextResponse("Modulo non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica il modulo.", status_code=400)
    try:
        righe_grezze = [
            {k: v for k, v in riga.items() if k != "analisi" and not k.startswith("_")}
            for riga in STATO["aziende"]
        ]
        aziende_analizzate = analizza(righe_grezze)
        metadati = dataset_store.salva_attivo(
            aziende_analizzate,
            origine=STATO["origine"],
            sintetico=bool(STATO["dataset_sintetico"]),
            hash_origine=STATO.get("hash_origine"),
        )
        STATO.update({
            "aziende": aziende_analizzate,
            "lotto_id": metadati["lotto_id"],
            "hash_origine": metadati["hash_origine"],
            "hash_dataset": metadati["hash_dataset"],
            "hash_configurazione": metadati["hash_configurazione"],
            "configurazione_corrente": True,
        })
        _registra_esecuzione(_utente(request), "ricalcolo esplicito")
        audit.registra(_utente(request), "ricalcolo_analisi", STATO["origine"], esito="ok", ruolo="amministratore", request_id=metadati["lotto_id"])
        return RedirectResponse("/", status_code=303)
    except Exception:
        audit.registra(_utente(request), "ricalcolo_analisi", "", esito="errore_interno", ruolo=_ruolo(request))
        return PlainTextResponse("Ricalcolo non completato. Il lotto precedente resta attivo.", status_code=500)


async def ripristina(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("ripristina_demo"))
    if denied:
        return denied
    form = await request.form()
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    provenienza.chiudi_attivo()
    _carica_sintetici(persisti=True)
    _registra_esecuzione(_utente(request), "ripristino del dataset dimostrativo")
    audit.registra(_utente(request), "ripristino_dati_sintetici", "", esito="ok", request_id=STATO.get("lotto_id"))
    return RedirectResponse("/", status_code=303)


async def audit_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("audit"))
    if denied:
        return denied
    audit.registra(_utente(request), "consultazione_audit", "", esito="ok")
    integrita = audit.verifica_integrita()
    return templates.TemplateResponse(request, "audit.html", _context(
        request, voci=audit.leggi(200), integrita=integrita))


async def settori_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("consulta_settori"))
    if denied:
        return denied
    return templates.TemplateResponse(request, "settori.html", _context(
        request, settori=settori.lista_settori(includi_archiviati=True), parametri=settori.lista_parametri(), documenti=settori.lista_documenti(), esito=None,
    ))


async def settori_parametro_aggiorna(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("configura_settori") | sicurezza.ruoli_per("valida_parametri"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=24, max_part_size=16 * 1024)
    except Exception:
        return PlainTextResponse("Modulo non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    parametro_id = str(form.get("parametro_id", ""))
    # Separazione dei compiti: solo il revisore dichiara un parametro verificato/approvato;
    # le modifiche tecniche restano all'amministratore o al responsabile dei dati.
    permesso = "valida_parametri" if str(form.get("stato", "")) in {"verificato", "approvato"} else "configura_settori"
    if _ruolo(request) not in sicurezza.ruoli_per(permesso):
        audit.registra(_utente(request), "aggiornamento_parametro", parametro_id, esito="negato", ruolo=_ruolo(request), motivo=permesso)
        return PlainTextResponse("Accesso negato: il ruolo corrente non può eseguire questa modifica del parametro.", status_code=403)
    try:
        versione = settori.aggiorna_parametro(
            parametro_id=parametro_id,
            nome=str(form.get("nome", "")), valore=str(form.get("valore", "")),
            unita=str(form.get("unita", "")), fonte=str(form.get("fonte", "")),
            descrizione=str(form.get("descrizione", "")), stato=str(form.get("stato", "da_verificare")),
            documento_validazione=str(form.get("documento_validazione", "")),
            nota_validazione=str(form.get("nota_validazione", "")), autore=_utente(request),
            natura=str(form.get("natura", "")) or None,
            riferimento_fonte={c: str(form.get(f"rf_{c}", "")) for c in settori.CAMPI_RIFERIMENTO}
            if any(form.get(f"rf_{c}") is not None for c in settori.CAMPI_RIFERIMENTO) else None,
        )
        if STATO.get("hash_configurazione") and STATO.get("hash_configurazione") != dataset_store.hash_configurazione():
            STATO["configurazione_corrente"] = False
        audit.registra(_utente(request), "aggiornamento_parametro", parametro_id, esito="ok", ruolo=_ruolo(request))
        esito = f"Parametro aggiornato alla versione {versione}. Verifica la provenienza e ricalcola il lotto se i dati/configurazioni sono cambiati."
        status_code = 200
    except (settori.ErroreRegistro, ValueError) as exc:
        audit.registra(_utente(request), "aggiornamento_parametro", parametro_id, esito="rifiutato", ruolo=_ruolo(request))
        esito = str(exc)
        status_code = 400
    except Exception:
        audit.registra(_utente(request), "aggiornamento_parametro", parametro_id, esito="errore_interno", ruolo=_ruolo(request))
        esito = "Parametro non aggiornato per un errore interno. La versione precedente è rimasta registrata."
        status_code = 500
    return templates.TemplateResponse(request, "settori.html", _context(
        request, settori=settori.lista_settori(includi_archiviati=True), parametri=settori.lista_parametri(),
        documenti=settori.lista_documenti(), esito=esito,
    ), status_code=status_code)


async def settori_campo_aggiungi(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("configura_settori"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=12, max_part_size=16 * 1024)
    except Exception:
        return PlainTextResponse("Modulo non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    try:
        campo = settori.aggiungi_campo_settore(
            settore_id=str(form.get("settore_id", "")),
            campo=str(form.get("campo", "")),
            etichetta=str(form.get("etichetta", "")),
            unita=str(form.get("unita", "")),
            obbligatorio=str(form.get("obbligatorio", "")) == "on",
            minimo=str(form.get("minimo", "")),
            massimo=str(form.get("massimo", "")),
            autore=_utente(request),
        )
        if STATO.get("hash_configurazione") and STATO.get("hash_configurazione") != dataset_store.hash_configurazione():
            STATO["configurazione_corrente"] = False
        audit.registra(_utente(request), "aggiunta_campo_settore", f"{form.get('settore_id')}:{campo}", esito="ok", ruolo=_ruolo(request))
        esito = f"Campo '{campo}' aggiunto. Il settore è passato in revisione e le analisi precedenti sono marcate come obsolete fino al ricalcolo."
        status_code = 200
    except (settori.ErroreRegistro, ValueError) as exc:
        audit.registra(_utente(request), "aggiunta_campo_settore", str(form.get("settore_id", "")), esito="rifiutato", ruolo=_ruolo(request))
        esito = str(exc)
        status_code = 400
    return templates.TemplateResponse(request, "settori.html", _context(
        request, settori=settori.lista_settori(includi_archiviati=True), parametri=settori.lista_parametri(), documenti=settori.lista_documenti(), esito=esito,
    ), status_code=status_code)


async def settori_formula_aggiorna(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("modifica_formule"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=5, max_part_size=16 * 1024)
    except Exception:
        return PlainTextResponse("Modulo non valido o troppo grande.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    settore_id = str(form.get("settore_id", ""))
    formula_raw = form.get("formula_json", "")
    if not isinstance(formula_raw, str) or len(formula_raw.encode("utf-8")) > 16_384:
        esito = "La formula supera il limite di 16 KiB."
        status_code = 400
    else:
        try:
            formula = json.loads(formula_raw, parse_constant=lambda valore: (_ for _ in ()).throw(ValueError(f"Costante JSON non valida: {valore}")))
            versione = settori.aggiorna_formula_settore(settore_id=settore_id, formula=formula, autore=_utente(request))
            if STATO.get("hash_configurazione") and STATO.get("hash_configurazione") != dataset_store.hash_configurazione():
                STATO["configurazione_corrente"] = False
            audit.registra(_utente(request), "aggiornamento_formula_settore", settore_id, esito="ok", ruolo=_ruolo(request))
            esito = f"Formula salvata nella versione {versione}. Il settore è in revisione: verifica unità, fonte e metodologia prima dell'uso operativo."
            status_code = 200
        except (json.JSONDecodeError, ValueError, OverflowError, RecursionError, settori.ErroreRegistro) as exc:
            audit.registra(_utente(request), "aggiornamento_formula_settore", settore_id, esito="rifiutato", ruolo=_ruolo(request))
            esito = str(exc) if str(exc) else "Formula JSON non valida."
            status_code = 400
        except Exception:
            audit.registra(_utente(request), "aggiornamento_formula_settore", settore_id, esito="errore_interno", ruolo=_ruolo(request))
            esito = "Formula non salvata per un errore interno. La configurazione precedente è rimasta attiva."
            status_code = 500
    return templates.TemplateResponse(request, "settori.html", _context(
        request, settori=settori.lista_settori(includi_archiviati=True), parametri=settori.lista_parametri(), documenti=settori.lista_documenti(), esito=esito,
    ), status_code=status_code)


async def settori_parametro_crea(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("configura_settori"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=12)
    except Exception:
        return PlainTextResponse("Modulo non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica il modulo.", status_code=400)
    try:
        parametro_id = settori.crea_parametro(
            nome=str(form.get("nome", "")), valore=str(form.get("valore", "")),
            unita=str(form.get("unita", "")), fonte=str(form.get("fonte", "")),
            ambito=str(form.get("ambito", "trasversale")),
            descrizione=str(form.get("descrizione", "")), autore=_utente(request),
        )
        if STATO.get("hash_configurazione") and STATO.get("hash_configurazione") != dataset_store.hash_configurazione():
            STATO["configurazione_corrente"] = False
        audit.registra(_utente(request), "creazione_parametro", parametro_id, esito="ok", ruolo=_ruolo(request))
        esito = f"Parametro '{parametro_id}' creato in stato da verificare. Non è stato approvato e non modifica automaticamente le formule esistenti."
        status_code = 200
    except (settori.ErroreRegistro, ValueError) as exc:
        audit.registra(_utente(request), "creazione_parametro", "", esito="rifiutato", ruolo=_ruolo(request))
        esito = str(exc)
        status_code = 400
    return templates.TemplateResponse(request, "settori.html", _context(
        request, settori=settori.lista_settori(includi_archiviati=True), parametri=settori.lista_parametri(), documenti=settori.lista_documenti(), esito=esito,
    ), status_code=status_code)


async def settori_crea(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("configura_settori"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=20)
    except Exception:
        return PlainTextResponse("Modulo non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica il modulo.", status_code=400)
    try:
        nuovo_id = settori.crea_settore_semplice(
            nome=str(form.get("nome", "")), descrizione=str(form.get("descrizione", "")),
            campo=str(form.get("campo", "")), etichetta_campo=str(form.get("etichetta_campo", "")),
            unita_campo=str(form.get("unita_campo", "")), metodo=str(form.get("metodo", "")),
            valore_coefficiente=str(form.get("valore_coefficiente", "")), nome_coefficiente=str(form.get("nome_coefficiente", "")),
            unita_coefficiente=str(form.get("unita_coefficiente", "")), fonte=str(form.get("fonte", "")),
            riferimento_url=str(form.get("riferimento_url", "")),
        )
        if STATO.get("hash_configurazione") and STATO.get("hash_configurazione") != dataset_store.hash_configurazione():
            STATO["configurazione_corrente"] = False
        audit.registra(_utente(request), "creazione_settore", nuovo_id, esito="ok", ruolo=_ruolo(request))
        return templates.TemplateResponse(request, "settori.html", _context(
            request, settori=settori.lista_settori(includi_archiviati=True), parametri=settori.lista_parametri(), documenti=settori.lista_documenti(),
            esito=f"Settore '{nuovo_id}' creato in stato sperimentale. Il coefficiente resta da verificare: il settore non è validato per decisioni operative.",
        ))
    except (settori.ErroreRegistro, ValueError) as exc:
        audit.registra(_utente(request), "creazione_settore", "", esito="rifiutato")
        return templates.TemplateResponse(request, "settori.html", _context(
            request, settori=settori.lista_settori(includi_archiviati=True), parametri=settori.lista_parametri(), documenti=settori.lista_documenti(), esito=str(exc),
        ), status_code=400)


def _dati_relazioni():
    """Prepara nodi selezionabili e nomi leggibili per le relazioni metodologiche."""
    nodi = []
    etichette = {}
    for settore in settori.lista_settori(includi_archiviati=True):
        key = ("settore", settore["id"])
        label = f"Settore · {settore.get('nome', settore['id'])} [{settore['id']}]"
        nodi.append({"value": f"{key[0]}:{key[1]}", "label": label})
        etichette[key] = label
    for parametro in settori.lista_parametri():
        key = ("parametro", parametro["id"])
        label = f"Parametro · {parametro.get('nome', parametro['id'])} [{parametro['id']}]"
        nodi.append({"value": f"{key[0]}:{key[1]}", "label": label})
        etichette[key] = label
    for doc in settori.lista_documenti():
        key = ("documento", doc["id"])
        label = f"Documento · {doc.get('titolo', doc['id'])} [{doc['id']}]"
        nodi.append({"value": f"{key[0]}:{key[1]}", "label": label})
        etichette[key] = label
    nodi.sort(key=lambda n: n["label"].casefold())
    relazioni = []
    for relazione in settori.lista_relazioni():
        r = dict(relazione)
        r["sorgente_label"] = etichette.get((r.get("sorgente_tipo"), r.get("sorgente_id")), "Elemento non più disponibile")
        r["destinazione_label"] = etichette.get((r.get("destinazione_tipo"), r.get("destinazione_id")), "Elemento non più disponibile")
        relazioni.append(r)
    relazioni.sort(key=lambda r: r.get("creato_il", ""), reverse=True)
    return nodi, relazioni


def _contesto_documenti(request, esito=None):
    nodi, relazioni = _dati_relazioni()
    return _context(
        request, documenti=settori.lista_documenti(), settori=settori.lista_settori(),
        parametri=settori.lista_parametri(), nodi_relazione=nodi, relazioni=relazioni,
        tipi_relazione=[
            ("documenta", "documenta"), ("supporta", "supporta"), ("definisce", "definisce"),
            ("applicabile_a", "è applicabile a"), ("deriva_da", "deriva da"),
            ("aggiorna", "aggiorna"), ("correla_con", "è correlato a"),
            ("contraddice", "contraddice"), ("sostituisce", "sostituisce"), ("integra", "integra"),
        ], esito=esito,
    )


async def documenti_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("consulta_documenti"))
    if denied:
        return denied
    return templates.TemplateResponse(request, "documenti.html", _contesto_documenti(request))


async def documenti_carica(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("gestione_documenti"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=1, max_fields=15, max_part_size=64 * 1024)
    except Exception:
        return PlainTextResponse("Modulo documentale non valido o troppo complesso.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica il modulo.", status_code=400)
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", ""):
        return templates.TemplateResponse(request, "documenti.html", _contesto_documenti(request, "Seleziona un documento da registrare."), status_code=400)
    filename = str(upload.filename).replace("\\", "/").split("/")[-1][:180]
    contenuto = await upload.read(documenti.MAX_DOCUMENT_BYTES + 1)
    await upload.close()
    try:
        doc = documenti.aggiungi_documento(
            nome_file=filename, contenuto=contenuto, titolo=str(form.get("titolo", "")),
            descrizione=str(form.get("descrizione", "")), settore_id=str(form.get("settore", "")),
            parametro_id=str(form.get("parametro", "")), url_fonte=str(form.get("url_fonte", "")),
            utente=_utente(request),
        )
        audit.registra(_utente(request), "registrazione_documento", doc["id"], esito="ok", ruolo=_ruolo(request))
        esito = f"Documento registrato. SHA-256: {doc['sha256']}. Il contenuto resta da verificare; non è stata eseguita estrazione automatica."
        status_code = 200
    except (documenti.ErroreDocumento, settori.ErroreRegistro, ValueError) as exc:
        audit.registra(_utente(request), "registrazione_documento", filename, esito="rifiutato")
        esito = str(exc)
        status_code = 400
    except Exception:
        audit.registra(_utente(request), "registrazione_documento", filename, esito="errore_interno")
        esito = "Documento non registrato per un errore interno. Nessuna configurazione del motore è stata approvata."
        status_code = 500
    return templates.TemplateResponse(request, "documenti.html", _contesto_documenti(request, esito), status_code=status_code)


async def relazioni_crea(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("gestione_documenti"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=10)
    except Exception:
        return PlainTextResponse("Modulo di relazione non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica il modulo.", status_code=400)

    def parse_entita(valore):
        if not isinstance(valore, str) or ":" not in valore:
            raise settori.ErroreRegistro("Seleziona due elementi validi da collegare.")
        tipo, identificativo = valore.split(":", 1)
        return tipo, identificativo

    try:
        sorgente_tipo, sorgente_id = parse_entita(form.get("sorgente", ""))
        destinazione_tipo, destinazione_id = parse_entita(form.get("destinazione", ""))
        relazione = settori.registra_relazione(
            sorgente_tipo=sorgente_tipo, sorgente_id=sorgente_id,
            tipo=str(form.get("tipo", "")),
            destinazione_tipo=destinazione_tipo, destinazione_id=destinazione_id,
            descrizione=str(form.get("descrizione", "")), utente=_utente(request),
        )
        audit.registra(_utente(request), "creazione_relazione", relazione["id"], esito="ok", ruolo=_ruolo(request))
        esito = "Relazione registrata in stato da verificare. Non modifica automaticamente coefficienti o regole del motore."
        status_code = 200
    except (settori.ErroreRegistro, ValueError) as exc:
        audit.registra(_utente(request), "creazione_relazione", "", esito="rifiutato", ruolo=_ruolo(request))
        esito = str(exc)
        status_code = 400
    return templates.TemplateResponse(request, "documenti.html", _contesto_documenti(request, esito), status_code=status_code)


async def documenti_download(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("consulta_documenti"))
    if denied:
        return denied
    doc_id = request.path_params["doc_id"]
    doc = settori.ottieni_documento(doc_id)
    percorso = documenti.percorso_documento(doc) if doc else None
    audit.registra(_utente(request), "download_documento", doc_id, esito="ok" if percorso else "non_trovato")
    if percorso is None:
        return PlainTextResponse("Documento non trovato.", status_code=404)
    return FileResponse(
        str(percorso), media_type="application/octet-stream", filename=f"{doc_id}{percorso.suffix}",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def prestazioni_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("audit"))
    if denied:
        return denied
    righe = sorted(({"percorso": k, **v, "medio_s": v["totale_s"] / v["richieste"]} for k, v in PRESTAZIONI.items()),
                   key=lambda r: -r["massimo_s"])
    return templates.TemplateResponse(request, "prestazioni.html", _context(request, righe=righe, soglia=SOGLIA_LENTA_SECONDI))


async def salute(request):
    return PlainTextResponse("ok")



async def osint_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("osint_consulta"))
    if denied:
        return denied
    audit.registra(_utente(request), "consultazione_osint", "", esito="ok")
    return templates.TemplateResponse(request, "osint.html", _context(request,
        osservazioni=osint.elenco(100), domini=osint.domini_autorizzati(),
        esito=request.query_params.get("esito", "")))


async def osint_acquisisci(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("osint_acquisisci"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=8)
    except Exception:
        return PlainTextResponse("Modulo OSINT non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    url = str(form.get("url", "")).strip()
    motivazione = str(form.get("motivazione", "")).strip()
    try:
        osservazione = await asyncio.to_thread(osint.acquisisci, url, utente=_utente(request), motivazione=motivazione)
        audit.registra(_utente(request), "acquisizione_osint", osservazione["id"], esito="ok",
                       host=osservazione["host"], sha256=osservazione["sha256"])
        esito = f"Pagina acquisita e registrata come da verificare. Hash SHA-256: {osservazione['sha256']}. Nessuna inferenza di illecito è stata eseguita."
        status = 200
    except osint.ErroreOSINT as exc:
        audit.registra(_utente(request), "acquisizione_osint", url[:180], esito="rifiutato", motivo=str(exc)[:160])
        esito, status = str(exc), 400
    except Exception:
        audit.registra(_utente(request), "acquisizione_osint", url[:180], esito="errore_interno")
        esito, status = "Acquisizione non completata per un errore interno.", 500
    return templates.TemplateResponse(request, "osint.html", _context(request,
        osservazioni=osint.elenco(100), domini=osint.domini_autorizzati(), esito=esito), status_code=status)


async def osint_revisiona(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("osint_revisiona"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=8)
    except Exception:
        return PlainTextResponse("Modulo di revisione non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    ident = str(form.get("id", "")); stato = str(form.get("stato", "")); nota = str(form.get("nota", ""))
    try:
        osint.rivedi(ident, stato, _utente(request), nota)
        audit.registra(_utente(request), "revisione_osint", ident, esito="ok", stato=stato)
        esito = "Revisione registrata. La fonte resta un elemento documentale, non una conclusione automatica."
        code = 200
    except osint.ErroreOSINT as exc:
        audit.registra(_utente(request), "revisione_osint", ident, esito="rifiutato", motivo=str(exc)[:160])
        esito, code = str(exc), 400
    return templates.TemplateResponse(request, "osint.html", _context(request,
        osservazioni=osint.elenco(100), domini=osint.domini_autorizzati(), esito=esito), status_code=code)


def _svg_grafo(aziende, relazioni) -> str:
    import html as html_escape
    by_id = {str(a.get("id")): a for a in aziende if a.get("id") is not None}
    relazioni = relazioni[:80]
    ids = []
    for r in relazioni:
        for k in ("origine_id", "destinazione_id"):
            v = str(r[k])
            if v in by_id and v not in ids: ids.append(v)
    ids = ids[:30]
    if not ids:
        return '<svg viewBox="0 0 960 120" role="img" aria-label="Grafo relazioni aziendali vuoto"><text x="24" y="55" fill="#c1c8d2" font-size="16">Nessuna relazione aziendale documentata nel grafo.</text></svg>'
    import math
    w, h, cx, cy, radius = 960, 560, 480, 280, 205
    pos = {}
    for i, ident in enumerate(ids):
        angle = -math.pi / 2 + 2 * math.pi * i / len(ids)
        pos[ident] = (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
    parti = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Grafo delle relazioni aziendali documentate">']
    for r in relazioni:
        a, b = str(r["origine_id"]), str(r["destinazione_id"])
        if a not in pos or b not in pos: continue
        x1, y1 = pos[a]; x2, y2 = pos[b]
        # Etichetta arco non codificata per colore: stato leggibile in tabella.
        parti.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#8a96a8" stroke-width="2" opacity="0.72"/>')
    for ident in ids:
        x, y = pos[ident]
        az = by_id[ident]
        label = str(az.get("ragione_sociale") or ident)[:24]
        label = html_escape.escape(label, quote=True)
        parti.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="29" fill="#303b4d" stroke="#91baff" stroke-width="2"/>')
        parti.append(f'<text x="{x:.1f}" y="{y+45:.1f}" text-anchor="middle" fill="#f1f3f7" font-size="12">{label}</text>')
    parti.append('</svg>')
    return ''.join(parti)


async def grafo_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("grafo_consulta"))
    if denied:
        return denied
    alla_data = request.query_params.get("alla_data", "").strip()
    try:
        relazioni = grafo.elenco(500, includi_riservate=_ruolo(request) in sicurezza.ruoli_per("grafo_riservato"),
                                 alla_data=alla_data)
    except grafo.ErroreGrafo:
        relazioni, alla_data = grafo.elenco(500, includi_riservate=_ruolo(request) in sicurezza.ruoli_per("grafo_riservato")), ""
    aziende = STATO["aziende"]
    by_id = {str(a.get("id")): a for a in aziende if a.get("id") is not None}
    for r in relazioni:
        r["origine_nome"] = by_id.get(r["origine_id"], {}).get("ragione_sociale", r["origine_id"])
        r["destinazione_nome"] = by_id.get(r["destinazione_id"], {}).get("ragione_sociale", r["destinazione_id"])
    audit.registra(_utente(request), "consultazione_grafo_aziende", "", esito="ok")
    suggerimenti = grafo.suggerimenti_da_record(aziende)
    return templates.TemplateResponse(request, "grafo.html", _context(request,
        aziende=sorted(aziende, key=lambda a: str(a.get("ragione_sociale") or a.get("id", "")).casefold()),
        relazioni=relazioni, suggerimenti=suggerimenti, tipi_relazione=grafo.TIPI.items(), svg_grafo=_svg_grafo(aziende, relazioni),
        esito=request.query_params.get("esito", ""), dataset_hash=STATO.get("hash_dataset") or "", alla_data=alla_data,
        acquisizioni=_acquisizioni_recenti()))


async def grafo_aggiungi(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("grafo_aggiungi"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=16)
    except Exception:
        return PlainTextResponse("Modulo grafo non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    origine = str(form.get("origine_id", "")); destinazione = str(form.get("destinazione_id", ""))
    ids = {str(a.get("id")) for a in STATO["aziende"] if a.get("id") is not None}
    try:
        if origine not in ids or destinazione not in ids:
            raise grafo.ErroreGrafo("Le due aziende devono appartenere al lotto attivo.")
        doc_id = str(form.get("riferimento_documento", "")).strip()
        if doc_id and settori.ottieni_documento(doc_id) is None:
            raise grafo.ErroreGrafo("Il riferimento indicato non corrisponde a un documento registrato.")
        edge = grafo.aggiungi_relazione(origine_id=origine, destinazione_id=destinazione,
            tipo=str(form.get("tipo", "")), evidenza=str(form.get("evidenza", "")),
            url_fonte=str(form.get("url_fonte", "")), riferimento_documento=doc_id,
            dataset_hash=STATO.get("hash_dataset") or "", utente=_utente(request),
            valido_dal=str(form.get("valido_dal", "")), valido_al=str(form.get("valido_al", "")),
            riservatezza=str(form.get("riservatezza", "pubblica")))
        audit.registra(_utente(request), "creazione_relazione_azienda", edge["id"], esito="ok", tipo=edge["tipo"], sha256= edge["hash_evidenza"])
        esito = "Relazione registrata come da verificare; non costituisce prova di illecito."
        code = 200
    except grafo.ErroreGrafo as exc:
        audit.registra(_utente(request), "creazione_relazione_azienda", f"{origine}:{destinazione}", esito="rifiutato", motivo=str(exc)[:160])
        esito, code = str(exc), 400
    relazioni = grafo.elenco(500)
    by_id = {str(a.get("id")): a for a in STATO["aziende"] if a.get("id") is not None}
    for r in relazioni:
        r["origine_nome"] = by_id.get(r["origine_id"], {}).get("ragione_sociale", r["origine_id"])
        r["destinazione_nome"] = by_id.get(r["destinazione_id"], {}).get("ragione_sociale", r["destinazione_id"])
    return templates.TemplateResponse(request, "grafo.html", _context(request,
        aziende=sorted(STATO["aziende"], key=lambda a: str(a.get("ragione_sociale") or a.get("id", "")).casefold()),
        relazioni=relazioni, suggerimenti=grafo.suggerimenti_da_record(STATO["aziende"]),
        tipi_relazione=grafo.TIPI.items(), svg_grafo=_svg_grafo(STATO["aziende"], relazioni),
        esito=esito, dataset_hash=STATO.get("hash_dataset") or ""), status_code=code)


async def grafo_revisiona(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("grafo_revisiona"))
    if denied:
        return denied
    try:
        form = await request.form(max_files=0, max_fields=8)
    except Exception:
        return PlainTextResponse("Modulo revisione non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    ident = str(form.get("id", "")); stato = str(form.get("stato", "")); nota = str(form.get("nota", ""))
    try:
        grafo.revisiona(ident, stato=stato, nota=nota, revisore=_utente(request))
        audit.registra(_utente(request), "revisione_relazione_azienda", ident, esito="ok", stato=stato)
        esito, code = "Revisione registrata.", 200
    except grafo.ErroreGrafo as exc:
        esito, code = str(exc), 400
    relazioni = grafo.elenco(500)
    by_id = {str(a.get("id")): a for a in STATO["aziende"] if a.get("id") is not None}
    for r in relazioni:
        r["origine_nome"] = by_id.get(r["origine_id"], {}).get("ragione_sociale", r["origine_id"])
        r["destinazione_nome"] = by_id.get(r["destinazione_id"], {}).get("ragione_sociale", r["destinazione_id"])
    return templates.TemplateResponse(request, "grafo.html", _context(request,
        aziende=sorted(STATO["aziende"], key=lambda a: str(a.get("ragione_sociale") or a.get("id", "")).casefold()),
        relazioni=relazioni, suggerimenti=grafo.suggerimenti_da_record(STATO["aziende"]),
        tipi_relazione=grafo.TIPI.items(), svg_grafo=_svg_grafo(STATO["aziende"], relazioni),
        esito=esito, dataset_hash=STATO.get("hash_dataset") or ""), status_code=code)


# ---------------------------------------------------------------------------
# Esecuzioni del motore, esportazione, pratiche (sezioni 10, 11, 18, 22)
# ---------------------------------------------------------------------------

async def _form_csrf(request, max_fields: int = 12):
    try:
        form = await request.form(max_files=0, max_fields=max_fields, max_part_size=16 * 1024)
    except Exception:
        return None, PlainTextResponse("Modulo non valido.", status_code=400)
    if not _csrf_valido(request, form):
        return None, PlainTextResponse("Richiesta non valida. Ricarica la pagina.", status_code=400)
    return form, None


async def esecuzioni_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("esecuzioni"))
    if denied:
        return denied
    audit.registra(_utente(request), "consultazione_esecuzioni", "", esito="ok")
    return templates.TemplateResponse(request, "esecuzioni.html", _context(
        request, esecuzioni=db_operativo.elenco_esecuzioni(100), corrente=STATO.get("esecuzione_id")))


async def esporta_csv(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("esporta_dati"))
    if denied:
        return denied
    bloccato = _blocco_autorizzazione(request, "esportazione_csv")
    if bloccato:
        return bloccato
    try:
        contenuto = csv_import.esporta_csv_bytes(STATO["aziende"])
    except ValueError as exc:
        audit.registra(_utente(request), "esportazione_csv", "", esito="rifiutato", motivo=str(exc)[:150])
        return PlainTextResponse(str(exc), status_code=400)
    audit.registra(_utente(request), "esportazione_csv", STATO["origine"][:200], esito="ok",
                   numero_record=len(STATO["aziende"]), sha256=hashlib.sha256(contenuto).hexdigest())
    return Response(content=contenuto, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="emersione-esportazione.csv"', "Cache-Control": "no-store"})


async def pratiche_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("pratiche_consulta"))
    if denied:
        return denied
    audit.registra(_utente(request), "consultazione_pratiche", "", esito="ok")
    return templates.TemplateResponse(request, "pratiche.html", _context(request, pratiche=pratiche.elenco(200), esito=None))


async def pratiche_crea(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("pratiche_gestisci"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    bloccato = _blocco_autorizzazione(request, "creazione_pratica")
    if bloccato:
        return bloccato
    azienda_id = str(form.get("azienda_id", ""))[:100]
    if not any(a.get("id") == azienda_id for a in STATO["aziende"]):
        return PlainTextResponse("Azienda non presente nel lotto attivo.", status_code=404)
    try:
        esecuzione_id = _assicura_esecuzione(_utente(request))
        pratica_id = pratiche.crea(azienda_id=azienda_id, esecuzione_id=esecuzione_id,
                                   finalita=str(form.get("finalita", "")), ambito=str(form.get("ambito", "")),
                                   utente=_utente(request))
    except pratiche.ErrorePratica as exc:
        audit.registra(_utente(request), "creazione_pratica", azienda_id, esito="rifiutato", motivo=str(exc)[:150])
        return templates.TemplateResponse(request, "pratiche.html", _context(request, pratiche=pratiche.elenco(200), esito=str(exc)), status_code=400)
    audit.registra(_utente(request), "creazione_pratica", azienda_id, esito="ok", request_id=pratica_id, ruolo=_ruolo(request))
    return RedirectResponse(f"/pratiche/{pratica_id}", status_code=303)


async def pratica_dettaglio(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("pratiche_consulta"))
    if denied:
        return denied
    pratica = pratiche.ottieni(request.path_params["pratica_id"])
    audit.registra(_utente(request), "consultazione_pratica", request.path_params["pratica_id"][:40], esito="ok" if pratica else "non_trovato")
    if pratica is None:
        return PlainTextResponse("Pratica non trovata.", status_code=404)
    storico = db_operativo.risultato_storico(pratica["esecuzione_id"], pratica["azienda_id"]) if pratica.get("esecuzione_id") else None
    return templates.TemplateResponse(request, "pratica.html", _context(
        request, pratica=pratica, analisi_storica=storico, stati=pratiche.STATI, esito=None))


async def pratica_evento(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("pratiche_gestisci"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    pratica_id = request.path_params["pratica_id"]
    nuovo_stato = str(form.get("nuovo_stato", "")) or None
    try:
        pratiche.aggiungi_evento(pratica_id, utente=_utente(request), nota=str(form.get("nota", "")), nuovo_stato=nuovo_stato)
    except pratiche.ErrorePratica as exc:
        audit.registra(_utente(request), "aggiornamento_pratica", pratica_id[:40], esito="rifiutato", motivo=str(exc)[:150])
        return PlainTextResponse(str(exc), status_code=400)
    audit.registra(_utente(request), "aggiornamento_pratica", pratica_id[:40], esito="ok", stato=nuovo_stato or "nota")
    return RedirectResponse(f"/pratiche/{pratica_id}", status_code=303)


async def report_verifica(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("pratiche_consulta") | sicurezza.ruoli_per("genera_report"))
    if denied:
        return denied
    impronta = request.query_params.get("sha256", "").strip().lower()
    risultato = None
    if impronta:
        import re as _re
        if not _re.fullmatch(r"[0-9a-f]{64}", impronta):
            return templates.TemplateResponse(request, "verifica_report.html", _context(request, impronta=impronta, risultato=None, errore="Impronta SHA-256 non valida."), status_code=400)
        risultato = db_operativo.verifica_report(impronta)
        audit.registra(_utente(request), "verifica_report", impronta[:16], esito="trovato" if risultato else "non_trovato")
    return templates.TemplateResponse(request, "verifica_report.html", _context(request, impronta=impronta, risultato=risultato, errore=None))


# ---------------------------------------------------------------------------
# Ciclo di vita dei settori, collaudo, versioni, dipendenze (sezione 30)
# ---------------------------------------------------------------------------

def _contesto_settore(request, settore_id: str, **extra):
    cfg = settori.configurazione_settore(settore_id)
    return _context(
        request, sid=settore_id, settore=cfg,
        collaudo=collaudo_settori.ultimo_collaudo(settore_id),
        hash_attuale=collaudo_settori.hash_settore(settore_id),
        transizioni=ciclo_settori.transizioni_disponibili(settore_id, utente=_utente(request), ruolo=_ruolo(request)),
        storico_transizioni=ciclo_settori.storico_transizioni(settore_id),
        versioni=ciclo_settori.storico_versioni_settore(settore_id, 50),
        impatto=dipendenze.impatto_settore(settore_id),
        descrizione_stati=ciclo_settori.DESCRIZIONE_STATI,
        documenti=settori.lista_documenti(),
        **extra,
    )


async def settore_gestione(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("consulta_settori"))
    if denied:
        return denied
    sid = request.path_params["settore_id"]
    if settori.configurazione_settore(sid) is None:
        return PlainTextResponse("Settore non trovato.", status_code=404)
    differenze = None
    a, b = request.query_params.get("a"), request.query_params.get("b")
    if a and b and a.isdigit() and b.isdigit():
        try:
            differenze = ciclo_settori.confronta_versioni(sid, int(a), int(b))
        except settori.ErroreRegistro as exc:
            differenze = [{"percorso": "errore", "prima": str(exc), "dopo": ""}]
    audit.registra(_utente(request), "consultazione_settore", sid, esito="ok")
    return templates.TemplateResponse(request, "settore_gestione.html", _contesto_settore(request, sid, differenze=differenze, esito=None))


async def settore_collaudo(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("settori_collaudo"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    sid = request.path_params["settore_id"]
    if settori.configurazione_settore(sid) is None:
        return PlainTextResponse("Settore non trovato.", status_code=404)
    try:
        risultato = await asyncio.to_thread(collaudo_settori.collauda, sid, utente=_utente(request))
    except Exception:
        audit.registra(_utente(request), "collaudo_settore", sid, esito="errore_interno")
        return PlainTextResponse("Collaudo non completato per un errore interno.", status_code=500)
    audit.registra(_utente(request), "collaudo_settore", sid, esito="superato" if risultato["superato"] else "fallito",
                   sha256=risultato["hash_settore"], ruolo=_ruolo(request))
    return templates.TemplateResponse(request, "settore_gestione.html", _contesto_settore(
        request, sid, differenze=None, esito="Collaudo superato." if risultato["superato"] else "Collaudo NON superato: vedere i controlli falliti."))


async def settore_transizione(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("settori_transizione"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    sid = request.path_params["settore_id"]
    a_stato = str(form.get("a_stato", ""))
    try:
        esito_t = ciclo_settori.esegui_transizione(sid, a_stato, utente=_utente(request), ruolo=_ruolo(request),
                                                   motivazione=str(form.get("motivazione", ""))[:2000],
                                                   evidenza=str(form.get("evidenza", ""))[:100])
    except (ciclo_settori.ErroreTransizione, settori.ErroreRegistro) as exc:
        audit.registra(_utente(request), "transizione_settore", sid, esito="rifiutato", stato=a_stato, motivo=str(exc)[:180], ruolo=_ruolo(request))
        return templates.TemplateResponse(request, "settore_gestione.html", _contesto_settore(request, sid, differenze=None, esito=str(exc)), status_code=400)
    if STATO.get("hash_configurazione") and STATO.get("hash_configurazione") != dataset_store.hash_configurazione():
        STATO["configurazione_corrente"] = False
    audit.registra(_utente(request), "transizione_settore", sid, esito="ok", stato=f"{esito_t['da_stato']}->{a_stato}",
                   sha256=esito_t["hash_settore"], ruolo=_ruolo(request))
    return RedirectResponse(f"/settori/{sid}/gestione", status_code=303)


async def settore_ripristina_versione(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("settori_ripristino"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    sid = request.path_params["settore_id"]
    progressivo = str(form.get("progressivo", ""))
    try:
        if not progressivo.isdigit():
            raise settori.ErroreRegistro("Versione non valida.")
        versione = ciclo_settori.ripristina_versione(sid, int(progressivo), utente=_utente(request), ruolo=_ruolo(request),
                                                     motivazione=str(form.get("motivazione", "")))
    except (ciclo_settori.ErroreTransizione, settori.ErroreRegistro) as exc:
        audit.registra(_utente(request), "ripristino_versione_settore", sid, esito="rifiutato", motivo=str(exc)[:180])
        return templates.TemplateResponse(request, "settore_gestione.html", _contesto_settore(request, sid, differenze=None, esito=str(exc)), status_code=400)
    if STATO.get("hash_configurazione") and STATO.get("hash_configurazione") != dataset_store.hash_configurazione():
        STATO["configurazione_corrente"] = False
    audit.registra(_utente(request), "ripristino_versione_settore", sid, esito="ok", stato=f"versione {versione} da storico {progressivo}")
    return RedirectResponse(f"/settori/{sid}/gestione", status_code=303)


async def dipendenze_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("dipendenze"))
    if denied:
        return denied
    impatto = None
    tipo, ident = request.query_params.get("tipo", ""), request.query_params.get("id", "")
    try:
        if tipo == "parametro" and ident:
            impatto = dipendenze.impatto_parametro(ident)
        elif tipo == "documento" and ident:
            impatto = dipendenze.impatto_documento(ident)
        elif tipo == "settore" and ident:
            impatto = dipendenze.impatto_settore(ident)
    except settori.ErroreRegistro as exc:
        impatto = {"errore": str(exc)}
    audit.registra(_utente(request), "consultazione_dipendenze", f"{tipo}:{ident}"[:120], esito="ok")
    return templates.TemplateResponse(request, "dipendenze.html", _context(
        request, mappa=dipendenze.mappa_completa(), impatto=impatto, parametri=settori.lista_parametri(),
        versioni=versioni_registro.elenco(30)))


async def audit_esporta(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("esporta_audit"))
    if denied:
        return denied
    import csv as _csv
    import io as _io
    buffer = _io.StringIO()
    writer = _csv.writer(buffer, lineterminator="\n")
    integrita = audit.verifica_integrita()
    writer.writerow(["# integrita", json.dumps(integrita, ensure_ascii=False)])
    writer.writerow(["quando", "utente", "azione", "dettaglio", "metadati"])
    for voce in reversed(audit.leggi(100_000)):
        metadati = {k: v for k, v in voce.items() if k not in {"quando", "utente", "azione", "dettaglio"}}
        writer.writerow([csv_import._proteggi_formula_csv(str(voce.get(k, ""))) for k in ("quando", "utente", "azione", "dettaglio")]
                        + [csv_import._proteggi_formula_csv(json.dumps(metadati, ensure_ascii=False))])
    contenuto = buffer.getvalue().encode("utf-8")
    audit.registra(_utente(request), "esportazione_audit", "", esito="ok", sha256=hashlib.sha256(contenuto).hexdigest(), ruolo=_ruolo(request))
    return Response(content=contenuto, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="emersione-audit.csv"', "Cache-Control": "no-store"})



# ---------------------------------------------------------------------------
# Scoperta dataset, collegamenti ai parametri, OSINT esteso, suggerimenti OCDS
# ---------------------------------------------------------------------------

def _acquisizioni_recenti():
    try:
        return fonti_store.elenco(50)
    except Exception:
        return []


async def catalogo_view(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("catalogo_fonti"))
    if denied:
        return denied
    testo = request.query_params.get("q", "")[:100]
    fonte = request.query_params.get("fonte", "")
    if fonte not in {"", "istat", "anac"}:
        fonte = ""
    voci = scoperta.cerca_catalogo(testo, fonte, 200)
    return templates.TemplateResponse(request, "catalogo.html", _context(
        request, voci=voci, q=testo, fonte=fonte, connettori=scoperta.stato_connettori(),
        mappature=fonti_mapping.elenco(100), proposte=collegamento_semantico.elenco(),
        suggerimenti=collegamento_semantico.suggerisci_parametri(testo.split()) if testo else [], esito=request.query_params.get("esito", "")))


async def catalogo_scopri(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("acquisisci_fonti"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    fonte = str(form.get("fonte", ""))
    try:
        if fonte == "istat":
            esito = await asyncio.to_thread(scoperta.scopri_istat)
        elif fonte == "anac":
            esito = await asyncio.to_thread(scoperta.scopri_anac, str(form.get("q", "")))
        else:
            raise scoperta.ErroreScoperta("Fonte non supportata.")
    except (scoperta.ErroreScoperta, fonti_live.ErroreAcquisizione) as exc:
        audit.registra(_utente(request), "scoperta_dataset", fonte, esito="rifiutato", motivo=str(exc)[:180])
        return RedirectResponse("/fonti/catalogo?esito=" + quote(str(exc)[:200]), status_code=303)
    audit.registra(_utente(request), "scoperta_dataset", fonte, esito="ok", numero_record=esito["voci"], sha256=esito["sha256"])
    return RedirectResponse("/fonti/catalogo?esito=" + quote(f"Catalogo aggiornato: {esito['voci']} voci da {fonte}."), status_code=303)


async def proposta_crea(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("proponi_collegamenti"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    try:
        esito = collegamento_semantico.proponi(
            mapping_id=str(form.get("mapping_id", "")), parametro_id=str(form.get("parametro_id", "")),
            statistica=str(form.get("statistica", "")), utente=_utente(request),
            periodo=str(form.get("periodo", ""))[:100], territorio=str(form.get("territorio", ""))[:100],
            categoria=str(form.get("categoria", ""))[:100])
    except (collegamento_semantico.ErroreCollegamento, fonti_mapping.ErroreMappatura) as exc:
        audit.registra(_utente(request), "proposta_parametro", str(form.get("parametro_id", ""))[:80], esito="rifiutato", motivo=str(exc)[:180])
        return RedirectResponse("/fonti/catalogo?esito=" + quote(str(exc)[:200]), status_code=303)
    audit.registra(_utente(request), "proposta_parametro", str(form.get("parametro_id", ""))[:80], esito="ok", request_id=esito["id"])
    return RedirectResponse("/fonti/catalogo?esito=" + quote(f"Proposta {esito['id']} registrata: valore {esito['valore_proposto']:g}, in attesa del revisore."), status_code=303)


async def proposta_decidi(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("decidi_collegamenti"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    proposta_id = str(form.get("proposta_id", ""))[:40]
    try:
        esito = collegamento_semantico.decidi(proposta_id, decisione=str(form.get("decisione", "")), utente=_utente(request),
                                              ruolo=_ruolo(request), nota=str(form.get("nota", ""))[:1000])
    except (collegamento_semantico.ErroreCollegamento, settori.ErroreRegistro) as exc:
        audit.registra(_utente(request), "decisione_proposta_parametro", proposta_id, esito="rifiutato", motivo=str(exc)[:180])
        return RedirectResponse("/fonti/catalogo?esito=" + quote(str(exc)[:200]), status_code=303)
    if STATO.get("hash_configurazione") and STATO.get("hash_configurazione") != dataset_store.hash_configurazione():
        STATO["configurazione_corrente"] = False
    audit.registra(_utente(request), "decisione_proposta_parametro", proposta_id, esito=esito["decisione"], ruolo=_ruolo(request))
    return RedirectResponse("/fonti/catalogo?esito=" + quote(f"Proposta {proposta_id}: {esito['decisione']}."), status_code=303)


async def osint_raccolta(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("osint_acquisisci"))
    if denied:
        return denied
    form, errore = await _form_csrf(request)
    if errore:
        return errore
    try:
        esito = await asyncio.to_thread(
            osint_esteso.raccogli, str(form.get("url", "")), utente=_utente(request),
            motivazione=str(form.get("motivazione", "")), max_pagine=int(str(form.get("max_pagine", "5")) or 5),
            profondita=int(str(form.get("profondita", "1")) or 1))
    except (osint.ErroreOSINT, ValueError) as exc:
        audit.registra(_utente(request), "osint_raccolta", "", esito="rifiutato", motivo=str(exc)[:180])
        return RedirectResponse("/osint?esito=" + quote(str(exc)[:200]), status_code=303)
    audit.registra(_utente(request), "osint_raccolta", esito["host"], esito="ok", numero_record=len(esito["pagine_salvate"]),
                   request_id=esito["raccolta_id"])
    return RedirectResponse("/osint?esito=" + quote(f"Raccolta {esito['raccolta_id']}: {len(esito['pagine_salvate'])} pagine salvate, {len(esito['saltate'])} saltate."), status_code=303)


async def osint_verifica(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("osint_consulta"))
    if denied:
        return denied
    affermazione = request.query_params.get("affermazione", "")[:300]
    try:
        risultato = osint_esteso.verifica_incrociata(affermazione)
        code = 200
    except osint.ErroreOSINT as exc:
        risultato, code = {"errore": str(exc)}, 400
    audit.registra(_utente(request), "osint_verifica_incrociata", affermazione[:100], esito="ok" if code == 200 else "rifiutato")
    return templates.TemplateResponse(request, "osint_verifica.html", _context(request, affermazione=affermazione, r=risultato), status_code=code)


async def grafo_suggerimenti_ocds(request):
    denied = _accesso_negato(request, sicurezza.ruoli_per("grafo_consulta"))
    if denied:
        return denied
    fetch_id = request.query_params.get("fetch_id", "")
    trovato = fonti_store.contenuto(fetch_id) if fetch_id else None
    if trovato is None:
        return PlainTextResponse("Acquisizione non trovata.", status_code=404)
    meta, contenuto = trovato
    try:
        suggerimenti = grafo.suggerimenti_da_ocds(contenuto, STATO["aziende"], url_fonte=str(meta.get("url", "")))
        errore = None
    except (grafo.ErroreGrafo, UnicodeDecodeError, ValueError) as exc:
        suggerimenti, errore = [], f"Payload non interpretabile come OCDS: {str(exc)[:150]}"
    audit.registra(_utente(request), "grafo_suggerimenti_ocds", fetch_id[:40], esito="ok" if errore is None else "rifiutato",
                   numero_record=len(suggerimenti))
    return templates.TemplateResponse(request, "grafo_ocds.html", _context(request, suggerimenti=suggerimenti, errore=errore, meta=meta))


routes = [
    Route("/login", login_form, methods=["GET"]),
    Route("/login", login_post, methods=["POST"]),
    Route("/logout", logout, methods=["POST"]),
    Route("/", home),
    Route("/azienda/{az_id}/report.pdf", report_azienda, methods=["GET"]),
    Route("/azienda/{az_id}", dettaglio),
    Route("/fonti", fonti),
    Route("/fonti/acquisisci", fonti_acquisisci, methods=["POST"]),
    Route("/fonti/mappatura/crea", fonti_mappatura_crea, methods=["POST"]),
    Route("/fonti/mappatura/revisiona", fonti_mappatura_revisiona, methods=["POST"]),
    Route("/fonti/mappature/{mapping_id}", fonti_mappatura_dettaglio, methods=["GET"]),
    Route("/fonti/{fetch_id}/mappatura", fonti_mappatura_view, methods=["GET"]),
    Route("/fonti/{fetch_id}/scarica", fonti_scarica, methods=["GET"]),
    Route("/carica", carica_form, methods=["GET"]),
    Route("/carica", carica_post, methods=["POST"]),
    Route("/carica/conferma", carica_conferma, methods=["POST"]),
    Route("/carica/annulla", carica_annulla, methods=["POST"]),
    Route("/lotto/revoca", lotto_revoca, methods=["POST"]),
    Route("/ripristina", ripristina, methods=["POST"]),
    Route("/ricalcola", ricalcola, methods=["POST"]),
    Route("/valutazione", valutazione),
    Route("/audit", audit_view),
    Route("/settori", settori_view, methods=["GET"]),
    Route("/settori/crea", settori_crea, methods=["POST"]),
    Route("/settori/parametri/aggiorna", settori_parametro_aggiorna, methods=["POST"]),
    Route("/settori/campi/aggiungi", settori_campo_aggiungi, methods=["POST"]),
    Route("/settori/formula", settori_formula_aggiorna, methods=["POST"]),
    Route("/settori/parametri/crea", settori_parametro_crea, methods=["POST"]),
    Route("/documenti", documenti_view, methods=["GET"]),
    Route("/relazioni/crea", relazioni_crea, methods=["POST"]),
    Route("/documenti/carica", documenti_carica, methods=["POST"]),
    Route("/documenti/{doc_id}/download", documenti_download, methods=["GET"]),
    Route("/osint", osint_view),
    Route("/osint/acquisisci", osint_acquisisci, methods=["POST"]),
    Route("/osint/revisiona", osint_revisiona, methods=["POST"]),
    Route("/grafo", grafo_view),
    Route("/grafo/aggiungi", grafo_aggiungi, methods=["POST"]),
    Route("/grafo/revisiona", grafo_revisiona, methods=["POST"]),
    Route("/salute", salute),
    Route("/esecuzioni", esecuzioni_view),
    Route("/prestazioni", prestazioni_view),
    Route("/esporta.csv", esporta_csv),
    Route("/pratiche", pratiche_view),
    Route("/pratiche/crea", pratiche_crea, methods=["POST"]),
    Route("/pratiche/{pratica_id}", pratica_dettaglio),
    Route("/pratiche/{pratica_id}/evento", pratica_evento, methods=["POST"]),
    Route("/report/verifica", report_verifica),
    Route("/settori/{settore_id}/gestione", settore_gestione),
    Route("/settori/{settore_id}/collaudo", settore_collaudo, methods=["POST"]),
    Route("/settori/{settore_id}/transizione", settore_transizione, methods=["POST"]),
    Route("/settori/{settore_id}/ripristina", settore_ripristina_versione, methods=["POST"]),
    Route("/dipendenze", dipendenze_view),
    Route("/audit/esporta.csv", audit_esporta),
    Route("/fonti/catalogo", catalogo_view),
    Route("/fonti/catalogo/scopri", catalogo_scopri, methods=["POST"]),
    Route("/fonti/proposte/crea", proposta_crea, methods=["POST"]),
    Route("/fonti/proposte/decidi", proposta_decidi, methods=["POST"]),
    Route("/osint/raccolta", osint_raccolta, methods=["POST"]),
    Route("/osint/verifica", osint_verifica),
    Route("/grafo/ocds", grafo_suggerimenti_ocds),
]

ambiente = os.environ.get("EMERSIONE_ENV", "development").strip().casefold()
sicurezza.verifica_configurazione_produzione()
segreto_sessione = os.environ.get("EMERSIONE_SESSION_SECRET")
if not segreto_sessione:
    # Solo sviluppo/test. In produzione la configurazione obbligatoria è verificata sopra.
    segreto_sessione = secrets.token_urlsafe(48)
app = Starlette(routes=routes)
app.add_middleware(SessionMiddleware, secret_key=segreto_sessione, session_cookie="emersione_session", max_age=8 * 60 * 60, same_site="strict", https_only=(ambiente == "production"))
app.add_middleware(LimiteDimensioneRichiestaMiddleware)
app.add_middleware(IntestazioniSicurezzaMiddleware)
app.add_middleware(CorrelazioneMiddleware)

_inizializza_dataset()
