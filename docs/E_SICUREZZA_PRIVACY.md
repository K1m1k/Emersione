# E. Sicurezza e privacy

## Ruoli e permessi
Ruoli: amministratore tecnico, responsabile dei dati e delle fonti, analista, consultazione (ispettore o operatore), revisore, auditor. Nessun account predefinito, nessun privilegio amministrativo implicito. **L'amministratore non valida parametri e non approva settori.** Chi crea o modifica un settore non può approvarlo. Chi propone un valore non può deciderlo. Ogni permesso è verificato sul server; ruolo e abilitazione sono riletti dalla configurazione a ogni richiesta.

| Permesso | amministratore | responsabile_dati | analista | consultazione | revisore | auditor |
|---|---|---|---|---|---|---|
| `acquisisci_fonti` | ✔ | ✔ | — | — | — | — |
| `audit` | ✔ | — | — | — | — | ✔ |
| `catalogo_fonti` | ✔ | ✔ | ✔ | — | ✔ | ✔ |
| `configura_settori` | ✔ | ✔ | — | — | — | — |
| `consulta_documenti` | ✔ | ✔ | — | — | ✔ | ✔ |
| `consulta_elenco` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| `consulta_fonti` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| `consulta_mappature` | ✔ | ✔ | ✔ | — | ✔ | ✔ |
| `consulta_scheda` | ✔ | ✔ | ✔ | ✔ | ✔ | — |
| `consulta_settori` | ✔ | ✔ | — | — | ✔ | ✔ |
| `crea_mappature` | ✔ | ✔ | — | — | — | — |
| `decidi_collegamenti` | — | — | — | — | ✔ | — |
| `dipendenze` | ✔ | ✔ | — | — | ✔ | ✔ |
| `esecuzioni` | ✔ | — | ✔ | — | ✔ | ✔ |
| `esporta_audit` | ✔ | — | — | — | — | ✔ |
| `esporta_dati` | ✔ | — | ✔ | — | — | — |
| `genera_report` | ✔ | — | ✔ | — | — | — |
| `gestione_documenti` | ✔ | ✔ | — | — | — | — |
| `grafo_aggiungi` | ✔ | — | ✔ | — | — | — |
| `grafo_consulta` | ✔ | — | ✔ | — | ✔ | ✔ |
| `grafo_revisiona` | ✔ | — | — | — | ✔ | — |
| `grafo_riservato` | ✔ | — | ✔ | — | ✔ | — |
| `importa_dati` | ✔ | ✔ | — | — | — | — |
| `modifica_formule` | ✔ | — | — | — | — | — |
| `osint_acquisisci` | ✔ | ✔ | ✔ | — | — | — |
| `osint_consulta` | ✔ | — | ✔ | — | ✔ | ✔ |
| `osint_revisiona` | ✔ | — | — | — | ✔ | — |
| `pratiche_consulta` | ✔ | — | ✔ | ✔ | ✔ | ✔ |
| `pratiche_gestisci` | ✔ | — | ✔ | — | — | — |
| `proponi_collegamenti` | ✔ | ✔ | — | — | — | — |
| `revisiona_mappature` | ✔ | — | — | — | ✔ | — |
| `ricalcola` | ✔ | — | — | — | — | — |
| `ripristina_demo` | ✔ | — | — | — | — | — |
| `scarica_fonti` | ✔ | ✔ | ✔ | — | — | ✔ |
| `settori_collaudo` | ✔ | ✔ | — | — | ✔ | — |
| `settori_ripristino` | ✔ | — | — | — | — | — |
| `settori_transizione` | ✔ | ✔ | — | — | ✔ | — |
| `valida_parametri` | — | — | — | — | ✔ | — |
| `valutazione` | ✔ | ✔ | ✔ | ✔ | ✔ | — |

La matrice va validata con l'ente destinatario. I passaggi di stato dei settori hanno ruoli propri (vedi `app/ciclo_settori.py`, tabella `TRANSIZIONI`).

## Modello delle minacce (sintesi)
| Minaccia | Contromisura nel prototipo | Rischio residuo |
|---|---|---|
| Accesso non autorizzato | login, PBKDF2-SHA256 (600.000 iterazioni), sessione firmata e revocabile, limite ai tentativi | nessuna autenticazione forte o federata (OIDC/SAML da integrare) |
| Escalation di privilegi | matrice permessi sul server, ruolo riletto a ogni richiesta, separazione dei compiti | revisione indipendente non svolta |
| CSRF | token su ogni POST | — |
| XSS | autoescape Jinja2, CSP restrittiva | test di penetrazione non svolto |
| SSRF | allowlist di host e prefissi, rifiuto dei redirect, blocco degli IP non pubblici | DNS rebinding tra risoluzione e connessione non escluso del tutto |
| Upload malevoli | limiti di dimensione e righe, schema, rifiuto di DTD/entità XML, estensioni ammesse | nessun antivirus |
| Formula injection nei CSV | prefisso apice su `= + - @` | — |
| Path traversal | identificativi validati, archivi di backup con controllo dei percorsi | — |
| Manomissione dell'audit | catena di hash, ancoraggio esterno, rotazione collegata | chi ha accesso al file può riscrivere la catena: serve un archivio separato a sola aggiunta |
| Abuso di risorse | limiti di dimensione, righe, pagine OSINT, frequenza verso le fonti | nessun limitatore condiviso tra processi |
| Esposizione di dati nei log | allowlist dei metadati, nessuna password, token o record | — |

## Sessioni e account
- Cookie `HttpOnly` e `SameSite=Strict`; `Secure` e HSTS in produzione; durata 8 ore; nuova sessione a ogni login.
- Revoca: `python -m app.gestione_sessioni revoca-utente NOME` oppure `revoca-tutte`.
- Recupero di un account: revocare le sessioni, generare un nuovo hash con `python -m app.genera_hash_password`, aggiornare `EMERSIONE_USERS_JSON` nel gestore dei segreti e riavviare. Rimuovere un utente dalla configurazione lo disattiva dalla richiesta successiva.

## Audit
- Campi: data e ora UTC, utente autenticato, ruolo, azione, risorsa, esito, motivo, identificativo di correlazione (header `X-Request-ID`), hash e numero di record quando pertinenti. Le analisi registrano versione del motore e impronta della configurazione nelle esecuzioni.
- Integrità: catena di hash (`python -m app.audit_cli verifica`). Per rilevare il taglio delle ultime righe, conservare **fuori dal sistema** il punto di ancoraggio (`ancora`) e verificarlo (`verifica-ancora`).
- Rotazione: `python -m app.audit_cli ruota CARTELLA`; il nuovo segmento riporta l'ultimo hash del precedente.
- **Conservazione (proposta da validare):** segmenti mensili, conservati per il periodo stabilito dall'ente (ad esempio 5 anni), su un archivio separato con accesso in sola lettura per l'auditor. Il prototipo non cancella mai eventi da solo.
- Esportazione: solo auditor e amministratore (`/audit/esporta.csv`); l'esportazione stessa viene registrata.

## Segreti
Mai nel codice o nel repository: `EMERSIONE_SESSION_SECRET` (≥ 32 byte) e `EMERSIONE_USERS_JSON` dal gestore dei segreti dell'ente. In produzione l'avvio fallisce se mancano.

## Questioni normative aperte (da sottoporre al DPO e ai consulenti)
1. Titolare e responsabili del trattamento; nomina di eventuali responsabili esterni.
2. Base giuridica per ciascun trattamento: import dei dati dell'ente, OSINT, grafo, pratiche, relazioni.
3. Necessità di una DPIA (art. 35 GDPR): **probabilmente necessaria**, data la valutazione sistematica di soggetti, anche persone fisiche (ditte individuali), con possibili effetti significativi. La decisione spetta al titolare.
4. Art. 22 GDPR: il sistema non prende decisioni automatizzate; va documentato che ogni esito passa da un esame umano effettivo.
5. Classificazione secondo il Regolamento (UE) 2024/1689 (AI Act): va valutata sulla funzione effettiva (uso da parte di autorità pubbliche, effetti sui soggetti). Il motore è a regole dichiarative e non apprende dai dati, ma questo non basta a escludere obblighi. **Nessuna conclusione in questa sede.**
6. Minimizzazione e conservazione: quali campi servono davvero e per quanto tempo; procedure di rettifica e contestazione da parte delle imprese.
7. OSINT: compatibilità con i termini d'uso dei siti, diritti sui contenuti, limiti alla ripubblicazione degli estratti.
8. Dati dei registri societari: condizioni contrattuali di riuso.
9. Accessibilità (L. 4/2004 e linee guida AgID) e requisiti di approvvigionamento pubblico.

Riferimenti: [Regolamento (UE) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj/ita), [Regolamento (UE) 2016/679](https://eur-lex.europa.eu/eli/reg/2016/679/oj/ita), [Garante privacy](https://www.garanteprivacy.it/), [AgID, intelligenza artificiale](https://www.agid.gov.it/it/ambiti-intervento/intelligenza-artificiale). I collegamenti sono quelli indicati nel capitolato; il loro contenuto non è stato analizzato in questa sede.
