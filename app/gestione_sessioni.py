"""Revoca delle sessioni e procedura di recupero degli account.

Uso (dalla cartella del progetto, con le stesse variabili d'ambiente del server):
    python -m app.gestione_sessioni attive
    python -m app.gestione_sessioni revoca-utente NOME
    python -m app.gestione_sessioni revoca-tutte

Recupero di un account (password dimenticata o compromessa):
  1. revoca-utente NOME (le sessioni aperte smettono subito di funzionare);
  2. python -m app.genera_hash_password  → nuovo hash;
  3. sostituire l'hash dell'utente in EMERSIONE_USERS_JSON nel gestore dei segreti;
  4. riavviare il servizio; l'evento va annotato nel registro dell'ente.
La disattivazione di un account si ottiene rimuovendolo da EMERSIONE_USERS_JSON:
dal successivo accesso a una pagina la sessione non è più accettata.
"""
from __future__ import annotations

import sys

from app import audit, sessioni


def main(argv: list[str]) -> int:
    if argv == ["attive"]:
        for r in sessioni.attive():
            print(f"{r['username']:30} sessioni attive: {r['sessioni']}")
        return 0
    if len(argv) == 2 and argv[0] == "revoca-utente":
        n = sessioni.revoca_utente(argv[1])
        audit.registra("console", "revoca_sessioni_utente", argv[1][:100], esito="ok", numero_record=n)
        print(f"Sessioni revocate: {n}")
        return 0
    if argv == ["revoca-tutte"]:
        n = sessioni.revoca_tutte()
        audit.registra("console", "revoca_tutte_le_sessioni", "", esito="ok", numero_record=n)
        print(f"Sessioni revocate: {n}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
