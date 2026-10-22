# Emersione — indicatori spiegabili di possibile irregolarità del lavoro

[![Test](https://github.com/K1m1k/emersione/actions/workflows/test.yml/badge.svg)](https://github.com/K1m1k/emersione/actions/workflows/test.yml)
[![Licenza: EUPL-1.2](https://img.shields.io/badge/licenza-EUPL--1.2-blue.svg)](LICENSE)
[![Documentazione: CC BY 4.0](https://img.shields.io/badge/documentazione-CC%20BY%204.0-lightgrey.svg)](docs/LICENSE.md)
![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)
![Stato: prototipo](https://img.shields.io/badge/stato-prototipo-orange.svg)

> **Prototipo di ricerca, versione 3.1, su dati sintetici.** Non va usato su dati reali di persone o imprese al di fuori di un accordo formale con un ente competente.

Emersione aiuta operatori autorizzati a individuare elementi che meritano un approfondimento umano. **Non accerta illeciti, non stima probabilità di illecito, non produce classifiche pubbliche** e non è pronto per l'uso operativo su dati reali: coefficienti, metodologia e conformità normativa devono ancora essere validati (vedi `docs/H_LIMITI_NOTI.md`).

## Avvio rapido (sviluppo, dalla cartella del progetto)
```bash
python3 -m venv .venv
. .venv/bin/activate                     # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
python -m unittest discover -s tests     # deve terminare con "OK"
python -m app.genera_hash_password       # copia l'hash stampato
export EMERSIONE_SESSION_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export EMERSIONE_USERS_JSON='[{"username":"admin","password_hash":"HASH","ruolo":"amministratore"},{"username":"revisore","password_hash":"HASH","ruolo":"revisore"}]'
python -m app.migrazioni applica
uvicorn app.web.server:app
```
Poi apri `http://127.0.0.1:8000/login`. Ruoli disponibili: `amministratore`, `responsabile_dati`, `analista`, `consultazione`, `revisore`, `auditor`. Nessun account è predefinito. All'avvio i dati sono sintetici.

## Documentazione
| Documento | Contenuto |
|---|---|
| `docs/A_PRESENTAZIONE.md` | problema, obiettivi, destinatari, cosa fa e cosa non fa |
| `docs/B_ARCHITETTURA.md` | componenti, flussi, persistenza, dipendenze |
| `docs/C_CATALOGO_DATI.md` | fonti, accessi, licenze, limiti, provenienza |
| `docs/D_METODOLOGIA.md` | formule, segnali, robustezza, validazione |
| `docs/E_SICUREZZA_PRIVACY.md` | ruoli, minacce, audit, conservazione, questioni normative aperte |
| `docs/F_PIANO_SPERIMENTAZIONE.md` | requisiti, dataset, metriche, criteri di interruzione |
| `docs/G_MANUALE_OPERATIVO.md` | installazione, configurazione, backup, aggiornamenti, diagnostica |
| `docs/H_LIMITI_NOTI.md` | limiti e rischi residui |
| `docs/I_MATRICE_REQUISITI.md` | stato di ogni requisito con evidenze e test |
| `docs/J_INTELLIGENZA_ARTIFICIALE.md` | valutazione sull'integrazione di funzioni IA: condizioni, priorità, principi |
| `docs/K_ROADMAP_IA.md` | fasi di realizzazione dell'IA con criteri di uscita |
| `docs/L_PROSPETTIVE_E_COLLABORAZIONI.md` | accesso ai dati reali, competenze necessarie, come contribuire |
| `docs/VERIFICHE.md` | verifiche eseguite, ambiente, verifiche non ancora possibili |
| `docs/INDICI_EDILIZIA.md` | tabella D.M. 143/2021 e limiti dello screening |

## Struttura essenziale
```
app/motore/          nucleo di analisi e valutazione (nessuna regola per nome di settore)
app/settori.py       registro dichiarativo di settori, parametri, documenti, relazioni
app/ciclo_settori.py collaudo, approvazioni, versioni      app/dipendenze.py  analisi d'impatto
app/connettori/      import CSV, fonti ISTAT/INAIL/ANAC, scoperta dataset
app/web/             interfaccia (Starlette + Jinja2)
config/              registro e storico delle versioni
docs/                documentazione istituzionale
tests/               test automatici (unittest)
```

## Contribuire
Critiche alla metodologia, fonti per i coefficienti, verifiche di sicurezza e proposte di sperimentazione sono benvenute. Le regole sono in [`CONTRIBUTING.md`](CONTRIBUTING.md); il contesto e le collaborazioni cercate in [`docs/L_PROSPETTIVE_E_COLLABORAZIONI.md`](docs/L_PROSPETTIVE_E_COLLABORAZIONI.md). Chi partecipa accetta il [codice di condotta](CODE_OF_CONDUCT.md).

**Non inserire mai dati personali o riservati in issue, discussioni o pull request.**

## Sicurezza
Le vulnerabilità vanno segnalate in privato, come descritto in [`SECURITY.md`](SECURITY.md), non in una issue pubblica.

## Citare il progetto
I metadati di citazione sono in [`CITATION.cff`](CITATION.cff) (pulsante *Cite this repository* su GitHub).

## Licenza
© 2026 K1m1k.

- **Codice:** [European Union Public Licence v. 1.2](LICENSE) (EUPL-1.2). Il testo ufficiale è disponibile in tutte le lingue dell'Unione, italiano compreso, sul sito [interoperable-europe.ec.europa.eu](https://interoperable-europe.ec.europa.eu/collection/eupl/eupl-text-eupl-12).
- **Documentazione** (`docs/`, README e altri file Markdown): [Creative Commons Attribuzione 4.0 Internazionale](docs/LICENSE.md) (CC BY 4.0).
- I dati in `dati/` sono sintetici e non riguardano persone o imprese reali.
