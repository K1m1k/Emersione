# Verifiche eseguite e verifiche non ancora possibili (sezione 26)

## Ambiente di collaudo (22 ottobre 2026)
Linux, Python 3.13.16. Rete esterna non disponibile per pip né per le fonti: nessun pacchetto installato o aggiornato, nessun endpoint interrogato dal vivo.

| Pacchetto | Vincolo in `requirements.txt` | Versione usata nei test locali |
|---|---|---|
| starlette | 1.7.0 | 1.7.0 |
| uvicorn | 0.53.0 | **0.54.0** |
| jinja2 | 3.1.6 | 3.1.6 |
| python-multipart | 0.0.32 | 0.0.32 |
| itsdangerous | 2.2.0 | 2.2.0 |
| reportlab | 4.4.9 | **5.0.1** |
| pypdf | 6.21.1 | **5.9.0** |
| httpx (sviluppo) | 0.28.1 | non installato; il client di test ha usato il pacchetto `httpx2` presente |

## Integrazione continua su GitHub (22 ottobre 2026)
Il workflow `.github/workflows/test.yml` installa in un ambiente pulito (Ubuntu, Python 3.13) **esattamente le versioni bloccate** e a ogni modifica esegue:
```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m unittest discover -s tests -v
pip-audit -r requirements.txt
```
| Verifica | Esito |
|---|---|
| Suite completa con le versioni bloccate | **superata** |
| `pip-audit` con starlette 0.50.0 e pypdf 6.21.0 | 11 vulnerabilità note (10 starlette, 1 pypdf) |
| Aggiornamento a starlette 1.7.0 e pypdf 6.21.1 | **superato**: test verdi, nessuna vulnerabilità nota |

L'esito di ogni esecuzione è pubblico nella scheda *Actions* del repository.

Se un test fallisce con le versioni bloccate, la correzione va fatta e documentata prima dell'uso.

## Verifiche eseguite
| Verifica | Esito |
|---|---|
| `python -m compileall -q app config tests` | superata |
| `python -m unittest discover -s tests` | **116 test superati** |
| Regressione dei risultati sintetici (500 aziende, seme 42) prima e dopo le modifiche | identica (impronta `cb82abaf…19bf`) |
| Collaudo automatico dei 4 settori iniziali e del settore dimostrativo "servizi di pulizia" | superato |
| Isolamento dei test: nessun file scritto in `dati/` o `config/` | verificato |
| Server reale (uvicorn): login, pagine principali, relazione PDF, verifica d'integrità, intestazioni, correlazione, audit, backup | superato |
| Apertura di tutte le 500 schede e di relazioni PDF edilizie | superata (dopo la correzione di un difetto della v3) |
| Prestazioni del motore: 500 / 5.000 / 25.000 record | 0,04 / 0,41 / 2,40 s, robustezza inclusa |
| Tabella D.M. 143/2021 confrontata con due fonti secondarie indipendenti | 17 valori identici |
| Endpoint ISTAT e limite di 5 richieste/minuto | verificati sulla pagina ufficiale ISTAT |

## Difetti trovati e corretti durante questo lavoro
1. Edilizia: senza alcuna quantità, i valori predefiniti a zero producevano "nessuna anomalia" invece di "non valutabile" (trovato dal collaudo automatico).
2. Edilizia: incoerenza dimensionale (quantità senza periodo divise per ore annue).
3. Estrattore documentale: "1100" veniva letto come "110".
4. Scheda azienda: errore 500 su 136 aziende edilizie con dati di screening incompleti.
5. Controlli e validazioni legati al nome "edilizia" nel codice: ora dichiarati nel registro.
6. Etichette di valutazione mescolate ai dati analizzati: ora separate.
7. Test che scrivevano negli archivi reali del progetto: ora isolati.
8. Ruolo registrato nell'audit sempre come "amministratore" in alcune operazioni: ora quello reale.

## Verifiche non ancora possibili
| Verifica | Motivo | Chi |
|---|---|---|
| Test con le versioni bloccate delle dipendenze e `pip-audit` | rete assente | ente / sviluppatore, comando sopra |
| Connettori ISTAT, INAIL e ANAC dal vivo | rete assente | ente, in rete controllata |
| Esistenza di un'API di catalogo ANAC | non documentata nelle fonti consultate | ente |
| Revisione di sicurezza indipendente e test di penetrazione | richiede soggetto terzo | ente |
| Accessibilità con utenti e tecnologie assistive, contrasto | solo controlli automatici svolti | ente |
| Validazione dei coefficienti e delle metriche su dati reali | dati ed etichette non disponibili | ente ed esperti |
| Valutazioni GDPR, DPIA e AI Act | competenza giuridica | titolare, DPO, consulenti |
| Backup e ripristino nell'ambiente di produzione | ambiente non disponibile | ente |
| Comportamento con più processi o più nodi | progettato per un solo processo | ente |
