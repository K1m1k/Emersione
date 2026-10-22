"""Estrazione documentale assistita: propone evidenze candidate, mai parametri attivi.

L'estrazione testuale è solo una fase di triage; unità, contesto, validità e
applicabilità devono essere verificati dall'operatore contro la fonte originale.
"""
from __future__ import annotations
import csv, io, json, re
from pathlib import Path
from typing import Any

MAX_PDF_PAGES = 120
MAX_TEXT_CHARS = 1_000_000
MAX_CANDIDATI = 120
_NUM_UNIT = re.compile(r"(?<![A-Za-z0-9])(?P<num>-?\d{1,3}(?:[.\s]\d{3})+(?:[,.]\d+)?(?!\d)|-?\d+(?:[,.]\d+)?(?!\d))(?:\s*)(?P<unit>%|percento|euro|EUR|€/ora|euro/ora|ore/ettaro|ore per ettaro|ore/m²|ore/m2|m2|ore/mc|ore/m³|giorni|mesi|anni|kg|tonnellate|ettari|m²|mq|mc|m³|coperti|addetti|lavoratori)?(?![A-Za-z])", re.IGNORECASE)
_NORME = re.compile(r"\b(?:D\.?\s*M\.?\s*\d{1,4}\s*/\s*\d{4}|D\.?\s*Lgs\.?\s*\d{1,4}\s*/\s*\d{4}|Regolamento\s*(?:UE|\(UE\))?\s*\d{1,4}\s*/\s*\d{4}|Legge\s*\d{1,4}\s*/\s*\d{4})\b", re.IGNORECASE)

class ErroreEstrazione(ValueError): pass

def _testo_pdf(contenuto: bytes) -> tuple[str, list[dict[str, Any]]]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(contenuto), strict=True)
        if reader.is_encrypted:
            raise ErroreEstrazione("PDF cifrato: estrazione non consentita senza una procedura autorizzata.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ErroreEstrazione(f"PDF oltre il limite di {MAX_PDF_PAGES} pagine per singola estrazione.")
        pagine = []
        testi = []
        totale = 0
        for n, pagina in enumerate(reader.pages, start=1):
            t = pagina.extract_text() or ""
            totale += len(t)
            if totale > MAX_TEXT_CHARS: raise ErroreEstrazione("Testo estratto oltre il limite massimo.")
            pagine.append({"pagina": n, "testo": t[:100_000]})
            testi.append(t)
        return "\n".join(testi), pagine
    except ErroreEstrazione:
        raise
    except Exception as exc:
        raise ErroreEstrazione("PDF non leggibile o danneggiato; il file originale resta conservato.") from exc

def _flatten_json(value: Any, prefix: str = "") -> list[str]:
    out = []
    if isinstance(value, dict):
        for k, v in list(value.items())[:10000]: out.extend(_flatten_json(v, f"{prefix}{k}: "))
    elif isinstance(value, list):
        for v in value[:10000]: out.extend(_flatten_json(v, prefix))
    elif value is not None:
        out.append(f"{prefix}{value}")
    return out

def estrai(nome_file: str, contenuto: bytes) -> dict[str, Any]:
    ext = Path(nome_file).suffix.casefold()
    pagine: list[dict[str, Any]] = []
    try:
        if ext == ".pdf":
            testo, pagine = _testo_pdf(contenuto)
        elif ext == ".txt":
            testo = contenuto.decode("utf-8-sig", errors="strict")
            pagine = [{"pagina": None, "testo": testo}]
        elif ext == ".csv":
            testo_raw = contenuto.decode("utf-8-sig", errors="strict")
            righe = list(csv.reader(io.StringIO(testo_raw), strict=True))
            testo = "\n".join(" | ".join(cell for cell in riga) for riga in righe[:20000])
            pagine = [{"pagina": None, "testo": testo}]
        elif ext == ".json":
            dato = json.loads(contenuto.decode("utf-8-sig", errors="strict"))
            testo = "\n".join(_flatten_json(dato))
            pagine = [{"pagina": None, "testo": testo}]
        else:
            return {"stato": "non_supportata", "candidati": [], "nota": "Formato non supportato per estrazione testuale."}
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error) as exc:
        return {"stato": "errore_estrazione", "candidati": [], "nota": f"Il testo strutturato non è interpretabile: {type(exc).__name__}."}
    testo = testo[:MAX_TEXT_CHARS]
    candidati: list[dict[str, Any]] = []
    # Le corrispondenze numeriche sono volutamente candidati generici: l'estrattore
    # non decide se siano coefficienti applicabili al settore.
    for pagina in pagine:
        body = pagina["testo"] or ""
        for match in _NUM_UNIT.finditer(body):
            raw = match.group("num").strip()
            unit = (match.group("unit") or "").strip()
            inizio = max(0, match.start() - 100)
            fine = min(len(body), match.end() + 100)
            candidati.append({"tipo": "valore_numerico_candidato", "valore_testuale": raw,
                "unita_testuale": unit or None, "pagina": pagina["pagina"],
                "estratto": re.sub(r"\s+", " ", body[inizio:fine]).strip()[:260],
                "stato": "da_verificare"})
            if len(candidati) >= MAX_CANDIDATI: break
        if len(candidati) >= MAX_CANDIDATI: break
        for match in _NORME.finditer(body):
            inizio = max(0, match.start() - 100); fine = min(len(body), match.end() + 120)
            candidati.append({"tipo": "riferimento_normativo_candidato", "valore_testuale": match.group(0),
                "unita_testuale": None, "pagina": pagina["pagina"],
                "estratto": re.sub(r"\s+", " ", body[inizio:fine]).strip()[:260],
                "stato": "da_verificare"})
            if len(candidati) >= MAX_CANDIDATI: break
    return {"stato": "candidati_estratti" if candidati else "nessun_candidato_rilevato",
        "candidati": candidati[:MAX_CANDIDATI],
        "nota": "Estrazione automatica preliminare. Nessun valore è approvato o applicato al motore; verificare sempre la fonte originale, il contesto, l'unità, il periodo e l'ambito.",
        "caratteri_analizzati": len(testo), "pagine_lette": len(pagine)}
