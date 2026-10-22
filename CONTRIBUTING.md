# Come contribuire a Emersione

Grazie per l'interesse. Emersione è un prototipo di ricerca: i contributi più utili oggi non sono solo righe di codice, ma **critiche alla metodologia, fonti verificabili, verifiche indipendenti e competenze di settore**. Il contesto è descritto in [`docs/L_PROSPETTIVE_E_COLLABORAZIONI.md`](docs/L_PROSPETTIVE_E_COLLABORAZIONI.md).

## Regola fondamentale: nessun dato reale

**Non inserire mai** in issue, discussioni, pull request, commit o allegati:

- dati personali (nomi, codici fiscali, indirizzi, dati di lavoratori o amministratori);
- dati di imprese reali che non siano già pubblici e citati con la fonte;
- documenti riservati, esiti di ispezioni, estratti di banche dati non pubbliche;
- credenziali, chiavi, segreti di configurazione.

Per esempi e test si usano solo dati sintetici, come quelli in `dati/esempio_sintetico.csv`. Un contributo che contiene dati reali viene rimosso.

## Tipi di contributo

| Contributo | Dove |
|---|---|
| Difetto del software | issue, modello *Segnalazione di difetto* |
| Fonte o valore per un coefficiente | issue, modello *Fonte o coefficiente* |
| Critica o proposta metodologica | issue, modello *Metodologia* |
| Domande, idee, proposte di collaborazione | scheda *Discussions* |
| Vulnerabilità di sicurezza | **in privato**, secondo [`SECURITY.md`](SECURITY.md) |
| Modifiche al codice o alla documentazione | pull request |

## Coefficienti e parametri

Ogni valore proposto deve indicare: documento di origine (titolo, ente, data), pagina o tabella, estratto testuale, unità di misura e ambito di validità (settore, territorio, periodo). Un valore senza fonte verificabile non può superare la revisione, come previsto dal ciclo di vita descritto in [`docs/D_METODOLOGIA.md`](docs/D_METODOLOGIA.md).

## Pull request

1. Prepara l'ambiente come indicato nel [README](README.md) (ambiente virtuale `.venv`, nessuna installazione di sistema).
2. Fai una modifica per pull request, con una descrizione chiara di cosa cambia e perché.
3. Esegui i test dalla cartella del progetto:
   ```bash
   python -m unittest discover -s tests
   ```
   devono terminare con `OK`. I test sono eseguiti anche automaticamente su GitHub.
4. Aggiungi o aggiorna i test per il comportamento modificato.
5. Se cambi il comportamento del motore, dei settori o dei permessi, aggiorna la documentazione in `docs/` e il [`CHANGELOG.md`](CHANGELOG.md).
6. Le modifiche al motore non devono introdurre regole legate al nome di un settore: i settori si descrivono nel registro (`config/registro_emersione.json`).

## Stile

- Codice Python leggibile, nomi in italiano coerenti con quelli esistenti.
- Documentazione in italiano, tono tecnico e sobrio; nessuna affermazione di prestazioni non misurate.

## Licenza dei contributi

Inviando un contributo accetti che venga distribuito con le licenze del progetto: **EUPL-1.2** per il codice e **CC BY 4.0** per la documentazione (vedi [README](README.md#licenza)). Dichiari inoltre di avere il diritto di cederlo con queste licenze.

## Comportamento

Chi partecipa accetta il [codice di condotta](CODE_OF_CONDUCT.md).
