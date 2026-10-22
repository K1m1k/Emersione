"""Pratiche di approfondimento (sezioni 18 e 22).

Una pratica raccoglie, per una singola azienda e una specifica esecuzione del
motore, la finalità dichiarata, l'ambito, le note degli operatori e lo stato del
lavoro umano. Una pratica non è un provvedimento: non avvia ispezioni, sanzioni o
comunicazioni, e lo stato "trasmessa" indica solo che l'operatore ha inoltrato
il fascicolo all'ufficio competente con le modalità previste dall'ente.
"""
from __future__ import annotations

import secrets
from contextlib import closing
from typing import Any

from app import db_operativo

STATI = {
    "aperta": "Aperta: in attesa di esame.",
    "in_approfondimento": "In approfondimento da parte del personale competente.",
    "chiusa_senza_seguito": "Chiusa senza seguito: l'esame umano non ha ritenuto necessari approfondimenti.",
    "trasmessa": "Fascicolo trasmesso all'ufficio competente secondo le procedure dell'ente.",
}
TRANSIZIONI = {
    "aperta": {"in_approfondimento", "chiusa_senza_seguito"},
    "in_approfondimento": {"chiusa_senza_seguito", "trasmessa", "aperta"},
    "chiusa_senza_seguito": {"aperta"},
    "trasmessa": set(),
}
MAX_TESTO = 2000


class ErrorePratica(ValueError):
    pass


def _testo(valore: Any, nome: str, minimo: int = 1, massimo: int = MAX_TESTO) -> str:
    t = str(valore or "").strip()
    if len(t) < minimo or len(t) > massimo:
        raise ErrorePratica(f"Il campo '{nome}' deve contenere da {minimo} a {massimo} caratteri.")
    return t


def crea(*, azienda_id: str, esecuzione_id: int | None, finalita: str, ambito: str, utente: str) -> str:
    azienda_id = _testo(azienda_id, "azienda", 1, 100)
    finalita = _testo(finalita, "finalità", 10, 500)
    ambito = _testo(ambito, "ambito", 5, 500)
    pratica_id = "PR-" + secrets.token_hex(6).upper()
    ora = db_operativo.adesso()
    with closing(db_operativo.connessione()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """INSERT INTO pratiche(id, azienda_id, esecuzione_id, finalita, ambito, stato, creata_da, creata_il, aggiornata_il, assegnata_a)
                   VALUES (?,?,?,?,?,?,?,?,?,NULL)""",
                (pratica_id, azienda_id, esecuzione_id, finalita, ambito, "aperta", utente[:100], ora, ora))
            conn.execute("INSERT INTO pratiche_eventi(pratica_id, quando, utente, tipo, nota) VALUES (?,?,?,?,?)",
                         (pratica_id, ora, utente[:100], "creazione", f"Finalità: {finalita}"))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return pratica_id


def ottieni(pratica_id: str) -> dict[str, Any] | None:
    with closing(db_operativo.connessione()) as conn:
        r = conn.execute("SELECT * FROM pratiche WHERE id=?", (pratica_id,)).fetchone()
        if not r:
            return None
        eventi = conn.execute("SELECT quando, utente, tipo, nota FROM pratiche_eventi WHERE pratica_id=? ORDER BY id",
                              (pratica_id,)).fetchall()
    d = dict(r)
    d["eventi"] = [dict(e) for e in eventi]
    d["descrizione_stato"] = STATI.get(d["stato"], "")
    d["transizioni"] = sorted(TRANSIZIONI.get(d["stato"], set()))
    return d


def elenco(limite: int = 200, azienda_id: str | None = None) -> list[dict[str, Any]]:
    with closing(db_operativo.connessione()) as conn:
        if azienda_id:
            righe = conn.execute("SELECT * FROM pratiche WHERE azienda_id=? ORDER BY creata_il DESC LIMIT ?", (azienda_id, int(limite))).fetchall()
        else:
            righe = conn.execute("SELECT * FROM pratiche ORDER BY creata_il DESC LIMIT ?", (int(limite),)).fetchall()
    return [dict(r) for r in righe]


def aggiungi_evento(pratica_id: str, *, utente: str, nota: str, nuovo_stato: str | None = None) -> None:
    nota = _testo(nota, "nota", 5)
    with closing(db_operativo.connessione()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            r = conn.execute("SELECT stato FROM pratiche WHERE id=?", (pratica_id,)).fetchone()
            if not r:
                raise ErrorePratica("Pratica non trovata.")
            tipo = "nota"
            if nuovo_stato and nuovo_stato != r["stato"]:
                if nuovo_stato not in TRANSIZIONI.get(r["stato"], set()):
                    raise ErrorePratica(f"Passaggio da '{r['stato']}' a '{nuovo_stato}' non consentito.")
                conn.execute("UPDATE pratiche SET stato=?, aggiornata_il=? WHERE id=?", (nuovo_stato, db_operativo.adesso(), pratica_id))
                tipo = f"stato:{r['stato']}→{nuovo_stato}"
            else:
                conn.execute("UPDATE pratiche SET aggiornata_il=? WHERE id=?", (db_operativo.adesso(), pratica_id))
            conn.execute("INSERT INTO pratiche_eventi(pratica_id, quando, utente, tipo, nota) VALUES (?,?,?,?,?)",
                         (pratica_id, db_operativo.adesso(), utente[:100], tipo, nota))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
