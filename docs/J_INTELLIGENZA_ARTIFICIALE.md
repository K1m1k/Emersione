# J. Intelligenza artificiale in Emersione: valutazione, principi e priorità

> **Tipo di documento:** valutazione interna di fattibilità e principi di progetto
> **Versione di riferimento:** Emersione 3.1 — 22 ottobre 2026
> **Stato:** proposta. **Nessun modello di IA è oggi integrato nel sistema.** Questo documento non costituisce approvazione all'uso operativo, né valutazione indipendente, parere legale o certificazione.
> **Piano operativo:** [`K_ROADMAP_IA.md`](K_ROADMAP_IA.md)

---

## Sintesi

Emersione dispone di una base adatta a ospitare funzioni di intelligenza artificiale: motore a regole spiegabile, configurazione dichiarativa dei settori, ciclo di revisione e approvazione, tracciamento delle fonti, separazione esplicita tra indicatori e accertamento.

**La valutazione è favorevole a un'integrazione progressiva dell'IA, ma non all'introduzione immediata di un modello predittivo di rischio.**

| Ambito | Utilità | Fattibilità oggi | Decisione |
|---|---|---|---|
| Lettura assistita dei documenti | alta | medio-alta, solo fonti pubbliche | **prima funzione da sperimentare** |
| Riconoscimento delle entità (grafo) | alta | media, dipende dalla qualità dei record | seconda priorità |
| Classificazione e sintesi OSINT | media | media | dopo aver definito fonti e insieme di prova |
| Raggruppamento di imprese comparabili | da valutare | media | solo con gruppi motivati e stabili |
| Modello supervisionato di rischio | potenziale, non dimostrata | bassa senza dati autorizzati | **rinviare** fino a dati ed etichette adeguati |
| Uso operativo su dati reali | — | non giustificato dal solo codice e dai test | richiede verifiche tecniche, metodologiche, di sicurezza e normative |

**Criterio guida:** non "aggiungere più IA", ma introdurre solo funzioni che dimostrano un **miglioramento misurabile, riproducibile, spiegabile e compatibile con l'uso previsto**.

---

## 1. Perché considerare l'IA

Emersione funziona oggi con **regole dichiarative**: formule, coefficienti e soglie scelti da persone e registrati con fonte e versione. L'approccio è trasparente, ma ha limiti strutturali.

| Limite attuale | Effetto | Contributo possibile dell'IA |
|---|---|---|
| Soglie e pesi fissati a mano (scarto 30%/60%, punti 25/50/20) | l'indice ordina le aziende ma non dice quanto spesso ha ragione | apprendimento dagli **esiti reali dei controlli**, se disponibili |
| Confronto solo per settore | imprese molto diverse confrontate tra loro | gruppi di imprese **realmente comparabili** |
| Segnali correlati sommati | possibile doppio conteggio | ponderazione che tiene conto delle dipendenze |
| Estrazione documentale senza OCR né tabelle | coefficienti trascritti a mano | lettura assistita con **proposte** da verificare |
| Grafo costruito a mano o per identificativo esatto | relazioni incomplete | riconoscimento della stessa entità tra fonti diverse |
| OSINT letta pagina per pagina | tempo dell'operatore assorbito da contenuti irrilevanti | filtro di pertinenza e sintesi con citazione |

**Obiettivo:** ridurre e **misurare** falsi positivi (imprese regolari segnalate) e falsi negativi (irregolarità non rilevate).

---

## 2. Stato del progetto rispetto all'IA

La presenza di un modulo non equivale alla sua validazione.

| Area | Stato nella versione 3.1 | Conseguenza per l'IA |
|---|---|---|
| Motore a regole | implementato e collaudato su dati sintetici | resta il riferimento con cui confrontare ogni nuova funzione |
| Settori e parametri | ciclo di revisione presente; coefficienti in gran parte ipotesi sperimentali | l'IA non deve conferire validità ai parametri |
| Screening D.M. 143/2021 | modulo separato di screening preliminare | non è un'attestazione di congruità |
| Estrazione documentale | PDF testuali, TXT, CSV, JSON; candidati preliminari | OCR, tabelle e interpretazione assistita da sviluppare |
| Collegamento dati–parametri | suggerimenti lessicali; flusso proposta → revisione | un modello linguistico può aiutare, mantenendo provenienza e revisione |
| Grafo | relazioni documentate; suggerimenti per identificativo esatto | riconoscimento probabilistico come estensione futura |
| OSINT | raccolta limitata; la verifica incrociata non accerta i fatti | un classificatore filtra, non certifica |
| IA predittiva | non integrata | funzione nuova, con valutazione distinta |
| Dati reali ed etichette | validazione su dati reali non eseguita | prestazioni predittive non dimostrate |

### Limiti metodologici determinanti

Dalla documentazione del progetto ([`D_METODOLOGIA.md`](D_METODOLOGIA.md), [`H_LIMITI_NOTI.md`](H_LIMITI_NOTI.md)):

- i coefficienti settoriali, tranne gli indici del D.M. 143/2021, sono **ipotesi sperimentali**;
- il dataset sintetico verifica il software, **non** la capacità di riconoscere irregolarità reali, ed è inadatto all'addestramento: le anomalie generate riflettono le grandezze che il motore misura;
- manodopera stimata e costo del lavoro sono segnali correlati;
- con una variazione del ±20% dei parametri, 74 aziende su 500 del dataset sintetico risultano **instabili**;
- precisione, falsi positivi e falsi negativi **non sono validati** su casi reali.

Questi limiti non impediscono di usare l'IA per leggere documenti od organizzare informazioni. Impediscono di considerare affidabile un nuovo punteggio predittivo senza prove ulteriori.

---

## 3. Condizione indispensabile per il modello di rischio: i dati

> Un modello impara solo da esempi reali. **Senza esiti di controlli conclusi, un'IA non rende Emersione più preciso**: imparerebbe le regole che le vengono date e renderebbe il sistema meno trasparente.

Prima di valutare un modello supervisionato servono almeno:

- base giuridica e autorizzazione al trattamento;
- definizione scritta e verificabile dell'esito da prevedere ("irregolarità accertata");
- dati storici con fonti, periodo, popolazione e limiti documentati;
- esiti di controlli conclusi, **inclusi i casi senza irregolarità**;
- un **campione di controlli casuali** o altre misure contro la distorsione di selezione: i controlli passati riguardano soprattutto soggetti già sospettati;
- confronto con il motore a regole sulle stesse etichette indipendenti;
- analisi degli errori, calibrazione, metriche per gruppo con intervalli di confidenza;
- validazione indipendente, monitoraggio e criteri di sospensione.

Nessuna soglia numerica di casi positivi garantisce da sola la sufficienza statistica: vanno considerati anche casi negativi, copertura dei settori, squilibrio tra classi e dipendenza tra osservazioni.

Le funzioni che usano solo fonti pubbliche e documenti possono invece procedere subito. Le strade per accedere ai dati sono discusse in [`L_PROSPETTIVE_E_COLLABORAZIONI.md`](L_PROSPETTIVE_E_COLLABORAZIONI.md).

---

## 4. Funzioni candidate

### 4.1 Lettura assistita dei documenti — priorità alta

**Obiettivo:** individuare in decreti, contratti collettivi e capitolati valori, unità di misura, periodi di validità e riferimenti normativi.

- OCR locale per i documenti scansionati; estrazione di tabelle dai PDF testuali.
- Proposta di associazione tra contenuto estratto e parametro del registro.
- Ogni proposta riporta documento, pagina, estratto originale e, se disponibile, tabella o riga. **Una proposta senza evidenza riconducibile alla fonte viene scartata.**
- Il revisore verifica contesto, unità, periodo, territorio e applicabilità prima che il dato diventi un parametro.

È la funzione più adatta a iniziare: l'output si confronta direttamente con il documento originale.

### 4.2 Riconoscimento delle entità — priorità alta

**Obiettivo:** riconoscere record che rappresentano la stessa impresa o persona anche con grafie diverse.

Tre esiti: **corrispondenza probabile**, **da verificare**, **record differenti**. **Il nome da solo non conferma mai un'identità.** Il risultato è un candidato per il grafo; il collegamento richiede la revisione prevista. Nessun algoritmo recupera informazioni che non esistono nei dati.

### 4.3 Classificazione OSINT — priorità media

**Obiettivo:** separare contenuti pertinenti da quelli non pertinenti e facilitarne la lettura con sintesi che citano le frasi di origine.

**Pertinenza e veridicità sono questioni diverse.** La classificazione non dimostra che un contenuto sia corretto, aggiornato o riferito all'impresa giusta.

### 4.4 Imprese comparabili — da valutare

Un gruppo numeroso non è necessariamente omogeneo. Variabili, esclusioni e stabilità dei gruppi vanno motivate e provate; i gruppi instabili o troppo piccoli non si usano.

### 4.5 Modello supervisionato di rischio — rinviato

Tecnicamente plausibile, **utilità non dimostrata**. Si valuta solo alle condizioni della sezione 3.

---

## 5. Principi non negoziabili

| Principio | Applicazione |
|---|---|
| **Supporto, mai decisione** | ogni output è un indicatore da approfondire; l'esame umano è effettivo e documentato (art. 22 GDPR) |
| **Affiancamento, non sostituzione** | il risultato IA è in un campo separato e mostrato accanto al punteggio a regole, mai al suo posto senza validazione e approvazione formale |
| **Non interferenza** | il motore a regole funziona senza IA; errore, timeout o assenza del modello non ne alterano i risultati |
| **Spiegabilità** | per ogni risultato: fattori, evidenze e fonti |
| **Equità misurata** | metriche e falsi positivi per settore, territorio e dimensione; sospensione se un gruppo è penalizzato |
| **Tracciabilità** | versione, impronta di modello e artefatti, configurazione e dati registrati in ogni esecuzione |
| **Dati in casa** | esecuzione locale; verificare che log, telemetria e aggiornamenti non trasferiscano dati all'esterno |
| **Elenco chiuso** | nessun caricamento di codice arbitrario da configurazione o da file di modello non controllati |
| **Stesso ciclo di approvazione** | bozza → collaudo → revisione → sperimentazione → approvazione, come per i settori |
| **Nessuna promessa non dimostrata** | nessuna prestazione dichiarata prima di una validazione indipendente |

---

## 6. Principi di architettura

- **Contratti distinti per tipo di funzione.** OCR, estrazione documentale, riconoscimento delle entità, classificazione OSINT e modelli predittivi hanno ingressi, uscite, criteri di verifica e rischi diversi: non vanno forzati in un'unica interfaccia.
- **Requisiti comuni:** identificativo e versione; impronta del modello e degli artefatti; versione del codice di esecuzione e dell'ambiente; provenienza dei dati; metriche e scheda tecnica; stato di approvazione; registro delle esecuzioni e degli errori; possibilità di disattivazione e ritorno alla situazione precedente.
- **Modalità in ombra.** Nella prima sperimentazione la funzione calcola e registra i risultati senza mostrarli agli operatori. Prima di iniziare si definiscono popolazione, periodo, metrica principale, soglie di accettazione, gestione dei dati mancanti, criteri di arresto e responsabili. La modalità in ombra non sostituisce l'autorizzazione al trattamento.
- **Repository.** Contiene codice, configurazione non segreta, test e schede tecniche non riservate. **Non** contiene dataset autorizzati, dati personali, credenziali né file di modello custoditi dall'ente.

---

## 7. Criteri di valutazione per tipo di funzione

Non esiste un singolo numero che dimostri l'affidabilità dell'IA. Le soglie indicate nella roadmap sono **obiettivi proposti**, non risultati raggiunti: vanno accompagnate da descrizione del campione, stima dell'incertezza e analisi degli errori residui.

| Funzione | Cosa misurare |
|---|---|
| Documenti | precisione dei valori, completezza, correttezza di unità e riferimento; risultati separati per PDF testuali e scansionati, tabelle semplici e complesse; errori critici (valore associato al parametro o al periodo sbagliato) |
| Entità | precisione e richiamo su collegamenti e non-collegamenti; analisi separata per record con identificativi affidabili, incompleti o con denominazioni comuni; attenzione ai falsi abbinamenti, che si propagano nel grafo |
| OSINT | precisione della classe pertinente e contenuti rilevanti mancati; fedeltà dei riassunti, attribuzione, datazione, contesto |
| Modello predittivo | separazione temporale; confronto con le regole; precisione, richiamo, falsi positivi e negativi con intervalli di confidenza per gruppo; calibrazione; stabilità e deriva nel tempo |

---

## 8. Quando procedere e quando fermarsi

**Procedere con una sperimentazione quando:**
- la funzione risolve un problema definito e misurabile;
- esiste un insieme di prova rappresentativo, verificato indipendentemente;
- input, output, errori e limiti sono documentati e ogni output è riconducibile alle fonti;
- revisione umana e approvazione sono definite;
- il motore a regole non viene modificato in modo silenzioso;
- il trattamento dei dati è autorizzato e la sicurezza è adeguata.

**Fermarsi o non attivare quando:**
- non si può risalire alla fonte di un valore o di un'affermazione;
- si producono collegamenti automatici non verificabili;
- non c'è un miglioramento misurabile rispetto al processo esistente;
- errori o falsi positivi sono incompatibili con l'uso previsto;
- il campione di verifica è piccolo, distorto o non indipendente;
- mancano responsabilità, modalità di contestazione o criteri di sospensione;
- l'uso dei dati o la finalità non sono autorizzati.

---

## 9. Quadro normativo e responsabilità

- **Regolamento (UE) 2024/1689 (AI Act).** Un sistema che classifica imprese per conto di un'autorità pubblica va valutato con attenzione. Se l'uso ricade tra quelli ad alto rischio, servono gestione del rischio, qualità dei dati, documentazione tecnica, registrazione degli eventi, supervisione umana e accuratezza dichiarata. **La classificazione spetta a soggetti competenti: questo documento non trae conclusioni.**
- **GDPR.** Ditte individuali e amministratori sono persone fisiche: base giuridica, minimizzazione, valutazione d'impatto e coinvolgimento del DPO.
- **Prima di trattare dati riservati:** gestione di accessi, conservazione, rettifica e contestazione; protezione dell'audit; backup cifrati e prove di ripristino; gestione dei segreti; revisione di sicurezza indipendente; responsabilità assegnate per sviluppo, approvazione, uso e sospensione dei modelli.

Software open source ed esecuzione locale non risolvono, da soli, questi aspetti. Le questioni aperte sono elencate in [`E_SICUREZZA_PRIVACY.md`](E_SICUREZZA_PRIVACY.md).

---

## 10. Cosa l'IA non farà in Emersione

- Non accerterà illeciti e non produrrà prove.
- Non avvierà ispezioni, sanzioni o comunicazioni.
- Non applicherà parametri senza revisione.
- Non confermerà relazioni tra imprese sulla base di somiglianze deboli.
- Non sostituirà il motore a regole prima di un miglioramento dimostrato.
- Non sarà attivata su dati reali prima di validazione indipendente e approvazioni.
- Non userà nomi, luoghi o caratteristiche personali per collegare o penalizzare soggetti senza fondamento documentale.

---

## 11. Decisione raccomandata

1. **Consolidare la riproducibilità:** installazione pulita e test completi con le versioni bloccate (vedi [`VERIFICHE.md`](VERIFICHE.md)).
2. **Realizzare le fondamenta comuni** per registrare e governare le funzioni IA, senza alterare il motore a regole.
3. **Sperimentare la lettura assistita dei documenti.**
4. **Sperimentare il riconoscimento delle entità**, mantenendo i collegamenti come proposte.
5. **Valutare la classificazione OSINT** con un insieme di prova adeguato.
6. **Rinviare il modello predittivo** fino a dati autorizzati, etichette attendibili e un disegno di validazione.

Le funzioni 3, 4 e 5 si valutano separatamente: l'esito negativo di una non obbliga a introdurne un'altra.

---

## Documenti correlati

- [`K_ROADMAP_IA.md`](K_ROADMAP_IA.md) — fasi operative e criteri di uscita
- [`L_PROSPETTIVE_E_COLLABORAZIONI.md`](L_PROSPETTIVE_E_COLLABORAZIONI.md) — accesso ai dati e collaborazioni
- [`B_ARCHITETTURA.md`](B_ARCHITETTURA.md) — architettura attuale
- [`D_METODOLOGIA.md`](D_METODOLOGIA.md) — metodologia degli indicatori
- [`E_SICUREZZA_PRIVACY.md`](E_SICUREZZA_PRIVACY.md) — sicurezza, privacy, questioni aperte
- [`F_PIANO_SPERIMENTAZIONE.md`](F_PIANO_SPERIMENTAZIONE.md) — piano di sperimentazione
- [`H_LIMITI_NOTI.md`](H_LIMITI_NOTI.md) — limiti noti
- [`VERIFICHE.md`](VERIFICHE.md) — verifiche eseguite e da eseguire
