from functools import lru_cache
from django.conf import settings
from google.cloud import bigquery


@lru_cache(maxsize=1)
def get_client() -> bigquery.Client:
    return bigquery.Client(project=settings.GCP_PROJECT)


def table_ref() -> str:
    return f"{settings.GCP_PROJECT}.{settings.BQ_DATASET}.{settings.BQ_TABLE}"
