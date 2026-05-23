"""Tests des endpoints API REST Django."""
import pytest
from unittest.mock import patch
from django.test import Client

pytestmark = pytest.mark.django_db(databases=[])


# ── Données de mock ───────────────────────────────────────────────────────────

MOCK_PRIX_MOYEN = [
    {
        "last_date": "2024-01-15T08:00:00+00:00",
        "nb_stations": 12345,
        "gazole_prix_moyen": 1.709,
        "gazole_taux_rupture": 0.02,
        "sp95_prix_moyen": 1.759,
        "sp95_taux_rupture": 0.01,
        "sp98_prix_moyen": 1.789,
        "sp98_taux_rupture": 0.01,
        "e10_prix_moyen": 1.659,
        "e10_taux_rupture": 0.01,
        "e85_prix_moyen": 0.899,
        "e85_taux_rupture": 0.03,
        "gplc_prix_moyen": 1.1,
        "gplc_taux_rupture": 0.05,
    }
]

MOCK_STATIONS = [
    {
        "station_id": "12345",
        "adresse": "1 rue de Rivoli",
        "ville": "Paris",
        "code_postal": "75001",
        "departement": "Paris",
        "region": "Île-de-France",
        "latitude": 48.8566,
        "longitude": 2.3522,
        "prix": 1.509,
        "rupture": False,
    }
]


@pytest.fixture
def client():
    return Client()


# ── /api/prix-moyen/ ──────────────────────────────────────────────────────────


class TestPrixMoyen:
    def test_france_retourne_200(self, client):
        with patch("carburants.views.queries.prix_moyen_par_zone", return_value=MOCK_PRIX_MOYEN):
            response = client.get("/api/prix-moyen/?zone_type=france")
        assert response.status_code == 200

    def test_region_sans_zone_value_retourne_400(self, client):
        response = client.get("/api/prix-moyen/?zone_type=region")
        assert response.status_code == 400

    def test_departement_sans_zone_value_retourne_400(self, client):
        response = client.get("/api/prix-moyen/?zone_type=departement")
        assert response.status_code == 400

    def test_zone_type_invalide_retourne_400(self, client):
        response = client.get("/api/prix-moyen/?zone_type=continent")
        assert response.status_code == 400

    def test_departement_avec_zone_value_retourne_200(self, client):
        with patch("carburants.views.queries.prix_moyen_par_zone", return_value=MOCK_PRIX_MOYEN):
            response = client.get("/api/prix-moyen/?zone_type=departement&zone_value=75")
        assert response.status_code == 200

    def test_reponse_est_une_liste(self, client):
        with patch("carburants.views.queries.prix_moyen_par_zone", return_value=MOCK_PRIX_MOYEN):
            response = client.get("/api/prix-moyen/?zone_type=france")
        assert isinstance(response.json(), list)


# ── /api/top-prix/ ────────────────────────────────────────────────────────────


class TestTopPrix:
    def test_nominal_retourne_200(self, client):
        with patch("carburants.views.queries.top_prix", return_value=MOCK_STATIONS):
            response = client.get("/api/top-prix/?fuel=gazole&zone_type=france")
        assert response.status_code == 200

    def test_fuel_invalide_retourne_400(self, client):
        response = client.get("/api/top-prix/?fuel=essence_supreme")
        assert response.status_code == 400

    def test_limit_plafonnee_a_50(self, client):
        with patch("carburants.views.queries.top_prix", return_value=MOCK_STATIONS) as mock_q:
            client.get("/api/top-prix/?fuel=gazole&limit=100")
        assert mock_q.call_args.kwargs["limit"] <= 50

    def test_order_asc_par_defaut(self, client):
        with patch("carburants.views.queries.top_prix", return_value=MOCK_STATIONS) as mock_q:
            client.get("/api/top-prix/?fuel=gazole")
        assert mock_q.call_args.kwargs["order"] == "ASC"

    def test_order_desc_transmis(self, client):
        with patch("carburants.views.queries.top_prix", return_value=MOCK_STATIONS) as mock_q:
            client.get("/api/top-prix/?fuel=sp95&order=DESC")
        assert mock_q.call_args.kwargs["order"] == "DESC"

    def test_limit_invalide_utilise_defaut(self, client):
        with patch("carburants.views.queries.top_prix", return_value=MOCK_STATIONS) as mock_q:
            client.get("/api/top-prix/?fuel=gazole&limit=abc")
        assert mock_q.call_args.kwargs["limit"] == 10


# ── /api/worst-prix/ ─────────────────────────────────────────────────────────


class TestWorstPrix:
    def test_nominal_retourne_200(self, client):
        with patch("carburants.views.queries.top_prix", return_value=MOCK_STATIONS):
            response = client.get("/api/worst-prix/?fuel=gazole")
        assert response.status_code == 200

    def test_fuel_invalide_retourne_400(self, client):
        response = client.get("/api/worst-prix/?fuel=super_plomb")
        assert response.status_code == 400

    def test_appel_top_prix_avec_order_desc(self, client):
        with patch("carburants.views.queries.top_prix", return_value=MOCK_STATIONS) as mock_q:
            client.get("/api/worst-prix/?fuel=sp98")
        assert mock_q.call_args.kwargs["order"] == "DESC"


# ── /api/stations-proches/ ───────────────────────────────────────────────────


class TestStationsProches:
    def test_nominal_retourne_200(self, client):
        with patch("carburants.views.queries.stations_proches", return_value=MOCK_STATIONS):
            response = client.get("/api/stations-proches/?lat=48.85&lng=2.35&fuel=gazole")
        assert response.status_code == 200

    def test_lat_manquant_retourne_400(self, client):
        response = client.get("/api/stations-proches/?lng=2.35")
        assert response.status_code == 400

    def test_lng_manquant_retourne_400(self, client):
        response = client.get("/api/stations-proches/?lat=48.85")
        assert response.status_code == 400

    def test_lat_non_numerique_retourne_400(self, client):
        response = client.get("/api/stations-proches/?lat=abc&lng=2.35")
        assert response.status_code == 400

    def test_rayon_plafonne_a_100_km(self, client):
        with patch("carburants.views.queries.stations_proches", return_value=[]) as mock_q:
            client.get("/api/stations-proches/?lat=48.85&lng=2.35&rayon=999")
        assert mock_q.call_args.kwargs["rayon_km"] <= 100

    def test_fuel_inconnu_utilise_gazole(self, client):
        with patch("carburants.views.queries.stations_proches", return_value=[]) as mock_q:
            client.get("/api/stations-proches/?lat=48.85&lng=2.35&fuel=super_carburant")
        assert mock_q.call_args.args[2] == "gazole"

    def test_coordonnees_transmises_correctement(self, client):
        with patch("carburants.views.queries.stations_proches", return_value=[]) as mock_q:
            client.get("/api/stations-proches/?lat=48.8566&lng=2.3522")
        assert mock_q.call_args.args[0] == pytest.approx(48.8566)
        assert mock_q.call_args.args[1] == pytest.approx(2.3522)
