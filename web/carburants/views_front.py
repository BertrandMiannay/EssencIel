from django.shortcuts import render
from django.core.cache import cache
from . import queries

_CACHE_TTL = 3600  # 1 heure — données ingérées quotidiennement

_SERVICES_COMMUNS = [
    "Lavage", "Gonflage", "Boutique", "Restauration",
    "DAB", "Toilettes", "WiFi", "Automate 24/24",
]

FUELS = queries.FUELS
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
    if fuel not in FUELS:
        fuel = "gazole"

    stats = cache.get_or_set("dashboard:stats", lambda: queries.prix_moyen_par_zone("france"), _CACHE_TTL)
    top = cache.get_or_set(f"dashboard:top:{fuel}", lambda: queries.top_prix(fuel, "france", None, limit=10, order="ASC"), _CACHE_TTL)
    worst = cache.get_or_set(f"dashboard:worst:{fuel}", lambda: queries.top_prix(fuel, "france", None, limit=10, order="DESC"), _CACHE_TTL)

    stats_row = stats[0] if stats else {}
    return render(request, "carburants/index.html", {
        "stats": stats_row,
        "top": top,
        "worst": worst,
        "fuels": FUEL_LABELS,
        "selected_fuel": fuel,
    })


def carte(request):
    fuel = request.GET.get("fuel", "gazole")
    region = request.GET.get("region", "")
    departement = request.GET.get("departement", "")
    if fuel not in FUELS:
        fuel = "gazole"

    return render(request, "carburants/carte.html", {
        "fuels": FUEL_LABELS,
        "selected_fuel": fuel,
        "region": region,
        "departement": departement,
    })


def trouver(request):
    return render(request, "carburants/trouver.html", {
        "fuels": FUEL_LABELS,
    })


def evolution(request):
    zone_type = request.GET.get("zone_type", "france")
    zone_value = request.GET.get("zone_value", "").strip()
    periode = request.GET.get("periode", "7j")

    valid_zones = ("france", "region", "departement", "code_postal")
    valid_periodes = ("24h", "7j", "30j")
    if zone_type not in valid_zones:
        zone_type = "france"
    if periode not in valid_periodes:
        periode = "7j"

    return render(request, "carburants/evolution.html", {
        "fuels": FUEL_LABELS,
        "zone_type": zone_type,
        "zone_value": zone_value,
        "periode": periode,
    })


def recherche(request):
    service = request.GET.get("service", "").strip()
    code_postal = request.GET.get("code_postal", "").strip()
    results = []

    if service:
        results = queries.recherche_par_service(service, code_postal or None, limit=100)

    return render(request, "carburants/recherche.html", {
        "results": results,
        "service": service,
        "code_postal": code_postal,
        "services_communs": _SERVICES_COMMUNS,
    })
