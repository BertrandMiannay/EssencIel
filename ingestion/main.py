import io
import os
import csv
import logging
from datetime import datetime, timezone

import requests
from google.cloud import bigquery, storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SOURCE_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
    "/prix-des-carburants-en-france-flux-instantane-v2/exports/csv"
    "?delimiter=%3B&list_separator=%2C&quote_all=false&with_bom=true"
)

GCP_PROJECT = os.environ["GCP_PROJECT"]
GCS_BUCKET = os.environ["GCS_BUCKET"]
BQ_DATASET = os.environ.get("BQ_DATASET", "carburants")
BQ_TABLE = os.environ.get("BQ_TABLE", "snapshots")

FUEL_COLS = ["gazole", "sp95", "sp98", "e10", "e85", "gplc"]

# Maps CSV column names → BQ field names
CSV_TO_BQ = {
    "id": "station_id",
    "adresse": "adresse",
    "code_postal": "code_postal",
    "ville": "ville",
    "departement": "departement",
    "region": "region",
    "latitude": "latitude",
    "longitude": "longitude",
    "autoroute": "autoroute",
    "services_service": "services",
    "horaires": "horaires",
}


def _parse_bool(value: str) -> bool | None:
    if value is None or value.strip() == "":
        return None
    return value.strip().lower() in ("true", "1", "oui", "o")


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
            dt = datetime.strptime(value.strip(), fmt)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _transform_row(row: dict, ingested_at: str) -> dict:
    record = {"ingested_at": ingested_at}

    for csv_col, bq_col in CSV_TO_BQ.items():
        record[bq_col] = row.get(csv_col, "").strip() or None

    record["latitude"] = _parse_float(row.get("latitude", ""))
    record["longitude"] = _parse_float(row.get("longitude", ""))
    record["autoroute"] = _parse_bool(row.get("autoroute", ""))

    for fuel in FUEL_COLS:
        record[f"{fuel}_prix"] = _parse_float(row.get(f"{fuel}_prix", ""))
        record[f"{fuel}_maj"] = _parse_timestamp(row.get(f"{fuel}_maj", ""))
        rupture_raw = row.get(f"{fuel}_rupture_type", "") or row.get(f"{fuel}_rupture", "")
        record[f"{fuel}_rupture"] = bool(rupture_raw.strip()) if rupture_raw else False

    return record


def fetch_csv() -> bytes:
    logger.info("Fetching CSV from source...")
    resp = requests.get(SOURCE_URL, timeout=120)
    resp.raise_for_status()
    logger.info(f"Downloaded {len(resp.content):,} bytes")
    return resp.content


def upload_to_gcs(content: bytes, date_str: str) -> str:
    client = storage.Client(project=GCP_PROJECT)
    bucket = client.bucket(GCS_BUCKET)
    blob_name = f"raw/{date_str}/carburants.csv"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(content, content_type="text/csv")
    gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
    logger.info(f"Uploaded to {gcs_uri}")
    return gcs_uri


def load_to_bigquery(content: bytes, ingested_at: str) -> int:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=";")
    rows = [_transform_row(row, ingested_at) for row in reader]

    client = bigquery.Client(project=GCP_PROJECT)
    table_ref = f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"

    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors[:5]}")

    logger.info(f"Inserted {len(rows):,} rows into {table_ref}")
    return len(rows)


def ingest(request=None):
    """Cloud Function entrypoint."""
    now = datetime.now(timezone.utc)
    ingested_at = now.isoformat()
    date_str = now.strftime("%Y-%m-%d")

    content = fetch_csv()
    upload_to_gcs(content, date_str)
    count = load_to_bigquery(content, ingested_at)

    return {"status": "ok", "rows": count, "date": date_str}, 200
