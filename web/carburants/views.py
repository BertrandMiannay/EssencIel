from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from . import queries

VALID_FUELS = queries.FUELS
VALID_ZONES = ["france", "region", "departement", "code_postal"]


@api_view(["GET"])
def prix_moyen(request):
    """
    GET /api/prix-moyen/?zone_type=france
    GET /api/prix-moyen/?zone_type=region&zone_value=Île-de-France
    """
    zone_type = request.query_params.get("zone_type", "france")
    zone_value = request.query_params.get("zone_value")

    if zone_type not in VALID_ZONES:
        return Response({"error": f"zone_type must be one of {VALID_ZONES}"}, status=status.HTTP_400_BAD_REQUEST)
    if zone_type != "france" and not zone_value:
        return Response({"error": "zone_value is required when zone_type != france"}, status=status.HTTP_400_BAD_REQUEST)

    data = queries.prix_moyen_par_zone(zone_type, zone_value)
    return Response(data)


@api_view(["GET"])
def top_prix(request):
    """
    GET /api/top-prix/?fuel=gazole&zone_type=france&order=ASC&limit=10
    """
    fuel = request.query_params.get("fuel", "gazole")
    zone_type = request.query_params.get("zone_type", "france")
    zone_value = request.query_params.get("zone_value")
    order = request.query_params.get("order", "ASC")
    try:
        limit = min(int(request.query_params.get("limit", 10)), 50)
    except ValueError:
        limit = 10

    if fuel not in VALID_FUELS:
        return Response({"error": f"fuel must be one of {VALID_FUELS}"}, status=status.HTTP_400_BAD_REQUEST)

    data = queries.top_prix(fuel, zone_type, zone_value, limit=limit, order=order)
    return Response(data)


@api_view(["GET"])
def worst_prix(request):
    """GET /api/worst-prix/?fuel=gazole&zone_type=france"""
    fuel = request.query_params.get("fuel", "gazole")
    zone_type = request.query_params.get("zone_type", "france")
    zone_value = request.query_params.get("zone_value")
    try:
        limit = min(int(request.query_params.get("limit", 10)), 50)
    except ValueError:
        limit = 10

    data = queries.top_prix(fuel, zone_type, zone_value, limit=limit, order="DESC")
    return Response(data)


@api_view(["GET"])
def recherche_service(request):
    """
    GET /api/services/?service=lavage
    GET /api/services/?service=lavage&code_postal=75001
    """
    service = request.query_params.get("service", "").strip()
    if not service:
        return Response({"error": "service parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    code_postal = request.query_params.get("code_postal")
    try:
        limit = min(int(request.query_params.get("limit", 50)), 200)
    except ValueError:
        limit = 50

    data = queries.recherche_par_service(service, code_postal, limit=limit)
    return Response(data)


@api_view(["GET"])
def stations_proches(request):
    """
    GET /api/stations-proches/?lat=48.85&lng=2.35&fuel=gazole&rayon=20&limit=20
    """
    try:
        lat = float(request.query_params["lat"])
        lng = float(request.query_params["lng"])
    except (KeyError, ValueError, TypeError):
        return Response({"error": "lat and lng are required numeric parameters"}, status=status.HTTP_400_BAD_REQUEST)

    fuel = request.query_params.get("fuel", "gazole")
    if fuel not in VALID_FUELS:
        fuel = "gazole"

    try:
        rayon = min(float(request.query_params.get("rayon", 20)), 100)
    except ValueError:
        rayon = 20

    try:
        limit = min(int(request.query_params.get("limit", 20)), 50)
    except ValueError:
        limit = 20

    data = queries.stations_proches(lat, lng, fuel, rayon_km=rayon, limit=limit)
    return Response(data)


@api_view(["GET"])
def stations_carte(request):
    """
    GET /api/carte/?fuel=gazole
    GET /api/carte/?fuel=gazole&region=Bretagne
    """
    fuel = request.query_params.get("fuel", "gazole")
    region = request.query_params.get("region")
    departement = request.query_params.get("departement")

    if fuel not in VALID_FUELS:
        fuel = "gazole"

    data = queries.stations_carte(region=region, departement=departement, fuel=fuel)
    return Response(data)
