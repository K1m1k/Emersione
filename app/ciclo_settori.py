"""Ciclo di vita e approvazione dei settori (sezioni 30.3, 30.9, 30.11).

Ogni passaggio di stato:
  - è ammesso solo dagli stati e dai ruoli previsti dalla tabella TRANSIZIONI;
  - richiede una motivazione, registrata con utente, ruolo e hash del settore;
  - verso gli stati di verifica/approvazione richiede un collaudo superato
    sull'esatta configurazione corrente;
  - per le approvazioni applica la separazione dei compiti: chi ha creato o
    modificato per ultimo il settore non può approvarlo;
  - per "approvato" (uso previsto) richiede che tutti i parametri usati siano
    verificati/approvati e un documento di evidenza registrato.

La configurazione degli stati e dei ruoli va adattata all'organizzazione
destinataria. Il software registra le decisioni: non certifica la competenza di
chi approva né la correttezza scientifica o giuridica delle regole.
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timezone
from typing import Any

from app import collaudo_settori, db_operativo, settori

APPROVAZIONI = {"approvata_sperimentazione", "approvato"}
RICHIEDE_COLLAUDO = {"verificata_tecnicamente", "approvata_sperimentazione", "approvato"}

# da_stato -> {a_stato: ruoli ammessi}
TRANSIZIONI: dict[str, dict[str, set[str]]] = {
    "bozza": {"in_revisione": {"amministratore", "responsabile_dati"}, "archiviato": {"amministratore"}},
    "in_revisione": {"verificata_tecnicamente": {"amministratore"}, "bozza": {"amministratore", "responsabile_dati"},
                     "sospeso": {"amministratore", "revisore"}, "archiviato": {"amministratore"}},
    "verificata_tecnicamente": {"in_validazione_metodologica": {"amministratore", "revisore"},
                                "in_revisione": {"amministratore", "revisore"}, "sospeso": {"amministratore", "revisore"}},
    "in_validazione_metodologica": {"in_verifica_normativa": {"revisore"}, "approvata_sperimentazione": {"revisore"},
                                    "in_revisione": {"revisore"}, "sospeso": {"amministratore", "revisore"}},
    "in_verifica_normativa": {"approvata_sperimentazione": {"revisore"}, "in_revisione": {"revisore"},
                              "sospeso": {"amministratore", "revisore"}},
    "approvata_sperimentazione": {"approvato": {"revisore"}, "in_revisione": {"amministratore", "revisore"},
                                  "sospeso": {"amministratore", "revisore"}, "archiviato": {"amministratore"}},
    "sperimentale": {"approvato": {"revisore"}, "in_revisione": {"amministratore", "revisore"},
                     "sospeso": {"amministratore", "revisore"}, "archiviato": {"amministratore"}},
    "approvato": {"in_revisione": {"amministratore", "revisore"}, "sospeso": {"amministratore", "revisore"},
                  "archiviato": {"amministratore"}},
    "sospeso": {"in_revisione": {"amministratore"}, "archiviato": {"amministratore"}},
    "archiviato": {},
}

DESCRIZIONE_STATI = {
    "bozza": "Bozza: non produce risultati.",
    "in_revisione": "In revisione tecnica: non produce risultati operativi; eseguibile solo in collaudo.",
    "verificata_tecnicamente": "Collaudo tecnico superato: in attesa di validazione metodologica.",
    "in_validazione_metodologica": "In validazione metodologica.",
    "in_verifica_normativa": "In verifica normativa.",
    "approvata_sperimentazione": "Approvata per la sola sperimentazione: risultati sempre marcati sperimentali.",
    "sperimentale": "Stato iniziale dei settori dimostrativi, equivalente all'approvazione per la sperimentazione.",
    "approvato": "Approvata per l'uso previsto dall'ente.",
    "sospeso": "Sospeso: non produce risultati; storico conservato.",
    "archiviato": "Archiviato: superato, conservato per lo storico.",
}


class ErroreTransizione(ValueError):
    pass


def requisiti_mancanti(settore_id: str, a_stato: str, *, utente: str, ruolo: str,
                       motivazione: str = "", evidenza: str = "") -> list[str]:
    """Elenco leggibile di ciò che manca per eseguire la transizione (vuoto = ammessa)."""
    registro = settori.leggi_registro()
    settore = registro["settori"].get(settore_id)
    if settore is None:
        return ["Settore inesistente."]
    da_stato = settore.get("stato", "bozza")
    mancanti: list[str] = []
    ammesse = TRANSIZIONI.get(da_stato, {})
    if a_stato not in ammesse:
        return [f"Transizione da '{da_stato}' a '{a_stato}' non prevista."]
    if ruolo not in ammesse[a_stato]:
        mancanti.append(f"Ruolo '{ruolo}' non autorizzato: servono {', '.join(sorted(ammesse[a_stato]))}.")
    minimo = 20 if a_stato in APPROVAZIONI else 10
    if len((motivazione or "").strip()) < minimo:
        mancanti.append(f"Motivazione di almeno {minimo} caratteri.")
    if a_stato in RICHIEDE_COLLAUDO:
        ultimo = collaudo_settori.ultimo_collaudo(settore_id)
        attuale = collaudo_settori.hash_settore(settore_id, registro)
        if ultimo is None:
            mancanti.append("Collaudo automatico non ancora eseguito.")
        elif not ultimo["superato"]:
            mancanti.append("L'ultimo collaudo non è superato.")
        elif ultimo["hash_settore"] != attuale:
            mancanti.append("La configurazione è cambiata dopo l'ultimo collaudo: ripetere il collaudo.")
    if a_stato in APPROVAZIONI:
        autori = {settore.get("creato_da"), settore.get("aggiornato_da")} - {None, "", "sconosciuto", "sistema"}
        if utente in autori:
            mancanti.append("Separazione dei compiti: chi ha creato o modificato il settore non può approvarlo.")
    if a_stato == "approvato":
        parametri = registro["parametri"]
        non_validati = sorted(pid for pid in settori.parametri_usati_da_settore(settore)
                              if parametri.get(pid, {}).get("stato") not in {"verificato", "approvato"})
        if non_validati:
            mancanti.append("Parametri non verificati/approvati: " + ", ".join(non_validati) + ".")
        documenti = {d.get("id") for d in registro.get("documenti", []) if isinstance(d, dict)}
        if not evidenza or evidenza not in documenti:
            mancanti.append("Indicare un documento di evidenza registrato (validazione metodologica/normativa).")
    return mancanti


def transizioni_disponibili(settore_id: str, *, utente: str, ruolo: str) -> list[dict[str, Any]]:
    settore = settori.configurazione_settore(settore_id)
    if settore is None:
        return []
    out = []
    for a_stato in TRANSIZIONI.get(settore.get("stato", "bozza"), {}):
        mancanti = [m for m in requisiti_mancanti(settore_id, a_stato, utente=utente, ruolo=ruolo,
                                                   motivazione="x" * 40, evidenza="__non_verificata__")
                    if not m.startswith("Indicare un documento")]
        out.append({"a_stato": a_stato, "descrizione": DESCRIZIONE_STATI.get(a_stato, ""), "requisiti_mancanti": mancanti})
    return out


def esegui_transizione(settore_id: str, a_stato: str, *, utente: str, ruolo: str,
                       motivazione: str, evidenza: str = "") -> dict[str, Any]:
    mancanti = requisiti_mancanti(settore_id, a_stato, utente=utente, ruolo=ruolo,
                                  motivazione=motivazione, evidenza=evidenza)
    if mancanti:
        raise ErroreTransizione(" ".join(mancanti))
    registro = settori.leggi_registro()
    settore = registro["settori"][settore_id]
    da_stato = settore.get("stato", "bozza")
    hash_attuale = collaudo_settori.hash_settore(settore_id, registro)
    collaudo = collaudo_settori.ultimo_collaudo(settore_id) if a_stato in RICHIEDE_COLLAUDO else None
    settore["stato"] = a_stato
    settore["stato_aggiornato_il"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    settore["stato_aggiornato_da"] = utente[:100]
    settore.pop("motivo_revisione", None)
    settori.salva_registro(registro, autore=utente, motivo=f"Settore {settore_id}: {da_stato} → {a_stato}")
    with closing(db_operativo.connessione()) as conn:
        cur = conn.execute(
            """INSERT INTO transizioni_settore(settore_id, da_stato, a_stato, utente, ruolo, motivazione, evidenza,
               hash_settore, collaudo_id, registrata_il) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (settore_id, da_stato, a_stato, utente[:100], ruolo, motivazione.strip()[:2000], evidenza or None,
             hash_attuale, collaudo["collaudo_id"] if collaudo else None, db_operativo.adesso()),
        )
    return {"id": int(cur.lastrowid), "settore_id": settore_id, "da_stato": da_stato, "a_stato": a_stato,
            "hash_settore": hash_attuale}


def storico_transizioni(settore_id: str) -> list[dict[str, Any]]:
    with closing(db_operativo.connessione()) as conn:
        righe = conn.execute("SELECT * FROM transizioni_settore WHERE settore_id=? ORDER BY id DESC", (settore_id,)).fetchall()
    return [dict(r) for r in righe]


# ---------------------------------------------------------------------------
# Versioni: confronto e ripristino (sezione 30.9)
# ---------------------------------------------------------------------------

def storico_versioni_settore(settore_id: str, limite: int = 100) -> list[dict[str, Any]]:
    """Versioni distinte della configurazione del settore tratte dallo storico completo del registro."""
    from app import versioni_registro
    out, visti = [], set()
    for v in versioni_registro.elenco(2000):
        contenuto = versioni_registro.leggi(v["progressivo"]) or {}
        cfg = (contenuto.get("settori") or {}).get(settore_id)
        if cfg is None:
            continue
        h = collaudo_settori.hash_settore(settore_id, contenuto)
        chiave = (h, cfg.get("stato"))
        if chiave in visti:
            continue
        visti.add(chiave)
        out.append({"progressivo": v["progressivo"], "registrata_il": v["registrata_il"], "autore": v["autore"],
                    "motivo": v["motivo"], "stato": cfg.get("stato"), "versione_configurazione": cfg.get("versione_configurazione", 1),
                    "hash_settore": h})
        if len(out) >= limite:
            break
    return out


def _differenze(a: Any, b: Any, percorso: str = "") -> list[dict[str, Any]]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k in {"storico_configurazioni", "aggiornato_il", "stato_aggiornato_il"}:
                continue
            out += _differenze(a.get(k), b.get(k), f"{percorso}.{k}" if percorso else k)
        return out
    if a != b:
        return [{"percorso": percorso, "prima": json.dumps(a, ensure_ascii=False)[:300],
                 "dopo": json.dumps(b, ensure_ascii=False)[:300]}]
    return []


def confronta_versioni(settore_id: str, progressivo_a: int, progressivo_b: int) -> list[dict[str, Any]]:
    from app import versioni_registro
    va, vb = versioni_registro.leggi(progressivo_a), versioni_registro.leggi(progressivo_b)
    if va is None or vb is None:
        raise settori.ErroreRegistro("Versione non trovata.")
    return _differenze((va.get("settori") or {}).get(settore_id), (vb.get("settori") or {}).get(settore_id))


def ripristina_versione(settore_id: str, progressivo: int, *, utente: str, ruolo: str, motivazione: str) -> int:
    """Ripristina la configurazione del settore da una versione storica creando una NUOVA versione.

    Lo storico successivo non viene cancellato; il settore torna in revisione e
    richiede di nuovo collaudo e approvazioni.
    """
    from app import versioni_registro
    if ruolo != "amministratore":
        raise ErroreTransizione("Solo l'amministratore tecnico può ripristinare una versione.")
    if len((motivazione or "").strip()) < 10:
        raise ErroreTransizione("Motivazione di almeno 10 caratteri.")
    storica = versioni_registro.leggi(progressivo)
    cfg = ((storica or {}).get("settori") or {}).get(settore_id)
    if cfg is None:
        raise settori.ErroreRegistro("La versione indicata non contiene il settore.")
    registro = settori.leggi_registro()
    attuale = registro["settori"].get(settore_id)
    if attuale is None:
        raise settori.ErroreRegistro("Settore non trovato.")
    mancanti = [pid for pid in settori.parametri_usati_da_settore(cfg) if pid not in registro["parametri"]]
    if mancanti:
        raise settori.ErroreRegistro("Parametri della versione storica non più presenti: " + ", ".join(sorted(mancanti)))
    nuova = json.loads(json.dumps(cfg))
    nuova["storico_configurazioni"] = (attuale.get("storico_configurazioni") or [])[-19:] + [{
        "versione_precedente": attuale.get("versione_configurazione", 1),
        "registrata_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "autore": utente[:100], "motivo": f"Ripristino della versione storica n. {progressivo}: {motivazione.strip()[:150]}",
        "configurazione_precedente": {k: v for k, v in attuale.items() if k != "storico_configurazioni"},
    }]
    nuova["versione_configurazione"] = int(attuale.get("versione_configurazione", 1)) + 1
    nuova["stato"] = "in_revisione"
    nuova["aggiornato_da"] = utente[:100]
    nuova["aggiornato_il"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    nuova["ripristinata_da_versione"] = progressivo
    registro["settori"][settore_id] = nuova
    settori.salva_registro(registro, autore=utente, motivo=f"Ripristino settore {settore_id} dalla versione {progressivo}")
    return nuova["versione_configurazione"]
