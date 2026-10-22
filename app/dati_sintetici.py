"""
Generatore di dati sintetici.

Crea aziende FINTE con dati plausibili, in quattro settori, e inserisce
di proposito delle anomalie in una parte di esse. Ogni azienda porta con
se' una "verita' nascosta" (campo _irregolare) che serve SOLO per misurare
quante anomalie il motore riesce a riconoscere. Nessun dato reale, nessuna
persona reale.

Uso tipico:
    from app.dati_sintetici import genera_aziende
    aziende = genera_aziende(500, seme=42)
"""

import random


NOMI = ["Verde", "Rossi", "Sole", "Terra", "Orizzonte", "Ponte", "Aurora",
        "Granaio", "Cantiere", "Gusto", "Rapido", "Monte", "Fiume", "Borgo",
        "Stella", "Quercia", "Ulivo", "Spiga", "Mattone", "Ruota"]
SUFFISSI = ["S.r.l.", "S.n.c.", "S.a.s.", "S.p.A.", "& figli", "Soc. Coop."]
CITTA = ["Roma", "Latina", "Caserta", "Foggia", "Bari", "Napoli", "Milano",
         "Torino", "Palermo", "Catania", "Reggio Calabria", "Brescia"]


def _nome(rnd):
    return f"{rnd.choice(NOMI)} {rnd.choice(SUFFISSI)}"


def _azienda_agricola(rnd, irregolare):
    coltura = rnd.choice(["pomodoro", "uva", "olivo", "ortaggi", "cereali"])
    ettari = rnd.randint(5, 120)
    # manodopera "vera" implicita nella produzione
    if irregolare:
        # dichiara molti meno addetti del necessario
        dipendenti = max(1, rnd.randint(1, 3))
        costo_addetto = rnd.randint(5000, 9000)
    else:
        dipendenti = rnd.randint(4, 40)
        costo_addetto = rnd.randint(14000, 22000)
    return {
        "settore": "agricoltura",
        "coltura": coltura,
        "ettari": ettari,
        "dipendenti_dichiarati": dipendenti,
        "costo_lavoro_per_addetto": costo_addetto,
        "mezzi_agricoli": rnd.randint(1, 8),
    }


def _azienda_edile(rnd, irregolare):
    mc_getto = rnd.randint(50, 2000)
    mq_solaio = rnd.randint(100, 4000)
    valore_opera = (mc_getto * 300) + (mq_solaio * 180)  # stima grezza in euro
    if irregolare:
        dipendenti = max(1, rnd.randint(2, 4))
        costo_addetto = rnd.randint(6000, 11000)
        dpi = rnd.randint(1, 3)
    else:
        dipendenti = rnd.randint(6, 30)
        costo_addetto = rnd.randint(16000, 26000)
        dpi = dipendenti + rnd.randint(0, 5)
    return {
        "settore": "edilizia",
        "mc_getto": mc_getto,
        "mq_solaio": mq_solaio,
        "valore_opera": valore_opera,
        "dipendenti_dichiarati": dipendenti,
        "costo_lavoro_per_addetto": costo_addetto,
        "dpi_acquistati": dpi,
        "costo_manodopera_dichiarato": dipendenti * costo_addetto,
    }


def _azienda_ristorazione(rnd, irregolare):
    coperti_giorno = rnd.randint(40, 300)
    giorni_apertura = rnd.choice([5, 6, 7])
    kg_carne_settimana = coperti_giorno * giorni_apertura * 0.25 * rnd.uniform(0.8, 1.2)
    if irregolare:
        dipendenti = max(1, rnd.randint(1, 3))
        costo_addetto = rnd.randint(5000, 9000)
    else:
        dipendenti = rnd.randint(4, 20)
        costo_addetto = rnd.randint(13000, 20000)
    return {
        "settore": "ristorazione",
        "coperti_giorno_stimati": coperti_giorno,
        "giorni_apertura": giorni_apertura,
        "kg_materia_prima_settimana": round(kg_carne_settimana, 1),
        "dipendenti_dichiarati": dipendenti,
        "costo_lavoro_per_addetto": costo_addetto,
    }


def _azienda_logistica(rnd, irregolare):
    consegne_giorno = rnd.randint(50, 600)
    if irregolare:
        dipendenti = max(1, rnd.randint(1, 4))
        costo_addetto = rnd.randint(6000, 10000)
    else:
        dipendenti = rnd.randint(5, 40)
        costo_addetto = rnd.randint(15000, 24000)
    return {
        "settore": "logistica",
        "consegne_giorno": consegne_giorno,
        "mezzi": rnd.randint(2, 30),
        "dipendenti_dichiarati": dipendenti,
        "costo_lavoro_per_addetto": costo_addetto,
    }


_FABBRICHE = {
    "agricoltura": _azienda_agricola,
    "edilizia": _azienda_edile,
    "ristorazione": _azienda_ristorazione,
    "logistica": _azienda_logistica,
}


def genera_aziende(quante=500, quota_irregolari=0.25, seme=42):
    """Restituisce una lista di dizionari-azienda con verita' nascosta."""
    rnd = random.Random(seme)
    aziende = []
    for i in range(quante):
        settore = rnd.choice(list(_FABBRICHE.keys()))
        irregolare = rnd.random() < quota_irregolari
        dati = _FABBRICHE[settore](rnd, irregolare)
        dati["id"] = f"AZ{i:05d}"
        dati["ragione_sociale"] = _nome(rnd)
        dati["citta"] = rnd.choice(CITTA)
        dati["_irregolare"] = irregolare  # SOLO per la valutazione del motore
        aziende.append(dati)
    return aziende


if __name__ == "__main__":
    az = genera_aziende(10)
    for a in az:
        print(a["id"], a["settore"], a["ragione_sociale"],
              "irregolare" if a["_irregolare"] else "regolare")
