# Emersione 3.1 — registro delle modifiche

## Pubblicazione su GitHub (22 ottobre 2026)
- Licenze: EUPL-1.2 per il codice, CC BY 4.0 per la documentazione.
- Aggiunti `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CITATION.cff`, `publiccode.yml`, modelli di issue e pull request.
- Integrazione continua: test con le versioni bloccate e controllo delle vulnerabilità (`pip-audit`) a ogni modifica.
- Sicurezza delle dipendenze: starlette da 0.50.0 a **1.7.0** (10 vulnerabilità note corrette), pypdf da 6.21.0 a **6.21.1** (1 vulnerabilità nota corretta). Suite completa superata con le nuove versioni.
- Chiusa la verifica aperta sull'installazione pulita con le versioni bloccate (vedi `docs/VERIFICHE.md`).
- Documentazione sull'intelligenza artificiale riorganizzata in `docs/J_INTELLIGENZA_ARTIFICIALE.md`, `docs/K_ROADMAP_IA.md`, `docs/L_PROSPETTIVE_E_COLLABORAZIONI.md`.

## Estensibilità (sezione 30)
- Ciclo di vita dei settori: bozza, in revisione, verificata tecnicamente, validazione metodologica, verifica normativa, approvata per la sperimentazione, approvata, sospesa, archiviata. Un nuovo settore nasce in bozza e non produce risultati operativi.
- Collaudo automatico isolato: struttura, formula, riferimenti, unità di misura, casi normali/limite/incompleti/errati, riproducibilità, tracciabilità, non interferenza.
- Approvazioni con separazione dei compiti; "approvato" richiede parametri verificati e un documento di evidenza.
- Storico completo del registro, confronto e ripristino delle versioni, ricostruzione della configurazione delle analisi storiche.
- Analisi d'impatto e mappa delle dipendenze; rifiuto dei cicli nelle relazioni di derivazione.
- Analisi dimensionale delle formule.
- Controlli e moduli di settore dichiarati nel registro: il nucleo non contiene più regole per nome di settore.
- Settore dimostrativo "servizi di pulizia" nel collaudo dei 15 scenari di accettazione.

## Motore e valutazione
- Robustezza: variazione di ±20% dei parametri, risultato "instabile" dichiarato.
- Dati fuori intervallo e assenza di tutte le quantità alternative ora "non valutabili".
- Etichette separate dai dati; metriche con intervalli di Wilson, tasso di falsi negativi, distribuzione delle classi, metriche per settore, territorio e dimensione.
- Metadati dei coefficienti: natura, riferimento completo alla fonte; per la validazione servono il riferimento e il ruolo di revisore.

## Dati e fonti
- Import in due fasi (anteprima e conferma) con provenienza dichiarata, scadenza dell'autorizzazione, revoca del lotto.
- Scoperta dataset ISTAT (SDMX, `/dataflow/IT1`) e ANAC (solo se configurata), catalogo locale.
- Proposte di valore per i parametri dalle osservazioni mappate, decise da un revisore diverso dal proponente.
- Limitatore di frequenza lato client (ISTAT: 4 richieste al minuto contro un limite ufficiale di 5).
- OSINT su più pagine dello stesso dominio autorizzato, con robots.txt e limiti; verifica incrociata tra fonti.
- Grafo: periodo di validità, riservatezza, candidati da dati OCDS per solo identificativo.

## Operatività e sicurezza
- Archivio operativo con 6 migrazioni numerate; esecuzioni e risultati storici per azienda.
- Pratiche di approfondimento; relazioni PDF con le 16 voci della sezione 18, identificativo e verifica d'integrità SHA-256.
- Ruoli `responsabile_dati` e `revisore`; matrice dei permessi unica; ruolo e abilitazione riletti a ogni richiesta; revoca delle sessioni da riga di comando.
- Audit: identificativo di correlazione, ancoraggio esterno, rotazione con collegamento tra segmenti, esportazione per l'auditor.
- Backup, verifica e ripristino con manifesto SHA-256; esportazione CSV del lotto; monitoraggio delle prestazioni; ricerca nell'elenco.
- Accessibilità: salto al contenuto, etichette su tutti i campi, intestazioni di tabella.

## Difetti corretti
Vedi `docs/VERIFICHE.md`, sezione "Difetti trovati e corretti".

## Test
116 test superati (la v3 ne aveva 46). Tre test della v3 sono stati aggiornati perché codificavano comportamenti che il capitolato vieta: settore attivo appena creato, approvazione di un parametro da parte dell'amministratore senza riferimento completo, import senza anteprima.

---

# Emersione v3 — registro delle modifiche

## Implementato/esteso

- Mantenuti autenticazione locale, ruoli, token CSRF, sessioni revocabili, autorizzazioni server-side, import CSV validato e persistenza transazionale del lotto attivo.
- Aggiunti connettori puntuali per cinque endpoint Open API INAIL, risorse dirette ANAC e endpoint SDMX ISTAT scelti dall'operatore, con limiti su host, protocollo, redirect, tempo e dimensione.
- Aggiunto flusso di anteprima, mapping e normalizzazione di CSV/JSON/XML in osservazioni di riferimento con dimensioni, unità, provenienza e hash; transazione atomica, prevenzione dei mapping duplicati e revisione umana. Le osservazioni restano separate dalle formule/punteggi.
- Aggiunto archivio persistente dei payload acquisiti con URL, timestamp, metadati e SHA-256; il download ricalcola l'hash prima di restituire il contenuto.
- Aggiunta acquisizione OSINT di singola pagina HTTPS da allowlist di domini, con limiti, conservazione del contenuto originale, hash, motivazione e revisione tracciata. Non è un crawler.
- Aggiunto grafo persistente di relazioni aziendali documentate, con evidenza, fonte, hash e stato di revisione; candidati generati soltanto da corrispondenze esatte sui campi strutturati supportati.
- Aggiunta estrazione documentale di candidati testuali da PDF testuali, TXT, CSV e JSON; nessun candidato viene approvato o applicato automaticamente.
- Aggiunto screening preliminare edilizio separato dal punteggio, con gli indici del D.M. 143/2021 e riferimenti alla fonte; non è un'attestazione ufficiale.
- Esteso il parsing dei payload CSV/XML, inclusi controlli su righe/colonne e rifiuto di DTD/entity XML anche per input UTF-16.
- Estesa la suite a 46 test in questa copia: integrazione web con acquisizione fonte, download, relazione aziendale, revisione, mapping/normalizzazione, audit hash-chain, parsing CSV/XML e moduli preesistenti.
- Aggiunta verifica della catena hash nella pagina audit e logging di metadati operativi ammessi.

## Collaudo corrente

- `python -m compileall -q app config tests` — superato.
- `python -m unittest discover -s tests -v` — 46 test superati nell'ambiente disponibile.
- I test di rete usano risposte simulate; non attestano disponibilità live degli endpoint né validazione semantica dei dataset esterni.
- `requirements.txt` aggiorna pypdf a 6.21.0 per includere mitigazioni recenti relative ai limiti di parsing PDF. L'ambiente di collaudo non ha accesso alla rete e dispone ancora di pypdf 5.9.0: la versione dichiarata dovrà essere installata e l'intera suite rieseguita in un ambiente isolato prima di qualsiasi pilota. Questo controllo è aperto, non superato. Anche l'aggiornamento di Starlette oltre il pin 0.50.0 resta da valutare con una migrazione separata e testata; non è stato aggiornato alla cieca.

## Limiti bloccanti per un impiego istituzionale

- Non esiste mapping semantico automatico end-to-end dai payload ANAC/ISTAT/INAIL a parametri/indicatori. Il mapping strutturale configura osservazioni normalizzate, che non incidono automaticamente sul punteggio.
- Nessun connettore societario a bilanci/Registro Imprese; nessuna integrazione con identità istituzionale OIDC/SAML.
- OSINT puntuale, non crawling né verifica automatica delle notizie.
- Grafo documentale manuale, non riconciliazione automatica con registri ufficiali.
- Estrattore testuale preliminare, senza OCR o interpretazione affidabile di tabelle/formule complesse.
- Database e audit restano locali; manca un archivio centrale multiistanza con retention e ancoraggio indipendente. La catena hash locale rileva alcune alterazioni, ma non rende il file immutabile e non rileva con certezza la rimozione della coda senza ancoraggio esterno.
- Restano necessarie revisione dei coefficienti, validazione scientifica indipendente, verifiche di sicurezza indipendenti, valutazioni privacy/AI Act e approvazione dell'ente responsabile.

La versione v3 è un prototipo tecnico più funzionale e verificabile, ma non deve essere descritta come certificata o pronta per l'elaborazione operativa di dati riservati.
