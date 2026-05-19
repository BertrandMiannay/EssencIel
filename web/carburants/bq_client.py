from functools import lru_cache
from django.conf import settings
from google.cloud import bigquery


@lru_cache(maxsize=1)
def get_client() -> bigquery.Client:
    return bigquery.Client(project=settings.GCP_PROJECT)


def _ref(table_name: str) -> str:
    return f"{settings.GCP_PROJECT}.{settings.BQ_DATASET}.{table_name}"


def table_ref() -> str:
    return _ref(settings.BQ_TABLE)


def silver_table_ref() -> str:
    return _ref("stations_latest")


def gold_zone_table_ref() -> str:
    return _ref("prix_moyens_zone")


def gold_synthese_table_ref() -> str:
    return _ref("nationale_synthese")


def gold_top_table_ref() -> str:
    return _ref("gold_top_stations")
