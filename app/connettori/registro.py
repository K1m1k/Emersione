"""Catalogo delle fonti e del loro stato effettivo di implementazione.

Una descrizione o un campo `campi_attesi` non significa che la fonte sia collegata.
Le basi giuridiche qui indicate sono note di orientamento, non pareri legali.
"""
FONTI = [
    {
        "chiave": "anac_appalti", "nome": "Contratti pubblici / dati ANAC", "categoria": "pubblica",
        "base_giuridica": "Da verificare per dataset e finalità specifici; la pubblicazione di un dato non autorizza ogni riutilizzo.",
        "stato": "connettore_download_disponibile", "operativo": True,
        "campi_attesi": ["codice_contratto", "aggiudicatario", "importo", "durata", "oggetto"],
        "nota": "Scaricamento puntuale operativo per URL diretto HTTPS di una risorsa Open Data ANAC. La scoperta automatica dei dataset e il mapping semantico non sono implementati.",
    },
    {
        "chiave": "istat_settori", "nome": "Statistiche di settore ISTAT", "categoria": "pubblica",
        "base_giuridica": "Da verificare secondo dataset, licenza, granularità e finalità di utilizzo.",
        "stato": "connettore_sdmx_disponibile", "operativo": True,
        "campi_attesi": ["settore", "territorio", "periodo", "valore_statistico"],
        "nota": "Acquisizione SDMX puntuale da endpoint ISTAT ufficiale operativo; richiede dataflow/key scelti dalla documentazione. La normalizzazione dei singoli dataflow non è automatica.",
    },
    {
        "chiave": "inail_open_data", "nome": "Open data INAIL", "categoria": "pubblica",
        "base_giuridica": "Da verificare per ogni dataset e per l'uso concreto; non include accesso a dati riservati.",
        "stato": "connettore_api_disponibile", "operativo": True,
        "campi_attesi": ["settore", "territorio", "periodo", "indicatori_aggregati"],
        "nota": "Connettore operativo per cinque endpoint Open API INAIL documentati. I payload sono acquisiti grezzi e devono essere mappati e verificati prima di ogni uso analitico.",
    },
    {
        "chiave": "bilanci_societari", "nome": "Bilanci e dati societari", "categoria": "pubblica",
        "base_giuridica": "Disponibilità, costi, licenze e condizioni di riutilizzo vanno verificati per il servizio specifico.",
        "stato": "non_implementato", "operativo": False,
        "campi_attesi": ["identificativo_societario", "fatturato", "costo_personale", "periodo"],
        "nota": "Nessun connettore automatico è implementato in questa versione.",
    },
    {
        "chiave": "import_manuale", "nome": "Import CSV da soggetto autorizzato", "categoria": "riservata",
        "base_giuridica": "Il conferente deve avere titolo per fornire i dati e l'ente destinatario deve documentare finalità e base giuridica del trattamento.",
        "stato": "disponibile_con_limiti", "operativo": True,
        "campi_attesi": ["id", "settore", "dipendenti_dichiarati", "costo_lavoro_per_addetto", "campi_di_settore"],
        "nota": "L'applicazione legge soltanto il CSV caricato dall'operatore autenticato; non accede a sistemi riservati.",
    },
]


def elenco():
    return [dict(f) for f in FONTI]


def per_categoria():
    out = {"pubblica": [], "riservata": []}
    for fonte in FONTI:
        out[fonte["categoria"]].append(dict(fonte))
    return out
