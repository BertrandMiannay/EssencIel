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
BQ_TABLE = os.environ.get("BQ_TABLE", "snapshots")
BQ_LOG_TABLE = f"{GCP_PROJECT}.{BQ_DATASET}.ingestion_log"

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

    record["latitude"] = _parse_float(row.get("latitude", ""))
    record["longitude"] = _parse_float(row.get("longitude", ""))
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


def _md5(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


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


def load_to_bigquery(client: bigquery.Client, content: bytes, ingested_at: str) -> int:
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
    return len(rows)


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

    if _already_ingested(client, file_md5):
        logger.info("Déjà ingéré (MD5 %s) — skip", file_md5)
        return {"status": "skipped", "md5": file_md5}, 200

    gcs_uri = None
    if GCS_BUCKET:
        gcs_uri = upload_to_gcs(content, date_str)
    else:
        logger.warning("GCS_BUCKET non défini — upload GCS ignoré")

    count = load_to_bigquery(client, content, ingested_at)
    _record_ingestion(client, file_md5, ingested_at, count, gcs_uri)

    elapsed = time.perf_counter() - t_start
    logger.info("=== Ingestion terminée : %d lignes en %.1fs ===", count, elapsed)
    return {"status": "ok", "rows": count, "date": date_str, "md5": file_md5}, 200


if __name__ == "__main__":
    result, status = ingest()
    print(json.dumps(result, indent=2))
