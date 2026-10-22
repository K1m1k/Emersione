# G. Manuale operativo

Tutti i comandi vanno eseguiti **nella cartella del progetto** (quella che contiene `app/`), con l'ambiente virtuale attivo e le stesse variabili d'ambiente del servizio.

## 1. Installazione (Python 3.10 o successivo; collaudato con 3.13)
```bash
python3 -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m unittest discover -s tests      # deve terminare con "OK"
```
L'ambiente virtuale isola le dipendenze: Python di sistema e gli altri progetti restano invariati.

## 2. Configurazione
| Variabile | Scopo |
|---|---|
| `EMERSIONE_ENV` | `development`, `test` o `production` |
| `EMERSIONE_SESSION_SECRET` | segreto di sessione, ≥ 32 byte (obbligatorio in produzione) |
| `EMERSIONE_USERS_JSON` | account: `[{"username":"…","password_hash":"…","ruolo":"…"}]` |
| `EMERSIONE_REGISTRO` | percorso del registro settori/parametri (lo storico sta nella stessa cartella) |
| `EMERSIONE_OPERATIVO_DB`, `EMERSIONE_DATASET_DB`, `EMERSIONE_SESSION_DB`, `EMERSIONE_FONTI_DB`, `EMERSIONE_MAPPATURE_DB`, `EMERSIONE_OSINT_DB`, `EMERSIONE_GRAFO_DB` | archivi SQLite |
| `EMERSIONE_AUDIT_PATH`, `EMERSIONE_DOCUMENTI_DIR` | audit e documenti |
| `EMERSIONE_OSINT_ALLOWED_DOMAINS` | domini OSINT autorizzati, separati da virgola |
| `EMERSIONE_ANAC_CATALOGO_API` | API di catalogo ANAC, solo dopo averla verificata |

Hash di una password: `python -m app.genera_hash_password` (minimo 14 caratteri).

## 3. Avvio e arresto
```bash
python -m app.migrazioni applica        # prima dell'avvio e dopo ogni aggiornamento
uvicorn app.web.server:app --host 127.0.0.1 --port 8000
```
Arresto: Ctrl+C oppure `systemctl stop` se installato come servizio. In produzione va dietro un proxy HTTPS (`EMERSIONE_ENV=production` attiva cookie `Secure` e HSTS). Usare un solo processo: limitatori di frequenza, statistiche e aree temporanee d'importazione sono per processo.

## 4. Backup e ripristino
```bash
python -m app.backup crea /percorso/backup                     # crea emersione-backup-<data>.tar.gz
python -m app.backup verifica /percorso/backup/FILE.tar.gz     # impronte SHA-256 + integrità SQLite
python -m app.backup ripristina /percorso/backup/FILE.tar.gz --forza   # a servizio fermo
```
Il ripristino conserva i file sostituiti (`.pre-ripristino-<data>`) e revoca tutte le sessioni. **Il backup non è cifrato:** va conservato su un supporto protetto. Le prove di ripristino vanno ripetute periodicamente nell'ambiente dell'ente.

## 5. Aggiornamento dei coefficienti
1. Controllare l'impatto: pagina **Dipendenze**, oppure il link "Vedi impatto" nel catalogo dei parametri.
2. Il responsabile dei dati crea una nuova versione "da verificare". I settori che usano il parametro tornano in revisione.
3. Si carica il documento della fonte e lo si collega al parametro (pagina **Documenti**).
4. Il revisore compila il riferimento completo e dichiara il parametro "verificato" o "approvato".
5. Si ripetono collaudo e approvazioni dei settori interessati (pagina **Gestisci** del settore), poi il ricalcolo del lotto.

## 6. Connettori
- Stato: pagina **Catalogo dataset**.
- ISTAT: non superare 4 richieste al minuto (lo fa il client); un blocco ISTAT dura 1–2 giorni.
- Nuove fonti: aggiungere host e prefissi in `app/connettori/fonti_live.py`, scrivere i test con risposte simulate, verificare dal vivo, documentare in `C_CATALOGO_DATI.md`.

## 7. Audit e log
```bash
python -m app.audit_cli verifica
python -m app.audit_cli ancora > ancoraggio-$(date +%F).json     # da conservare FUORI dal sistema
python -m app.audit_cli verifica-ancora ancoraggio-AAAA-MM-GG.json
python -m app.audit_cli ruota /percorso/archivio-audit           # ad esempio mensile
```
Gli errori interni non mostrano dettagli all'utente: vengono registrati come `errore_interno` con identificativo di correlazione (header `X-Request-ID`).

## 8. Sessioni e account
```bash
python -m app.gestione_sessioni attive
python -m app.gestione_sessioni revoca-utente NOME
python -m app.gestione_sessioni revoca-tutte
```

## 9. Diagnostica
- `/salute` risponde `ok` (senza autenticazione) per il controllo di funzionamento.
- `/prestazioni` (amministratore e auditor): tempi medi e massimi per pagina, errori 5xx, richieste oltre 2 s.
- `/esecuzioni`: storico delle analisi con versione del motore e impronta della configurazione.

## 10. Aggiornamento del software e ritorno alla versione precedente
1. Backup (punto 4) e punto di ancoraggio dell'audit.
2. Installare la nuova versione in una cartella separata e lanciare i test.
3. `python -m app.migrazioni applica`, poi riavviare il servizio.
4. **Ritorno alla versione precedente:** fermare il servizio, ripristinare il backup del punto 1 e riavviare la versione precedente. Un software più vecchio rifiuta un database con schema più recente, per evitare corruzioni.

## 11. Dipendenze e vulnerabilità
- Versioni bloccate in `requirements.txt`. Controllo con `pip-audit -r requirements.txt` almeno mensile e prima di ogni rilascio.
- Aggiornare una dipendenza alla volta, rilanciando l'intera suite.
- Incidente di sicurezza: revocare le sessioni, cambiare segreto e password, verificare l'audit con l'ancoraggio, preservare backup e log, avvisare titolare e DPO (eventuale notifica entro 72 ore, art. 33 GDPR, secondo le procedure dell'ente).

## 12. Cosa non fare
Non esporre l'istanza dimostrativa su Internet. Non caricare dati reali prima delle approvazioni elencate in `F_PIANO_SPERIMENTAZIONE.md`. Non usare gli indicatori come prova.
