install:
    uv sync --all-extras

test:
    uv run pytest -v

lint:
    uv run ruff check

# Database commands (via Doppler for Neon credentials)
migrate:
    doppler run --project apps-data --config dev -- uv run techdeals migrate

migrate-reset:
    doppler run --project apps-data --config dev -- uv run techdeals migrate --reset

ingest:
    doppler run --project apps-data --config dev -- uv run techdeals ingest

extract:
    doppler run --project apps-data --config dev -- uv run techdeals extract

query name="available":
    doppler run --project apps-data --config dev -- uv run techdeals query {{name}}

# Direct psql access
psql:
    doppler run --project apps-data --config dev -- bash -c 'psql "$NEON_DATABASE_URL"'

# Acceptance checks
acceptance:
    doppler run --project apps-data --config dev -- bash -c 'psql "$NEON_DATABASE_URL" -f tests/acceptance_queries.sql'