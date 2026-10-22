"""Provenienza dei lotti importati da enti conferenti (sezioni 10 e 13).

Per ogni lotto si registrano soggetto conferente, titolare del trattamento,
finalità dichiarata, autorizzazione o base giuridica indicata, data di
ricezione, eventuale scadenza dell'autorizzazione e condizioni d'uso. Il
software registra quanto dichiarato dall'operatore: non verifica la legittimità
del trattamento, che resta in capo all'ente e al suo DPO.

Un lotto con autorizzazione scaduta resta consultabile ma blocca relazioni,
esportazioni e nuove pratiche; un lotto revocato viene rimosso dall'uso
operativo (si torna al dataset dimostrativo) e la revoca resta registrata.
"""
from __future__ import annotations

import re
from contextlib import closing
from datetime import date
from typing import Any

from app import db_operativo

CAMPI = ("conferente", "titolare", "finalita", "autorizzazione", "data_ricezione", "condizioni_uso")


class ErroreProvenienza(ValueError):
    pass


def valida(dati: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    etichette = {"conferente": "soggetto conferente", "titolare": "titolare del trattamento", "finalita": "finalità dichiarata",
                 "autorizzazione": "autorizzazione o base giuridica", "data_ricezione": "data di ricezione",
                 "condizioni_uso": "condizioni d'uso"}
    for campo in CAMPI:
        valore = str(dati.get(campo, "") or "").strip()
        if not 3 <= len(valore) <= 500:
            raise ErroreProvenienza(f"Indicare {etichette[campo]} (3–500 caratteri).")
        out[campo] = valore
    for campo in ("data_ricezione", "scadenza_autorizzazione"):
        valore = str(dati.get(campo, "") or "").strip()
        if campo == "scadenza_autorizzazione" and not valore:
            out[campo] = ""
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valore):
            raise ErroreProvenienza(f"Il campo {campo.replace('_', ' ')} deve avere formato AAAA-MM-GG.")
        try:
            date.fromisoformat(valore)
        except ValueError as exc:
            raise ErroreProvenienza(f"Data non valida: {valore}.") from exc
        out[campo] = valore
    if out["scadenza_autorizzazione"] and out["scadenza_autorizzazione"] < out["data_ricezione"]:
        raise ErroreProvenienza("La scadenza dell'autorizzazione precede la data di ricezione.")
    return out


def registra(*, lotto_id: str, file: str, sha256: str, dati: dict[str, str], utente: str) -> None:
    with closing(db_operativo.connessione()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("UPDATE provenienza_lotti SET stato='sostituito' WHERE stato='attivo'")
            conn.execute(
                """INSERT INTO provenienza_lotti(lotto_id, file, sha256, conferente, titolare, finalita, autorizzazione,
                   data_ricezione, scadenza_autorizzazione, condizioni_uso, caricato_da, caricato_il, stato)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'attivo')""",
                (lotto_id, file[:200], sha256, dati["conferente"], dati["titolare"], dati["finalita"], dati["autorizzazione"],
                 dati["data_ricezione"], dati["scadenza_autorizzazione"] or None, dati["condizioni_uso"], utente[:100],
                 db_operativo.adesso()))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def per_lotto(lotto_id: str | None) -> dict[str, Any] | None:
    if not lotto_id:
        return None
    with closing(db_operativo.connessione()) as conn:
        r = conn.execute("SELECT * FROM provenienza_lotti WHERE lotto_id=?", (lotto_id,)).fetchone()
    return dict(r) if r else None


def scaduta(prov: dict[str, Any] | None, oggi: date | None = None) -> bool:
    if not prov or not prov.get("scadenza_autorizzazione"):
        return False
    return date.fromisoformat(prov["scadenza_autorizzazione"]) < (oggi or date.today())


def revoca(lotto_id: str, *, utente: str, motivo: str) -> None:
    if len((motivo or "").strip()) < 10:
        raise ErroreProvenienza("Indicare il motivo della revoca (almeno 10 caratteri).")
    with closing(db_operativo.connessione()) as conn:
        cur = conn.execute("UPDATE provenienza_lotti SET stato='revocato', revocato_da=?, revocato_il=?, motivo_revoca=? WHERE lotto_id=? AND stato='attivo'",
                           (utente[:100], db_operativo.adesso(), motivo.strip()[:1000], lotto_id))
        if cur.rowcount != 1:
            raise ErroreProvenienza("Nessun lotto attivo con questo identificativo.")


def elenco(limite: int = 100) -> list[dict[str, Any]]:
    with closing(db_operativo.connessione()) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM provenienza_lotti ORDER BY caricato_il DESC LIMIT ?", (int(limite),))]


def chiudi_attivo() -> None:
    """Segna come sostituito l'eventuale lotto attivo (es. ripristino del dataset dimostrativo)."""
    with closing(db_operativo.connessione()) as conn:
        conn.execute("UPDATE provenienza_lotti SET stato='sostituito' WHERE stato='attivo'")
