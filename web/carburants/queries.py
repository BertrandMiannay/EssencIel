"""BigQuery queries — toutes les fonctions retournent des listes de dicts."""
from .bq_client import get_client, table_ref

FUELS = ["gazole", "sp95", "sp98", "e10", "e85", "gplc"]

_ZONE_FILTER = {
    "france": "",
    "region": "AND region = @zone_value",
    "departement": "AND departement = @zone_value",
    "code_postal": "AND code_postal = @zone_value",
}


def prix_moyen_par_zone(zone_type: str, zone_value: str | None = None) -> list[dict]:
    """Prix moyen et taux de rupture par carburant pour une zone donnée, snapshot le plus récent."""
    fuel_avg = ", ".join(
        f"ROUND(AVG(IF({f}_rupture IS FALSE AND {f}_prix IS NOT NULL, {f}_prix, NULL)), 3) AS {f}_prix_moyen"
        for f in FUELS
    )
    fuel_rupture = ", ".join(
        f"ROUND(COUNTIF({f}_rupture IS TRUE) / COUNT(*), 4) AS {f}_taux_rupture"
        for f in FUELS
    )
    zone_filter = _ZONE_FILTER.get(zone_type, "")

    sql = f"""
    WITH latest AS (
      SELECT DATE(MAX(ingested_at)) AS last_date
      FROM `{table_ref()}`
    )
    SELECT
      MAX(last_date) AS last_date,
      {fuel_avg},
      {fuel_rupture},
      COUNT(*) AS nb_stations
    FROM `{table_ref()}`, latest
    WHERE DATE(ingested_at) = last_date
      {zone_filter}
    """

    params = []
    if zone_value:
        params.append(_str_param("zone_value", zone_value))

    job = get_client().query(sql, job_config=_job_config(params))
    return [dict(row) for row in job.result()]


def top_prix(fuel: str, zone_type: str, zone_value: str | None, limit: int = 10, order: str = "ASC") -> list[dict]:
    """Top ou worst stations par prix pour un carburant donné."""
    zone_filter = _ZONE_FILTER.get(zone_type, "")
    order = "ASC" if order.upper() == "ASC" else "DESC"

    sql = f"""
    WITH latest AS (
      SELECT DATE(MAX(ingested_at)) AS last_date
      FROM `{table_ref()}`
    )
    SELECT
      station_id, adresse, ville, code_postal, departement, region,
      latitude, longitude,
      {fuel}_prix AS prix,
      {fuel}_rupture AS rupture
    FROM `{table_ref()}`, latest
    WHERE DATE(ingested_at) = last_date
      AND {fuel}_prix IS NOT NULL
      AND {fuel}_rupture IS FALSE
      {zone_filter}
    ORDER BY {fuel}_prix {order}
    LIMIT @limit
    """

    params = [_int_param("limit", limit)]
    if zone_value:
        params.append(_str_param("zone_value", zone_value))

    job = get_client().query(sql, job_config=_job_config(params))
    return [dict(row) for row in job.result()]


def recherche_par_service(service: str, code_postal: str | None = None, limit: int = 50) -> list[dict]:
    """Stations proposant un service donné, optionnellement filtrées par code postal."""
    cp_filter = "AND code_postal = @code_postal" if code_postal else ""

    sql = f"""
    WITH latest AS (
      SELECT DATE(MAX(ingested_at)) AS last_date
      FROM `{table_ref()}`
    )
    SELECT
      station_id, adresse, ville, code_postal, departement, region,
      latitude, longitude, services, horaires,
      gazole_prix, sp95_prix, sp98_prix, e10_prix, e85_prix, gplc_prix
    FROM `{table_ref()}`, latest
    WHERE DATE(ingested_at) = last_date
      AND LOWER(services) LIKE CONCAT('%', LOWER(@service), '%')
      {cp_filter}
    ORDER BY region, ville
    LIMIT @limit
    """

    params = [_str_param("service", service), _int_param("limit", limit)]
    if code_postal:
        params.append(_str_param("code_postal", code_postal))

    job = get_client().query(sql, job_config=_job_config(params))
    return [dict(row) for row in job.result()]


def stations_carte(region: str | None = None, departement: str | None = None, fuel: str | None = None) -> list[dict]:
    """Retourne les stations avec coordonnées GPS et prix pour la carte."""
    filters = []
    params = []

    if region:
        filters.append("AND region = @region")
        params.append(_str_param("region", region))
    if departement:
        filters.append("AND departement = @departement")
        params.append(_str_param("departement", departement))

    fuel_col = f"{fuel}_prix" if fuel in FUELS else "gazole_prix"

    sql = f"""
    WITH latest AS (
      SELECT DATE(MAX(ingested_at)) AS last_date
      FROM `{table_ref()}`
    )
    SELECT
      station_id, adresse, ville, code_postal, region,
      latitude, longitude, services,
      gazole_prix, sp95_prix, sp98_prix, e10_prix, e85_prix, gplc_prix
    FROM `{table_ref()}`, latest
    WHERE DATE(ingested_at) = last_date
      AND latitude IS NOT NULL
      AND longitude IS NOT NULL
      {"".join(filters)}
    ORDER BY {fuel_col} ASC
    """

    job = get_client().query(sql, job_config=_job_config(params))
    return [dict(row) for row in job.result()]


def stations_proches(lat: float, lng: float, fuel: str, rayon_km: float = 20, limit: int = 20) -> list[dict]:
    """Stations dans un rayon donné, triées par prix croissant pour le carburant demandé."""
    sql = f"""
    WITH latest AS (
      SELECT DATE(MAX(ingested_at)) AS last_date
      FROM `{table_ref()}`
    )
    SELECT
      station_id, adresse, ville, code_postal, departement, region,
      latitude, longitude, services,
      {fuel}_prix AS prix,
      {fuel}_rupture AS rupture,
      ROUND(ST_DISTANCE(
        ST_GEOGPOINT(longitude, latitude),
        ST_GEOGPOINT(@lng, @lat)
      ) / 1000, 1) AS distance_km
    FROM `{table_ref()}`, latest
    WHERE DATE(ingested_at) = last_date
      AND {fuel}_prix IS NOT NULL
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

    job = get_client().query(sql, job_config=_job_config(params))
    return [dict(row) for row in job.result()]


# --- helpers ---

def _str_param(name: str, value: str):
    from google.cloud.bigquery import ScalarQueryParameter, enums
    return ScalarQueryParameter(name, enums.SqlTypeNames.STRING, value)


def _int_param(name: str, value: int):
    from google.cloud.bigquery import ScalarQueryParameter, enums
    return ScalarQueryParameter(name, enums.SqlTypeNames.INT64, value)


def _float_param(name: str, value: float):
    from google.cloud.bigquery import ScalarQueryParameter, enums
    return ScalarQueryParameter(name, enums.SqlTypeNames.FLOAT64, value)


def _job_config(params: list):
    from google.cloud.bigquery import QueryJobConfig
    cfg = QueryJobConfig()
    cfg.query_parameters = params
    return cfg
