# F. Piano di sperimentazione

## Requisiti preliminari (bloccanti)
1. Approvazione del titolare e parere del DPO; DPIA se ritenuta necessaria (vedi E).
2. Ambiente isolato dell'ente, con dipendenze installate in un ambiente pulito e suite di test rieseguita (vedi `VERIFICHE.md`).
3. Integrazione con l'identità dell'ente, oppure account locali gestiti dal gestore dei segreti.
4. Coefficienti dei settori in sperimentazione verificati e approvati dal revisore con documento e riferimento completo.
5. Settori portati almeno ad "approvata per la sperimentazione" tramite collaudo e approvazioni.

## Dataset
- Dati storici già in possesso dell'ente, caricati con provenienza e autorizzazione.
- **Etichette di riferimento indipendenti:** esiti di controlli già conclusi, con criteri documentati, raccolti senza usare Emersione. Senza queste etichette non si misura alcuna prestazione.

## Casi di prova
Per ogni settore: casi conformi, casi con irregolarità accertate, casi con dati incompleti e casi limite (stagionalità, meccanizzazione, subappalti).

## Metriche
Matrice di confusione, precisione, richiamo, specificità, tassi di falsi positivi e negativi con intervalli di confidenza, per settore, territorio e dimensione. Più la quota di risultati instabili e non valutabili.

## Supervisione
Ogni esito esaminato da un operatore; decisioni nelle pratiche; revisione periodica dei casi di falso positivo.

## Criteri di interruzione
- Tasso di falsi positivi in un gruppo significativamente superiore agli altri (possibile discriminazione).
- Uso dei risultati come prova o fuori dalla finalità.
- Incidenti di sicurezza o anomalie dell'audit.
- Intervalli di confidenza troppo ampi per trarre conclusioni.

## Valutazione indipendente
Da un soggetto che non ha sviluppato né configurato il sistema, con accesso a codice, configurazioni, esecuzioni registrate e audit.
