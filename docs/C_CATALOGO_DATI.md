# C. Catalogo dei dati

Stato verificato il 22 ottobre 2026 durante lo sviluppo. Nessun endpoint è stato interrogato dal vivo dall'ambiente di sviluppo, perché la rete esterna era bloccata: tutti i connettori sono provati con risposte simulate.

## Fonti pubbliche

| Fonte | Accesso | Formato | Licenza / condizioni | Limiti | Stato nel software |
|---|---|---|---|---|---|
| ISTAT, servizio SDMX | `https://esploradati.istat.it/SDMXWS/rest`, agenzia `IT1` | SDMX-ML 2.1 | accesso gratuito; licenza da verificare sul sito ISTAT | **5 richieste/minuto per IP**, blocco di 1–2 giorni se superato; il client si ferma a 4/minuto | scoperta dei dataflow (`/dataflow/IT1`) e acquisizione da URL scelto; da verificare dal vivo |
| INAIL, Open Data API | 5 endpoint `https://dati.inail.it/api/OpenData/...` (vedi `fonti_live.py`) | JSON/CSV | da verificare | 30 richieste/minuto lato client | acquisizione puntuale; da verificare dal vivo |
| ANAC, Open Data | portale `https://dati.anticorruzione.it/opendata`; dati OCDS | OCDS JSON/JSONL, CSV, XLSX | CC BY 4.0 (fonte: Open Contracting Partnership, publication 117); aggiornamento mensile dichiarato | 30 richieste/minuto lato client | acquisizione da URL diretto; **scoperta non configurata**: in sviluppo non è stata trovata documentazione ufficiale di un'API di catalogo, quindi va abilitata con `EMERSIONE_ANAC_CATALOGO_API` solo dopo verifica |
| D.M. 143/2021 (congruità edilizia) | Ministero del Lavoro (link in `INDICI_EDILIZIA.md`) | tabella PDF | atto normativo | — | 17 indici trascritti; tabella confrontata con due fonti secondarie indipendenti (ANCE Ragusa, Cassa Edile di Milano) con valori identici |
| Bilanci / Registro Imprese | servizi a pagamento o convenzionati | — | contratto | — | **non integrato**: richiede accesso autorizzato |

Fonti dei limiti e degli indirizzi: [ISTAT, SDMX web services](https://www.istat.it/en/classifications-and-tools/sdmx-web-services); [istatR, documentazione](https://cloud.r-project.org/web/packages/istatR/readme/README.html); [ANAC su Open Contracting Partnership](https://data.open-contracting.org/en/publication/117).

## Dati riservati
Arrivano solo tramite import CSV di un ente legittimato. Per ogni lotto si registrano conferente, titolare, finalità, autorizzazione dichiarata, data di ricezione, scadenza e condizioni d'uso (`app/provenienza.py`). Con autorizzazione scaduta il sistema sospende relazioni, esportazioni e nuove pratiche. La revoca rimuove il lotto dall'uso operativo.

## Schema dell'import CSV
- Obbligatori: `id`, `settore`, `dipendenti_dichiarati`, più i campi obbligatori del settore.
- Facoltativi trasversali: `costo_lavoro_per_addetto`, `ragione_sociale`, `citta`, `dpi_acquistati`, `valore_opera`, `costo_manodopera_dichiarato`, `categoria_opera`, `tipo_commessa`, identificativi per il grafo.
- La colonna `_irregolare`, se presente, viene separata dai dati e mai usata dal motore.
- Limiti: 5 MiB, 25.000 righe, 100 colonne.

## Dati derivati
Le osservazioni normalizzate dalle mappature non entrano nel punteggio. Possono solo generare **proposte** di valore per un parametro, che un revisore diverso dal proponente decide se applicare. Quando applicata, la proposta crea una nuova versione del parametro "da verificare" e riapre la revisione dei settori che lo usano.

## Qualità
Ogni payload acquisito ha URL, data, formato e SHA-256. I documenti hanno SHA-256 e pagina o riga dei valori estratti. I valori estratti automaticamente sono sempre "da verificare".
