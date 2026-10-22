"""Strumenti dell'auditor per il registro degli eventi.

Uso (dalla cartella del progetto, con le stesse variabili d'ambiente del server):
    python -m app.audit_cli verifica                 # controlla la catena di hash
    python -m app.audit_cli ancora > punto.json      # punto di controllo da conservare FUORI dal sistema
    python -m app.audit_cli verifica-ancora punto.json
    python -m app.audit_cli ruota CARTELLA_ARCHIVIO  # archivia il segmento e ne apre uno nuovo collegato
    python -m app.audit_cli verifica-file FILE.jsonl # verifica un segmento archiviato

La catena di hash e l'ancoraggio rilevano molte alterazioni ma non rendono il
registro immutabile: per l'impiego istituzionale serve un archivio separato a
sola aggiunta gestito dall'ente.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app import audit


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    comando = argv[0]
    if comando == "verifica":
        esito = audit.verifica_integrita()
        print(json.dumps(esito, ensure_ascii=False, indent=2))
        return 0 if esito["valida"] else 1
    if comando == "ancora":
        print(json.dumps(audit.ancoraggio(), ensure_ascii=False, indent=2))
        return 0
    if comando == "verifica-ancora" and len(argv) == 2:
        esito = audit.verifica_ancoraggio(json.loads(Path(argv[1]).read_text(encoding="utf-8")))
        print(json.dumps(esito, ensure_ascii=False, indent=2))
        return 0 if esito["esito"] == "conforme" else 1
    if comando == "ruota" and len(argv) == 2:
        print(json.dumps(audit.ruota(Path(argv[1])), ensure_ascii=False, indent=2))
        return 0
    if comando == "verifica-file" and len(argv) == 2:
        esito = audit.verifica_integrita(Path(argv[1]))
        print(json.dumps(esito, ensure_ascii=False, indent=2))
        return 0 if esito["valida"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
