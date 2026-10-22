# D. Metodologia di analisi

## Principio
Ogni risultato è un **indicatore da verificare**. L'indice 0–100 è un ordine di priorità tecnico: **non è una probabilità di illecito**.

## Stima della manodopera
Per ogni settore il registro contiene una formula dichiarativa: campi, coefficienti, somma, prodotto, divisione, costanti e scelta del coefficiente per categoria. Non viene eseguito codice arbitrario. Il risultato deve avere dimensione "addetti": il collaudo verifica l'analisi dimensionale (`app/unita.py`).

| Settore | Formula (coefficienti tutti da verificare) | Dimensioni |
|---|---|---|
| Agricoltura | ettari × ore/(ettaro·anno) per coltura ÷ ore/(addetto·anno) | ettaro · ora/(ettaro·anno) / (ora/(addetto·anno)) = addetto |
| Edilizia | (m³/anno × ore/m³ + m²/anno × ore/m² + …) ÷ ore/(addetto·anno) | addetto |
| Ristorazione | coperti/giorno ÷ coperti/(addetto·giorno) | addetto |
| Logistica | consegne/giorno ÷ consegne/(addetto·giorno) | addetto |

**Correzione v3.1 in edilizia:** le quantità ora sono esplicitamente "realizzate nell'anno di riferimento". Prima la formula divideva quantità senza periodo per ore annue, e il risultato aveva dimensione addetti × anno. Per un singolo cantiere serve la durata dei lavori, oggi non gestita.

## Segnali e punteggio
| Segnale | Condizione | Punti |
|---|---|---|
| Manodopera, grave | scarto ≥ 60% (soglia configurabile) | 50 |
| Manodopera, attenzione | scarto ≥ 30% | 25 |
| Costo del lavoro | ≥ 40% sotto la mediana del settore, solo con almeno 10 aziende comparabili | 20 |
| DPI (edilizia, dichiarato nel registro) | DPI acquistati < addetti × 1 | 10 |

Livelli: alto ≥ 60, medio ≥ 30, basso > 0, nessuno = 0, non valutabile se mancano i dati.

**Doppio conteggio:** manodopera e costo del lavoro dipendono entrambi dagli addetti dichiarati e non sono indipendenti. Il sistema non corregge questa correlazione e lo dichiara. Una correzione richiede dati etichettati reali.

## Dati mancanti e non comparabili
- Un dato assente, vuoto, non numerico, infinito o fuori dall'intervallo del campo **non diventa mai zero**: l'analisi risulta "non valutabile" con il motivo.
- Le voci alternative di un settore (es. le quantità edilizie) possono valere zero solo se almeno una è dichiarata. Se mancano tutte, la stima non c'è (difetto della v3 trovato dal collaudo e corretto).
- I gruppi di confronto con meno di 10 aziende non producono segnali.
- Il confronto per territorio e dimensione **non è attivato**: con i dati disponibili i gruppi sarebbero troppo piccoli (sezione 8 del capitolato). Le prestazioni per territorio e dimensione sono comunque misurate nella pagina di valutazione.

## Robustezza
Per ogni azienda valutabile il livello viene ricalcolato variando ogni parametro della formula di ±20%, uno alla volta. Se il livello cambia, il risultato è marcato **instabile**, elenca i parametri responsabili e non va presentato come affidabile. Sul dataset sintetico di prova risultano instabili 74 aziende su 500.

## Screening D.M. 143/2021
È un modulo separato e non incide sul punteggio. Confronta l'incidenza dichiarata con l'indice della categoria. Non è un'attestazione di congruità (vedi `INDICI_EDILIZIA.md`).

## Coefficienti
Ogni parametro ha natura dichiarata (norma, dato statistico, stima tecnica, ipotesi sperimentale, soglia configurabile, regola interna), stato, versione, storico e riferimento alla fonte (titolo, URL, articolo o tabella, date, periodo di validità, territorio, condizioni d'uso, responsabile). Per dichiararlo verificato servono riferimento completo, documento caricato e collegato, nota motivata e il ruolo di revisore. **Oggi tutti i coefficienti di settore sono ipotesi sperimentali "da verificare"**, tranne gli indici del D.M. 143/2021, che stanno nel loro modulo.

## Validazione
Le metriche (matrice di confusione, precisione, richiamo, specificità, tassi di falsi positivi e negativi con intervallo di Wilson al 95%, per settore, territorio e dimensione) si calcolano solo con etichette di riferimento separate dai dati. Sul dataset sintetico sono **un test del software, non una prestazione reale**: il generatore crea le anomalie con le stesse grandezze che il motore misura. La soglia di segnalazione (≥ 30) è fissa e non ottimizzata sulle etichette.
