# A. Presentazione del progetto

## Problema affrontato
Il lavoro irregolare lascia tracce indirette: produzione dichiarata che richiederebbe più manodopera di quella dichiarata, costi del lavoro anomali rispetto ad aziende comparabili, incongruenze tra dotazioni di sicurezza e addetti. Emersione aiuta operatori autorizzati a individuare **elementi che meritano un approfondimento umano**.

## Obiettivi
- Calcolare indicatori spiegabili e riproducibili, con fonte e versione di ogni parametro.
- Distinguere sempre dato acquisito, dato derivato, anomalia statistica, indizio documentale, relazione documentata, informazione non verificata e risultato non valutabile.
- Consentire all'ente di aggiungere settori, parametri e regole senza modificare il nucleo del software, con collaudo e approvazioni tracciate.

## Destinatari
Personale autorizzato di un ente competente (ispettori, analisti, responsabili dei dati, revisori metodologici, auditor), secondo la matrice dei ruoli in `E_SICUREZZA_PRIVACY.md`.

## Cosa fa il sistema (versione 3.1, prototipo)
- Indicatori per agricoltura, edilizia, ristorazione e logistica, e per ogni settore aggiunto dall'ente.
- Registro dei settori con ciclo di approvazione, collaudo automatico, storico e ripristino delle versioni.
- Import CSV con anteprima, conferma e provenienza dichiarata. Connettori ISTAT, INAIL e ANAC con scoperta dei dataset. Collegamento controllato tra dati e parametri.
- OSINT limitata a domini autorizzati, grafo delle relazioni documentate, pratiche, relazioni PDF verificabili, audit con catena di hash, backup e ripristino.

## Cosa NON fa
- Non accerta illeciti, non stima probabilità di illecito, non avvia ispezioni o sanzioni e non produce classifiche pubbliche.
- Non accede a sistemi riservati: i dati non pubblici vi arrivano solo per caricamento da parte di un ente legittimato.

## Valore potenziale e limiti
Il valore dipende da coefficienti verificati, dati autorizzati e da una sperimentazione indipendente, oggi **non ancora svolti** (vedi `H_LIMITI_NOTI.md`). Allo stato attuale è un prototipo tecnicamente collaudato su dati sintetici.
