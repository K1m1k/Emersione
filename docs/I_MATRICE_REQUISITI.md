# I. Matrice dei requisiti

Stato: **verificato** = implementato e coperto da test automatici; **parziale** = implementato con limiti dichiarati; **aperto** = richiede attività esterne al software. Il responsabile della verifica va indicato dall'ente.

## Requisiti per sezione del capitolato
| Sez. | Requisito | Stato | Evidenza | Test | Criticità |
|---|---|---|---|---|---|
| 2 | Lavoro sul progetto esistente, senza riscritture inutili | verificato | v3 estesa; risultati sintetici identici (impronta `cb82ab…`) | `test_estensibilita` | — |
| 3 | Lavoro per fasi con rapporto | verificato | `CHANGELOG.md`, questo documento | — | — |
| 4 | Indicatori da verificare, mai prove; distinzioni tra tipi di informazione | verificato | interfaccia, relazione PDF sez. 4-ter, `D_METODOLOGIA.md` | `test_web_v31` (PDF) | — |
| 5 | Monolite modulare, nessuna infrastruttura superflua | verificato | `B_ARCHITETTURA.md` | — | — |
| 6 | Motore: dati assenti mai zero, non applicabili senza falsi segnali, coefficienti usati, nessuna formula duplicata | verificato | `analisi.py`; difetti v3 corretti (zero predefiniti, intervalli) | `test_motore_valutazione`, collaudo | coefficienti non validati (H1) |
| 6 | Specificità settoriali (stagionalità, meccanizzazione…) | aperto | — | — | servono dati (H10) |
| 7 | Coefficienti con identificativo, natura, fonte, riferimento, date, validità, territorio, stato, versione | verificato | `settori.py` (`NATURE_PARAMETRO`, `CAMPI_RIFERIMENTO`), storico | `test_registro_settori` | valori da verificare |
| 7 | D.M. 143/2021 | parziale | modulo di screening; tabella confrontata con 2 fonti | `test_normativa_edilizia` | non è attestazione |
| 8 | Spiegazione per azienda, versioni, robustezza, gruppi comparabili minimi | verificato | `analisi.py` (robustezza ±20%), minimo 10 | `test_motore_valutazione` | doppio conteggio (H11) |
| 9 | Dati sintetici riproducibili, etichette separate, metriche complete con IC, per gruppo | verificato | `valutazione.py` | `test_motore_valutazione`, `test_web_v31` | metriche circolari (H2) |
| 10 | Import robusto, staging, anteprima, conferma, atomicità, export protetto | verificato | `carica_post` / `carica_conferma`, `esporta_csv_bytes` | `test_csv_import`, `test_web_v31` | — |
| 11 | Persistenza relazionale, migrazioni, storico non sovrascritto | verificato | `db_operativo.py` (6 migrazioni), `versioni_registro.py` | `test_operativo` | SQLite (H14) |
| 12 | Connettori con interfaccia comune, stato, timeout, limiti, errori | parziale | `fonti_live.py`, `scoperta.py` | `test_fonti_live`, `test_fonti_osint_grafo` | non verificati dal vivo (H3–H5) |
| 13 | Separazione dati pubblici/riservati, provenienza, scadenza, revoca | verificato | `provenienza.py` | `test_web_v31` | base giuridica da valutare (H19) |
| 14 | OSINT con allowlist, robots.txt, limiti, provenienza, verifica incrociata | parziale | `osint.py`, `osint_esteso.py` | `test_fonti_osint_grafo`, `test_osint` | H7, H8 |
| 15 | Grafo documentato, temporale, riservatezza, niente omonimie | parziale | `grafo.py` (OCDS per identificativo) | `test_grafo`, `test_fonti_osint_grafo` | H6 |
| 16 | Autenticazione, matrice ruoli, CSRF, sessioni, recupero account, intestazioni | verificato | `sicurezza.py`, `gestione_sessioni.py` | `test_web_v31`, `test_sicurezza` | OIDC assente (H13), nessun test di penetrazione (H18) |
| 17 | Audit completo, correlazione, integrità, conservazione, esportazione | verificato | `audit.py`, `audit_cli.py` | `test_operativo`, `test_audit` | non immutabile (H15) |
| 18 | Relazione PDF con le 16 voci, identificativo e verifica d'integrità | verificato | `report.py`, `/report/verifica` | `test_web_v31` | — |
| 19 | Governance, privacy e AI Act | aperto | `E_SICUREZZA_PRIVACY.md` (questioni aperte) | — | H19 |
| 20 | Fonti ufficiali verificate, niente invenzioni | parziale | `C_CATALOGO_DATI.md` | — | verifica dal vivo |
| 21 | Test: unità, integrazione, sicurezza, regressione, resilienza, consistenza, accessibilità | verificato | 116 test | tutta la suite | accessibilità solo automatica (H21) |
| 22 | Interfaccia: panoramica, ricerca, scheda, fonti, connettori, import, audit, valutazione, pratiche, report | verificato | 60 rotte | `test_web_v31` | — |
| 23 | Efficienza e monitoraggio | verificato | 25.000 record in circa 2,4 s; `/prestazioni` | `test_web_v31` | per processo |
| 24 | Configurazione riproducibile, backup e ripristino, aggiornamento e ritorno indietro | verificato | `G_MANUALE_OPERATIVO.md`, `backup.py` | `test_operativo` | backup non cifrato (H16) |
| 25 | Documentazione A–I | verificato | `docs/` | — | — |
| 30 | Estensibilità: registro, catalogo, documenti, relazioni, ciclo di vita, collaudo, dipendenze, versioni, nessun limite di settori | verificato | sezioni 30.2–30.14 | `test_estensibilita` (15 scenari, settore "servizi di pulizia") | validazione scientifica esterna |

## Criteri di accettazione finali (sezione 26)
| # | Criterio | Stato |
|---|---|---|
| 1 | Installazione documentata e ripetibile | verificato (G §1); ripetizione in ambiente pulito: aperto (H17) |
| 2 | Avvio e arresto controllati | verificato (G §3) |
| 3 | Suite di test eseguibile | verificato |
| 4 | Modello dati con migrazioni | verificato |
| 5 | Autenticazione e autorizzazioni verificate | verificato |
| 6 | Import con validazione e rollback | verificato |
| 7 | Audit con identità attendibile e protezione adeguata | verificato, nei limiti di H15 |
| 8 | Motore verificabile e riproducibile | verificato |
| 9 | Registro dei coefficienti con stato di validazione | verificato |
| 10 | Metriche distinte tra test sintetici e validazione reale | verificato |
| 11 | Connettori marcati secondo lo stato effettivo | verificato |
| 12 | Fonti e dati tracciabili | verificato |
| 13 | Relazioni PDF verificabili | verificato |
| 14 | Gestione corretta degli errori | verificato |
| 15 | Backup e ripristino collaudati | verificato in sviluppo; collaudo nell'ambiente previsto: aperto |
| 16 | Documentazione metodologica, tecnica e di sicurezza | verificato |
| 17 | Elenco delle questioni normative aperte | verificato (E) |
| 18 | Piano di sperimentazione | verificato (F) |
