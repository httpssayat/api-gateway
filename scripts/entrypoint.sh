#!/bin/sh
set -e

echo "Applying database migration..."
python scripts/migrate.py

echo "Seeding database..."
python scripts/seed.py

echo "Starting gateway..."
exec uvicorn gateway.main:app --host 0.0.0.0 --port 8080 --workers 1