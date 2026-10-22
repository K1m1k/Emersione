"""
Valutazione del motore contro etichette di riferimento.

Regole:
  - le etichette NON stanno nei dati che il motore analizza: vengono estratte
    prima dell'analisi (estrai_etichette) e tenute a parte;
  - le metriche si calcolano soltanto per le aziende che hanno un'etichetta
    valida E un risultato valutabile; se non ci sono etichette di riferimento
    il sistema si rifiuta di presentare metriche;
  - ogni valutazione dichiara l'origine delle etichette. Le metriche ottenute
    su dati sintetici sono un TEST DEL SOFTWARE, non una misura di
    prestazione sul mondo reale: il generatore costruisce le anomalie con le
    stesse grandezze che il motore misura, quindi il risultato e' circolare.
"""

import math

SOGLIA_PUNTEGGIO = 30  # livello "medio"; scelta fissa, NON ottimizzata sulle etichette

_VERI = {"true", "1", "si", "sì", "vero", "yes"}
_FALSI = {"false", "0", "no", "falso"}


def _a_bool(x):
    """Converte in modo rigoroso; restituisce None se non interpretabile."""
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if x == 1:
            return True
        if x == 0:
            return False
        return None
    if isinstance(x, str):
        t = x.strip().lower()
        if t in _VERI:
            return True
        if t in _FALSI:
            return False
    return None


def estrai_etichette(aziende, campo):
    """Rimuove 'campo' da ogni azienda e restituisce {id: bool} per le sole
    aziende con id univoco e etichetta interpretabile. Le altre vengono
    semplicemente escluse dalla valutazione (mai trattate come 'regolari')."""
    conteggio = {}
    for a in aziende:
        conteggio[a.get("id")] = conteggio.get(a.get("id"), 0) + 1
    etichette = {}
    for a in aziende:
        grezza = a.pop(campo, None)
        az_id = a.get("id")
        if az_id in (None, "") or conteggio[az_id] != 1:
            continue
        valore = _a_bool(grezza)
        if valore is not None:
            etichette[az_id] = valore
    return etichette


def intervallo_wilson(successi, totale, z=1.96):
    """Intervallo di confidenza di Wilson (95% di default). None se totale = 0."""
    if totale == 0:
        return None
    p = successi / totale
    den = 1 + z * z / totale
    centro = (p + z * z / (2 * totale)) / den
    scarto = z * math.sqrt(p * (1 - p) / totale + z * z / (4 * totale * totale)) / den
    return (round(max(0.0, centro - scarto), 3), round(min(1.0, centro + scarto), 3))


def _rapporto(num, den):
    if den == 0:
        return {"valore": None, "ic95": None, "n": 0}
    return {"valore": round(num / den, 3), "ic95": intervallo_wilson(num, den), "n": den}


def valuta_motore(aziende, etichette, tipo_etichette=None, soglia=SOGLIA_PUNTEGGIO):
    """Confronta i punteggi con le etichette di riferimento.

    tipo_etichette: None (nessuna), "sintetiche" (test del software) oppure
    "dichiarate" (fornite da un ente, non verificate dal sistema).
    """
    if not etichette or not tipo_etichette:
        return {
            "valutabile": False,
            "motivo": ("Nessuna etichetta di riferimento validata nei dati: le metriche di "
                       "precisione non vengono calcolate. Un risultato del motore senza "
                       "etichette indipendenti non e' misurabile."),
        }

    tp = fp = tn = fn = 0
    non_valutabili = senza_etichetta = 0
    for a in aziende:
        punteggio = a["analisi"]["punteggio"]
        if punteggio is None:
            non_valutabili += 1
            continue
        if a.get("id") not in etichette:
            senza_etichetta += 1
            continue
        segnalata = punteggio >= soglia
        reale = etichette[a["id"]]
        if segnalata and reale:
            tp += 1
        elif segnalata:
            fp += 1
        elif reale:
            fn += 1
        else:
            tn += 1

    n = tp + fp + tn + fn
    if n == 0:
        return {"valutabile": False,
                "motivo": "Nessuna azienda ha insieme un'etichetta valida e un risultato valutabile."}

    return {
        "valutabile": True,
        "tipo_etichette": tipo_etichette,
        "avviso": (
            "Test sintetico: misura il funzionamento del software, non la prestazione sul "
            "mondo reale (il generatore crea le anomalie con le stesse grandezze che il "
            "motore misura)." if tipo_etichette == "sintetiche" else
            "Etichette dichiarate dall'ente conferente e non verificate dal sistema: "
            "le metriche valgono solo quanto l'indipendenza e la correttezza di quelle etichette."),
        "soglia_punteggio": soglia,
        "criterio_soglia": "soglia fissa (livello 'medio'), non ottimizzata sulle etichette",
        "casi_valutati": n,
        "esclusi_non_valutabili": non_valutabili,
        "esclusi_senza_etichetta": senza_etichetta,
        "classi": {"irregolari": tp + fn, "regolari": tn + fp},
        "matrice": {"veri_positivi": tp, "falsi_positivi": fp, "veri_negativi": tn, "falsi_negativi": fn},
        "precisione": _rapporto(tp, tp + fp),
        "richiamo": _rapporto(tp, tp + fn),
        "specificita": _rapporto(tn, tn + fp),
        "tasso_falsi_positivi": _rapporto(fp, fp + tn),
        "tasso_falsi_negativi": _rapporto(fn, fn + tp),
    }


def classe_dimensionale(azienda) -> str:
    try:
        n = float(azienda.get("dipendenti_dichiarati"))
    except (TypeError, ValueError):
        return "non indicata"
    return "1-9 addetti" if n < 10 else "10-49 addetti" if n < 50 else "50 e oltre"


def per_gruppo(aziende, etichette, tipo_etichette, chiave, minimo=20, soglia=SOGLIA_PUNTEGGIO):
    """Metriche separate per gruppo (settore, territorio, dimensione).

    I gruppi con meno di `minimo` casi valutabili sono indicati ma senza metriche:
    numeri su campioni minuscoli darebbero un'impressione di precisione infondata.
    """
    gruppi = {}
    for a in aziende:
        gruppi.setdefault(str(chiave(a) or "non indicato"), []).append(a)
    righe = []
    for nome, membri in sorted(gruppi.items()):
        m = valuta_motore(membri, etichette, tipo_etichette, soglia)
        if not m.get("valutabile") or m["casi_valutati"] < minimo:
            righe.append({"gruppo": nome, "casi": m.get("casi_valutati", 0), "sufficiente": False})
            continue
        righe.append({"gruppo": nome, "casi": m["casi_valutati"], "sufficiente": True,
                      "precisione": m["precisione"], "richiamo": m["richiamo"],
                      "tasso_falsi_positivi": m["tasso_falsi_positivi"], "classi": m["classi"]})
    return righe
