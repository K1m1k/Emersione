"""Generazione di una relazione PDF descrittiva e non provvedimentale."""
from __future__ import annotations

import io
from datetime import datetime, timezone
from html import escape
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)


class ErroreReport(ValueError):
    """Dati insufficienti o non validi per creare la relazione."""


def _testo(valore: Any) -> str:
    if valore is None or valore == "":
        return "Non disponibile"
    if isinstance(valore, bool):
        return "Sì" if valore else "No"
    if isinstance(valore, float):
        return f"{valore:.6g}"
    return str(valore)


def _p(valore: Any, stile: ParagraphStyle) -> Paragraph:
    # I valori del dataset sono input non attendibili: sempre escaping XML per ReportLab.
    return Paragraph(escape(_testo(valore)), stile)


def _footer(canvas, doc):
    canvas.saveState()
    larghezza, _ = A4
    canvas.setStrokeColor(colors.HexColor("#B9C1CC"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 15 * mm, larghezza - 18 * mm, 15 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#475467"))
    canvas.drawString(18 * mm, 10 * mm, "EMERSIONE · Relazione sperimentale · Revisione umana obbligatoria")
    canvas.drawRightString(larghezza - 18 * mm, 10 * mm, f"Pagina {doc.page}")
    canvas.restoreState()


def genera_relazione_azienda(
    azienda: dict[str, Any],
    *,
    metadati_lotto: dict[str, Any] | None = None,
    configurazione_settore: dict[str, Any] | None = None,
    contesto: dict[str, Any] | None = None,
) -> bytes:
    """Genera un PDF con gli indicatori e la provenienza senza formulare giudizi giuridici."""
    if not isinstance(azienda, dict) or not isinstance(azienda.get("id"), str):
        raise ErroreReport("Record aziendale non valido.")
    analisi = azienda.get("analisi")
    if not isinstance(analisi, dict):
        raise ErroreReport("Il record non contiene un'analisi utilizzabile.")
    lotto = metadati_lotto if isinstance(metadati_lotto, dict) else {}
    settore = configurazione_settore if isinstance(configurazione_settore, dict) else {}
    ctx = contesto if isinstance(contesto, dict) else {}
    pratica = ctx.get("pratica") if isinstance(ctx.get("pratica"), dict) else {}

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title=f"Emersione - relazione {azienda['id']}",
        author="Emersione",
        subject="Relazione descrittiva degli indicatori sperimentali",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="TitoloEmersione", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=19, leading=23, textColor=colors.HexColor("#26364A"), alignment=TA_CENTER,
        spaceAfter=5 * mm,
    ))
    styles.add(ParagraphStyle(
        name="SottotitoloEmersione", parent=styles["Normal"], fontSize=9,
        leading=12, textColor=colors.HexColor("#475467"), alignment=TA_CENTER,
        spaceAfter=6 * mm,
    ))
    styles.add(ParagraphStyle(
        name="SezioneEmersione", parent=styles["Heading2"], fontSize=12,
        leading=15, textColor=colors.HexColor("#26364A"), spaceBefore=5 * mm,
        spaceAfter=2 * mm, keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        name="TestoPiccolo", parent=styles["BodyText"], fontSize=8.5,
        leading=11, spaceAfter=1.5 * mm, wordWrap="LTR",
    ))
    styles.add(ParagraphStyle(
        name="TestoTabella", parent=styles["BodyText"], fontSize=8,
        leading=10, wordWrap="LTR",
    ))
    styles.add(ParagraphStyle(
        name="AvvisoEmersione", parent=styles["BodyText"], fontSize=9,
        leading=12, textColor=colors.HexColor("#4A2D05"),
        borderColor=colors.HexColor("#B78124"), borderWidth=0.8,
        borderPadding=7, backColor=colors.HexColor("#FFF4D6"),
        spaceBefore=3 * mm, spaceAfter=3 * mm,
    ))

    elementi = [
        Paragraph("EMERSIONE", styles["TitoloEmersione"]),
        Paragraph("Relazione descrittiva degli indicatori di analisi", styles["SottotitoloEmersione"]),
        Paragraph(
            "DOCUMENTO SPERIMENTALE — non è un provvedimento, non accerta illeciti e non certifica la regolarità dell'impresa. "
            "Ogni segnale richiede valutazione indipendente da parte di personale competente.",
            styles["AvvisoEmersione"],
        ),
    ]
    elementi.append(Paragraph("0. Identificativi della relazione e finalità", styles["SezioneEmersione"]))
    dati_relazione = [
        ["Identificativo relazione", _p(ctx.get("report_id", "non assegnato"), styles["TestoTabella"])],
        ["Versione del documento", _p(ctx.get("versione_documento", "1"), styles["TestoTabella"])],
        ["Esecuzione del motore", _p(ctx.get("esecuzione_id", "non registrata"), styles["TestoTabella"])],
        ["Pratica", _p(pratica.get("id", "nessuna pratica associata"), styles["TestoTabella"])],
        ["Finalità dichiarata", _p(pratica.get("finalita", "non indicata: relazione di sola consultazione"), styles["TestoTabella"])],
        ["Ambito della verifica", _p(pratica.get("ambito", "non indicato"), styles["TestoTabella"])],
        ["Operatore e ruolo", _p(f"{ctx.get('operatore', 'non indicato')} ({ctx.get('ruolo', '-')})", styles["TestoTabella"])],
    ]
    tabella_relazione = Table(dati_relazione, colWidths=[52 * mm, 112 * mm], hAlign="LEFT")
    tabella_relazione.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF1F5")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8CFD8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elementi.append(tabella_relazione)
    elementi.append(Paragraph(
        "L'identificativo e l'impronta SHA-256 di questo file sono registrati dall'istanza che lo ha prodotto e possono essere "
        "verificati nella pagina \"Verifica relazione\". La verifica indica solo che il file non è stato alterato dopo la "
        "generazione: non conferisce al documento alcun valore giuridico, protocollo o firma.", styles["TestoPiccolo"]))

    elementi.append(Paragraph("1. Identificazione e contesto", styles["SezioneEmersione"]))
    dati_identita = [
        ["Identificativo record", _p(azienda.get("id"), styles["TestoTabella"])],
        ["Ragione sociale dichiarata", _p(azienda.get("ragione_sociale"), styles["TestoTabella"])],
        ["Settore", _p(settore.get("nome", azienda.get("settore")), styles["TestoTabella"])],
        ["Città / territorio disponibile", _p(azienda.get("citta"), styles["TestoTabella"])],
        ["Data e ora di generazione (UTC)", _p(datetime.now(timezone.utc).isoformat(timespec="seconds"), styles["TestoTabella"])],
    ]
    tabella_identita = Table(dati_identita, colWidths=[52 * mm, 112 * mm], hAlign="LEFT")
    tabella_identita.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF1F5")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#202733")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8CFD8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elementi.append(tabella_identita)

    elementi.append(Paragraph("2. Sintesi dell'elaborazione", styles["SezioneEmersione"]))
    punteggio = analisi.get("punteggio")
    sintesi = [
        ["Indice tecnico", _p(punteggio if punteggio is not None else "N/D — non valutabile", styles["TestoTabella"])],
        ["Esito tecnico", _p(analisi.get("livello"), styles["TestoTabella"])],
        ["Stato metodologico", _p(analisi.get("stato_metodologico"), styles["TestoTabella"])],
        ["Stima addetti equivalenti", _p(analisi.get("addetti_attesi"), styles["TestoTabella"])],
        ["Formula dichiarata", _p(analisi.get("formula"), styles["TestoTabella"])],
        ["Robustezza (±20% sui parametri)", _p(
            {"stabile": "stabile: il livello non cambia variando i parametri",
             "instabile": "INSTABILE: il livello cambia variando i parametri — risultato non affidabile",
             }.get((analisi.get("robustezza") or {}).get("stato"), "non calcolata"), styles["TestoTabella"])],
    ]
    pre_congruita = analisi.get("pre_screening_congruita_edilizia")
    if isinstance(pre_congruita, dict):
        sintesi.append(["Screening preliminare indici edilizi", _p(pre_congruita.get("stato"), styles["TestoTabella"])])
        sintesi.append(["Nota screening edilizio", _p(pre_congruita.get("nota"), styles["TestoTabella"])])
        if pre_congruita.get("incidenza_dichiarata") is not None:
            sintesi.append(["Incidenza / indice tabellare", _p(f"{pre_congruita['incidenza_dichiarata']*100:.2f}% / {pre_congruita['indice_minimo_tabellare']*100:.2f}%", styles["TestoTabella"])])
    tabella_sintesi = Table(sintesi, colWidths=[52 * mm, 112 * mm], hAlign="LEFT")
    tabella_sintesi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF1F5")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8CFD8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elementi.append(tabella_sintesi)

    elementi.append(Paragraph("3. Dati di input rilevanti", styles["SezioneEmersione"]))
    campi = ["dipendenti_dichiarati", "costo_lavoro_per_addetto", "dpi_acquistati",
             "valore_opera", "costo_manodopera_dichiarato", "categoria_opera", "tipo_commessa",
             "gruppo_societario_id", "codice_contratto_pubblico", "codice_subappalto", "sede_locale_codice"]
    campi.extend(list(settore.get("campi", {}).keys()))
    righe = [[_p("Campo", styles["TestoTabella"]), _p("Valore ricevuto", styles["TestoTabella"]), _p("Unità", styles["TestoTabella"])]]
    viste = set()
    for campo in campi:
        if campo in viste or campo not in azienda:
            continue
        viste.add(campo)
        definizione = settore.get("campi", {}).get(campo, {})
        righe.append([
            _p(definizione.get("etichetta", campo), styles["TestoTabella"]),
            _p(azienda.get(campo), styles["TestoTabella"]),
            _p(definizione.get("unita", "non specificata"), styles["TestoTabella"]),
        ])
    tabella_dati = Table(righe, colWidths=[57 * mm, 57 * mm, 50 * mm], repeatRows=1, hAlign="LEFT")
    tabella_dati.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE4ED")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8CFD8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementi.append(tabella_dati)

    elementi.append(Paragraph("4. Indicatori e motivazioni", styles["SezioneEmersione"]))
    segnali = analisi.get("segnali") if isinstance(analisi.get("segnali"), list) else []
    if not segnali:
        elementi.append(Paragraph(
            "Non sono stati generati indicatori dalle regole attive per questo record. "
            "Questo risultato non dimostra l'assenza di irregolarità.", styles["TestoPiccolo"]
        ))
    else:
        for indice, segnale in enumerate(segnali, start=1):
            if not isinstance(segnale, dict):
                continue
            blocco = [Paragraph(
                f"Indicatore {indice}: {escape(_testo(segnale.get('tipo')))} — {escape(_testo(segnale.get('gravita')))}",
                styles["Heading3"],
            ), Paragraph(escape(_testo(segnale.get("testo"))), styles["TestoPiccolo"])]
            elementi.append(KeepTogether(blocco))

    elementi.append(Paragraph("4-bis. Dati mancanti e controlli non valutabili", styles["SezioneEmersione"]))
    mancanti = [c for c in settore.get("campi", {}) if azienda.get(c) in (None, "")]
    righe_mancanti = []
    if analisi.get("livello") == "non_valutabile":
        righe_mancanti.append("Analisi non valutabile: " + _testo(analisi.get("formula")))
    if mancanti:
        righe_mancanti.append("Campi del settore non forniti: " + ", ".join(mancanti) + ". Non sono stati sostituiti con zero.")
    if analisi.get("confronto_pari_n", 0) < 10:
        righe_mancanti.append("Confronto con aziende comparabili non eseguito: gruppo inferiore a 10 record.")
    for riga in righe_mancanti or ["Nessun dato richiesto dai controlli attivi risulta mancante."]:
        elementi.append(Paragraph("- " + escape(riga), styles["TestoPiccolo"]))

    elementi.append(Paragraph("4-ter. Natura delle informazioni", styles["SezioneEmersione"]))
    parametri_non_validati = [p.get("nome", p.get("id")) for p in (analisi.get("parametri_formula") or [])
                              if isinstance(p, dict) and p.get("stato") not in {"verificato", "approvato"}]
    natura = [
        ["Dato acquisito", "Valori della sezione 3, come ricevuti nel lotto indicato nella sezione 7 (non verificati dal sistema)."],
        ["Dato derivato", f"Stima addetti equivalenti ({analisi.get('addetti_attesi')}) e rapporti descrittivi calcolati dalla formula."],
        ["Anomalia statistica", f"{len(segnali)} indicatori della sezione 4: scostamenti rispetto a coefficienti o mediane, non fatti accertati."],
        ["Informazione non verificata", ("Parametri senza verifica documentata: " + ", ".join(parametri_non_validati)) if parametri_non_validati else "Nessun parametro non verificato nella formula."],
        ["Indizio documentale / relazioni societarie", "Non inclusi automaticamente: eventuali elementi OSINT o del grafo vanno allegati dall'operatore dopo revisione."],
        ["Elemento da approfondire", "Solo su decisione del personale competente; questa relazione non lo stabilisce."],
    ]
    tabella_natura = Table([[_p(a, styles["TestoTabella"]), _p(b, styles["TestoTabella"])] for a, b in natura],
                           colWidths=[52 * mm, 112 * mm], hAlign="LEFT")
    tabella_natura.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF1F5")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8CFD8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    elementi.append(tabella_natura)

    parametri = analisi.get("parametri_formula") if isinstance(analisi.get("parametri_formula"), list) else []
    if parametri:
        elementi.append(Paragraph("5. Parametri e riferimenti utilizzati dalla formula", styles["SezioneEmersione"]))
        righe_parametri = [["Parametro", "Valore", "Unità", "Stato", "Fonte dichiarata"]]
        for parametro in parametri:
            if not isinstance(parametro, dict):
                continue
            righe_parametri.append([
                _p(parametro.get("nome", parametro.get("id")), styles["TestoTabella"]),
                _p(parametro.get("valore"), styles["TestoTabella"]),
                _p(parametro.get("unita"), styles["TestoTabella"]),
                _p(parametro.get("stato"), styles["TestoTabella"]),
                _p(parametro.get("fonte"), styles["TestoTabella"]),
            ])
        tabella_parametri = Table(righe_parametri, colWidths=[34 * mm, 20 * mm, 26 * mm, 24 * mm, 60 * mm], repeatRows=1, hAlign="LEFT")
        tabella_parametri.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE4ED")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8CFD8")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elementi.append(tabella_parametri)

    limitazioni = analisi.get("limitazioni") if isinstance(analisi.get("limitazioni"), list) else []
    elementi.append(Paragraph("6. Limitazioni e controlli necessari", styles["SezioneEmersione"]))
    limitazioni_default = [
        "Il punteggio è un indice sperimentale, non una probabilità di illecito.",
        "Le informazioni e le fonti devono essere verificate da un operatore competente.",
        "La relazione non sostituisce controlli ufficiali, contraddittorio o valutazione giuridica.",
    ]
    for limite in dict.fromkeys([str(x) for x in limitazioni] + limitazioni_default):
        elementi.append(Paragraph("- " + escape(limite), styles["TestoPiccolo"]))

    if isinstance(pre_congruita, dict):
        from app.normativa_edilizia import FONTE as FONTE_DM143
        elementi.append(Paragraph("6-bis. Riferimenti normativi pertinenti", styles["SezioneEmersione"]))
        elementi.append(Paragraph(escape(
            f"{FONTE_DM143['titolo']} ({FONTE_DM143['url_tabella']}), fonte controllata il {FONTE_DM143['data_verifica_fonte']}. "
            "Usato solo per lo screening preliminare: l'applicabilità al caso va verificata dal personale competente."),
            styles["TestoPiccolo"]))

    elementi.append(Paragraph("7. Provenienza e riproducibilità", styles["SezioneEmersione"]))
    metadati = [
        ("Identificativo lotto", lotto.get("lotto_id")),
        ("Hash sorgente", lotto.get("hash_origine")),
        ("Hash dataset persistito", lotto.get("hash_dataset")),
        ("Hash configurazione settori/parametri", lotto.get("hash_configurazione")),
        ("Versione motore registrata", analisi.get("versione_motore", lotto.get("versione_motore", "non registrata"))),
        ("Versione configurazione del settore", analisi.get("versione_configurazione_settore")),
        ("Configurazione corrente", "Sì" if lotto.get("configurazione_corrente", True) else "No — analisi da ricalcolare"),
    ]
    righe_meta = [[_p(nome, styles["TestoTabella"]), _p(valore, styles["TestoTabella"])] for nome, valore in metadati]
    tabella_meta = Table(righe_meta, colWidths=[60 * mm, 104 * mm], hAlign="LEFT")
    tabella_meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF1F5")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C8CFD8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementi.append(tabella_meta)
    elementi.append(Spacer(1, 4 * mm))
    elementi.append(Paragraph(
        "Fine relazione. La produzione del documento attesta esclusivamente che è stata generata questa rappresentazione dei dati disponibili; "
        "non attesta autenticità della fonte, validità scientifica dei coefficienti o fondatezza di un'ipotesi di illecito.",
        styles["TestoPiccolo"],
    ))

    doc.build(elementi, onFirstPage=_footer, onLaterPages=_footer)
    contenuto = buffer.getvalue()
    buffer.close()
    if not contenuto.startswith(b"%PDF-"):
        raise ErroreReport("La relazione PDF non è stata generata correttamente.")
    return contenuto
