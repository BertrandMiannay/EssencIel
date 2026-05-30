"""Couche requêtes — toutes les fonctions retournent des listes de dicts."""
import logging
import math
import time
from datetime import timedelta

from django.db.models import Avg, Count, F, Max, Q
from django.utils import timezone as dj_timezone

from .models import PrixMoyensZone, Snapshot, StationsLatest, TopStations

logger = logging.getLogger("carburants.queries")

FUELS = ["gazole", "sp95", "sp98", "e10", "e85", "gplc"]

_PERIODE_DAYS = {"24h": 1, "7j": 7, "30j": 30}

_KM_PER_LAT = 111.32


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def prix_moyen_par_zone(zone_type: str, zone_value: str | None = None) -> list[dict]:
    """Prix moyen et taux de rupture par carburant pour une zone donnée."""
    t0 = time.monotonic()
    row = (
        PrixMoyensZone.objects
        .filter(zone_type=zone_type, zone_value=zone_value or "")
        .values()
        .first()
    )
    if not row:
        return []
    row.pop("id")
    row["last_date"] = row.pop("ingested_at")
    logger.info("query=prix_moyen_par_zone rows=1 duration_ms=%d",
                round((time.monotonic() - t0) * 1000))
    return [row]


def top_prix(
    fuel: str,
    zone_type: str,
    zone_value: str | None,
    limit: int = 10,
    order: str = "ASC",
) -> list[dict]:
    """Top ou worst stations par prix pour un carburant donné."""
    t0 = time.monotonic()
    qs = StationsLatest.objects.filter(
        **{f"{fuel}_rupture": False, f"{fuel}_prix__isnull": False}
    )
    if zone_type == "region":
        qs = qs.filter(region=zone_value)
    elif zone_type == "departement":
        qs = qs.filter(departement=zone_value)
    elif zone_type == "code_postal":
        qs = qs.filter(code_postal=zone_value)

    order_field = f"{fuel}_prix" if order.upper() == "ASC" else f"-{fuel}_prix"
    rows = list(
        qs.order_by(order_field)
        .values(
            "station_id", "adresse", "ville", "code_postal",
            "departement", "region", "latitude", "longitude",
            prix=F(f"{fuel}_prix"),
            rupture=F(f"{fuel}_rupture"),
        )[:limit]
    )
    logger.info("query=top_prix rows=%d duration_ms=%d",
                len(rows), round((time.monotonic() - t0) * 1000))
    return rows


def top_worst_gold(fuel: str, zone_type: str, zone_value: str | None) -> dict:
    """Top et worst stations, retourne {'top': [...], 'worst': [...]}."""
    t0 = time.monotonic()
    qs = (
        TopStations.objects
        .filter(zone_type=zone_type, zone_value=zone_value or "", fuel=fuel)
        .order_by("rank_type", "rank")
        .values()
    )
    result: dict = {"top": [], "worst": []}
    for row in qs:
        row.pop("id")
        result[row["rank_type"]].append(row)
    logger.info("query=top_worst_gold rows=%d duration_ms=%d",
                len(result["top"]) + len(result["worst"]),
                round((time.monotonic() - t0) * 1000))
    return result


def stations_proches(
    lat: float,
    lng: float,
    fuel: str,
    rayon_km: float = 20,
    limit: int = 20,
) -> list[dict]:
    """Stations dans un rayon donné, triées par prix croissant."""
    t0 = time.monotonic()
    d_lat = rayon_km / _KM_PER_LAT
    d_lng = rayon_km / (_KM_PER_LAT * math.cos(math.radians(lat)))

    qs = StationsLatest.objects.filter(
        **{f"{fuel}_prix__isnull": False, f"{fuel}_rupture": False},
        latitude__isnull=False,
        longitude__isnull=False,
        latitude__gte=lat - d_lat,
        latitude__lte=lat + d_lat,
        longitude__gte=lng - d_lng,
        longitude__lte=lng + d_lng,
    ).values(
        "station_id", "adresse", "ville", "code_postal",
        "departement", "region", "latitude", "longitude", "services",
        prix=F(f"{fuel}_prix"),
        rupture=F(f"{fuel}_rupture"),
    )

    candidates = []
    for s in qs:
        d = _haversine(lat, lng, s["latitude"], s["longitude"])
        if d <= rayon_km:
            candidates.append({**s, "distance_km": round(d, 1)})

    candidates.sort(key=lambda r: r["prix"])
    rows = candidates[:limit]
    logger.info("query=stations_proches rows=%d duration_ms=%d",
                len(rows), round((time.monotonic() - t0) * 1000))
    return rows


def evolution_prix(zone_type: str, zone_value: str | None, periode: str) -> list[dict]:
    """Prix moyen journalier par carburant sur une période glissante."""
    t0 = time.monotonic()
    nb_jours = _PERIODE_DAYS.get(periode, 7)
    cutoff = dj_timezone.now() - timedelta(days=nb_jours)

    qs = Snapshot.objects.filter(ingested_at__gte=cutoff)
    if zone_type == "region" and zone_value:
        qs = qs.filter(region=zone_value)
    elif zone_type == "departement" and zone_value:
        qs = qs.filter(departement=zone_value)
    elif zone_type == "code_postal" and zone_value:
        qs = qs.filter(code_postal=zone_value)

    agg = {
        f"{f}_prix_moyen": Avg(
            f"{f}_prix",
            filter=Q(**{f"{f}_rupture": False}) & Q(**{f"{f}_prix__isnull": False}),
        )
        for f in FUELS
    }
    raw = qs.values("ingested_at").annotate(**agg).order_by("ingested_at")

    result = []
    for r in raw:
        row = {"date": r["ingested_at"]}
        for f in FUELS:
            v = r.get(f"{f}_prix_moyen")
            row[f"{f}_prix_moyen"] = round(v, 3) if v is not None else None
        result.append(row)

    logger.info("query=evolution_prix rows=%d duration_ms=%d",
                len(result), round((time.monotonic() - t0) * 1000))
    return result


def evolution_ruptures(zone_type: str, zone_value: str | None, periode: str) -> list[dict]:
    """Taux de rupture journalier (%) par carburant sur une période glissante."""
    t0 = time.monotonic()
    nb_jours = _PERIODE_DAYS.get(periode, 7)
    cutoff = dj_timezone.now() - timedelta(days=nb_jours)

    qs = Snapshot.objects.filter(ingested_at__gte=cutoff)
    if zone_type == "region" and zone_value:
        qs = qs.filter(region=zone_value)
    elif zone_type == "departement" and zone_value:
        qs = qs.filter(departement=zone_value)
    elif zone_type == "code_postal" and zone_value:
        qs = qs.filter(code_postal=zone_value)

    agg = {}
    for f in FUELS:
        agg[f"{f}_nb_rupture"] = Count("id", filter=Q(**{f"{f}_rupture": True}))
        agg[f"{f}_nb_denom"] = Count(
            "id",
            filter=Q(**{f"{f}_prix__isnull": False}) | Q(**{f"{f}_rupture": True}),
        )

    raw = qs.values("ingested_at").annotate(**agg).order_by("ingested_at")

    result = []
    for r in raw:
        row = {"date": r["ingested_at"]}
        for f in FUELS:
            denom = r[f"{f}_nb_denom"]
            row[f"{f}_taux_rupture"] = (
                round(100 * r[f"{f}_nb_rupture"] / denom, 1) if denom else None
            )
        result.append(row)

    logger.info("query=evolution_ruptures rows=%d duration_ms=%d",
                len(result), round((time.monotonic() - t0) * 1000))
    return result
