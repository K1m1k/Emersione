"""Grafo aziendale con archi esplicitamente documentati e stato di revisione.

Il modulo non deduce automaticamente illeciti. Ogni collegamento inserito
richiede una motivazione e una fonte o un riferimento verificabile.
"""
from __future__ import annotations
import hashlib, json, os, re, sqlite3, secrets, threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("EMERSIONE_GRAFO_DB", str(Path(__file__).resolve().parents[1] / "dati" / "emersione_grafo.sqlite3")))
_LOCK = threading.Lock()
_READY: set[str] = set()
TIPI = {
    "amministratore_condiviso": "Possibile amministratore condiviso",
    "partecipazione_societaria": "Partecipazione societaria documentata",
    "appalto_condiviso": "Rapporto relativo a contratto pubblico",
    "subappalto_documentato": "Subappalto documentato",
    "sede_condivisa": "Sede condivisa da verificare",
    "gruppo_societario": "Appartenenza a gruppo societario dichiarata",
    "altro_documentato": "Altra relazione documentata",
}
class ErroreGrafo(ValueError): pass

def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = str(DB_PATH.resolve())
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    if key not in _READY:
        with _LOCK:
            if key not in _READY:
                conn.execute("""CREATE TABLE IF NOT EXISTS relazioni_aziende(
                    id TEXT PRIMARY KEY, origine_id TEXT NOT NULL, destinazione_id TEXT NOT NULL,
                    tipo TEXT NOT NULL, evidenza TEXT NOT NULL, url_fonte TEXT NOT NULL,
                    riferimento_documento TEXT NOT NULL, hash_evidenza TEXT NOT NULL,
                    dataset_hash TEXT NOT NULL, creato_da TEXT NOT NULL, creato_il TEXT NOT NULL,
                    stato TEXT NOT NULL, nota_revisore TEXT NOT NULL DEFAULT '', revisionato_da TEXT NOT NULL DEFAULT '')""")
                colonne = {r[1] for r in conn.execute("PRAGMA table_info(relazioni_aziende)").fetchall()}
                # Estensione v3.1: periodo di validità e riservatezza (sezione 15).
                for nome, definizione in (("valido_dal", "TEXT NOT NULL DEFAULT ''"), ("valido_al", "TEXT NOT NULL DEFAULT ''"),
                                          ("riservatezza", "TEXT NOT NULL DEFAULT 'pubblica'")):
                    if nome not in colonne:
                        conn.execute(f"ALTER TABLE relazioni_aziende ADD COLUMN {nome} {definizione}")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_grafo_origine ON relazioni_aziende(origine_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_grafo_destinazione ON relazioni_aziende(destinazione_id)")
                conn.commit()
                try: os.chmod(DB_PATH, 0o600)
                except OSError: pass
                _READY.add(key)
    return conn

def _testo(v: Any, nome: str, minimo: int, massimo: int) -> str:
    if not isinstance(v, str): raise ErroreGrafo(f"{nome} non valido.")
    v = v.strip()
    if not minimo <= len(v) <= massimo: raise ErroreGrafo(f"{nome} deve contenere da {minimo} a {massimo} caratteri.")
    if any(ord(c) < 32 and c not in "\n\t\r" for c in v): raise ErroreGrafo(f"{nome} contiene caratteri non validi.")
    return v

def _data(valore: str, nome: str) -> str:
    valore = (valore or "").strip()
    if valore and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valore):
        raise ErroreGrafo(f"{nome}: usare il formato AAAA-MM-GG.")
    return valore


def aggiungi_relazione(*, origine_id: str, destinazione_id: str, tipo: str, evidenza: str,
                       url_fonte: str = "", riferimento_documento: str = "", dataset_hash: str = "",
                       utente: str, valido_dal: str = "", valido_al: str = "",
                       riservatezza: str = "pubblica") -> dict[str, Any]:
    valido_dal, valido_al = _data(valido_dal, "Inizio validità"), _data(valido_al, "Fine validità")
    if valido_dal and valido_al and valido_al < valido_dal:
        raise ErroreGrafo("La fine della validità precede l'inizio.")
    if riservatezza not in {"pubblica", "riservata"}:
        raise ErroreGrafo("Riservatezza non valida.")
    origine_id = _testo(origine_id, "Azienda origine", 1, 100)
    destinazione_id = _testo(destinazione_id, "Azienda destinazione", 1, 100)
    if origine_id == destinazione_id: raise ErroreGrafo("Una relazione non può collegare un'azienda a sé stessa.")
    if tipo not in TIPI: raise ErroreGrafo("Tipo di relazione non supportato.")
    evidenza = _testo(evidenza, "Evidenza documentale", 20, 3000)
    url_fonte = (url_fonte or "").strip()
    if url_fonte:
        from urllib.parse import urlparse
        p = urlparse(url_fonte)
        if p.scheme != "https" or not p.hostname or p.username or p.password or len(url_fonte) > 1000:
            raise ErroreGrafo("URL della fonte non valido: è richiesto HTTPS.")
    riferimento_documento = (riferimento_documento or "").strip()
    if len(riferimento_documento) > 200: raise ErroreGrafo("Riferimento documento troppo lungo.")
    if not (url_fonte or riferimento_documento):
        raise ErroreGrafo("Indicare un URL della fonte o un riferimento a un documento registrato.")
    utente = _testo(utente, "Operatore", 1, 100)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ident = secrets.token_hex(16)
    evidence_hash = hashlib.sha256(evidenza.encode("utf-8")).hexdigest()
    with closing(_conn()) as conn:
        duplicate = conn.execute("SELECT 1 FROM relazioni_aziende WHERE origine_id=? AND destinazione_id=? AND tipo=? AND hash_evidenza=? LIMIT 1",
            (origine_id, destinazione_id, tipo, evidence_hash)).fetchone()
        if duplicate:
            raise ErroreGrafo("La stessa relazione con identica evidenza è già registrata.")
        conn.execute("""INSERT INTO relazioni_aziende(id, origine_id, destinazione_id, tipo, evidenza, url_fonte,
            riferimento_documento, hash_evidenza, dataset_hash, creato_da, creato_il, stato, nota_revisore, revisionato_da,
            valido_dal, valido_al, riservatezza) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            ident, origine_id, destinazione_id, tipo, evidenza, url_fonte, riferimento_documento,
            evidence_hash, dataset_hash[:128], utente, now, "da_verificare", "", "", valido_dal, valido_al, riservatezza))
        conn.commit()
    return {"id": ident, "origine_id": origine_id, "destinazione_id": destinazione_id,
        "tipo": tipo, "tipo_label": TIPI[tipo], "evidenza": evidenza, "url_fonte": url_fonte,
        "riferimento_documento": riferimento_documento, "hash_evidenza": evidence_hash,
        "dataset_hash": dataset_hash[:128], "creato_da": utente, "creato_il": now,
        "stato": "da_verificare", "nota_revisore": "", "revisionato_da": ""}

def elenco(limite: int = 500, *, includi_riservate: bool = True, alla_data: str = "") -> list[dict[str, Any]]:
    """Relazioni registrate. Le riservate sono escluse per chi non è autorizzato;
    con alla_data si ottiene la situazione valida in quella data (relazioni temporali)."""
    limite = max(1, min(int(limite), 1000))
    condizioni, valori = [], []
    if not includi_riservate:
        condizioni.append("riservatezza='pubblica'")
    if alla_data:
        _data(alla_data, "Data")
        condizioni.append("(valido_dal='' OR valido_dal<=?) AND (valido_al='' OR valido_al>=?)")
        valori += [alla_data, alla_data]
    sql = "SELECT * FROM relazioni_aziende" + (" WHERE " + " AND ".join(condizioni) if condizioni else "") + " ORDER BY creato_il DESC LIMIT ?"
    with closing(_conn()) as conn:
        rows = conn.execute(sql, (*valori, limite)).fetchall()
    output = []
    for row in rows:
        d = dict(row); d["tipo_label"] = TIPI.get(d["tipo"], d["tipo"]); output.append(d)
    return output


def suggerimenti_da_record(aziende: list[dict[str, Any]], max_suggerimenti: int = 200) -> list[dict[str, Any]]:
    """Trova corrispondenze esatte su identificativi strutturati noti.

    I risultati sono soltanto candidati. Non sono salvati nel grafo e non creano
    relazioni senza fonte documentale esplicita e revisione da parte dell'utente.
    Non si usa la sola denominazione o la sola città per collegare imprese.
    """
    if not isinstance(aziende, list):
        raise ErroreGrafo("Il dataset per i suggerimenti non è valido.")
    campi = {
        "gruppo_societario_id": ("gruppo_societario", "Possibile identificativo di gruppo condiviso"),
        "codice_contratto_pubblico": ("appalto_condiviso", "Possibile contratto pubblico condiviso"),
        "codice_subappalto": ("subappalto_documentato", "Possibile riferimento di subappalto condiviso"),
        "sede_locale_codice": ("sede_condivisa", "Possibile identificativo di sede condiviso"),
    }
    esclusi = {"na", "n/a", "nd", "n.d.", "sconosciuto", "nessuno", "null", "0", "-"}
    suggerimenti: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for campo, (tipo, descrizione) in campi.items():
        gruppi: dict[str, list[dict[str, Any]]] = {}
        for azienda in aziende:
            if not isinstance(azienda, dict) or azienda.get("id") is None:
                continue
            raw = azienda.get(campo)
            if not isinstance(raw, (str, int)) or isinstance(raw, bool):
                continue
            valore = str(raw).strip()
            norm = re.sub(r"\s+", "", valore).casefold()
            if len(norm) < 3 or norm in esclusi or len(valore) > 200:
                continue
            gruppi.setdefault(norm, []).append(azienda)
        for norm, records in gruppi.items():
            ids = sorted({str(r.get("id")) for r in records})
            if len(ids) < 2:
                continue
            valore_originale = str(next(r.get(campo) for r in records if str(r.get(campo, "")).strip().casefold().replace(" ", "") == norm))
            # Genera coppie ordinate e limita il numero di edge proposti per
            # proteggere risorse e contenere gruppi generici/importati male.
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    key = (ids[i], ids[j], campo, norm)
                    if key in seen: continue
                    seen.add(key)
                    a = next(r for r in records if str(r.get("id")) == ids[i])
                    b = next(r for r in records if str(r.get("id")) == ids[j])
                    suggerimenti.append({
                        "origine_id": ids[i], "destinazione_id": ids[j], "tipo": tipo,
                        "tipo_label": descrizione, "campo": campo, "valore_condiviso": valore_originale,
                        "origine_nome": str(a.get("ragione_sociale") or ids[i]),
                        "destinazione_nome": str(b.get("ragione_sociale") or ids[j]),
                        "stato": "candidato_non_verificato",
                        "nota": "Corrispondenza esatta nel lotto importato; verificare il significato del campo e la fonte primaria prima di registrare una relazione.",
                    })
                    if len(suggerimenti) >= max(1, min(int(max_suggerimenti), 1000)):
                        return suggerimenti
    return suggerimenti

def revisiona(identificativo: str, *, stato: str, nota: str, revisore: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{32}", identificativo or ""): raise ErroreGrafo("Identificativo relazione non valido.")
    if stato not in {"confermata_documentalmente", "non_pertinente", "contestata", "da_verificare"}: raise ErroreGrafo("Stato di revisione non valido.")
    nota = _testo(nota, "Nota revisore", 10, 1500)
    revisore = _testo(revisore, "Revisore", 1, 100)
    with closing(_conn()) as conn:
        cur = conn.execute("UPDATE relazioni_aziende SET stato=?,nota_revisore=?,revisionato_da=? WHERE id=?", (stato, nota, revisore, identificativo))
        conn.commit()
        if cur.rowcount != 1: raise ErroreGrafo("Relazione non trovata.")



def _norm_id(valore: Any) -> str:
    return re.sub(r"[\s.\-]", "", str(valore or "")).upper()


def suggerimenti_da_ocds(contenuto: bytes, aziende: list[dict[str, Any]], *, url_fonte: str = "",
                         max_suggerimenti: int = 200) -> list[dict[str, Any]]:
    """Candidati "appalto_condiviso" da dati OCDS (es. open data ANAC): due aziende del
    lotto figurano come aggiudicatarie/fornitrici della stessa aggiudicazione.

    Il collegamento con le aziende del lotto usa solo corrispondenze ESATTE
    dell'identificativo (id, partita_iva o codice_fiscale del record) con
    l'identificativo della parte OCDS; mai il nome. I candidati non sono salvati.
    Una co-aggiudicazione (es. raggruppamento temporaneo) non implica irregolarità.
    """
    testo = contenuto.decode("utf-8-sig", errors="strict").strip()
    if testo.startswith("{") or testo.startswith("["):
        try:
            dato = json.loads(testo)
            documenti = dato if isinstance(dato, list) else [dato]
        except json.JSONDecodeError:
            documenti = [json.loads(r) for r in testo.splitlines() if r.strip()]
    else:
        raise ErroreGrafo("Formato OCDS non riconosciuto (atteso JSON o JSON Lines).")
    indice: dict[str, str] = {}
    for a in aziende:
        for campo in ("id", "partita_iva", "codice_fiscale"):
            if a.get(campo):
                indice[_norm_id(a[campo])] = str(a["id"])
    rilasci: list[dict[str, Any]] = []
    for d in documenti:
        if isinstance(d, dict):
            rilasci += [r for r in d.get("releases", []) if isinstance(r, dict)] if "releases" in d else [d]
    suggerimenti, visti = [], set()
    for r in rilasci:
        parti = {p.get("id"): p for p in r.get("parties", []) if isinstance(p, dict)}
        for award in r.get("awards", []) if isinstance(r.get("awards"), list) else []:
            fornitori = []
            for s in award.get("suppliers", []) if isinstance(award, dict) else []:
                if not isinstance(s, dict):
                    continue
                parte = parti.get(s.get("id"), {})
                candidati = [s.get("id"), (parte.get("identifier") or {}).get("id")]
                trovato = next((indice[_norm_id(c)] for c in candidati if c and _norm_id(c) in indice), None)
                if trovato:
                    fornitori.append(trovato)
            fornitori = sorted(set(fornitori))
            for i in range(len(fornitori)):
                for j in range(i + 1, len(fornitori)):
                    chiave = (fornitori[i], fornitori[j], r.get("ocid"), award.get("id"))
                    if chiave in visti:
                        continue
                    visti.add(chiave)
                    suggerimenti.append({
                        "origine_id": fornitori[i], "destinazione_id": fornitori[j], "tipo": "appalto_condiviso",
                        "tipo_label": TIPI["appalto_condiviso"], "ocid": r.get("ocid"), "award_id": award.get("id"),
                        "url_fonte": url_fonte, "stato": "candidato_non_verificato",
                        "nota": "Co-aggiudicazione nella stessa aggiudicazione OCDS; verificare il documento di gara prima di registrare la relazione.",
                    })
                    if len(suggerimenti) >= max_suggerimenti:
                        return suggerimenti
    return suggerimenti
