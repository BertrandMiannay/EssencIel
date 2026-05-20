import functools
import hashlib
import io
import json
import os
import csv
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery, storage

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SOURCE_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
    "/prix-des-carburants-en-france-flux-instantane-v2/exports/csv"
    "?delimiter=%3B&lang=fr&timezone=Europe%2FParis&use_labels=true"
)

GCP_PROJECT = os.environ["GCP_PROJECT"]
GCS_BUCKET = os.environ.get("GCS_BUCKET")
BQ_DATASET = os.environ.get("BQ_DATASET", "carburants")
BQ_TABLE = "raw_snapshots"
BQ_LOG_TABLE = f"{GCP_PROJECT}.{BQ_DATASET}.raw_ingestion_log"
BQ_SILVER = f"{GCP_PROJECT}.{BQ_DATASET}.silver_stations_latest"
BQ_GOLD_ZONE = f"{GCP_PROJECT}.{BQ_DATASET}.gold_prix_moyens_zone"
BQ_GOLD_TOP = f"{GCP_PROJECT}.{BQ_DATASET}.gold_top_stations"

# (bq_prefix, csv_prix_label, csv_rupture_label)
FUEL_MAP = [
    ("gazole", "Gazole", "gazole"),
    ("sp95",   "SP95",   "sp95"),
    ("sp98",   "SP98",   "sp98"),
    ("e10",    "E10",    "e10"),
    ("e85",    "E85",    "e85"),
    ("gplc",   "GPLc",   "GPLc"),
]

CSV_TO_BQ = {
    "id":               "station_id",
    "Code postal":      "code_postal",
    "Adresse":          "adresse",
    "Ville":            "ville",
    "Département":      "departement",
    "Région":           "region",
    "Services proposés": "services",
    "horaires détaillés": "horaires",
}


def _parse_float(value: str) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _parse_timestamp(value: str) -> str | None:
    if value is None or value.strip() == "":
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value.strip(), fmt).isoformat()
        except ValueError:
            continue
    return None


def _transform_row(row: dict, ingested_at: str) -> dict:
    record = {"ingested_at": ingested_at}

    for csv_col, bq_col in CSV_TO_BQ.items():
        record[bq_col] = row.get(csv_col, "").strip() or None

    lat_raw = _parse_float(row.get("latitude", ""))
    lng_raw = _parse_float(row.get("longitude", ""))
    # The API stores coordinates as integers × 100 000 (e.g. 4620516 → 46.20516°)
    record["latitude"] = lat_raw / 100_000 if lat_raw is not None else None
    record["longitude"] = lng_raw / 100_000 if lng_raw is not None else None
    # pop: "R" = route, "A" = autoroute
    record["autoroute"] = row.get("pop", "").strip() == "A"

    for bq_prefix, prix_label, rupture_label in FUEL_MAP:
        record[f"{bq_prefix}_prix"] = _parse_float(row.get(f"Prix {prix_label}", ""))
        record[f"{bq_prefix}_maj"] = _parse_timestamp(row.get(f"Prix {prix_label} mis à jour le", ""))
        rupture_raw = row.get(f"Type rupture {rupture_label}", "")
        record[f"{bq_prefix}_rupture"] = bool(rupture_raw.strip()) if rupture_raw else False

    return record


def fetch_csv() -> bytes:
    logger.info("Téléchargement du CSV depuis la source...")
    t0 = time.perf_counter()
    resp = requests.get(SOURCE_URL, timeout=120)
    resp.raise_for_status()
    logger.info("CSV téléchargé : %d octets en %.1fs", len(resp.content), time.perf_counter() - t0)
    return resp.content


def upload_to_gcs(content: bytes, date_str: str) -> str:
    t0 = time.perf_counter()
    client = storage.Client(project=GCP_PROJECT)
    bucket = client.bucket(GCS_BUCKET)
    blob_name = f"raw/{date_str}/carburants.csv"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(content, content_type="text/csv")
    gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
    logger.info("GCS upload OK : %s (%.1fs)", gcs_uri, time.perf_counter() - t0)
    return gcs_uri


@functools.lru_cache(maxsize=None)
def _bq_schema() -> list[bigquery.SchemaField]:
    schema_path = Path(__file__).parent / "bigquery" / "schema.json"
    return [
        bigquery.SchemaField(f["name"], f["type"], mode=f.get("mode", "NULLABLE"))
        for f in json.loads(schema_path.read_text())
    ]


def _log_schema() -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField("file_md5",    "STRING",    mode="REQUIRED"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("rows_count",  "INT64",     mode="NULLABLE"),
        bigquery.SchemaField("gcs_uri",     "STRING",    mode="NULLABLE"),
    ]


def _gold_zone_schema() -> list[bigquery.SchemaField]:
    fields = [
        bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("zone_type",   "STRING",    mode="REQUIRED"),
        bigquery.SchemaField("zone_value",  "STRING",    mode="REQUIRED"),
        bigquery.SchemaField("nb_stations", "INT64",     mode="NULLABLE"),
    ]
    for bq_prefix, *_ in FUEL_MAP:
        fields += [
            bigquery.SchemaField(f"{bq_prefix}_prix_moyen",   "FLOAT64", mode="NULLABLE"),
            bigquery.SchemaField(f"{bq_prefix}_taux_rupture", "FLOAT64", mode="NULLABLE"),
        ]
    return fields


def _gold_top_schema() -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField("zone_type",   "STRING",  mode="REQUIRED"),
        bigquery.SchemaField("zone_value",  "STRING",  mode="REQUIRED"),
        bigquery.SchemaField("fuel",        "STRING",  mode="REQUIRED"),
        bigquery.SchemaField("rank_type",   "STRING",  mode="REQUIRED"),
        bigquery.SchemaField("rank",        "INT64",   mode="REQUIRED"),
        bigquery.SchemaField("station_id",  "STRING",  mode="NULLABLE"),
        bigquery.SchemaField("adresse",     "STRING",  mode="NULLABLE"),
        bigquery.SchemaField("ville",       "STRING",  mode="NULLABLE"),
        bigquery.SchemaField("code_postal", "STRING",  mode="NULLABLE"),
        bigquery.SchemaField("departement", "STRING",  mode="NULLABLE"),
        bigquery.SchemaField("region",      "STRING",  mode="NULLABLE"),
        bigquery.SchemaField("latitude",    "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("longitude",   "FLOAT64", mode="NULLABLE"),
        bigquery.SchemaField("prix",        "FLOAT64", mode="NULLABLE"),
    ]



def _ensure_table(
    client: bigquery.Client,
    table_name: str,
    schema: list[bigquery.SchemaField],
    partition_field: str | None = None,
    cluster: list[str] | None = None,
) -> None:
    table = bigquery.Table(f"{GCP_PROJECT}.{BQ_DATASET}.{table_name}", schema=schema)
    if partition_field:
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=partition_field,
        )
    if cluster:
        table.clustering_fields = cluster
    client.create_table(table, exists_ok=True)
    logger.info("Table %s.%s OK", BQ_DATASET, table_name)


def ensure_infrastructure(client: bigquery.Client) -> None:
    ds = bigquery.Dataset(f"{GCP_PROJECT}.{BQ_DATASET}")
    ds.location = "EU"
    client.create_dataset(ds, exists_ok=True)
    logger.info("Dataset %s OK", BQ_DATASET)

    _ensure_table(client, BQ_TABLE, _bq_schema(),
                  partition_field="ingested_at", cluster=["region", "code_postal"])
    _ensure_table(client, "raw_ingestion_log", _log_schema())
    _ensure_table(client, "silver_stations_latest", _bq_schema(),
                  cluster=["region", "code_postal"])
    _ensure_table(client, "gold_prix_moyens_zone", _gold_zone_schema(),
                  cluster=["zone_type", "zone_value"])
    _ensure_table(client, "gold_top_stations", _gold_top_schema(),
                  cluster=["zone_type", "zone_value", "fuel"])


def _md5(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


def _log_table_exists(client: bigquery.Client) -> bool:
    try:
        client.get_table(BQ_LOG_TABLE)
        return True
    except NotFound:
        return False


def _already_ingested(client: bigquery.Client, file_md5: str) -> bool:
    rows = list(client.query(
        f"SELECT 1 FROM `{BQ_LOG_TABLE}` WHERE file_md5 = @md5 LIMIT 1",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("md5", "STRING", file_md5)
        ]),
    ).result())
    return len(rows) > 0


def _record_ingestion(client: bigquery.Client, file_md5: str, ingested_at: str, rows_count: int, gcs_uri: str | None) -> None:
    errors = client.insert_rows_json(BQ_LOG_TABLE, [{
        "file_md5":    file_md5,
        "ingested_at": ingested_at,
        "rows_count":  rows_count,
        "gcs_uri":     gcs_uri,
    }])
    if errors:
        raise RuntimeError(f"ingestion_log insert errors: {errors}")


def load_to_bigquery(client: bigquery.Client, content: bytes, ingested_at: str) -> tuple[list[dict], int]:
    t0 = time.perf_counter()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=";")
    rows = [_transform_row(row, ingested_at) for row in reader]
    logger.info("Transformation : %d lignes en %.1fs", len(rows), time.perf_counter() - t0)

    price_counts = {bq_prefix: 0 for bq_prefix, *_ in FUEL_MAP}
    for r in rows:
        for bq_prefix in price_counts:
            if r.get(f"{bq_prefix}_prix") is not None:
                price_counts[bq_prefix] += 1
    for bq_prefix, count in price_counts.items():
        logger.info("  %-8s %d/%d stations avec prix", bq_prefix, count, len(rows))

    main_table = f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"
    staging_table = f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}_staging"

    t1 = time.perf_counter()
    job = client.load_table_from_json(
        rows,
        staging_table,
        job_config=bigquery.LoadJobConfig(
            schema=_bq_schema(),
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    )
    job.result()
    logger.info("Staging chargée : %d lignes en %.1fs", len(rows), time.perf_counter() - t1)

    t2 = time.perf_counter()
    # MERGE idempotent sur (station_id, ingested_at)
    client.query(f"""
        MERGE `{main_table}` T
        USING `{staging_table}` S
        ON T.station_id = S.station_id AND T.ingested_at = S.ingested_at
        WHEN NOT MATCHED THEN INSERT ROW
    """).result()
    logger.info("Merge OK en %.1fs → %s", time.perf_counter() - t2, main_table)

    client.delete_table(staging_table)
    logger.info("Durée totale BQ : %.1fs", time.perf_counter() - t0)
    return rows, len(rows)


def _refresh_silver(client: bigquery.Client, rows: list[dict]) -> None:
    t0 = time.perf_counter()
    job = client.load_table_from_json(
        rows,
        BQ_SILVER,
        job_config=bigquery.LoadJobConfig(
            schema=_bq_schema(),
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    )
    job.result()
    logger.info("Silver stations_latest : %d lignes en %.1fs", len(rows), time.perf_counter() - t0)


def _fuel_zone_agg(fuel: str) -> str:
    return (
        f"ROUND(AVG(IF({fuel}_rupture IS FALSE AND {fuel}_prix IS NOT NULL, {fuel}_prix, NULL)), 3) AS {fuel}_prix_moyen"
        f", ROUND(COUNTIF({fuel}_rupture IS TRUE) / COUNT(*), 4) AS {fuel}_taux_rupture"
    )



def _refresh_gold(client: bigquery.Client, ingested_at: str) -> None:
    t0 = time.perf_counter()
    fuels = [bq_prefix for bq_prefix, *_ in FUEL_MAP]
    ts_param = bigquery.ScalarQueryParameter("ingested_at", "TIMESTAMP", ingested_at)

    fuel_zone_cols = ", ".join(_fuel_zone_agg(f) for f in fuels)

    prix_moyens_sql = f"""
    SELECT @ingested_at AS ingested_at, 'france' AS zone_type, '' AS zone_value,
      COUNT(*) AS nb_stations, {fuel_zone_cols}
    FROM `{BQ_SILVER}`

    UNION ALL

    SELECT @ingested_at, 'region', region, COUNT(*), {fuel_zone_cols}
    FROM `{BQ_SILVER}` WHERE region IS NOT NULL GROUP BY region

    UNION ALL

    SELECT @ingested_at, 'departement', departement, COUNT(*), {fuel_zone_cols}
    FROM `{BQ_SILVER}` WHERE departement IS NOT NULL GROUP BY departement

    UNION ALL

    SELECT @ingested_at, 'code_postal', code_postal, COUNT(*), {fuel_zone_cols}
    FROM `{BQ_SILVER}` WHERE code_postal IS NOT NULL GROUP BY code_postal
    """

    client.query(prix_moyens_sql, job_config=bigquery.QueryJobConfig(
        destination=BQ_GOLD_ZONE,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        query_parameters=[ts_param],
    )).result()
    logger.info("Gold prix_moyens_zone OK en %.1fs", time.perf_counter() - t0)

    t2 = time.perf_counter()
    station_cols = "station_id, adresse, ville, code_postal, departement, region, latitude, longitude"

    client.query(f"TRUNCATE TABLE `{BQ_GOLD_TOP}`").result()

    jobs = []
    for fuel in fuels:
        sql = f"""
        WITH base AS (
          SELECT {station_cols}, {fuel}_prix AS prix
          FROM `{BQ_SILVER}`
          WHERE {fuel}_prix IS NOT NULL AND {fuel}_rupture IS FALSE
        ),
        zones AS (
          SELECT {station_cols}, prix, 'france' AS zone_type, '' AS zone_value FROM base
          UNION ALL
          SELECT {station_cols}, prix, 'region', region FROM base WHERE region IS NOT NULL
          UNION ALL
          SELECT {station_cols}, prix, 'departement', departement FROM base WHERE departement IS NOT NULL
        ),
        ranked AS (
          SELECT *,
            ROW_NUMBER() OVER (PARTITION BY zone_type, zone_value ORDER BY prix ASC)  AS rn_asc,
            ROW_NUMBER() OVER (PARTITION BY zone_type, zone_value ORDER BY prix DESC) AS rn_desc
          FROM zones
        )
        SELECT zone_type, zone_value, '{fuel}' AS fuel, 'top' AS rank_type, rn_asc AS rank, {station_cols}, prix
        FROM ranked WHERE rn_asc <= 10
        UNION ALL
        SELECT zone_type, zone_value, '{fuel}', 'worst', rn_desc, {station_cols}, prix
        FROM ranked WHERE rn_desc <= 10
        """
        jobs.append(client.query(sql, job_config=bigquery.QueryJobConfig(
            destination=BQ_GOLD_TOP,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )))

    for job in jobs:
        job.result()

    logger.info("Gold top_stations OK en %.1fs", time.perf_counter() - t2)


def ingest(request=None):
    """Cloud Function entrypoint."""
    t_start = time.perf_counter()
    now = datetime.now(timezone.utc)
    ingested_at = now.isoformat()
    date_str = now.strftime("%Y-%m-%d")

    logger.info("=== Début ingestion %s ===", ingested_at)

    content = fetch_csv()
    file_md5 = _md5(content)
    logger.info("MD5 : %s", file_md5)

    client = bigquery.Client(project=GCP_PROJECT)

    if _log_table_exists(client) and _already_ingested(client, file_md5):
        logger.info("Déjà ingéré (MD5 %s) — skip", file_md5)
        return {"status": "skipped", "md5": file_md5}, 200

    ensure_infrastructure(client)

    gcs_uri = None
    if GCS_BUCKET:
        gcs_uri = upload_to_gcs(content, date_str)
    else:
        logger.warning("GCS_BUCKET non défini — upload GCS ignoré")

    rows, count = load_to_bigquery(client, content, ingested_at)
    _record_ingestion(client, file_md5, ingested_at, count, gcs_uri)

    _refresh_silver(client, rows)
    _refresh_gold(client, ingested_at)

    elapsed = time.perf_counter() - t_start
    logger.info("=== Ingestion terminée : %d lignes en %.1fs ===", count, elapsed)
    return {"status": "ok", "rows": count, "date": date_str, "md5": file_md5}, 200


if __name__ == "__main__":
    result, status = ingest()
    print(json.dumps(result, indent=2))
