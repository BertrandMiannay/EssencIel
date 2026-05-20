import json
from zoneinfo import ZoneInfo
from django.shortcuts import render
from django.core.cache import cache
from . import queries

_PARIS_TZ = ZoneInfo("Europe/Paris")
_MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
               "juil.", "août", "sept.", "oct.", "nov.", "déc."]

def _fmt_dt(dt):
    if dt.tzinfo is not None:
        dt = dt.astimezone(_PARIS_TZ)
    return f"{dt.day} {_MONTHS_FR[dt.month - 1]} {dt.hour:02d}h{dt.minute:02d}"

_CACHE_TTL = 3600  # données ingérées quotidiennement

FUELS = queries.FUELS
VALID_ZONE_TYPES = ("france", "region", "departement")

REGIONS = [
    "Auvergne-Rhône-Alpes",
    "Bourgogne-Franche-Comté",
    "Bretagne",
    "Centre-Val de Loire",
    "Corse",
    "Grand Est",
    "Guadeloupe",
    "Guyane",
    "Hauts-de-France",
    "Île-de-France",
    "La Réunion",
    "Martinique",
    "Mayotte",
    "Normandie",
    "Nouvelle-Aquitaine",
    "Occitanie",
    "Pays de la Loire",
    "Provence-Alpes-Côte d'Azur",
]

DEPARTEMENTS = [
    ("01", "Ain"), ("02", "Aisne"), ("03", "Allier"), ("04", "Alpes-de-Haute-Provence"),
    ("05", "Hautes-Alpes"), ("06", "Alpes-Maritimes"), ("07", "Ardèche"), ("08", "Ardennes"),
    ("09", "Ariège"), ("10", "Aube"), ("11", "Aude"), ("12", "Aveyron"),
    ("13", "Bouches-du-Rhône"), ("14", "Calvados"), ("15", "Cantal"), ("16", "Charente"),
    ("17", "Charente-Maritime"), ("18", "Cher"), ("19", "Corrèze"), ("2A", "Corse-du-Sud"),
    ("2B", "Haute-Corse"), ("21", "Côte-d'Or"), ("22", "Côtes-d'Armor"), ("23", "Creuse"),
    ("24", "Dordogne"), ("25", "Doubs"), ("26", "Drôme"), ("27", "Eure"),
    ("28", "Eure-et-Loir"), ("29", "Finistère"), ("30", "Gard"), ("31", "Haute-Garonne"),
    ("32", "Gers"), ("33", "Gironde"), ("34", "Hérault"), ("35", "Ille-et-Vilaine"),
    ("36", "Indre"), ("37", "Indre-et-Loire"), ("38", "Isère"), ("39", "Jura"),
    ("40", "Landes"), ("41", "Loir-et-Cher"), ("42", "Loire"), ("43", "Haute-Loire"),
    ("44", "Loire-Atlantique"), ("45", "Loiret"), ("46", "Lot"), ("47", "Lot-et-Garonne"),
    ("48", "Lozère"), ("49", "Maine-et-Loire"), ("50", "Manche"), ("51", "Marne"),
    ("52", "Haute-Marne"), ("53", "Mayenne"), ("54", "Meurthe-et-Moselle"), ("55", "Meuse"),
    ("56", "Morbihan"), ("57", "Moselle"), ("58", "Nièvre"), ("59", "Nord"),
    ("60", "Oise"), ("61", "Orne"), ("62", "Pas-de-Calais"), ("63", "Puy-de-Dôme"),
    ("64", "Pyrénées-Atlantiques"), ("65", "Hautes-Pyrénées"), ("66", "Pyrénées-Orientales"),
    ("67", "Bas-Rhin"), ("68", "Haut-Rhin"), ("69", "Rhône"), ("70", "Haute-Saône"),
    ("71", "Saône-et-Loire"), ("72", "Sarthe"), ("73", "Savoie"), ("74", "Haute-Savoie"),
    ("75", "Paris"), ("76", "Seine-Maritime"), ("77", "Seine-et-Marne"), ("78", "Yvelines"),
    ("79", "Deux-Sèvres"), ("80", "Somme"), ("81", "Tarn"), ("82", "Tarn-et-Garonne"),
    ("83", "Var"), ("84", "Vaucluse"), ("85", "Vendée"), ("86", "Vienne"),
    ("87", "Haute-Vienne"), ("88", "Vosges"), ("89", "Yonne"), ("90", "Territoire de Belfort"),
    ("91", "Essonne"), ("92", "Hauts-de-Seine"), ("93", "Seine-Saint-Denis"), ("94", "Val-de-Marne"),
    ("95", "Val-d'Oise"), ("971", "Guadeloupe"), ("972", "Martinique"), ("973", "Guyane"),
    ("974", "La Réunion"), ("976", "Mayotte"),
]
FUEL_LABELS = {
    "gazole": "Gazole",
    "sp95": "SP95",
    "sp98": "SP98",
    "e10": "E10",
    "e85": "E85",
    "gplc": "GPLc",
}


def index(request):
    fuel = request.GET.get("fuel", "gazole")
    zone_type = request.GET.get("zone_type", "france")
    zone_value = request.GET.get("zone_value", "").strip()

    if fuel not in FUELS:
        fuel = "gazole"
    if zone_type not in VALID_ZONE_TYPES:
        zone_type = "france"

    stats = cache.get_or_set(
        f"dashboard:stats:{zone_type}:{zone_value}",
        lambda: queries.prix_moyen_par_zone(zone_type, zone_value or None),
        _CACHE_TTL,
    )
    top_worst = cache.get_or_set(
        f"dashboard:topworst:{fuel}:{zone_type}:{zone_value}",
        lambda: queries.top_worst_gold(fuel, zone_type, zone_value or None),
        _CACHE_TTL,
    )

    stats_row = stats[0] if stats else {}
    return render(request, "carburants/index.html", {
        "stats": stats_row,
        "top": top_worst.get("top", []),
        "worst": top_worst.get("worst", []),
        "fuels": FUEL_LABELS,
        "selected_fuel": fuel,
        "zone_type": zone_type,
        "zone_value": zone_value,
        "regions": REGIONS,
        "departements": DEPARTEMENTS,
    })


def trouver(request):
    return render(request, "carburants/trouver.html", {
        "fuels": FUEL_LABELS,
    })


def evolution(request):
    zone_type = request.GET.get("zone_type", "france")
    zone_value = request.GET.get("zone_value", "").strip()
    periode = request.GET.get("periode", "7j")

    valid_zones = ("france", "region", "departement")
    valid_periodes = ("24h", "7j", "30j")
    if zone_type not in valid_zones:
        zone_type = "france"
    if periode not in valid_periodes:
        periode = "7j"

    rows = cache.get_or_set(
        f"evolution:{zone_type}:{zone_value}:{periode}",
        lambda: queries.evolution_prix(zone_type, zone_value or None, periode),
        _CACHE_TTL,
    )
    rupture_rows = cache.get_or_set(
        f"evolution:ruptures:{zone_type}:{zone_value}:{periode}",
        lambda: queries.evolution_ruptures(zone_type, zone_value or None, periode),
        _CACHE_TTL,
    )

    labels = []
    fuel_series: dict[str, list] = {f: [] for f in FUELS}
    for r in rows:
        labels.append(_fmt_dt(r["date"]))
        for f in FUELS:
            fuel_series[f].append(r.get(f"{f}_prix_moyen"))
    chart_data = {"labels": labels, "fuels": fuel_series}

    rupture_table = [
        {
            "date": _fmt_dt(r["date"]),
            "fuels": [
                {"key": f, "label": FUEL_LABELS[f], "value": r.get(f"{f}_taux_rupture")}
                for f in FUELS
            ],
        }
        for r in rupture_rows
    ]

    return render(request, "carburants/evolution.html", {
        "fuels": FUEL_LABELS,
        "zone_type": zone_type,
        "zone_value": zone_value,
        "periode": periode,
        "chart_data_json": json.dumps(chart_data),
        "has_data": bool(rows),
        "rupture_table": rupture_table,
        "regions": REGIONS,
        "departements": DEPARTEMENTS,
    })
