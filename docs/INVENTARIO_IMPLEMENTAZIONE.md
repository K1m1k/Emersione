> **Nota (v3.1):** questo inventario descrive la v3. Lo stato aggiornato è in `I_MATRICE_REQUISITI.md`, i limiti in `H_LIMITI_NOTI.md` e le verifiche in `VERIFICHE.md`.

# Emersione v3 — inventario funzionale e limiti verificati

Questo inventario distingue ciò che è implementato nel codice da ciò che richiede integrazione o validazione esterna. La presenza di un modulo non equivale alla sua approvazione per uso istituzionale.

| Area | Stato nel prototipo | Evidenza / limite residuo |
|---|---|---|
| Login locale, sessioni, ruoli, CSRF | Implementato a livello prototipo | Non integrato con provider identità dell'ente; review di sicurezza indipendente necessaria |
| Import CSV del lotto attivo | Implementato | Validazione e aggiornamento atomico; storico operativo completo non presente |
| Configurazione dinamica dei settori | Implementato | Nuovi settori/campi/formule tramite configurazione dichiarativa; formula e metodologia richiedono revisione |
| Coefficienti statistici settoriali | Parziale | Molti valori restano sperimentali o `FONTE DA VERIFICARE`; non presentare come ufficiali |
| Screening edilizio D.M. 143/2021 | Implementato come screening preliminare | Non equivale a verifica ufficiale di congruità; applicabilità e disciplina aggiornata da verificare per ogni caso |
| API Open Data INAIL | Connettore puntuale implementato | Test con risposta simulata; endpoint, schema e disponibilità vanno verificati live prima dell'uso |
| ISTAT SDMX | Acquisizione da URL scelto dall'operatore | Nessuna scelta automatica di dataflow né normalizzazione semantica automatica |
| ANAC Open Data | Acquisizione da URL diretto consentito | Non esplora automaticamente catalogo e dataset; mapping configurato dall'operatore |
| Archivio payload fonti | Implementato in SQLite locale | Hash SHA-256 e download verificato; non è archivio probatorio o immutabile |
| Mapping e normalizzazione dataset | Implementato con passaggio esplicito | Osservazioni non entrano automaticamente nel motore/punteggio; significato e pertinenza richiedono revisione |
| OSINT | Acquisizione di singola pagina da allowlist | No crawler, schedulazione, verifica incrociata né analisi automatica della veridicità |
| Grafo aziende | Relazioni documentate manualmente e alcuni suggerimenti esatti | No riconciliazione automatica con registri societari/appalti ufficiali |
| Estrazione documenti | Candidati numerici/testuali da PDF testuale/TXT/CSV/JSON | No OCR; estrazione di tabelle/formule complesse non implementata; nessuna approvazione automatica |
| Report PDF | Implementato | Report descrittivo, non atto amministrativo né attestazione |
| Audit | JSON Lines con catena hash locale | Non impedisce da solo manomissione o cancellazione della coda; manca ancoraggio indipendente e raccolta centralizzata |
| Database di produzione | Non implementato | Persistenza locale SQLite; mancano architettura multiistanza, retention formalizzata e disaster recovery collaudato |
| Test automatizzati | 46 test superati nell'ambiente disponibile | I test di rete sono simulati; le prestazioni reali e gli endpoint live non sono validati |
| Dipendenza pypdf | Versione 6.21.1, verificata | Installazione pulita e suite completa superate nell'integrazione continua su GitHub; nessuna vulnerabilità nota (`pip-audit`) |
| Aggiornamento Starlette | Migrato a 1.7.0, verificato | La 0.50.0 aveva 10 vulnerabilità note; con la 1.7.0 la suite completa passa nell'integrazione continua su GitHub |
| Sicurezza indipendente | Non eseguita | Richiede threat modeling, test di penetrazione e revisione esterna |
| Validazione scientifica su dati reali | Non eseguita | Richiede etichette di riferimento lecite, campione rappresentativo e misure di falsi positivi/falsi negativi |
| Valutazioni privacy/AI Act | Non eseguite | Da svolgere con l'ente titolare, DPO e consulenti competenti sulla funzione effettiva |

## Significato dei test

Il superamento dei test indica che specifici percorsi del codice si comportano come previsto nei casi testati. Non dimostra conformità normativa, robustezza contro tutte le minacce, correttezza di fonti esterne, validità scientifica dei coefficienti o accuratezza nell'individuare irregolarità reali.

## Gate minimi prima di un pilota istituzionale

1. Creare un ambiente virtuale pulito e installare esattamente `requirements.txt` e `requirements-dev.txt`.
2. Ripetere compilazione e suite completa con tutte le dipendenze dichiarate.
3. Verificare in rete controllata gli endpoint attivi e documentare risposta, schema, licenza, freschezza e copertura dei dataset.
4. Effettuare review indipendente di autenticazione, sessioni, CSRF, SSRF, upload, separazione ruoli, audit e gestione segreti.
5. Definire titolarità, finalità, base giuridica, accessi, conservazione e procedure di rettifica per ogni categoria di dato.
6. Validare metodologie, coefficienti e metriche con esperti e dataset di riferimento rappresentativi.
7. Implementare database e audit coerenti con requisiti dell'ente, backup e prove di ripristino, monitoraggio e incident response.
8. Ottenere approvazioni formali prima di trattare dati riservati o utilizzare risultati in decisioni operative.
