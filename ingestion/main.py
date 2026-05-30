import csv
import hashlib
import io
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SOURCE_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets"
    "/prix-des-carburants-en-france-flux-instantane-v2/exports/csv"
    "?delimiter=%3B&lang=fr&timezone=Europe%2FParis&use_labels=true"
)

GCP_PROJECT = os.environ.get("GCP_PROJECT", "")
GCS_BUCKET = os.environ.get("GCS_BUCKET")

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

_SNAPSHOT_UPDATE_FIELDS = [
    "adresse", "code_postal", "ville", "departement", "region",
    "latitude", "longitude", "autoroute", "services", "horaires",
] + [
    f"{fuel}_{col}"
    for fuel, *_ in FUEL_MAP
    for col in ["prix", "maj", "rupture"]
]

_STATION_FIELDS = [
    "station_id", "adresse", "ville", "code_postal",
    "departement", "region", "latitude", "longitude",
]


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
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _transform_row(row: dict, ingested_at) -> dict:
    record = {"ingested_at": ingested_at}

    for csv_col, bq_col in CSV_TO_BQ.items():
        record[bq_col] = row.get(csv_col, "").strip() or None

    lat_raw = _parse_float(row.get("latitude", ""))
    lng_raw = _parse_float(row.get("longitude", ""))
    record["latitude"] = lat_raw / 100_000 if lat_raw is not None else None
    record["longitude"] = lng_raw / 100_000 if lng_raw is not None else None
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
    from google.cloud import storage
    t0 = time.perf_counter()
    client = storage.Client(project=GCP_PROJECT)
    bucket = client.bucket(GCS_BUCKET)
    blob_name = f"raw/{date_str}/carburants.csv"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(content, content_type="text/csv")
    gcs_uri = f"gs://{GCS_BUCKET}/{blob_name}"
    logger.info("GCS upload OK : %s (%.1fs)", gcs_uri, time.perf_counter() - t0)
    return gcs_uri


def _md5(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


def _already_ingested(file_md5: str) -> bool:
    from carburants.models import IngestionLog
    return IngestionLog.objects.filter(file_md5=file_md5).exists()


def _record_ingestion(
    file_md5: str,
    ingested_at,
    rows_count: int,
    gcs_uri: str | None,
) -> None:
    from carburants.models import IngestionLog
    IngestionLog.objects.create(
        file_md5=file_md5,
        ingested_at=ingested_at,
        rows_count=rows_count,
        gcs_uri=gcs_uri,
    )


def load_to_db(content: bytes, ingested_at) -> tuple[list[dict], int]:
    """Parse le CSV et insère les snapshots via bulk_create idempotent."""
    from carburants.models import Snapshot
    t0 = time.perf_counter()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=";")
    rows = [_transform_row(row, ingested_at) for row in reader]
    logger.info("Transformation : %d lignes en %.1fs", len(rows), time.perf_counter() - t0)

    if not rows:
        raise ValueError("CSV vide — 0 lignes après transformation (réponse API suspecte)")

    price_counts = {bq_prefix: 0 for bq_prefix, *_ in FUEL_MAP}
    for r in rows:
        for bq_prefix in price_counts:
            if r.get(f"{bq_prefix}_prix") is not None:
                price_counts[bq_prefix] += 1
    for bq_prefix, count in price_counts.items():
        logger.info("  %-8s %d/%d stations avec prix", bq_prefix, count, len(rows))

    t1 = time.perf_counter()
    objs = [Snapshot(**r) for r in rows]
    Snapshot.objects.bulk_create(
        objs,
        update_conflicts=True,
        unique_fields=["station_id", "ingested_at"],
        update_fields=_SNAPSHOT_UPDATE_FIELDS,
    )
    logger.info("DB upsert : %d lignes en %.1fs", len(rows), time.perf_counter() - t1)
    return rows, len(rows)


def _refresh_silver(rows: list[dict]) -> None:
    """Remplace StationsLatest par le snapshot courant (WRITE_TRUNCATE)."""
    from carburants.models import StationsLatest
    t0 = time.perf_counter()
    StationsLatest.objects.all().delete()
    objs = [StationsLatest(**r) for r in rows]
    StationsLatest.objects.bulk_create(objs)
    logger.info("Silver stations_latest : %d lignes en %.1fs", len(rows), time.perf_counter() - t0)


def _refresh_gold(rows: list[dict], ingested_at) -> None:
    """Recalcule PrixMoyensZone et TopStations à partir de StationsLatest."""
    from carburants.models import PrixMoyensZone, StationsLatest, TopStations
    from django.db.models import Avg, Count, Q

    t0 = time.perf_counter()
    fuels = [bq_prefix for bq_prefix, *_ in FUEL_MAP]

    # ── PrixMoyensZone (WRITE_TRUNCATE) ──────────────────────────────────────
    PrixMoyensZone.objects.all().delete()

    zone_configs = [
        ("france",      None),
        ("region",      "region"),
        ("departement", "departement"),
        ("code_postal", "code_postal"),
    ]

    gold_zone_objs = []
    for zone_type, group_field in zone_configs:
        base_qs = StationsLatest.objects.all()
        if group_field:
            zone_values = list(
                base_qs.exclude(**{group_field: None})
                .values_list(group_field, flat=True)
                .distinct()
            )
        else:
            zone_values = [""]

        for zone_value in zone_values:
            qs = base_qs.filter(**{group_field: zone_value}) if group_field else base_qs

            agg_kwargs = {"nb": Count("id")}
            for f in fuels:
                agg_kwargs[f"{f}_pm"] = Avg(
                    f"{f}_prix",
                    filter=Q(**{f"{f}_rupture": False}) & Q(**{f"{f}_prix__isnull": False}),
                )
                agg_kwargs[f"{f}_nr"] = Count("id", filter=Q(**{f"{f}_rupture": True}))

            result = qs.aggregate(**agg_kwargs)
            nb = result["nb"] or 1

            obj = PrixMoyensZone(
                ingested_at=ingested_at,
                zone_type=zone_type,
                zone_value=zone_value,
                nb_stations=result["nb"],
            )
            for f in fuels:
                pm = result[f"{f}_pm"]
                setattr(obj, f"{f}_prix_moyen", round(pm, 3) if pm is not None else None)
                setattr(obj, f"{f}_taux_rupture", round(result[f"{f}_nr"] / nb, 4))
            gold_zone_objs.append(obj)

    PrixMoyensZone.objects.bulk_create(gold_zone_objs)
    logger.info("Gold prix_moyens_zone : %d lignes en %.1fs",
                len(gold_zone_objs), time.perf_counter() - t0)

    # ── TopStations (TRUNCATE + INSERT) ──────────────────────────────────────
    t2 = time.perf_counter()
    TopStations.objects.all().delete()

    top_objs = []
    silver_all = StationsLatest.objects.all()

    zone_scope = [
        ("france",      None),
        ("region",      "region"),
        ("departement", "departement"),
    ]

    for bq_prefix, *_ in FUEL_MAP:
        fuel_qs = silver_all.filter(
            **{f"{bq_prefix}_prix__isnull": False, f"{bq_prefix}_rupture": False}
        )
        for zone_type, group_field in zone_scope:
            if group_field:
                zone_values = list(
                    fuel_qs.exclude(**{group_field: None})
                    .values_list(group_field, flat=True)
                    .distinct()
                )
            else:
                zone_values = [""]

            for zone_value in zone_values:
                scoped = (
                    fuel_qs.filter(**{group_field: zone_value})
                    if group_field
                    else fuel_qs
                )
                for rank_type, order_field in [
                    ("top",   f"{bq_prefix}_prix"),
                    ("worst", f"-{bq_prefix}_prix"),
                ]:
                    for rank, station in enumerate(scoped.order_by(order_field)[:10], start=1):
                        top_objs.append(
                            TopStations(
                                zone_type=zone_type,
                                zone_value=zone_value,
                                fuel=bq_prefix,
                                rank_type=rank_type,
                                rank=rank,
                                **{f: getattr(station, f) for f in _STATION_FIELDS},
                                prix=getattr(station, f"{bq_prefix}_prix"),
                            )
                        )

    TopStations.objects.bulk_create(top_objs)
    logger.info("Gold top_stations : %d lignes en %.1fs",
                len(top_objs), time.perf_counter() - t2)


_MAX_ATTEMPTS = 3
_RETRY_SLEEP = 60


def ingest(request=None):
    """Entrypoint principal (management command ou standalone)."""
    t_start = time.perf_counter()
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    logger.info("=== Début ingestion %s ===", now.isoformat())

    content = None
    rows = None
    count = 0
    file_md5 = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            content = fetch_csv()
            file_md5 = _md5(content)
            logger.info("MD5 : %s", file_md5)

            if _already_ingested(file_md5):
                logger.info("Déjà ingéré (MD5 %s) — skip", file_md5)
                return {"status": "skipped", "md5": file_md5}, 200

            rows, count = load_to_db(content, now)
            break
        except ValueError as exc:
            if attempt < _MAX_ATTEMPTS:
                logger.warning(
                    "Tentative %d/%d échouée : %s — relance dans %ds",
                    attempt, _MAX_ATTEMPTS, exc, _RETRY_SLEEP,
                )
                time.sleep(_RETRY_SLEEP)
            else:
                logger.error("Toutes les tentatives ont échoué : %s", exc)
                raise

    gcs_uri = None
    if GCS_BUCKET:
        gcs_uri = upload_to_gcs(content, date_str)
    else:
        logger.warning("GCS_BUCKET non défini — upload GCS ignoré")

    _record_ingestion(file_md5, now, count, gcs_uri)

    _refresh_silver(rows)
    _refresh_gold(rows, now)

    elapsed = time.perf_counter() - t_start
    logger.info("=== Ingestion terminée : %d lignes en %.1fs ===", count, elapsed)
    return {"status": "ok", "rows": count, "date": date_str, "md5": file_md5}, 200


if __name__ == "__main__":
    import sys
    import django

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

    result, status = ingest()
    print(json.dumps(result, indent=2, default=str))
