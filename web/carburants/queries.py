"""BigQuery queries — toutes les fonctions retournent des listes de dicts."""
import logging
import time

from .bq_client import get_client, table_ref, silver_table_ref, gold_zone_table_ref, gold_synthese_table_ref

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


def synthese_nationale() -> list[dict]:
    """Synthèse nationale (prix min/max/moy, taux rupture par carburant), depuis la table gold."""
    sql = f"SELECT * FROM `{gold_synthese_table_ref()}` LIMIT 1"
    return _run_query(sql, [], "synthese_nationale")


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


def recherche_par_service(service: str, code_postal: str | None = None, limit: int = 50) -> list[dict]:
    """Stations proposant un service donné, depuis la table silver."""
    cp_filter = "AND code_postal = @code_postal" if code_postal else ""

    sql = f"""
    SELECT
      station_id, adresse, ville, code_postal, departement, region,
      latitude, longitude, services, horaires,
      gazole_prix, sp95_prix, sp98_prix, e10_prix, e85_prix, gplc_prix
    FROM `{silver_table_ref()}`
    WHERE LOWER(services) LIKE CONCAT('%', LOWER(@service), '%')
      {cp_filter}
    ORDER BY region, ville
    LIMIT @limit
    """

    params = [_str_param("service", service), _int_param("limit", limit)]
    if code_postal:
        params.append(_str_param("code_postal", code_postal))

    return _run_query(sql, params, "recherche_par_service")


def stations_carte(region: str | None = None, departement: str | None = None, fuel: str | None = None) -> list[dict]:
    """Retourne les stations avec coordonnées GPS et prix pour la carte, depuis la table silver."""
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
    SELECT
      station_id, adresse, ville, code_postal, region,
      latitude, longitude, services,
      gazole_prix, sp95_prix, sp98_prix, e10_prix, e85_prix, gplc_prix
    FROM `{silver_table_ref()}`
    WHERE latitude IS NOT NULL
      AND longitude IS NOT NULL
      {"".join(filters)}
    ORDER BY {fuel_col} ASC
    """

    return _run_query(sql, params, "stations_carte")


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


# --- helpers ---

def _run_query(sql: str, params: list, label: str) -> list[dict]:
    t0 = time.monotonic()
    job = get_client().query(sql, job_config=_job_config(params))
    rows = [dict(row) for row in job.result()]
    logger.info("query=%s rows=%d duration_ms=%d", label, len(rows), round((time.monotonic() - t0) * 1000))
    return rows


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
