"""Create the BigQuery dataset and snapshots table."""
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.cloud import bigquery
from google.cloud.exceptions import Conflict

load_dotenv()

API_DATASET_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
    "/prix-des-carburants-en-france-flux-instantane-v2/"
)

GCP_PROJECT = os.environ.get("GCP_PROJECT")
BQ_DATASET = os.environ.get("BQ_DATASET", "carburants")
BQ_TABLE = "raw_snapshots"

SCHEMA_PATH = Path(__file__).parent.parent / "bigquery" / "schema.json"


def check_api_availability() -> None:
    try:
        resp = requests.get(API_DATASET_URL, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error: API is not reachable — {e}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()
    if not data.get("has_records"):
        print("Error: API returned 0 records.", file=sys.stderr)
        sys.exit(1)

    total = data.get("metas", {}).get("default", {}).get("records_count")
    print(f"API OK — {total:,} stations identifiées" if total else "API OK — ? stations identifiées")


def create_dataset(client: bigquery.Client) -> None:
    dataset_ref = bigquery.Dataset(f"{GCP_PROJECT}.{BQ_DATASET}")
    dataset_ref.location = "EU"
    try:
        client.create_dataset(dataset_ref)
        print(f"Dataset {BQ_DATASET} created.")
    except Conflict:
        print(f"Dataset {BQ_DATASET} already exists.")


def create_table(client: bigquery.Client) -> None:
    schema_raw = json.loads(SCHEMA_PATH.read_text())
    schema = [
        bigquery.SchemaField(f["name"], f["type"], mode=f.get("mode", "NULLABLE"))
        for f in schema_raw
    ]

    table_ref = bigquery.Table(f"{GCP_PROJECT}.{BQ_DATASET}.{BQ_TABLE}", schema=schema)

    table_ref.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field="ingested_at",
    )
    table_ref.clustering_fields = ["region", "code_postal"]

    try:
        client.create_table(table_ref)
        print(f"Table {BQ_DATASET}.{BQ_TABLE} created (partitioned by ingested_at, clustered by region, code_postal).")
    except Conflict:
        print(f"Table {BQ_DATASET}.{BQ_TABLE} already exists.")


def create_ingestion_log(client: bigquery.Client) -> None:
    schema = [
        bigquery.SchemaField("file_md5",    "STRING",    mode="REQUIRED"),
        bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("rows_count",  "INT64",     mode="NULLABLE"),
        bigquery.SchemaField("gcs_uri",     "STRING",    mode="NULLABLE"),
    ]
    table_ref = bigquery.Table(f"{GCP_PROJECT}.{BQ_DATASET}.ingestion_log", schema=schema)
    try:
        client.create_table(table_ref)
        print("Table ingestion_log created.")
    except Conflict:
        print("Table ingestion_log already exists.")


def main() -> None:
    if not GCP_PROJECT:
        print("Error: GCP_PROJECT environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    check_api_availability()

    client = bigquery.Client(project=GCP_PROJECT)
    create_dataset(client)
    create_table(client)
    create_ingestion_log(client)

    print("\nDone.")


if __name__ == "__main__":
    main()
