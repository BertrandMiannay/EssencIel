"""BigQuery queries — toutes les fonctions retournent des listes de dicts."""
import logging
import time

from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter, enums
from .bq_client import get_client, raw_table_ref, silver_table_ref, gold_zone_table_ref, gold_top_table_ref

logger = logging.getLogger("carburants.bq")

FUELS = ["gazole", "sp95", "sp98", "e10", "e85", "gplc"]

_ZONE_FILTER = {
    "france": "",
    "region": "AND region = @zone_value",
    "departement": "AND departement = @zone_value",
    "code_postal": "AND code_postal = @zone_value",
}


def prix_moyen_par_zone(zone_type: str, zone_value: str | None = None) -> list[dict]:
    """Prix moyen et taux de rupture par carburant pour une zone donnée, depuis la table gold."""
    sql = f"""
    SELECT
      ingested_at AS last_date,
      nb_stations,
      {", ".join(f"{f}_prix_moyen, {f}_taux_rupture" for f in FUELS)}
    FROM `{gold_zone_table_ref()}`
    WHERE zone_type = @zone_type
      AND zone_value = @zone_value
    LIMIT 1
    """

    params = [
        _str_param("zone_type", zone_type),
        _str_param("zone_value", zone_value if zone_value else ""),
    ]

    return _run_query(sql, params, "prix_moyen_par_zone")


def top_prix(fuel: str, zone_type: str, zone_value: str | None, limit: int = 10, order: str = "ASC") -> list[dict]:
    """Top ou worst stations par prix pour un carburant donné, depuis la table silver."""
    zone_filter = _ZONE_FILTER.get(zone_type, "")
    order = "ASC" if order.upper() == "ASC" else "DESC"

    sql = f"""
    SELECT
      station_id, adresse, ville, code_postal, departement, region,
      latitude, longitude,
      {fuel}_prix AS prix,
      {fuel}_rupture AS rupture
    FROM `{silver_table_ref()}`
    WHERE {fuel}_prix IS NOT NULL
      AND {fuel}_rupture IS FALSE
      {zone_filter}
    ORDER BY {fuel}_prix {order}
    LIMIT @limit
    """

    params = [_int_param("limit", limit)]
    if zone_value:
        params.append(_str_param("zone_value", zone_value))

    return _run_query(sql, params, "top_prix")


def top_worst_gold(fuel: str, zone_type: str, zone_value: str | None) -> dict:
    """Top et worst stations depuis la table gold, retourne {'top': [...], 'worst': [...]}."""
    sql = f"""
    SELECT rank_type, rank, station_id, adresse, ville, code_postal,
           departement, region, latitude, longitude, prix
    FROM `{gold_top_table_ref()}`
    WHERE zone_type = @zone_type
      AND zone_value = @zone_value
      AND fuel = @fuel
    ORDER BY rank_type, rank
    """
    params = [
        _str_param("zone_type", zone_type),
        _str_param("zone_value", zone_value or ""),
        _str_param("fuel", fuel),
    ]
    rows = _run_query(sql, params, "top_worst_gold")
    result: dict = {"top": [], "worst": []}
    for row in rows:
        result[row["rank_type"]].append(row)
    return result


def stations_proches(lat: float, lng: float, fuel: str, rayon_km: float = 20, limit: int = 20) -> list[dict]:
    """Stations dans un rayon donné, triées par prix croissant, depuis la table silver."""
    sql = f"""
    SELECT
      station_id, adresse, ville, code_postal, departement, region,
      latitude, longitude, services,
      {fuel}_prix AS prix,
      {fuel}_rupture AS rupture,
      ROUND(ST_DISTANCE(
        ST_GEOGPOINT(longitude, latitude),
        ST_GEOGPOINT(@lng, @lat)
      ) / 1000, 1) AS distance_km
    FROM `{silver_table_ref()}`
    WHERE {fuel}_prix IS NOT NULL
      AND {fuel}_rupture IS FALSE
      AND latitude IS NOT NULL
      AND longitude IS NOT NULL
      AND ST_DWITHIN(
        ST_GEOGPOINT(longitude, latitude),
        ST_GEOGPOINT(@lng, @lat),
        @rayon_meters
      )
    ORDER BY {fuel}_prix ASC
    LIMIT @limit
    """

    params = [
        _float_param("lat", lat),
        _float_param("lng", lng),
        _float_param("rayon_meters", rayon_km * 1000),
        _int_param("limit", limit),
    ]

    return _run_query(sql, params, "stations_proches")


_PERIODE_DAYS = {"24h": 2, "7j": 7, "30j": 30}


def evolution_ruptures(zone_type: str, zone_value: str | None, periode: str) -> list[dict]:
    """Taux de rupture journalier (%) par carburant sur une période glissante."""
    nb_jours = _PERIODE_DAYS.get(periode, 7)
    zone_filter = _ZONE_FILTER.get(zone_type, "")

    sql = f"""
    SELECT
      ingested_at AS date,
      {", ".join(
          f"ROUND(100 * COUNTIF({f}_rupture IS TRUE)"
          f" / NULLIF(COUNTIF({f}_prix IS NOT NULL OR {f}_rupture IS TRUE), 0), 1)"
          f" AS {f}_taux_rupture"
          for f in FUELS
      )}
    FROM `{raw_table_ref()}`
    WHERE ingested_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @nb_jours DAY)
      {zone_filter}
    GROUP BY ingested_at
    ORDER BY ingested_at
    """

    params = [_int_param("nb_jours", nb_jours)]
    if zone_value:
        params.append(_str_param("zone_value", zone_value))

    return _run_query(sql, params, "evolution_ruptures")


def evolution_prix(zone_type: str, zone_value: str | None, periode: str) -> list[dict]:
    """Prix moyen journalier par carburant sur une période glissante, depuis snapshots."""
    nb_jours = _PERIODE_DAYS.get(periode, 7)
    zone_filter = _ZONE_FILTER.get(zone_type, "")

    sql = f"""
    SELECT
      ingested_at AS date,
      {", ".join(
          f"ROUND(AVG(IF({f}_rupture IS FALSE, {f}_prix, NULL)), 3) AS {f}_prix_moyen"
          for f in FUELS
      )}
    FROM `{raw_table_ref()}`
    WHERE ingested_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @nb_jours DAY)
      {zone_filter}
    GROUP BY ingested_at
    ORDER BY ingested_at
    """

    params = [_int_param("nb_jours", nb_jours)]
    if zone_value:
        params.append(_str_param("zone_value", zone_value))

    return _run_query(sql, params, "evolution_prix")


# --- helpers ---

def _run_query(sql: str, params: list, label: str) -> list[dict]:
    t0 = time.monotonic()
    job = get_client().query(sql, job_config=QueryJobConfig(query_parameters=params))
    rows = [dict(row) for row in job.result()]
    logger.info("query=%s rows=%d duration_ms=%d", label, len(rows), round((time.monotonic() - t0) * 1000))
    return rows


def _str_param(name: str, value: str):
    return ScalarQueryParameter(name, enums.SqlTypeNames.STRING, value)


def _int_param(name: str, value: int):
    return ScalarQueryParameter(name, enums.SqlTypeNames.INT64, value)


def _float_param(name: str, value: float):
    return ScalarQueryParameter(name, enums.SqlTypeNames.FLOAT64, value)
