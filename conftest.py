import os

os.environ.setdefault("GCP_PROJECT", "test-project")
os.environ.setdefault("GCS_BUCKET", "test-bucket")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("BQ_DATASET", "carburants")
