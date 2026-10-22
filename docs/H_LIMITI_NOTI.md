# H. Registro dei limiti noti

| # | Limite | Conseguenza | Cosa serve |
|---|---|---|---|
| 1 | Tutti i coefficienti di settore sono ipotesi sperimentali "da verificare" | gli indici non hanno valore metodologico | fonti ufficiali, verifica del revisore, validazione |
| 2 | Nessuna validazione su dati reali | prestazioni reali ignote; le metriche sintetiche sono circolari | etichette indipendenti, sperimentazione (F) |
| 3 | Connettori ISTAT, INAIL e ANAC provati solo con risposte simulate | endpoint, schema e licenze non confermati dal vivo | verifica in rete dell'ente |
| 4 | Scoperta ANAC non configurata | nessun elenco automatico dei dataset ANAC | API di catalogo ufficiale documentata |
| 5 | Nessun connettore per bilanci e Registro Imprese | relazioni societarie solo manuali o da identificativi già forniti | contratto o convenzione di accesso |
| 6 | Grafo non riconciliato automaticamente con i registri ufficiali | i collegamenti dipendono dall'operatore o da OCDS | accesso ai registri, regole di riconciliazione |
| 7 | OSINT limitata: massimo 20 pagine, stesso host, nessuna pianificazione | copertura parziale | valutazione delle fonti da parte dell'ente |
| 8 | La verifica incrociata OSINT conta i domini, non accerta i fatti | "riscontrata" non significa vera | esame umano |
| 9 | Nessun OCR né estrazione di tabelle o formule complesse dai PDF | documenti scansionati non leggibili | librerie OCR, nuova revisione di sicurezza |
| 10 | Edilizia: niente durata dei cantieri; quantità riferite all'anno | non adatto a singoli cantieri | modello con durata, verifica D.M. 143/2021 |
| 11 | Segnali correlati sommati (manodopera e costo dipendono dagli addetti) | possibile doppio conteggio | validazione su dati etichettati |
| 12 | Confronti solo per settore (gruppi ≥ 10), non per territorio o dimensione | aziende diverse confrontate tra loro | campioni adeguati |
| 13 | Identità locale, nessuna integrazione OIDC/SAML | gestione account manuale | integrazione con il fornitore d'identità dell'ente |
| 14 | SQLite su singolo nodo; limitatori e statistiche per processo | niente alta affidabilità | PostgreSQL, limitatore condiviso |
| 15 | L'audit locale non è immutabile | un amministratore di sistema potrebbe riscriverlo | archivio esterno a sola aggiunta |
| 16 | Backup non cifrato | rischio se il supporto viene sottratto | cifratura e custodia dell'ente |
| 17 | Dipendenze: test eseguiti con versioni diverse dai vincoli (vedi `VERIFICHE.md`) | compatibilità con le versioni bloccate da confermare | reinstallazione pulita e test |
| 18 | Nessuna revisione di sicurezza indipendente né test di penetrazione | rischi non scoperti | verifica esterna |
| 19 | Valutazioni GDPR, DPIA e AI Act non svolte | uso istituzionale non autorizzabile | DPO e consulenti (vedi E) |
| 20 | Ricostruzione delle analisi storiche limitata alle versioni registrate dalla 3.1 | configurazioni precedenti non recuperabili | — |
| 21 | Prove di accessibilità automatiche (etichette, lingua, salto al contenuto, stati non solo a colori) | contrasto e lettori di schermo non provati con utenti | verifica AgID e test con utenti |
