"""Anteprima e mapping controllato dei payload di fonti in osservazioni di riferimento.

Le osservazioni normalizzate restano separate dal dataset aziendale e non incidono
sui punteggi automaticamente. Ogni mapping richiede una revisione umana esplicita.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import xml.etree.ElementTree as ET
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app import fonti_store, settori

DB_PATH = Path(os.environ.get(
    "EMERSIONE_MAPPATURE_DB",
    str(Path(__file__).resolve().parents[1] / "dati" / "emersione_mappature.sqlite3"),
))
MAX_PREVIEW_ROWS = 25
MAX_IMPORT_ROWS = 100_000
MAX_COLUMNS = 300
MAX_CELL_CHARS = 20_000
_LOCK = threading.Lock()
_READY: set[str] = set()


class ErroreMappatura(ValueError):
    """Payload o configurazione di mapping non valida."""


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = str(DB_PATH.resolve())
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=FULL")
    if key not in _READY:
        with _LOCK:
            if key not in _READY:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""CREATE TABLE IF NOT EXISTS mappature_fonti (
                    id TEXT PRIMARY KEY,
                    acquisizione_id TEXT NOT NULL,
                    chiave_fonte TEXT NOT NULL,
                    url_fonte TEXT NOT NULL,
                    hash_fonte TEXT NOT NULL,
                    settore_id TEXT NOT NULL,
                    parametro_id TEXT NOT NULL,
                    campo_valore TEXT NOT NULL,
                    campo_periodo TEXT NOT NULL,
                    campo_territorio TEXT NOT NULL,
                    campo_categoria TEXT NOT NULL,
                    campo_unita TEXT NOT NULL,
                    unita_fissa TEXT NOT NULL,
                    formato_numero TEXT NOT NULL,
                    numero_righe INTEGER NOT NULL,
                    configurazione_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    creato_il TEXT NOT NULL,
                    creato_da TEXT NOT NULL,
                    stato TEXT NOT NULL DEFAULT 'da_verificare',
                    nota_revisore TEXT NOT NULL DEFAULT '',
                    revisionato_da TEXT NOT NULL DEFAULT '',
                    revisionato_il TEXT NOT NULL DEFAULT ''
                )""")
                conn.execute("""CREATE TABLE IF NOT EXISTS osservazioni_riferimento (
                    id TEXT PRIMARY KEY,
                    mappatura_id TEXT NOT NULL REFERENCES mappature_fonti(id) ON DELETE CASCADE,
                    acquisizione_id TEXT NOT NULL,
                    settore_id TEXT NOT NULL,
                    parametro_id TEXT NOT NULL,
                    periodo TEXT NOT NULL,
                    territorio TEXT NOT NULL,
                    categoria TEXT NOT NULL,
                    valore REAL NOT NULL,
                    unita TEXT NOT NULL,
                    dimensioni_json TEXT NOT NULL,
                    riga_origine INTEGER NOT NULL,
                    hash_fonte TEXT NOT NULL,
                    stato TEXT NOT NULL DEFAULT 'da_verificare',
                    acquisito_il TEXT NOT NULL,
                    UNIQUE(mappatura_id, riga_origine)
                )""")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_oss_ref_parametro ON osservazioni_riferimento(parametro_id, periodo, territorio)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_oss_ref_mappatura ON osservazioni_riferimento(mappatura_id, riga_origine)")
                try:
                    os.chmod(DB_PATH, 0o600)
                except OSError:
                    pass
                _READY.add(key)
    return conn


def _tag_locale(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _flatten_object(record: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}

    def visit(value: Any, prefix: str, depth: int = 0) -> None:
        if len(out) >= MAX_COLUMNS or depth > 8:
            return
        if isinstance(value, dict):
            for key, child in list(value.items())[:MAX_COLUMNS]:
                name = f"{prefix}.{key}" if prefix else str(key)
                visit(child, name, depth + 1)
        elif isinstance(value, list):
            if all(not isinstance(v, (dict, list)) for v in value[:100]):
                out[prefix] = " | ".join(str(v) for v in value[:100])[:MAX_CELL_CHARS]
            else:
                out[prefix] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:MAX_CELL_CHARS]
        elif value is None:
            out[prefix] = ""
        else:
            out[prefix] = str(value)[:MAX_CELL_CHARS]

    visit(record, "")
    return out


def _rows_json(raw: bytes) -> list[dict[str, str]]:
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErroreMappatura("Il payload JSON non è valido.") from exc
    records: Any = None
    if isinstance(obj, list) and obj and all(isinstance(x, dict) for x in obj):
        records = obj
    elif isinstance(obj, dict):
        # Prova prima le chiavi comuni delle API; poi individua una lista di oggetti.
        for key in ("records", "data", "results", "items", "value", "result"):
            candidate = obj.get(key)
            if isinstance(candidate, list) and candidate and all(isinstance(x, dict) for x in candidate):
                records = candidate
                break
        if records is None:
            stack = [obj]
            while stack and records is None:
                node = stack.pop(0)
                for value in node.values():
                    if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                        records = value
                        break
                    if isinstance(value, dict) and len(stack) < 1000:
                        stack.append(value)
            if records is None:
                records = [obj]
    if not isinstance(records, list) or not records:
        raise ErroreMappatura("Il JSON non contiene record strutturati utilizzabili per il mapping.")
    if len(records) > MAX_IMPORT_ROWS:
        raise ErroreMappatura(f"Il payload supera il limite di {MAX_IMPORT_ROWS} record per singolo mapping.")
    rows = [_flatten_object(row) for row in records]
    return _verifica_righe(rows)


def _flatten_xml_node(element: ET.Element, prefix: str = "") -> dict[str, str]:
    out: dict[str, list[str]] = {}

    def walk(node: ET.Element, path: str, depth: int = 0) -> None:
        if depth > 12:
            return
        for key, value in list(node.attrib.items())[:50]:
            out.setdefault(f"{path}.@{_tag_locale(key)}", []).append(value[:MAX_CELL_CHARS])
        children = list(node)
        if not children:
            value = (node.text or "").strip()
            if value:
                out.setdefault(path, []).append(value[:MAX_CELL_CHARS])
            return
        for child in children[:MAX_COLUMNS]:
            child_name = _tag_locale(child.tag)
            child_path = f"{path}.{child_name}" if path else child_name
            walk(child, child_path, depth + 1)

    walk(element, prefix)
    return {key: " | ".join(values[:100])[:MAX_CELL_CHARS] for key, values in out.items()}


def _rows_xml(raw: bytes) -> list[dict[str, str]]:
    # DTD e entità sono rifiutati prima del parsing, anche se il documento è UTF-16.
    try:
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or raw[:100].count(b"\x00") > 5:
            text = raw.decode("utf-16")
        else:
            text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ErroreMappatura("Codifica XML non supportata.") from exc
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, flags=re.IGNORECASE):
        raise ErroreMappatura("XML con DTD/entity non ammessi.")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ErroreMappatura("XML non ben formato.") from exc
    # Seleziona il primo gruppo di elementi fratelli ripetuti, come le righe di un
    # dataset; se non c'è un gruppo ripetuto, tratta la radice come singolo record.
    candidates: list[tuple[int, list[ET.Element]]] = []
    queue = [root]
    while queue and len(queue) <= 100_000:
        node = queue.pop(0)
        children = list(node)
        if children:
            groups: dict[str, list[ET.Element]] = {}
            for child in children:
                groups.setdefault(child.tag, []).append(child)
            for group in groups.values():
                if len(group) > 1:
                    candidates.append((len(group), group))
            queue.extend(children[:500])
    if candidates:
        records = max(candidates, key=lambda item: item[0])[1]
    else:
        records = [root]
    if len(records) > MAX_IMPORT_ROWS:
        raise ErroreMappatura(f"XML oltre il limite di {MAX_IMPORT_ROWS} record per mapping.")
    rows = [_flatten_xml_node(record) for record in records]
    return _verifica_righe(rows)


def _rows_csv(raw: bytes) -> list[dict[str, str]]:
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ErroreMappatura("CSV non UTF-8: non è possibile generare un mapping sicuro.") from exc
    try:
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text, newline=""), dialect=dialect, strict=True)
        header = next(reader, None)
        if not header:
            raise ErroreMappatura("CSV senza intestazione o senza righe.")
        header = [str(value).strip() for value in header]
        if any(not col for col in header):
            raise ErroreMappatura("CSV con nomi di colonna vuoti; correggere il file prima del mapping.")
        if len(header) > MAX_COLUMNS:
            raise ErroreMappatura(f"CSV oltre il limite di {MAX_COLUMNS} colonne.")
        norm = [h.casefold() for h in header]
        if len(norm) != len(set(norm)):
            raise ErroreMappatura("CSV con intestazioni duplicate; correggere il file prima del mapping.")
        rows: list[dict[str, str]] = []
        for line_number, values in enumerate(reader, start=2):
            if not values or not any(v.strip() for v in values):
                continue
            if len(values) != len(header):
                raise ErroreMappatura(f"CSV: riga {line_number} con {len(values)} campi rispetto ai {len(header)} dell'intestazione.")
            if len(rows) >= MAX_IMPORT_ROWS:
                raise ErroreMappatura(f"CSV oltre il limite di {MAX_IMPORT_ROWS} record per mapping.")
            if any(len(v) > MAX_CELL_CHARS for v in values):
                raise ErroreMappatura(f"CSV: cella eccessivamente lunga alla riga {line_number}.")
            rows.append(dict(zip(header, values)))
    except (csv.Error, StopIteration) as exc:
        raise ErroreMappatura("CSV non interpretabile oppure privo di righe dati.") from exc
    if not rows:
        raise ErroreMappatura("CSV senza righe dati dopo l'intestazione.")
    return _verifica_righe(rows)


def _verifica_righe(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        raise ErroreMappatura("Il payload non contiene record da mappare.")
    if len(rows) > MAX_IMPORT_ROWS:
        raise ErroreMappatura(f"Il payload supera il limite di {MAX_IMPORT_ROWS} record.")
    columns = {col for row in rows for col in row}
    if not columns or len(columns) > MAX_COLUMNS:
        raise ErroreMappatura(f"Schema con un numero di colonne non supportato (massimo {MAX_COLUMNS}).")
    for row in rows:
        for col, val in row.items():
            if len(str(col)) > 300 or len(str(val)) > MAX_CELL_CHARS:
                raise ErroreMappatura("Il payload contiene un campo troppo lungo.")
    return rows


def anteprima(acquisizione_id: str) -> dict[str, Any]:
    trovato = fonti_store.contenuto(acquisizione_id)
    if trovato is None:
        raise ErroreMappatura("Acquisizione non trovata o identificativo non valido.")
    meta, raw = trovato
    ct = meta["content_type"].casefold()
    if "json" in ct or raw.lstrip().startswith((b"{", b"[")):
        formato, rows = "json", _rows_json(raw)
    elif "xml" in ct or raw.lstrip().startswith(b"<") or raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        formato, rows = "xml", _rows_xml(raw)
    elif "csv" in ct or "text/plain" in ct or raw[:2048].count(b",") >= 2 or raw[:2048].count(b";") >= 2:
        formato, rows = "csv", _rows_csv(raw)
    else:
        raise ErroreMappatura("Formato non mappabile in questa versione. Sono supportati CSV con intestazione, JSON con record strutturati e XML generico.")
    if not rows:
        raise ErroreMappatura("Nessuna riga normalizzabile trovata.")
    columns = sorted({col for row in rows for col in row})[:MAX_COLUMNS]
    records = []
    for row in rows[:MAX_PREVIEW_ROWS]:
        records.append({col: row.get(col, "")[:300] for col in columns})
    catalogo = {a["id"]: a for a in settori.lista_settori(includi_archiviati=True)}
    fonti = {f["id"]: f for f in fonti_store.elenco(100)}
    fonte = fonti.get(acquisizione_id, {})
    return {
        "acquisizione_id": acquisizione_id, "chiave_fonte": fonte.get("chiave", meta["chiave"]),
        "url_fonte": fonte.get("url", ""), "hash_fonte": meta["sha256"],
        "content_type": meta["content_type"], "formato": formato,
        "numero_righe": len(rows), "colonne": columns, "righe": records,
        "nota": "Anteprima strutturale. Il mapping conserva le dimensioni non selezionate come metadati e non modifica i punteggi.",
    }


def _numero(raw: Any, formato: str) -> float:
    if raw is None or isinstance(raw, bool):
        raise ValueError("valore non numerico")
    value = str(raw).strip().replace("\u00a0", "").replace(" ", "")
    if not value:
        raise ValueError("valore vuoto")
    if len(value) > 100:
        raise ValueError("valore troppo lungo")
    if formato == "virgola":
        value = value.replace(".", "").replace(",", ".")
    elif formato == "punto":
        value = value.replace(",", "")
    elif formato == "automatico":
        if "," in value and "." in value:
            if value.rfind(",") > value.rfind("."):
                value = value.replace(".", "").replace(",", ".")
            else:
                value = value.replace(",", "")
        elif "," in value:
            value = value.replace(".", "").replace(",", ".")
    else:
        raise ErroreMappatura("Formato numerico non valido.")
    try:
        dec = Decimal(value)
        if not dec.is_finite():
            raise ValueError("valore non finito")
        number = float(dec)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ValueError("valore non numerico") from exc
    if not math.isfinite(number):
        raise ValueError("valore non finito")
    return number


def crea_mappatura(*, acquisizione_id: str, settore_id: str, parametro_id: str,
                    campo_valore: str, campo_periodo: str = "", campo_territorio: str = "",
                    campo_categoria: str = "", campo_unita: str = "", unita_fissa: str = "",
                    formato_numero: str = "automatico", utente: str) -> dict[str, Any]:
    preview = anteprima(acquisizione_id)
    columns = set(preview["colonne"])
    chosen = [campo_valore, campo_periodo, campo_territorio, campo_categoria, campo_unita]
    if any(not isinstance(c, str) or c not in columns for c in chosen if c):
        raise ErroreMappatura("Uno dei campi selezionati non appartiene allo schema del payload.")
    if not campo_valore:
        raise ErroreMappatura("Il campo che contiene il valore numerico è obbligatorio.")
    if formato_numero not in {"automatico", "virgola", "punto"}:
        raise ErroreMappatura("Formato numerico non supportato.")
    if not isinstance(utente, str) or not utente.strip() or len(utente) > 100:
        raise ErroreMappatura("Operatore non valido.")
    # Le osservazioni di riferimento servono anche a preparare settori in bozza o revisione.
    sector = settori.configurazione_settore(settore_id)
    if sector is not None and sector.get("stato") == "archiviato":
        sector = None
    if sector is None:
        raise ErroreMappatura("Il settore non è attivo o non è disponibile per il mapping.")
    params = settori.catalogo_parametri()
    param = params.get(parametro_id)
    if not isinstance(param, dict):
        raise ErroreMappatura("Parametro non trovato.")
    if param.get("ambito") not in {settore_id, "trasversale"}:
        raise ErroreMappatura("Il parametro non appartiene al settore scelto.")
    unita = (unita_fissa or param.get("unita") or "").strip()
    if campo_unita and unita_fissa.strip():
        raise ErroreMappatura("Scegli una colonna unità oppure un'unità fissa, non entrambe.")
    if len(unita) > 100:
        raise ErroreMappatura("Unità di misura troppo lunga.")
    if not unita and not campo_unita:
        raise ErroreMappatura("Indicare una colonna unità o un'unità di misura fissa/ereditata dal parametro.")

    trovato = fonti_store.contenuto(acquisizione_id)
    if trovato is None:
        raise ErroreMappatura("Payload non disponibile; impossibile verificare provenienza e integrità.")
    meta, raw = trovato
    # Rilegge tutti i record verificando lo schema, non soltanto le righe di anteprima.
    if preview["formato"] == "csv":
        rows = _rows_csv(raw)
    elif preview["formato"] == "json":
        rows = _rows_json(raw)
    else:
        rows = _rows_xml(raw)

    normalizzate: list[dict[str, Any]] = []
    errori: list[str] = []
    for index, row in enumerate(rows, start=1):
        try:
            value = _numero(row.get(campo_valore), formato_numero)
            # Non assumere unità identiche se la fonte dichiara esplicitamente altro.
            unit_value = str(row.get(campo_unita, "")).strip() if campo_unita else unita
            if not unit_value:
                raise ValueError("unità mancante")
            reserved = {campo_valore, campo_periodo, campo_territorio, campo_categoria, campo_unita} - {""}
            extras = {k: v[:500] for k, v in row.items() if k not in reserved and v != ""}
            normalizzate.append({
                "id": secrets.token_hex(16), "settore_id": settore_id,
                "parametro_id": parametro_id, "periodo": str(row.get(campo_periodo, "")).strip()[:100] if campo_periodo else "",
                "territorio": str(row.get(campo_territorio, "")).strip()[:150] if campo_territorio else "",
                "categoria": str(row.get(campo_categoria, "")).strip()[:150] if campo_categoria else "",
                "valore": value, "unita": unit_value[:100],
                "dimensioni_json": json.dumps(extras, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                "riga_origine": index,
            })
        except (ValueError, TypeError) as exc:
            if len(errori) < 25:
                errori.append(f"riga {index}: {str(exc)[:160]}")
    if errori:
        raise ErroreMappatura("Mapping non salvato: valori mancanti/non numerici o unità non valide. " + "; ".join(errori))
    if len(normalizzate) != preview["numero_righe"]:
        raise ErroreMappatura("Numero di righe incoerente tra anteprima e normalizzazione. Ripetere l'acquisizione.")

    cfg = {
        "campo_valore": campo_valore, "campo_periodo": campo_periodo,
        "campo_territorio": campo_territorio, "campo_categoria": campo_categoria,
        "campo_unita": campo_unita, "unita_fissa": unita_fissa,
        "formato_numero": formato_numero,
    }
    fingerprint = hashlib.sha256(json.dumps({
        "acquisizione_id": acquisizione_id, "hash": meta["sha256"], "settore": settore_id,
        "parametro": parametro_id, "cfg": cfg,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    ident = secrets.token_hex(16)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""INSERT INTO mappature_fonti
                (id,acquisizione_id,chiave_fonte,url_fonte,hash_fonte,settore_id,parametro_id,
                 campo_valore,campo_periodo,campo_territorio,campo_categoria,campo_unita,
                 unita_fissa,formato_numero,numero_righe,configurazione_json,fingerprint,
                 creato_il,creato_da,stato)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'da_verificare')""", (
                ident, acquisizione_id, meta["chiave"], preview["url_fonte"], meta["sha256"],
                settore_id, parametro_id, campo_valore, campo_periodo, campo_territorio,
                campo_categoria, campo_unita, unita, formato_numero, len(normalizzate),
                json.dumps(cfg, ensure_ascii=False, sort_keys=True), fingerprint, now, utente[:100]))
            conn.executemany("""INSERT INTO osservazioni_riferimento
                (id,mappatura_id,acquisizione_id,settore_id,parametro_id,periodo,territorio,categoria,
                 valore,unita,dimensioni_json,riga_origine,hash_fonte,stato,acquisito_il)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'da_verificare',?)""", [(
                    r["id"], ident, acquisizione_id, r["settore_id"], r["parametro_id"], r["periodo"],
                    r["territorio"], r["categoria"], r["valore"], r["unita"], r["dimensioni_json"],
                    r["riga_origine"], meta["sha256"], now) for r in normalizzate])
            conn.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            try: conn.execute("ROLLBACK")
            except sqlite3.Error: pass
            raise ErroreMappatura("Questo payload e questa configurazione di mapping risultano già importati. Non sono stati creati duplicati.") from exc
        except Exception as exc:
            try: conn.execute("ROLLBACK")
            except sqlite3.Error: pass
            if isinstance(exc, ErroreMappatura): raise
            raise ErroreMappatura("Normalizzazione non salvata; la transazione è stata annullata.") from exc
    return {"id": ident, "acquisizione_id": acquisizione_id, "chiave_fonte": meta["chiave"],
        "url_fonte": preview["url_fonte"], "hash_fonte": meta["sha256"], "settore_id": settore_id,
        "parametro_id": parametro_id, "numero_righe": len(normalizzate), "stato": "da_verificare",
        "creato_il": now, "creato_da": utente[:100], "configurazione": cfg}


def elenco(limite: int = 100) -> list[dict[str, Any]]:
    limite = max(1, min(int(limite), 200))
    with closing(_conn()) as conn:
        rows = conn.execute("""SELECT id,acquisizione_id,chiave_fonte,url_fonte,hash_fonte,settore_id,
            parametro_id,numero_righe,creato_il,creato_da,stato,nota_revisore,revisionato_da,revisionato_il
            FROM mappature_fonti ORDER BY creato_il DESC LIMIT ?""", (limite,)).fetchall()
    return [dict(r) for r in rows]


def osservazioni(mapping_id: str, limite: int = 500) -> list[dict[str, Any]]:
    if not isinstance(mapping_id, str) or not re.fullmatch(r"[a-f0-9]{32}", mapping_id):
        raise ErroreMappatura("Identificativo mapping non valido.")
    limite = max(1, min(int(limite), 1000))
    with closing(_conn()) as conn:
        rows = conn.execute("""SELECT id,periodo,territorio,categoria,valore,unita,dimensioni_json,
            riga_origine,hash_fonte,stato FROM osservazioni_riferimento
            WHERE mappatura_id=? ORDER BY riga_origine LIMIT ?""", (mapping_id, limite)).fetchall()
    output = []
    for row in rows:
        d = dict(row)
        try: d["dimensioni"] = json.loads(d.pop("dimensioni_json"))
        except json.JSONDecodeError: d["dimensioni"] = {}
        output.append(d)
    return output


def revisiona(mapping_id: str, *, stato: str, nota: str, revisore: str) -> None:
    if not isinstance(mapping_id, str) or not re.fullmatch(r"[a-f0-9]{32}", mapping_id):
        raise ErroreMappatura("Identificativo mapping non valido.")
    if stato not in {"mapping_verificato", "non_pertinente", "da_verificare"}:
        raise ErroreMappatura("Stato del mapping non valido.")
    if not isinstance(nota, str) or not 15 <= len(nota.strip()) <= 1500:
        raise ErroreMappatura("La revisione richiede una nota tra 15 e 1500 caratteri.")
    if not isinstance(revisore, str) or not revisore.strip() or len(revisore) > 100:
        raise ErroreMappatura("Identità del revisore non valida.")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_conn()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute("UPDATE mappature_fonti SET stato=?,nota_revisore=?,revisionato_da=?,revisionato_il=? WHERE id=?",
                (stato, nota.strip(), revisore[:100], now, mapping_id))
            if cur.rowcount != 1:
                raise ErroreMappatura("Mapping non trovato.")
            conn.execute("UPDATE osservazioni_riferimento SET stato=? WHERE mappatura_id=?", (stato, mapping_id))
            conn.execute("COMMIT")
        except Exception as exc:
            try: conn.execute("ROLLBACK")
            except sqlite3.Error: pass
            if isinstance(exc, ErroreMappatura): raise
            raise ErroreMappatura("Revisione non salvata; nessuna osservazione è stata modificata.") from exc
