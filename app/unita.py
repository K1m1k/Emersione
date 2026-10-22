"""Analisi dimensionale delle formule dichiarative.

Ogni campo e ogni parametro può dichiarare una "dimensione": un dizionario
{unità_base: esponente}, per esempio ore per ettaro all'anno =
{"ora": 1, "ettaro": -1, "anno": -1}. La stima della manodopera deve avere
dimensione {"addetto": 1}.

Se un elemento della formula non dichiara la dimensione, la verifica restituisce
"non_verificabile": non si presume compatibilità. Le unità base sono etichette
controllate (vedi UNITA_BASE); la conversione tra unità diverse (es. m² ed
ettari) non è automatica e va esplicitata con un parametro di conversione.
"""
from __future__ import annotations

import re
from typing import Any

UNITA_BASE = {
    "ora", "giorno", "settimana", "mese", "anno", "addetto", "ettaro", "m2", "m3",
    "coperto", "consegna", "km", "euro", "dpi", "unita", "kg", "pasto", "posto_letto",
    "veicolo", "pratica", "capo", "pezzo",
}
_NOME_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
DIMENSIONE_ADDETTI = {"addetto": 1}


class ErroreDimensione(ValueError):
    pass


def valida_dimensione(dim: Any) -> dict[str, int]:
    if not isinstance(dim, dict) or len(dim) > 8:
        raise ErroreDimensione("La dimensione deve essere un oggetto {unità: esponente} con al massimo 8 voci.")
    out: dict[str, int] = {}
    for nome, esp in dim.items():
        if not isinstance(nome, str) or not _NOME_RE.fullmatch(nome) or nome not in UNITA_BASE:
            raise ErroreDimensione(f"Unità base non riconosciuta: {nome!r}. Ammesse: {', '.join(sorted(UNITA_BASE))}.")
        if isinstance(esp, bool) or not isinstance(esp, int) or not -4 <= esp <= 4:
            raise ErroreDimensione(f"Esponente non valido per {nome}: usare un intero tra -4 e 4.")
        if esp:
            out[nome] = esp
    return out


def _combina(a: dict[str, int], b: dict[str, int], segno: int) -> dict[str, int]:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + segno * v
        if out[k] == 0:
            del out[k]
    return out


def descrivi(dim: dict[str, int] | None) -> str:
    if dim is None:
        return "non dichiarata"
    if not dim:
        return "adimensionale"
    num = [f"{k}^{v}" if v != 1 else k for k, v in sorted(dim.items()) if v > 0]
    den = [f"{k}^{-v}" if v != -1 else k for k, v in sorted(dim.items()) if v < 0]
    return (" · ".join(num) or "1") + ((" / " + " · ".join(den)) if den else "")


def dimensione_formula(espr: Any, campi: dict[str, Any], parametri: dict[str, Any]) -> tuple[dict[str, int] | None, list[str]]:
    """Restituisce (dimensione, problemi). dimensione=None se non determinabile.

    I problemi elencano incompatibilità reali (es. somma di grandezze diverse) o
    elementi privi di dimensione dichiarata.
    """
    problemi: list[str] = []

    def dim_di(definizione: dict[str, Any] | None, etichetta: str) -> dict[str, int] | None:
        if not isinstance(definizione, dict) or "dimensione" not in definizione:
            problemi.append(f"{etichetta}: dimensione non dichiarata")
            return None
        try:
            return valida_dimensione(definizione["dimensione"])
        except ErroreDimensione as exc:
            problemi.append(f"{etichetta}: {exc}")
            return None

    def visita(nodo: Any) -> dict[str, int] | None:
        if not isinstance(nodo, dict):
            problemi.append("nodo formula non valido")
            return None
        op = nodo.get("op")
        if op == "campo":
            return dim_di(campi.get(nodo.get("nome")), f"campo {nodo.get('nome')}")
        if op == "coefficiente":
            return dim_di(parametri.get(nodo.get("id")), f"parametro {nodo.get('id')}")
        if op == "lookup_coefficiente":
            ids = [nodo.get("predefinito"), *dict(nodo.get("mappa") or {}).values()]
            dims = [dim_di(parametri.get(pid), f"parametro {pid}") for pid in dict.fromkeys(ids)]
            if any(d is None for d in dims):
                return None
            if any(d != dims[0] for d in dims):
                problemi.append("lookup: i parametri alternativi hanno dimensioni diverse")
                return None
            return dims[0]
        if op == "costante":
            return {}
        if op == "somma":
            dims = [visita(x) for x in nodo.get("elementi", [])]
            if any(d is None for d in dims):
                return None
            if any(d != dims[0] for d in dims):
                problemi.append("somma di grandezze con dimensioni diverse: " + ", ".join(descrivi(d) for d in dims))
                return None
            return dims[0]
        if op == "moltiplica":
            totale: dict[str, int] | None = {}
            for x in nodo.get("elementi", []):
                d = visita(x)
                totale = None if d is None or totale is None else _combina(totale, d, 1)
            return totale
        if op == "dividi":
            s, d = visita(nodo.get("sinistra")), visita(nodo.get("destra"))
            return None if s is None or d is None else _combina(s, d, -1)
        problemi.append(f"operazione non supportata: {op}")
        return None

    risultato = visita(espr)
    return risultato, problemi


def verifica_stima_addetti(espr: Any, campi: dict[str, Any], parametri: dict[str, Any]) -> dict[str, Any]:
    dim, problemi = dimensione_formula(espr, campi, parametri)
    if dim is None:
        incompatibili = [p for p in problemi if "dimensioni diverse" in p]
        return {"esito": "incompatibile" if incompatibili else "non_verificabile",
                "dimensione": None, "problemi": problemi}
    if dim != DIMENSIONE_ADDETTI:
        return {"esito": "incompatibile", "dimensione": descrivi(dim),
                "problemi": [f"la stima ha dimensione {descrivi(dim)}, attesa {descrivi(DIMENSIONE_ADDETTI)}"]}
    return {"esito": "compatibile", "dimensione": descrivi(dim), "problemi": []}
