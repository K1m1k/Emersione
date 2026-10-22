# Sicurezza

## Stato del progetto

Emersione è un prototipo di ricerca su dati sintetici e **non deve essere esposto su Internet né usato su dati reali**. Una revisione di sicurezza indipendente non è ancora stata svolta (vedi [`docs/E_SICUREZZA_PRIVACY.md`](docs/E_SICUREZZA_PRIVACY.md) e [`docs/H_LIMITI_NOTI.md`](docs/H_LIMITI_NOTI.md)).

## Versioni supportate

| Versione | Correzioni di sicurezza |
|---|---|
| 3.1.x | sì |
| precedenti | no |

## Come segnalare una vulnerabilità

**Non aprire una issue pubblica.** Usa la segnalazione privata di GitHub:

1. apri la scheda **Security** del repository;
2. scegli **Report a vulnerability**;
3. descrivi il problema, la versione, i passi per riprodurlo e l'impatto stimato.

La segnalazione resta visibile solo a te e al manutentore.

Nella segnalazione **non includere dati personali o riservati reali**: per dimostrare il problema bastano i dati sintetici del progetto.

## Cosa aspettarsi

- Conferma di ricezione indicativamente entro 7 giorni.
- Valutazione e, se confermata, correzione in una nuova versione, con nota nel [`CHANGELOG.md`](CHANGELOG.md).
- Se lo desideri, riconoscimento pubblico del contributo dopo la correzione.

Il progetto è mantenuto su base volontaria: i tempi sono indicativi.

## Ambito

Rientrano nell'ambito, per esempio: autenticazione e sessioni, controllo degli accessi per ruolo, integrità dell'audit e delle relazioni, caricamento di file e documenti, acquisizione da fonti esterne e OSINT, gestione delle credenziali.
