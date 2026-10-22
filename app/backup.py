"""Backup, verifica e ripristino dei dati locali (sezioni 24 e 26).

Uso (dalla cartella del progetto, con le stesse variabili d'ambiente del server):
    python -m app.backup crea CARTELLA_DESTINAZIONE
    python -m app.backup verifica FILE.tar.gz
    python -m app.backup ripristina FILE.tar.gz [--forza]

Il backup contiene: registro settori/parametri e suo storico, tutti gli archivi
SQLite (copiati con l'API di backup online di SQLite, coerente anche a servizio
attivo), registro di audit e documenti caricati. Un manifesto elenca percorso,
dimensione e SHA-256 di ogni file; la verifica li ricalcola.

Il ripristino rifiuta di sovrascrivere dati esistenti senza --forza e, con
--forza, salva prima una copia dei file sostituiti (".pre-ripristino-<data>").
Va eseguito a servizio fermo. Il backup NON è cifrato: va conservato su un
supporto protetto secondo le regole dell'ente (contiene dati potenzialmente
riservati e il registro di audit).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSIONE_FORMATO = 1


def componenti() -> dict[str, Path]:
    """Percorsi correnti (rispettano le variabili d'ambiente) dei dati da salvare."""
    from app import (audit, dataset_store, db_operativo, documenti, fonti_mapping, fonti_store, grafo, osint,
                     sessioni, settori, versioni_registro)
    return {
        "config/registro_emersione.json": Path(settori.PERCORSO_REGISTRO),
        "config/registro_versioni.sqlite3": versioni_registro.percorso(),
        "dati/emersione_operativo.sqlite3": Path(db_operativo.DB_PATH),
        "dati/emersione_dataset.sqlite3": Path(dataset_store.DB_PATH),
        "dati/emersione_fonti.sqlite3": Path(fonti_store.DB_PATH),
        "dati/emersione_mappature.sqlite3": Path(fonti_mapping.DB_PATH),
        "dati/emersione_osint.sqlite3": Path(osint.DB_PATH),
        "dati/emersione_grafo.sqlite3": Path(grafo.DB_PATH),
        "dati/sessioni.sqlite3": Path(sessioni.DB_PATH),
        "dati/audit.jsonl": Path(audit.PERCORSO_LOG),
        "dati/documenti": Path(documenti._STORAGE),
    }


def _sha256(percorso: Path) -> str:
    h = hashlib.sha256()
    with percorso.open("rb") as f:
        for blocco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(blocco)
    return h.hexdigest()


def _copia_sqlite(sorgente: Path, destinazione: Path) -> None:
    with closing(sqlite3.connect(f"file:{sorgente}?mode=ro", uri=True)) as src, closing(sqlite3.connect(destinazione)) as dst:
        src.backup(dst)


def crea(cartella: Path) -> Path:
    cartella.mkdir(parents=True, exist_ok=True)
    nome = f"emersione-backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
    destinazione = cartella / nome
    manifesto: dict[str, Any] = {"formato": VERSIONE_FORMATO, "creato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                 "file": [], "assenti": []}
    with tempfile.TemporaryDirectory() as tmp:
        radice = Path(tmp)
        for logico, reale in componenti().items():
            if not reale.exists():
                manifesto["assenti"].append(logico)
                continue
            copia = radice / logico
            copia.parent.mkdir(parents=True, exist_ok=True)
            if reale.is_dir():
                shutil.copytree(reale, copia)
            elif reale.suffix == ".sqlite3":
                _copia_sqlite(reale, copia)
            else:
                shutil.copy2(reale, copia)
        for f in sorted(p for p in radice.rglob("*") if p.is_file()):
            manifesto["file"].append({"percorso": f.relative_to(radice).as_posix(), "byte": f.stat().st_size, "sha256": _sha256(f)})
        (radice / "MANIFESTO.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
        with tarfile.open(destinazione, "w:gz") as tar:
            for f in sorted(p for p in radice.rglob("*") if p.is_file()):
                tar.add(f, arcname=f.relative_to(radice).as_posix())
    destinazione.chmod(0o600)
    return destinazione


def _membri_sicuri(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    membri = []
    for m in tar.getmembers():
        nome = Path(m.name)
        if m.issym() or m.islnk() or nome.is_absolute() or ".." in nome.parts or not (m.isfile() or m.isdir()):
            raise ValueError(f"Elemento non ammesso nell'archivio: {m.name}")
        membri.append(m)
    return membri


def verifica(archivio: Path) -> dict[str, Any]:
    errori: list[str] = []
    with tarfile.open(archivio, "r:gz") as tar:
        membri = {m.name: m for m in _membri_sicuri(tar)}
        if "MANIFESTO.json" not in membri:
            return {"valido": False, "errori": ["Manifesto assente."], "file": 0}
        manifesto = json.loads(tar.extractfile(membri["MANIFESTO.json"]).read().decode("utf-8"))
        for voce in manifesto.get("file", []):
            m = membri.get(voce["percorso"])
            if m is None:
                errori.append(f"mancante: {voce['percorso']}")
                continue
            contenuto = tar.extractfile(m).read()
            if hashlib.sha256(contenuto).hexdigest() != voce["sha256"]:
                errori.append(f"impronta diversa: {voce['percorso']}")
        for nome, m in membri.items():
            if m.isfile() and nome != "MANIFESTO.json" and nome not in {v["percorso"] for v in manifesto.get("file", [])}:
                errori.append(f"file non dichiarato: {nome}")
            if nome.endswith(".sqlite3") and m.isfile():
                with tempfile.NamedTemporaryFile(suffix=".sqlite3") as t:
                    t.write(tar.extractfile(m).read())
                    t.flush()
                    with closing(sqlite3.connect(t.name)) as c:
                        if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            errori.append(f"integrità SQLite non superata: {nome}")
    return {"valido": not errori, "errori": errori, "file": len(manifesto.get("file", [])),
            "creato_il": manifesto.get("creato_il"), "assenti_al_backup": manifesto.get("assenti", [])}


def ripristina(archivio: Path, *, forza: bool = False) -> dict[str, Any]:
    esito = verifica(archivio)
    if not esito["valido"]:
        raise ValueError("Backup non valido: " + "; ".join(esito["errori"][:5]))
    mappa = componenti()
    esistenti = [logico for logico, reale in mappa.items() if reale.exists() and logico != "dati/sessioni.sqlite3"]
    if esistenti and not forza:
        raise FileExistsError("Esistono già dati locali (" + ", ".join(esistenti) + "): usare --forza per sostituirli.")
    marca = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ripristinati = []
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(archivio, "r:gz") as tar:
        membri = _membri_sicuri(tar)
        for m in membri:
            if m.isfile():
                destinazione = Path(tmp) / m.name
                destinazione.parent.mkdir(parents=True, exist_ok=True)
                destinazione.write_bytes(tar.extractfile(m).read())
        for logico, reale in mappa.items():
            sorgente = Path(tmp) / logico
            if not sorgente.exists():
                continue
            if reale.exists():
                copia = reale.with_name(reale.name + f".pre-ripristino-{marca}")
                shutil.move(str(reale), str(copia))
            reale.parent.mkdir(parents=True, exist_ok=True)
            if sorgente.is_dir():
                shutil.copytree(sorgente, reale)
            else:
                shutil.copy2(sorgente, reale)
            ripristinati.append(logico)
    # Le sessioni non vanno mai riattivate da un backup: si revocano tutte.
    from app import sessioni
    try:
        sessioni.revoca_tutte()
    except Exception:
        pass
    return {"ripristinati": ripristinati, "backup": esito}


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "crea":
        print(crea(Path(argv[1])))
        return 0
    if len(argv) == 2 and argv[0] == "verifica":
        esito = verifica(Path(argv[1]))
        print(json.dumps(esito, ensure_ascii=False, indent=2))
        return 0 if esito["valido"] else 1
    if len(argv) >= 2 and argv[0] == "ripristina":
        print(json.dumps(ripristina(Path(argv[1]), forza="--forza" in argv), ensure_ascii=False, indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
