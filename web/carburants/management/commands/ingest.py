import sys
from pathlib import Path

from django.core.management.base import BaseCommand

# Ajoute la racine du projet au path pour importer ingestion/
ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.main import ingest  # noqa: E402


class Command(BaseCommand):
    help = "Ingère le snapshot carburants du jour dans BigQuery"

    def handle(self, *args, **options):
        self.stdout.write("Démarrage de l'ingestion…")
        ingest()
        self.stdout.write(self.style.SUCCESS("Ingestion terminée."))
