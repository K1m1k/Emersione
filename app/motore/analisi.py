"""Motore dichiarativo di analisi di indicatori.

Le formule, i controlli aggiuntivi e i moduli di ciascun settore sono letti dal
registro versionato (config/registro_emersione.json). Il nucleo non contiene
regole specifiche di un singolo settore: un nuovo settore si aggiunge con la
configurazione, senza modificare questo file (sezione 30.7 del capitolato).

Il punteggio è un indice tecnico di priorità sperimentale: non è una
probabilità di illecito né un accertamento.
"""
from __future__ import annotations

import copy
import math
from typing import Any

from app import moduli_settore
from app.settori import (
    STATI_ANALIZZABILI,
    ErroreRegistro,
    catalogo_parametri,
    descrizione_formula,
    lista_settori,
    valuta_formula,
)

VERSIONE_MOTORE = "emersione-motore-3.1"
MIN_GRUPPO_COMPARABILE = 10
VARIAZIONE_ROBUSTEZZA = 0.20
PUNTI_GRAVE, PUNTI_ATTENZIONE, PUNTI_COSTO = 50, 25, 20


def _numero(valore: Any) -> float | None:
    if isinstance(valore, bool) or valore is None or valore == "":
        return None
    try:
        numero = float(valore)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def _parametro_valore(parametri: dict[str, dict[str, Any]], parametro_id: str, predefinito: float = 0.0) -> float:
    parametro = parametri.get(parametro_id, {})
    valore = _numero(parametro.get("valore"))
    return valore if valore is not None else predefinito


def _campi_fuori_intervallo(azienda: dict[str, Any], settore: dict[str, Any]) -> list[str]:
    """Campi numerici presenti ma non validi rispetto alla definizione del settore."""
    problemi = []
    for campo, definizione in (settore.get("campi") or {}).items():
        if not isinstance(definizione, dict) or definizione.get("tipo") != "numero":
            continue
        grezzo = azienda.get(campo)
        if grezzo is None or grezzo == "":
            continue
        valore = _numero(grezzo)
        minimo, massimo = _numero(definizione.get("minimo")), _numero(definizione.get("massimo"))
        if valore is None:
            problemi.append(f"{campo} non numerico")
        elif minimo is not None and valore < minimo:
            problemi.append(f"{campo} inferiore al minimo {minimo:g}")
        elif massimo is not None and valore > massimo:
            problemi.append(f"{campo} superiore al massimo {massimo:g}")
    return problemi


def _addetti_attesi(azienda, settore, parametri_catalogo):
    if settore is None:
        return None, "Settore non configurato, sospeso, in revisione o non disponibile per l'analisi.", []
    fuori = _campi_fuori_intervallo(azienda, settore)
    if fuori:
        return None, "Stima non disponibile: dati non ammessi (" + "; ".join(fuori) + ").", []
    alternativi = settore.get("campi_almeno_uno") or []
    if alternativi and not any((_numero(azienda.get(c)) or 0) > 0 for c in alternativi):
        # I valori predefiniti a zero della formula valgono solo per le voci assenti
        # accanto ad almeno una voce dichiarata: senza alcuna quantità non c'è stima.
        return None, "Stima non disponibile: nessuna quantità dichiarata tra " + ", ".join(alternativi) + ".", []
    try:
        attesi, parametri_usati = valuta_formula(settore["stima"], azienda, parametri_catalogo)
    except (ErroreRegistro, KeyError, TypeError):
        return None, "Stima non disponibile: dati mancanti o configurazione da correggere.", []
    if attesi <= 0:
        return None, "Stima non disponibile: la produzione dichiarata corrisponde a zero addetti attesi.", []
    formula = descrizione_formula(settore["stima"], parametri_catalogo)
    fonti = ", ".join(
        f"{p['nome']}: {p.get('fonte', 'fonte non indicata')} [{p.get('stato', 'non verificato')}]"
        for p in parametri_usati
    )
    descrizione = f"Formula configurata: {formula}; risultato stimato {attesi:.2f} addetti equivalenti."
    if fonti:
        descrizione += f" Parametri: {fonti}."
    return attesi, descrizione, parametri_usati


def _mediana(valori: list[float]) -> float | None:
    valori = sorted(valori)
    n = len(valori)
    if not n:
        return None
    centro = n // 2
    if n % 2:
        return valori[centro]
    return (valori[centro - 1] + valori[centro]) / 2


def _stato_parametri(parametri: list[dict[str, Any]]) -> str:
    if any(p.get("stato") not in {"verificato", "approvato"} for p in parametri):
        return "sperimentale"
    return "verificato"


def _punti_manodopera(attesi: float | None, dipendenti: float | None, soglia_att: float, soglia_grave: float) -> tuple[int, float | None]:
    if attesi is None or attesi <= 0 or dipendenti is None:
        return 0, None
    scarto = (attesi - dipendenti) / attesi
    if scarto >= soglia_grave:
        return PUNTI_GRAVE, scarto
    if scarto >= soglia_att:
        return PUNTI_ATTENZIONE, scarto
    return 0, scarto


def livello_da_punteggio(punteggio: int) -> str:
    return "alto" if punteggio >= 60 else "medio" if punteggio >= 30 else "basso" if punteggio > 0 else "nessuno"


def _sostituisci(testo: str, valori: dict[str, float]) -> str:
    # Sostituzione testuale esplicita (niente str.format su testo di configurazione).
    for chiave, valore in valori.items():
        testo = testo.replace("{" + chiave + "}", f"{valore:g}")
    return testo


def _controllo_rapporto_minimo(controllo, azienda, parametri_catalogo):
    """numeratore < denominatore × coefficiente → segnale. Dati assenti: nessun segnale."""
    denominatore = _numero(azienda.get(controllo["denominatore"]))
    numeratore = _numero(azienda.get(controllo["numeratore"]))
    if denominatore is None or denominatore <= 0 or numeratore is None or numeratore < 0:
        return None
    pid = controllo["coefficiente"]
    minimo = _parametro_valore(parametri_catalogo, pid, 1.0)
    if numeratore >= denominatore * minimo:
        return None
    return {
        "tipo": controllo["id"],
        "gravita": controllo.get("gravita", "attenzione"),
        "punti": int(controllo.get("punti", 0)),
        "testo": _sostituisci(controllo.get("testo", "Rapporto {numeratore}/{denominatore} sotto la soglia {soglia}."),
                              {"numeratore": numeratore, "denominatore": denominatore, "soglia": minimo}),
        "parametri": [dict(id=pid, **parametri_catalogo[pid])] if pid in parametri_catalogo else [],
    }


def _rapporto_descrittivo(controllo, azienda):
    denominatore = _numero(azienda.get(controllo["denominatore"]))
    numeratore = _numero(azienda.get(controllo["numeratore"]))
    if denominatore is None or denominatore <= 0 or numeratore is None or numeratore < 0:
        return None
    return round(numeratore / denominatore, 5)


def _robustezza(settore, azienda, parametri_catalogo, parametri_formula, dipendenti,
                punti_altri: int, soglie: tuple[float, float], livello_base: str) -> dict[str, Any]:
    """Ricalcola il livello variando di ±20% ogni parametro della formula (uno alla volta).

    Se il livello cambia, il risultato è sensibile ai parametri e non deve essere
    presentato come affidabile (sezione 8 del capitolato).
    """
    if settore is None or not parametri_formula or dipendenti is None:
        return {"stato": "non_calcolata", "variazione": VARIAZIONE_ROBUSTEZZA, "livelli_osservati": [], "parametri_sensibili": []}
    osservati = {livello_base}
    sensibili: list[str] = []
    for p in parametri_formula:
        pid = p.get("id")
        base = _numero(parametri_catalogo.get(pid, {}).get("valore"))
        if pid is None or base is None:
            continue
        for fattore in (1 - VARIAZIONE_ROBUSTEZZA, 1 + VARIAZIONE_ROBUSTEZZA):
            perturbati = dict(parametri_catalogo)
            perturbati[pid] = dict(parametri_catalogo[pid], valore=base * fattore)
            try:
                attesi, _ = valuta_formula(settore["stima"], azienda, perturbati)
            except (ErroreRegistro, KeyError, TypeError):
                continue
            punti, _ = _punti_manodopera(attesi, dipendenti, *soglie)
            livello = livello_da_punteggio(min(100, punti + punti_altri))
            osservati.add(livello)
            if livello != livello_base and pid not in sensibili:
                sensibili.append(pid)
    return {
        "stato": "instabile" if len(osservati) > 1 else "stabile",
        "variazione": VARIAZIONE_ROBUSTEZZA,
        "livelli_osservati": sorted(osservati),
        "parametri_sensibili": sensibili,
    }


def analizza(aziende: list[dict[str, Any]], *, catalogo: tuple[dict[str, Any], dict[str, Any]] | None = None,
             settori_in_collaudo: set[str] | None = None) -> list[dict[str, Any]]:
    """Analizza record già validati e restituisce indicatori spiegati.

    catalogo: (settori, parametri) da usare al posto del registro corrente; serve
      per collaudi in ambiente isolato e per ricalcoli con configurazioni storiche.
    settori_in_collaudo: settori analizzati anche se non attivi, con esito marcato
      "collaudo" (non deve mai alimentare risultati operativi).

    Un dato non utilizzabile non diventa zero: l'analisi risulta non valutabile.
    """
    if not isinstance(aziende, list):
        raise TypeError("aziende deve essere una lista")
    settori_in_collaudo = set(settori_in_collaudo or ())

    if catalogo is None:
        parametri_catalogo = catalogo_parametri()
        settori_catalogo = {s["id"]: s for s in lista_settori(includi_archiviati=True)}
    else:
        settori_catalogo = {sid: {"id": sid, **cfg} for sid, cfg in copy.deepcopy(catalogo[0]).items()}
        parametri_catalogo = copy.deepcopy(catalogo[1])

    valori_per_settore: dict[str, list[float]] = {}
    for azienda in aziende:
        if not isinstance(azienda, dict):
            continue
        settore = azienda.get("settore")
        costo = _numero(azienda.get("costo_lavoro_per_addetto"))
        if isinstance(settore, str) and costo is not None and costo >= 0:
            valori_per_settore.setdefault(settore, []).append(costo)
    mediane = {settore: _mediana(valori) for settore, valori in valori_per_settore.items()}
    numerosita = {settore: len(valori) for settore, valori in valori_per_settore.items()}

    soglia_att = _parametro_valore(parametri_catalogo, "scarto_manodopera_attenzione", 0.30)
    soglia_grave = _parametro_valore(parametri_catalogo, "scarto_manodopera_grave", 0.60)
    soglia_costo = _parametro_valore(parametri_catalogo, "costo_addetto_scarto", 0.40)

    for azienda in aziende:
        if not isinstance(azienda, dict):
            continue
        settore_id = azienda.get("settore")
        settore_cfg = settori_catalogo.get(settore_id) if isinstance(settore_id, str) else None
        in_collaudo = settore_id in settori_in_collaudo
        if settore_cfg is not None and settore_cfg.get("stato") not in STATI_ANALIZZABILI and not in_collaudo:
            settore_cfg = None

        segnali: list[dict[str, Any]] = []
        punti_altri = 0
        attesi, descrizione_calcolo, parametri_formula = _addetti_attesi(azienda, settore_cfg, parametri_catalogo)
        dipendenti = _numero(azienda.get("dipendenti_dichiarati"))
        valutabile = settore_cfg is not None and attesi is not None and dipendenti is not None and dipendenti >= 0

        punti_mano = 0
        if valutabile:
            punti_mano, scarto = _punti_manodopera(attesi, dipendenti, soglia_att, soglia_grave)
            if punti_mano:
                segnali.append({
                    "tipo": "manodopera", "gravita": "grave" if punti_mano == PUNTI_GRAVE else "attenzione",
                    "testo": (f"Stima sperimentale: circa {attesi:.1f} addetti equivalenti rispetto a "
                              f"{dipendenti:g} dichiarati; scarto relativo {scarto * 100:.1f}%. "
                              f"{descrizione_calcolo}"),
                    "parametri": parametri_formula,
                })

        # Confronto omesso su gruppi troppo piccoli: una mediana instabile non deve
        # produrre segnalazioni apparentemente oggettive.
        costo = _numero(azienda.get("costo_lavoro_per_addetto"))
        mediana = mediane.get(settore_id)
        n_pari = numerosita.get(settore_id, 0)
        if costo is not None and costo >= 0 and mediana is not None and mediana > 0 and n_pari >= MIN_GRUPPO_COMPARABILE:
            diff = (mediana - costo) / mediana
            if diff >= soglia_costo:
                punti_altri += PUNTI_COSTO
                segnali.append({
                    "tipo": "costo_lavoro", "gravita": "attenzione",
                    "testo": (f"Costo del lavoro per addetto {costo:.2f} rispetto alla mediana osservata "
                              f"di {mediana:.2f} ({diff * 100:.1f}% inferiore; gruppo di {n_pari} record). "
                              "Confronto grezzo, non corretto per dimensione, territorio, orario o mansione."),
                    "parametri": [],
                })

        # Controlli aggiuntivi dichiarati dal settore (nessuna regola codificata per nome di settore).
        descrittivi: dict[str, Any] = {}
        moduli_risultati: dict[str, Any] = {chiave: None for chiave in moduli_settore.CHIAVI_RISULTATO}
        sorgente_controlli = settori_catalogo.get(settore_id) if isinstance(settore_id, str) else None
        for controllo in (sorgente_controlli or {}).get("controlli", []):
            if controllo.get("tipo") == "rapporto_minimo":
                segnale = _controllo_rapporto_minimo(controllo, azienda, parametri_catalogo)
                if segnale:
                    punti_altri += segnale.pop("punti")
                    segnali.append(segnale)
            elif controllo.get("tipo") == "rapporto_descrittivo":
                descrittivi[controllo["chiave_risultato"]] = _rapporto_descrittivo(controllo, azienda)
        for nome_modulo in (sorgente_controlli or {}).get("moduli", []):
            try:
                chiave, valore = moduli_settore.esegui(nome_modulo, azienda)
            except KeyError:
                continue
            moduli_risultati[chiave] = valore

        if not valutabile:
            punteggio = None
            livello = "non_valutabile"
            stato_metodologico = "non_valutabile"
            robustezza = {"stato": "non_calcolata", "variazione": VARIAZIONE_ROBUSTEZZA, "livelli_osservati": [], "parametri_sensibili": []}
        else:
            punteggio = min(100, punti_mano + punti_altri)
            livello = livello_da_punteggio(punteggio)
            parametri_segnali = [p for segnale in segnali for p in segnale.get("parametri", [])]
            stato_metodologico = _stato_parametri(parametri_formula + parametri_segnali)
            if settore_cfg.get("stato") != "approvato":
                stato_metodologico = "sperimentale"
            if in_collaudo:
                stato_metodologico = "collaudo"
            robustezza = _robustezza(settore_cfg, azienda, parametri_catalogo, parametri_formula, dipendenti,
                                     punti_altri, (soglia_att, soglia_grave), livello)

        limitazioni = []
        if stato_metodologico != "verificato":
            limitazioni = [
                "I coefficienti contrassegnati da FONTE DA VERIFICARE non sono validati.",
                "Il punteggio è un indicatore sperimentale e non una probabilità di illecito.",
            ]
        if robustezza["stato"] == "instabile":
            limitazioni.append(
                f"Risultato sensibile ai parametri: con una variazione di ±{int(VARIAZIONE_ROBUSTEZZA * 100)}% "
                f"di {', '.join(robustezza['parametri_sensibili'])} il livello cambia "
                f"({', '.join(robustezza['livelli_osservati'])}). Non presentarlo come risultato affidabile."
            )

        azienda["analisi"] = {
            "punteggio": punteggio,
            "livello": livello,
            "segnali": segnali,
            "addetti_attesi": round(attesi, 2) if attesi is not None else None,
            "stato_metodologico": stato_metodologico,
            "formula": descrizione_calcolo,
            # Copia dei parametri effettivamente impiegati: rende l'analisi ricostruibile.
            "parametri_formula": parametri_formula,
            "incidenza_manodopera_descrittiva": descrittivi.get("incidenza_manodopera_descrittiva"),
            **moduli_risultati,
            "descrittivi": descrittivi,
            "confronto_pari_n": numerosita.get(settore_id, 0),
            "robustezza": robustezza,
            "versione_motore": VERSIONE_MOTORE,
            "versione_configurazione_settore": (settori_catalogo.get(settore_id) or {}).get("versione_configurazione", 1)
            if isinstance(settore_id, str) else None,
            "limitazioni": limitazioni,
        }
    return aziende


def valuta_motore(aziende: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compatibilità: metriche su record che portano un'etichetta booleana `_irregolare`.

    Il percorso consigliato è app.motore.valutazione (etichette separate dai dati).
    """
    from app.motore.valutazione import valuta_motore as _valuta
    if not aziende or any("_irregolare" not in a or not isinstance(a.get("_irregolare"), bool) for a in aziende):
        return None
    if any(not isinstance(a.get("analisi"), dict) or not isinstance(a["analisi"].get("punteggio"), (int, float)) for a in aziende):
        return None
    etichette = {a["id"]: a["_irregolare"] for a in aziende}
    m = _valuta(aziende, etichette, "sintetiche")
    if not m.get("valutabile"):
        return None
    mat = m["matrice"]
    return {
        "veri_positivi": mat["veri_positivi"], "falsi_positivi": mat["falsi_positivi"],
        "veri_negativi": mat["veri_negativi"], "falsi_negativi": mat["falsi_negativi"],
        "aziende_totali": len(aziende),
        "precisione": m["precisione"]["valore"], "recupero": m["richiamo"]["valore"],
        "specificita": m["specificita"]["valore"], "tasso_falsi_positivi": m["tasso_falsi_positivi"]["valore"],
        "nota": "Metriche su etichette sintetiche; non descrivono l'accuratezza su aziende reali.",
    }
