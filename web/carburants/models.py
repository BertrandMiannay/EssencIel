from django.db import models


FUELS = ["gazole", "sp95", "sp98", "e10", "e85", "gplc"]

_FUEL_FIELDS = [
    f
    for fuel in FUELS
    for f in [f"{fuel}_prix", f"{fuel}_maj", f"{fuel}_rupture"]
]

_STATION_GEO_FIELDS = [
    "adresse", "code_postal", "ville", "departement", "region",
    "latitude", "longitude", "autoroute",
]

_STATION_FIELDS = ["station_id"] + _STATION_GEO_FIELDS + _FUEL_FIELDS + ["services", "horaires"]


class Snapshot(models.Model):
    ingested_at    = models.DateTimeField()
    station_id     = models.CharField(max_length=20)
    adresse        = models.CharField(max_length=200, null=True, blank=True)
    code_postal    = models.CharField(max_length=10, null=True, blank=True)
    ville          = models.CharField(max_length=100, null=True, blank=True)
    departement    = models.CharField(max_length=100, null=True, blank=True)
    region         = models.CharField(max_length=100, null=True, blank=True)
    latitude       = models.FloatField(null=True, blank=True)
    longitude      = models.FloatField(null=True, blank=True)
    autoroute      = models.BooleanField(null=True, blank=True)
    gazole_prix    = models.FloatField(null=True, blank=True)
    gazole_maj     = models.DateTimeField(null=True, blank=True)
    gazole_rupture = models.BooleanField(null=True, blank=True)
    sp95_prix      = models.FloatField(null=True, blank=True)
    sp95_maj       = models.DateTimeField(null=True, blank=True)
    sp95_rupture   = models.BooleanField(null=True, blank=True)
    sp98_prix      = models.FloatField(null=True, blank=True)
    sp98_maj       = models.DateTimeField(null=True, blank=True)
    sp98_rupture   = models.BooleanField(null=True, blank=True)
    e10_prix       = models.FloatField(null=True, blank=True)
    e10_maj        = models.DateTimeField(null=True, blank=True)
    e10_rupture    = models.BooleanField(null=True, blank=True)
    e85_prix       = models.FloatField(null=True, blank=True)
    e85_maj        = models.DateTimeField(null=True, blank=True)
    e85_rupture    = models.BooleanField(null=True, blank=True)
    gplc_prix      = models.FloatField(null=True, blank=True)
    gplc_maj       = models.DateTimeField(null=True, blank=True)
    gplc_rupture   = models.BooleanField(null=True, blank=True)
    services       = models.TextField(null=True, blank=True)
    horaires       = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = [("station_id", "ingested_at")]
        indexes = [
            models.Index(fields=["ingested_at"]),
            models.Index(fields=["region", "code_postal"]),
        ]

    def __str__(self):
        return f"{self.station_id} @ {self.ingested_at}"


class IngestionLog(models.Model):
    file_md5    = models.CharField(max_length=32, unique=True)
    ingested_at = models.DateTimeField()
    rows_count  = models.IntegerField(null=True, blank=True)
    gcs_uri     = models.CharField(max_length=500, null=True, blank=True)

    def __str__(self):
        return f"{self.file_md5} ({self.ingested_at})"


class StationsLatest(models.Model):
    """Dernier snapshot par station (équivalent silver_stations_latest)."""
    ingested_at    = models.DateTimeField()
    station_id     = models.CharField(max_length=20, unique=True)
    adresse        = models.CharField(max_length=200, null=True, blank=True)
    code_postal    = models.CharField(max_length=10, null=True, blank=True)
    ville          = models.CharField(max_length=100, null=True, blank=True)
    departement    = models.CharField(max_length=100, null=True, blank=True)
    region         = models.CharField(max_length=100, null=True, blank=True)
    latitude       = models.FloatField(null=True, blank=True)
    longitude      = models.FloatField(null=True, blank=True)
    autoroute      = models.BooleanField(null=True, blank=True)
    gazole_prix    = models.FloatField(null=True, blank=True)
    gazole_maj     = models.DateTimeField(null=True, blank=True)
    gazole_rupture = models.BooleanField(null=True, blank=True)
    sp95_prix      = models.FloatField(null=True, blank=True)
    sp95_maj       = models.DateTimeField(null=True, blank=True)
    sp95_rupture   = models.BooleanField(null=True, blank=True)
    sp98_prix      = models.FloatField(null=True, blank=True)
    sp98_maj       = models.DateTimeField(null=True, blank=True)
    sp98_rupture   = models.BooleanField(null=True, blank=True)
    e10_prix       = models.FloatField(null=True, blank=True)
    e10_maj        = models.DateTimeField(null=True, blank=True)
    e10_rupture    = models.BooleanField(null=True, blank=True)
    e85_prix       = models.FloatField(null=True, blank=True)
    e85_maj        = models.DateTimeField(null=True, blank=True)
    e85_rupture    = models.BooleanField(null=True, blank=True)
    gplc_prix      = models.FloatField(null=True, blank=True)
    gplc_maj       = models.DateTimeField(null=True, blank=True)
    gplc_rupture   = models.BooleanField(null=True, blank=True)
    services       = models.TextField(null=True, blank=True)
    horaires       = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["region", "code_postal"])]

    def __str__(self):
        return f"{self.station_id} (latest)"


class PrixMoyensZone(models.Model):
    """Agrégats de prix par zone géographique (équivalent gold_prix_moyens_zone)."""
    ingested_at         = models.DateTimeField()
    zone_type           = models.CharField(max_length=20)
    zone_value          = models.CharField(max_length=100)
    nb_stations         = models.IntegerField(null=True, blank=True)
    gazole_prix_moyen   = models.FloatField(null=True, blank=True)
    gazole_taux_rupture = models.FloatField(null=True, blank=True)
    sp95_prix_moyen     = models.FloatField(null=True, blank=True)
    sp95_taux_rupture   = models.FloatField(null=True, blank=True)
    sp98_prix_moyen     = models.FloatField(null=True, blank=True)
    sp98_taux_rupture   = models.FloatField(null=True, blank=True)
    e10_prix_moyen      = models.FloatField(null=True, blank=True)
    e10_taux_rupture    = models.FloatField(null=True, blank=True)
    e85_prix_moyen      = models.FloatField(null=True, blank=True)
    e85_taux_rupture    = models.FloatField(null=True, blank=True)
    gplc_prix_moyen     = models.FloatField(null=True, blank=True)
    gplc_taux_rupture   = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["zone_type", "zone_value"])]

    def __str__(self):
        return f"{self.zone_type}={self.zone_value}"


class TopStations(models.Model):
    """Classements top/worst par carburant et zone (équivalent gold_top_stations)."""
    zone_type   = models.CharField(max_length=20)
    zone_value  = models.CharField(max_length=100)
    fuel        = models.CharField(max_length=10)
    rank_type   = models.CharField(max_length=5)
    rank        = models.IntegerField()
    station_id  = models.CharField(max_length=20, null=True, blank=True)
    adresse     = models.CharField(max_length=200, null=True, blank=True)
    ville       = models.CharField(max_length=100, null=True, blank=True)
    code_postal = models.CharField(max_length=10, null=True, blank=True)
    departement = models.CharField(max_length=100, null=True, blank=True)
    region      = models.CharField(max_length=100, null=True, blank=True)
    latitude    = models.FloatField(null=True, blank=True)
    longitude   = models.FloatField(null=True, blank=True)
    prix        = models.FloatField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["zone_type", "zone_value", "fuel"])]

    def __str__(self):
        return f"{self.rank_type}#{self.rank} {self.fuel} {self.zone_type}={self.zone_value}"
