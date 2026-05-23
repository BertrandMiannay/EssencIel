"""Tests unitaires pour ingestion/main.py — transformations CSV et pipeline BigQuery."""
import io
import csv
from unittest.mock import MagicMock, patch

import pytest

from ingestion.main import (
    _parse_float,
    _parse_timestamp,
    _transform_row,
    _md5,
    _already_ingested,
    load_to_bigquery,
    ingest,
)


# ── Helpers CSV ───────────────────────────────────────────────────────────────


def _station(**overrides) -> dict:
    """Ligne CSV de référence avec toutes les colonnes attendues."""
    base = {
        "id": "12345",
        "Code postal": "75001",
        "Adresse": "1 rue de Rivoli",
        "Ville": "Paris",
        "Département": "Paris",
        "Région": "Île-de-France",
        "Services proposés": "Toilettes",
        "horaires détaillés": '{"hours": "24/7"}',
        "latitude": "4853476",  # → 48.53476°
        "longitude": "228640",  # → 2.2864°
        "pop": "R",
        "Prix Gazole": "1,509",
        "Prix Gazole mis à jour le": "2024-01-15T08:00:00",
        "Type rupture gazole": "",
        "Prix SP95": "1,759",
        "Prix SP95 mis à jour le": "2024-01-15T08:00:00",
        "Type rupture sp95": "",
        "Prix SP98": "1,789",
        "Prix SP98 mis à jour le": "2024-01-15T08:00:00",
        "Type rupture sp98": "",
        "Prix E10": "1,659",
        "Prix E10 mis à jour le": "2024-01-15T08:00:00",
        "Type rupture e10": "",
        "Prix E85": "0,899",
        "Prix E85 mis à jour le": "2024-01-15T08:00:00",
        "Type rupture e85": "",
        "Prix GPLc": "1,100",
        "Prix GPLc mis à jour le": "2024-01-15T08:00:00",
        "Type rupture GPLc": "",
    }
    base.update(overrides)
    return base


def _make_csv(rows: list[dict]) -> bytes:
    """Génère des octets CSV (UTF-8, séparateur ;) depuis une liste de dicts."""
    headers = list(rows[0].keys()) if rows else list(_station().keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, delimiter=";", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _mock_bq_client() -> MagicMock:
    """Client BigQuery minimal pour les tests de pipeline."""
    client = MagicMock()
    job = MagicMock()
    job.result.return_value = None
    client.load_table_from_json.return_value = job
    client.query.return_value = job
    client.insert_rows_json.return_value = []
    return client


# ── _parse_float ──────────────────────────────────────────────────────────────


class TestParseFloat:
    def test_virgule_decimale(self):
        assert _parse_float("1,509") == pytest.approx(1.509)

    def test_point_decimal(self):
        assert _parse_float("1.509") == pytest.approx(1.509)

    def test_chaine_vide(self):
        assert _parse_float("") is None

    def test_none(self):
        assert _parse_float(None) is None

    def test_espaces_trim(self):
        assert _parse_float("  1,509  ") == pytest.approx(1.509)

    def test_valeur_invalide(self):
        assert _parse_float("abc") is None

    def test_zero(self):
        assert _parse_float("0") == pytest.approx(0.0)


# ── _parse_timestamp ──────────────────────────────────────────────────────────


class TestParseTimestamp:
    def test_iso_avec_timezone(self):
        result = _parse_timestamp("2024-01-15T08:00:00+01:00")
        assert result is not None
        assert "2024-01-15" in result

    def test_iso_sans_timezone(self):
        result = _parse_timestamp("2024-01-15T08:00:00")
        assert result is not None
        assert "2024-01-15" in result

    def test_format_datetime_espace(self):
        result = _parse_timestamp("2024-01-15 08:00:00")
        assert result is not None
        assert "2024-01-15" in result

    def test_chaine_vide(self):
        assert _parse_timestamp("") is None

    def test_none(self):
        assert _parse_timestamp(None) is None

    def test_format_invalide(self):
        assert _parse_timestamp("pas-une-date") is None


# ── _transform_row ────────────────────────────────────────────────────────────


class TestTransformRow:
    TS = "2024-01-15T08:00:00+00:00"

    def test_cas_nominal_champs_de_base(self):
        result = _transform_row(_station(), self.TS)

        assert result["station_id"] == "12345"
        assert result["code_postal"] == "75001"
        assert result["ville"] == "Paris"
        assert result["departement"] == "Paris"
        assert result["region"] == "Île-de-France"
        assert result["ingested_at"] == self.TS

    def test_conversion_coordonnees_gps(self):
        """L'API source stocke les coordonnées comme entiers × 100 000."""
        result = _transform_row(_station(latitude="4620516", longitude="228640"), self.TS)

        assert result["latitude"] == pytest.approx(46.20516)
        assert result["longitude"] == pytest.approx(2.2864)

    def test_coordonnees_absentes(self):
        result = _transform_row(_station(latitude="", longitude=""), self.TS)

        assert result["latitude"] is None
        assert result["longitude"] is None

    def test_autoroute_flag_A(self):
        assert _transform_row(_station(pop="A"), self.TS)["autoroute"] is True

    def test_autoroute_flag_R(self):
        assert _transform_row(_station(pop="R"), self.TS)["autoroute"] is False

    def test_autoroute_flag_vide(self):
        assert _transform_row(_station(pop=""), self.TS)["autoroute"] is False

    def test_prix_carburant_avec_virgule(self):
        result = _transform_row(_station(**{"Prix Gazole": "1,509"}), self.TS)
        assert result["gazole_prix"] == pytest.approx(1.509)

    def test_prix_carburant_absent(self):
        result = _transform_row(_station(**{"Prix Gazole": ""}), self.TS)
        assert result["gazole_prix"] is None

    def test_rupture_renseignee(self):
        result = _transform_row(_station(**{"Type rupture gazole": "Totale"}), self.TS)
        assert result["gazole_rupture"] is True

    def test_rupture_vide(self):
        result = _transform_row(_station(**{"Type rupture gazole": ""}), self.TS)
        assert result["gazole_rupture"] is False

    def test_tous_carburants_transformes(self):
        """Les 6 carburants doivent tous avoir leurs 3 colonnes dans le résultat."""
        result = _transform_row(_station(), self.TS)
        for fuel in ("gazole", "sp95", "sp98", "e10", "e85", "gplc"):
            assert f"{fuel}_prix" in result
            assert f"{fuel}_maj" in result
            assert f"{fuel}_rupture" in result

    def test_colonnes_csv_supplementaires_ignorees(self):
        """Des colonnes inconnues ne doivent pas planter la transformation."""
        row = _station()
        row["colonne_inconnue"] = "valeur_ignoree"
        result = _transform_row(row, self.TS)
        assert result["station_id"] == "12345"

    def test_champs_optionnels_absents(self):
        """Un CSV minimal (id seulement) ne doit pas lever d'exception."""
        result = _transform_row({"id": "99999"}, self.TS)
        assert result["station_id"] == "99999"
        assert result["ville"] is None
        assert result["gazole_prix"] is None


# ── _md5 ──────────────────────────────────────────────────────────────────────


def test_md5_deterministe():
    content = b"hello world"
    assert _md5(content) == _md5(content)


def test_md5_different_si_contenu_different():
    assert _md5(b"aaa") != _md5(b"bbb")


def test_md5_valeur_connue():
    assert _md5(b"") == "d41d8cd98f00b204e9800998ecf8427e"


# ── _already_ingested ─────────────────────────────────────────────────────────


def test_already_ingested_retourne_true_si_md5_connu():
    client = MagicMock()
    client.query.return_value.result.return_value = [MagicMock()]
    assert _already_ingested(client, "abc123") is True


def test_already_ingested_retourne_false_si_md5_inconnu():
    client = MagicMock()
    client.query.return_value.result.return_value = []
    assert _already_ingested(client, "abc123") is False


# ── load_to_bigquery ──────────────────────────────────────────────────────────


class TestLoadToBigquery:
    TS = "2024-01-15T08:00:00+00:00"

    def test_cas_nominal_une_ligne(self):
        client = _mock_bq_client()
        rows, count = load_to_bigquery(client, _make_csv([_station()]), self.TS)

        assert count == 1
        assert len(rows) == 1
        client.load_table_from_json.assert_called_once()
        client.delete_table.assert_called_once()

    def test_merge_idempotent_execute(self):
        """Un MERGE doit être lancé sur (station_id, ingested_at) après le staging."""
        client = _mock_bq_client()
        load_to_bigquery(client, _make_csv([_station()]), self.TS)

        queries_sql = [str(c.args[0]) for c in client.query.call_args_list]
        assert any("MERGE" in q for q in queries_sql)

    def test_staging_supprime_apres_merge(self):
        """La table de staging doit être purgée même si une seule ligne est chargée."""
        client = _mock_bq_client()
        load_to_bigquery(client, _make_csv([_station()]), self.TS)

        client.delete_table.assert_called_once()

    def test_plusieurs_lignes(self):
        stations = [_station(id=str(i)) for i in range(5)]
        client = _mock_bq_client()
        rows, count = load_to_bigquery(client, _make_csv(stations), self.TS)

        assert count == 5

    def test_schema_different_colonnes_supplementaires(self):
        """Des colonnes inconnues dans le CSV ne doivent pas bloquer le chargement."""
        row = _station()
        row["colonne_inattendue"] = "x"
        client = _mock_bq_client()
        rows, count = load_to_bigquery(client, _make_csv([row]), self.TS)

        assert count == 1

    def test_csv_vide_zero_lignes(self):
        """Un CSV sans données (header seulement) doit charger 0 lignes sans erreur."""
        headers = list(_station().keys())
        csv_bytes = (";".join(headers) + "\n").encode("utf-8")
        client = _mock_bq_client()
        rows, count = load_to_bigquery(client, csv_bytes, self.TS)

        assert count == 0


# ── ingest — orchestration complète ──────────────────────────────────────────


class TestIngest:
    def _csv(self):
        return _make_csv([_station()])

    @patch("ingestion.main._log_table_exists", return_value=True)
    @patch("ingestion.main._already_ingested", return_value=True)
    @patch("ingestion.main.fetch_csv")
    def test_skip_si_md5_deja_connu(self, mock_fetch, _mock_already, _mock_log):
        mock_fetch.return_value = self._csv()
        with patch("ingestion.main.bigquery.Client"):
            result, code = ingest()

        assert code == 200
        assert result["status"] == "skipped"

    @patch("ingestion.main._log_table_exists", return_value=False)
    @patch("ingestion.main.fetch_csv")
    @patch("ingestion.main.bigquery.Client")
    @patch("ingestion.main.upload_to_gcs", return_value="gs://bucket/raw/2024-01-15/carburants.csv")
    def test_cas_nominal(self, _mock_gcs, mock_bq_cls, mock_fetch, _mock_log):
        mock_fetch.return_value = self._csv()
        mock_bq_cls.return_value = _mock_bq_client()

        result, code = ingest()

        assert code == 200
        assert result["status"] == "ok"
        assert result["rows"] == 1

    @patch("ingestion.main.GCS_BUCKET", None)
    @patch("ingestion.main._log_table_exists", return_value=False)
    @patch("ingestion.main.fetch_csv")
    @patch("ingestion.main.bigquery.Client")
    def test_pipeline_sans_gcs(self, mock_bq_cls, mock_fetch, _mock_log):
        """L'ingestion doit continuer si GCS_BUCKET n'est pas configuré."""
        mock_fetch.return_value = self._csv()
        mock_bq_cls.return_value = _mock_bq_client()

        result, code = ingest()

        assert code == 200
        assert result["status"] == "ok"
