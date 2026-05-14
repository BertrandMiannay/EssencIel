from django.shortcuts import render
from . import queries

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

    stats = queries.prix_moyen_par_zone("france")
    top = queries.top_prix(fuel, "france", None, limit=10, order="ASC")
    worst = queries.top_prix(fuel, "france", None, limit=10, order="DESC")

    return render(request, "carburants/index.html", {
        "stats": stats[0] if stats else {},
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


def recherche(request):
    service = request.GET.get("service", "").strip()
    code_postal = request.GET.get("code_postal", "").strip()
    results = []

    if service:
        results = queries.recherche_par_service(service, code_postal or None, limit=100)

    services_communs = [
        "Lavage", "Gonflage", "Boutique", "Restauration",
        "DAB", "Toilettes", "WiFi", "Automate 24/24",
    ]

    return render(request, "carburants/recherche.html", {
        "results": results,
        "service": service,
        "code_postal": code_postal,
        "services_communs": services_communs,
    })
