"""Collegamento tra dati acquisiti e parametri delle formule (sezioni 12, 30.4-30.6).

Percorso completo e controllato:
  1. scoperta del dataset (app.connettori.scoperta) e acquisizione (fonti_live);
  2. mappatura delle colonne in osservazioni normalizzate (fonti_mapping);
  3. revisione della mappatura: stato "mapping_verificato";
  4. PROPOSTA di nuovo valore per un parametro (questo modulo), con filtro su
     periodo/territorio/categoria, statistica dichiarata e controllo dell'unità;
  5. decisione di un revisore diverso dal proponente: solo allora il parametro
     riceve una nuova versione "da_verificare" e i settori che lo usano tornano
     in revisione (nessun effetto silenzioso sui punteggi).

suggerisci_parametri() offre solo suggerimenti lessicali (nome/unità): non è
un'interpretazione semantica affidabile e va sempre verificato dall'operatore.
"""
from __future__ import annotations

import json
import re
import secrets
import statistics
import unicodedata
from contextlib import closing
from typing import Any

from app import db_operativo, fonti_mapping, settori

STATISTICHE = {"valore_unico", "mediana", "media"}


class ErroreCollegamento(ValueError):
    pass


def _normalizza(testo: str) -> set[str]:
    t = unicodedata.normalize("NFKD", str(testo or "")).encode("ascii", "ignore").decode().casefold()
    return {p for p in re.split(r"[^a-z0-9]+", t) if len(p) > 2}


def _unita(testo: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(testo or "")).casefold())


def suggerisci_parametri(intestazioni: list[str], unita: str = "", limite: int = 5) -> list[dict[str, Any]]:
    """Ordina i parametri per somiglianza lessicale con colonne/unità. Solo un suggerimento."""
    parole = set().union(*[_normalizza(h) for h in intestazioni]) if intestazioni else set()
    risultati = []
    for p in settori.lista_parametri():
        chiavi = _normalizza(p.get("nome", "")) | _normalizza(p.get("descrizione", "")) | _normalizza(p["id"])
        comuni = parole & chiavi
        punteggio = len(comuni) + (2 if unita and _unita(unita) == _unita(p.get("unita", "")) else 0)
        if punteggio:
            risultati.append({"parametro_id": p["id"], "nome": p.get("nome"), "unita": p.get("unita"),
                              "corrispondenze": sorted(comuni), "punteggio": punteggio,
                              "nota": "Suggerimento lessicale non verificato."})
    return sorted(risultati, key=lambda r: -r["punteggio"])[:limite]


def proponi(*, mapping_id: str, parametro_id: str, statistica: str, utente: str,
            periodo: str = "", territorio: str = "", categoria: str = "") -> dict[str, Any]:
    if statistica not in STATISTICHE:
        raise ErroreCollegamento("Statistica non supportata.")
    mappature = {m["id"]: m for m in fonti_mapping.elenco(1000)}
    mappatura = mappature.get(mapping_id)
    if mappatura is None:
        raise ErroreCollegamento("Mappatura non trovata.")
    if mappatura.get("stato") != "mapping_verificato":
        raise ErroreCollegamento("La mappatura deve essere revisionata come 'mapping_verificato' prima di proporre valori.")
    if mappatura.get("parametro_id") != parametro_id:
        raise ErroreCollegamento("La mappatura è associata a un parametro diverso.")
    parametro = settori.catalogo_parametri().get(parametro_id)
    if parametro is None:
        raise ErroreCollegamento("Parametro non trovato.")
    righe = [o for o in fonti_mapping.osservazioni(mapping_id, 1000)
             if (not periodo or o["periodo"] == periodo) and (not territorio or o["territorio"] == territorio)
             and (not categoria or o["categoria"] == categoria)]
    if not righe:
        raise ErroreCollegamento("Nessuna osservazione corrisponde al filtro.")
    if statistica == "valore_unico" and len(righe) != 1:
        raise ErroreCollegamento(f"Il filtro seleziona {len(righe)} osservazioni: restringerlo o scegliere mediana/media.")
    unita_oss = {o["unita"] for o in righe}
    if len(unita_oss) != 1:
        raise ErroreCollegamento("Le osservazioni selezionate hanno unità diverse.")
    valori = [float(o["valore"]) for o in righe]
    valore = valori[0] if statistica == "valore_unico" else (statistics.median(valori) if statistica == "mediana" else statistics.fmean(valori))
    unita_o = next(iter(unita_oss))
    compatibili = _unita(unita_o) == _unita(parametro.get("unita", ""))
    provenienza = {
        "mappatura": mapping_id, "url_fonte": mappatura.get("url_fonte"), "hash_fonte": mappatura.get("hash_fonte"),
        "righe_origine": [o["riga_origine"] for o in righe][:200], "filtro": {"periodo": periodo, "territorio": territorio, "categoria": categoria},
    }
    proposta_id = "PP-" + secrets.token_hex(6).upper()
    with closing(db_operativo.connessione()) as conn:
        conn.execute(
            """INSERT INTO proposte_parametri(id, parametro_id, valore_proposto, unita_osservazioni, unita_parametro,
               unita_compatibili, mappatura_id, filtro, statistica, numero_osservazioni, provenienza, stato, creata_da, creata_il)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (proposta_id, parametro_id, valore, unita_o, parametro.get("unita", ""), 1 if compatibili else 0, mapping_id,
             json.dumps(provenienza["filtro"], ensure_ascii=False), statistica, len(righe),
             json.dumps(provenienza, ensure_ascii=False), "proposta", utente[:100], db_operativo.adesso()))
    return {"id": proposta_id, "valore_proposto": valore, "unita_compatibili": compatibili, "numero_osservazioni": len(righe)}


def elenco(stato: str = "") -> list[dict[str, Any]]:
    with closing(db_operativo.connessione()) as conn:
        if stato:
            righe = conn.execute("SELECT * FROM proposte_parametri WHERE stato=? ORDER BY creata_il DESC LIMIT 200", (stato,)).fetchall()
        else:
            righe = conn.execute("SELECT * FROM proposte_parametri ORDER BY creata_il DESC LIMIT 200").fetchall()
    return [dict(r) for r in righe]


def decidi(proposta_id: str, *, decisione: str, utente: str, ruolo: str, nota: str) -> dict[str, Any]:
    if ruolo != "revisore":
        raise ErroreCollegamento("Solo il revisore può applicare o respingere una proposta.")
    if decisione not in {"applicata", "respinta"}:
        raise ErroreCollegamento("Decisione non valida.")
    if len((nota or "").strip()) < 20:
        raise ErroreCollegamento("La decisione richiede una nota di almeno 20 caratteri.")
    with closing(db_operativo.connessione()) as conn:
        r = conn.execute("SELECT * FROM proposte_parametri WHERE id=?", (proposta_id,)).fetchone()
    if r is None:
        raise ErroreCollegamento("Proposta non trovata.")
    proposta = dict(r)
    if proposta["stato"] != "proposta":
        raise ErroreCollegamento("La proposta è già stata decisa.")
    if proposta["creata_da"] == utente:
        raise ErroreCollegamento("Separazione dei compiti: chi propone non può decidere.")
    versione = None
    if decisione == "applicata":
        if not proposta["unita_compatibili"]:
            raise ErroreCollegamento("Unità delle osservazioni e del parametro diverse: serve prima un parametro di conversione esplicito.")
        parametro = settori.catalogo_parametri()[proposta["parametro_id"]]
        provenienza = json.loads(proposta["provenienza"])
        fonte = (f"Osservazioni da mappatura {proposta['mappatura_id']} ({provenienza.get('url_fonte')}, sha256 "
                 f"{str(provenienza.get('hash_fonte'))[:16]}…), {proposta['statistica']} di {proposta['numero_osservazioni']} "
                 f"valori, filtro {proposta['filtro']}; proposta {proposta_id}")[:500]
        versione = settori.aggiorna_parametro(
            parametro_id=proposta["parametro_id"], nome=parametro["nome"], valore=proposta["valore_proposto"],
            unita=parametro["unita"], fonte=fonte, descrizione=parametro.get("descrizione", ""), stato="da_verificare",
            autore=utente)
    with closing(db_operativo.connessione()) as conn:
        conn.execute("UPDATE proposte_parametri SET stato=?, decisa_da=?, decisa_il=?, nota_decisione=? WHERE id=? AND stato='proposta'",
                     (decisione, utente[:100], db_operativo.adesso(), nota.strip()[:1000], proposta_id))
    return {"id": proposta_id, "decisione": decisione, "versione_parametro": versione}
