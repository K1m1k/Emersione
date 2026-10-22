"""Compatibilità per vecchi import: il registro JSON è l'unica fonte di verità.

Le strutture esportate qui sono una vista di sola lettura concettuale dei valori
in config/registro_emersione.json. I valori con stato `da_verificare` o `sperimentale`
non sono coefficienti ufficiali.
"""
from app.settori import catalogo_parametri

_P = catalogo_parametri()


def _parametro(pid):
    valore = _P[pid]
    return {"valore": valore["valore"], "fonte": valore["fonte"], "stato": valore["stato"], "unita": valore["unita"]}


ORE_ANNUE_PER_ADDETTO = _parametro("ore_annue_addetto")
AGRICOLTURA_ORE_PER_ETTARO = {
    coltura: _parametro(pid)
    for coltura, pid in {
        "pomodoro": "agri_ore_ha_pomodoro", "uva": "agri_ore_ha_uva", "olivo": "agri_ore_ha_olivo",
        "ortaggi": "agri_ore_ha_ortaggi", "cereali": "agri_ore_ha_cereali", "generico": "agri_ore_ha_generico",
    }.items()
}
EDILIZIA_ORE_PER_UNITA = {
    "mc_getto": _parametro("edilizia_ore_mc_getto"),
    "mq_solaio": _parametro("edilizia_ore_mq_solaio"),
    "mq_muratura": _parametro("edilizia_ore_mq_muratura"),
}
EDILIZIA_INCIDENZA_MIN_MANODOPERA = _parametro("edilizia_incidenza_min_manodopera")
RISTORAZIONE = {
    "coperti_per_addetto_giorno": _parametro("ristorazione_coperti_addetto"),
    "kg_materia_prima_per_coperto": _parametro("ristorazione_kg_materia_prima_coperto"),
}
LOGISTICA = {
    "consegne_per_autista_giorno": _parametro("logistica_consegne_autista"),
    "km_per_autista_giorno": _parametro("logistica_km_autista"),
}
SICUREZZA = {"dpi_per_operaio_min": _parametro("dpi_per_operaio_min")}
SOGLIE = {
    "scarto_manodopera_attenzione": _parametro("scarto_manodopera_attenzione"),
    "scarto_manodopera_grave": _parametro("scarto_manodopera_grave"),
    "costo_addetto_scarto": _parametro("costo_addetto_scarto"),
}
