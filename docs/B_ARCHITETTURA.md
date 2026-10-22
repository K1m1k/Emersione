# B. Architettura tecnica

Monolite modulare Python (Starlette + Jinja2 + SQLite), senza code, cache distribuite o orchestratori: nessun requisito verificabile li giustifica a questa scala (25.000 record analizzati in circa 2,4 s, misurato; vedi `VERIFICHE.md`).

## Componenti
| Area | Moduli |
|---|---|
| Interfaccia web | `app/web/server.py`, `app/web/templates/` |
| Autenticazione e autorizzazioni | `app/sicurezza.py` (matrice `PERMESSI`), `app/sessioni.py`, `app/gestione_sessioni.py` |
| Motore di analisi | `app/motore/analisi.py` (nucleo generico), `app/moduli_settore.py` (moduli specifici), `app/unita.py` (analisi dimensionale) |
| Valutazione | `app/motore/valutazione.py` |
| Registro settori e parametri | `app/settori.py`, `config/registro_emersione.json`, `app/versioni_registro.py` (storico completo) |
| Ciclo di vita e collaudo | `app/ciclo_settori.py`, `app/collaudo_settori.py`, `app/dipendenze.py` |
| Fonti e connettori | `app/connettori/fonti_live.py`, `app/connettori/scoperta.py`, `app/fonti_store.py`, `app/fonti_mapping.py`, `app/collegamento_semantico.py` |
| Import ed export | `app/connettori/csv_import.py`, `app/provenienza.py` |
| Documenti | `app/documenti.py`, `app/estrazione_documenti.py` |
| OSINT e grafo | `app/osint.py`, `app/osint_esteso.py`, `app/grafo.py` |
| Persistenza operativa | `app/db_operativo.py` (migrazioni numerate), `app/dataset_store.py`, `app/migrazioni.py` |
| Audit | `app/audit.py`, `app/audit_cli.py` |
| Relazioni | `app/report.py` |
| Backup | `app/backup.py` |

## Flussi principali
1. **Import:** CSV → validazione dello schema → analisi in area temporanea → anteprima → conferma → salvataggio transazionale e provenienza → esecuzione registrata con risultati per azienda.
2. **Configurazione:** bozza → in revisione → collaudo automatico → verificata tecnicamente → validazione metodologica (e normativa se serve) → approvata per la sperimentazione → approvata per l'uso previsto. Ogni modifica riapre la revisione.
3. **Fonti pubbliche:** scoperta nel catalogo → acquisizione (payload grezzo con hash) → mappatura delle colonne → revisione → proposta di valore per un parametro → decisione del revisore → nuova versione "da verificare" del parametro.

## Persistenza
| Archivio | Contenuto | Schema |
|---|---|---|
| `config/registro_emersione.json` | settori, parametri, documenti, relazioni | versione 1, sostituzione atomica |
| `config/registro_versioni.sqlite3` | ogni versione del registro (mai cancellata) | creato all'apertura |
| `dati/emersione_operativo.sqlite3` | esecuzioni, risultati, collaudi, transizioni, pratiche, relazioni PDF, catalogo dataset, proposte, provenienza | migrazioni 1–6 (`python -m app.migrazioni stato`) |
| `dati/emersione_dataset.sqlite3` | lotto attivo | schema 2 |
| `dati/*.sqlite3` (fonti, mappature, OSINT, grafo, sessioni) | come da nome | tabelle create all'apertura |
| `dati/audit.jsonl` | eventi con catena di hash | JSON Lines |
| `dati/documenti/` | documenti caricati | file con SHA-256 |

**Produzione:** lo schema relazionale è stato pensato per essere portato su PostgreSQL (vincoli, indici e transazioni esplicite). La migrazione va pianificata con l'ente: richiede un livello di accesso ai dati, la gestione delle connessioni e prove di ripristino, non ancora realizzati.

## Dipendenze
`requirements.txt`: starlette, uvicorn, jinja2, python-multipart, itsdangerous, reportlab, pypdf. Tutto il resto (crittografia delle password, SQLite, HTTP client, XML) è libreria standard. Le versioni realmente usate nel collaudo sono in `VERIFICHE.md`.

## Container
Valutato e non adottato per la demo locale: un ambiente virtuale Python è sufficiente e più semplice. Per la produzione un'immagine container può aiutare la riproducibilità, ma va costruita e collaudata dall'ente con il suo registro di immagini.
