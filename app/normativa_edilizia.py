"""Indici tabellari ufficiali del DM 143/2021 per screening preliminare.

Questa funzione NON rilascia attestazioni di congruità e non sostituisce le
procedure delle Casse Edili/Edilcasse. Confronta solo la percentuale dichiarata
con il minimo tabellare; esclusioni, costi computabili, varianti, subappalti,
regole procedurali e disciplina aggiornata vanno verificati nel caso specifico.
"""
from __future__ import annotations
from typing import Any
import math

FONTE = {
    "titolo": "Decreto del Ministro del lavoro e delle politiche sociali n. 143 del 25 giugno 2021 — Tabella indici di congruità",
    "url_documento": "https://www.lavoro.gov.it/documenti-e-norme/normative/Documents/2021/DM-143-del-25062021-congruita.pdf",
    "url_tabella": "https://www.lavoro.gov.it/sites/default/files/priorita/Documents/Tabella-Indici-Congruita-2021.pdf",
    "data_norma": "2021-06-25",
    "data_verifica_fonte": "2026-10-22",
    "stato": "tabella_trascritta_da_fonte_ufficiale; applicabilità al caso da verificare",
}

INDICI: dict[str, dict[str, Any]] = {
    "OG1_NUOVA_CIVILE": {"categoria": "OG1 — Nuova edilizia civile, compresi impianti e forniture", "quota_minima": 0.1428},
    "OG1_NUOVA_INDUSTRIALE": {"categoria": "OG1 — Nuova edilizia industriale, esclusi impianti", "quota_minima": 0.0536},
    "RISTRUTTURAZIONE_CIVILE": {"categoria": "Ristrutturazione di edifici civili", "quota_minima": 0.22},
    "RISTRUTTURAZIONE_INDUSTRIALE": {"categoria": "Ristrutturazione di edifici industriali, esclusi impianti", "quota_minima": 0.0669},
    "OG2_RESTAURO": {"categoria": "OG2 — Restauro e manutenzione di beni tutelati", "quota_minima": 0.30},
    "OG3_STRADALE": {"categoria": "OG3 — Opere stradali, ponti, ecc.", "quota_minima": 0.1377},
    "OG4_SOTTOSUOLO": {"categoria": "OG4 — Opere d'arte nel sottosuolo", "quota_minima": 0.1082},
    "OG5_DIGHE": {"categoria": "OG5 — Dighe", "quota_minima": 0.1607},
    "OG6_ACQUEDOTTI_FOGNATURE": {"categoria": "OG6 — Acquedotti e fognature", "quota_minima": 0.1463},
    "OG6_GASDOTTI": {"categoria": "OG6 — Gasdotti", "quota_minima": 0.1366},
    "OG6_OLEODOTTI": {"categoria": "OG6 — Oleodotti", "quota_minima": 0.1366},
    "OG6_IRRIGAZIONE_EVACUAZIONE": {"categoria": "OG6 — Opere di irrigazione ed evacuazione", "quota_minima": 0.1248},
    "OG7_MARITTIME": {"categoria": "OG7 — Opere marittime", "quota_minima": 0.1216},
    "OG8_FLUVIALI": {"categoria": "OG8 — Opere fluviali", "quota_minima": 0.1331},
    "OG9_IMPIANTI_ENERGIA": {"categoria": "OG9 — Impianti per la produzione di energia elettrica", "quota_minima": 0.1423},
    "OG10_DISTRIBUZIONE": {"categoria": "OG10 — Impianti per la trasformazione e distribuzione", "quota_minima": 0.0536},
    "OG12_OG13_AMBIENTALE": {"categoria": "OG12 / OG13 — Bonifica e protezione ambientale", "quota_minima": 0.1647},
}

def verifica_preliminare(*, categoria: Any, valore_opera: Any, costo_manodopera: Any,
                         tipo_commessa: Any) -> dict[str, Any]:
    """Restituisce uno screening separato dal punteggio generale.

    tipo_commessa deve essere 'pubblico' o 'privato'. Per un lavoro privato con
    valore inferiore a 70.000 euro viene segnalato il limite di ambito descritto
    nella pagina ufficiale del Ministero; non si formula alcuna conclusione.
    """
    mancanti = []
    if not isinstance(categoria, str) or categoria not in INDICI: mancanti.append("categoria_opera")
    try:
        valore = float(valore_opera) if valore_opera not in (None, "") else None
    except (TypeError, ValueError): valore = None
    try:
        costo = float(costo_manodopera) if costo_manodopera not in (None, "") else None
    except (TypeError, ValueError): costo = None
    if valore is None or not math.isfinite(valore) or valore <= 0: mancanti.append("valore_opera positivo e finito")
    if costo is None or not math.isfinite(costo) or costo < 0: mancanti.append("costo_manodopera_dichiarato non negativo e finito")
    if tipo_commessa not in {"pubblico", "privato"}: mancanti.append("tipo_commessa (pubblico/privato)")
    if mancanti:
        return {"stato": "non_valutabile", "categoria": INDICI.get(categoria, {}).get("categoria") if isinstance(categoria, str) else None,
            "mancanti": mancanti, "fonte": dict(FONTE),
            "nota": "Screening non eseguito: mancano dati o classificazione. Non equivale a un esito di congruità."}
    if tipo_commessa == "privato" and valore < 70000:
        return {"stato": "fuori_soglia_privati_dm143", "categoria": INDICI[categoria]["categoria"],
            "valore_opera": valore, "tipo_commessa": tipo_commessa, "fonte": dict(FONTE),
            "nota": "Il DM 143/2021 è indicato dal Ministero per lavori privati di importo pari o superiore a 70.000 euro. Questo screening non applica l'indice al caso sotto soglia."}
    incidenza = costo / valore
    minimo = float(INDICI[categoria]["quota_minima"])
    delta = incidenza - minimo
    return {"stato": "sotto_indice_tabellare" if delta < 0 else "pari_o_superiore_all_indice",
        "categoria_codice": categoria, "categoria": INDICI[categoria]["categoria"],
        "tipo_commessa": tipo_commessa, "valore_opera": valore,
        "costo_manodopera_dichiarato": costo, "incidenza_dichiarata": incidenza,
        "indice_minimo_tabellare": minimo, "scostamento": delta,
        "fonte": dict(FONTE),
        "nota": "Confronto preliminare della percentuale dichiarata con l'indice tabellare. Non è attestazione di congruità: verificare disciplina applicabile, valore computabile, costi riconoscibili, varianti, subappalti, documentazione e procedura con i soggetti competenti."}
