#!/bin/sh
set -e

echo "Running database migrations..."
poetry run alembic upgrade head

echo "Starting FastAPI server..."
exec poetry run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}
