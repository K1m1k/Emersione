"""Moduli specifici di settore con interfaccia definita (sezione 30.7).

Il nucleo del motore non contiene condizioni del tipo `if settore == ...`: un
settore dichiara nel registro i moduli che usa (chiave "moduli") e il motore li
richiama da questo elenco chiuso. Un nuovo modulo richiede codice, test
obbligatori e revisione prima dell'attivazione; la configurazione non può
caricare codice arbitrario, può solo scegliere tra i moduli registrati.

Interfaccia: funzione(azienda: dict) -> valore serializzabile in JSON, salvato
in analisi[chiave_risultato]. Un modulo non assegna punti: produce elementi
descrittivi separati dal punteggio.
"""
from __future__ import annotations

from typing import Any, Callable


def _screening_congruita_dm143(azienda: dict[str, Any]) -> dict[str, Any]:
    from app.normativa_edilizia import verifica_preliminare
    return verifica_preliminare(
        categoria=azienda.get("categoria_opera"),
        valore_opera=azienda.get("valore_opera"),
        costo_manodopera=azienda.get("costo_manodopera_dichiarato"),
        tipo_commessa=azienda.get("tipo_commessa"),
    )


MODULI: dict[str, dict[str, Any]] = {
    "screening_congruita_dm143": {
        "descrizione": "Screening preliminare con gli indici tabellari del D.M. 143/2021; non è un'attestazione di congruità.",
        "chiave_risultato": "pre_screening_congruita_edilizia",
        "funzione": _screening_congruita_dm143,
        "campi_usati": ["categoria_opera", "valore_opera", "costo_manodopera_dichiarato", "tipo_commessa"],
    },
}

CHIAVI_RISULTATO = sorted({m["chiave_risultato"] for m in MODULI.values()})


def esegui(nome: str, azienda: dict[str, Any]) -> tuple[str, Any]:
    modulo = MODULI.get(nome)
    if modulo is None:
        raise KeyError(f"Modulo di settore non registrato: {nome}")
    funzione: Callable[[dict[str, Any]], Any] = modulo["funzione"]
    return modulo["chiave_risultato"], funzione(azienda)
