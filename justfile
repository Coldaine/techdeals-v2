install:
    uv sync --all-extras

test:
    uv run pytest -v

# Full suite including DB-backed integration tests (needs a scratch Postgres).
# Bring one up with: ./scripts/local_postgres.sh up
test-db:
    TECHDEALS_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/techdeals_test uv run pytest -v

lint:
    uv run ruff check

# --- local pipeline (no credentials needed) ---------------------------------
# Local Postgres instead of Doppler. `just pipeline` is the full fixture loop.
migrate-local:
    NEON_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/techdeals uv run techdeals migrate

pipeline:
    NEON_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/techdeals uv run techdeals pipeline --provider offline

acceptance-local:
    NEON_DATABASE_URL=postgresql://postgres@127.0.0.1:55432/techdeals uv run techdeals acceptance

# --- Neon / Doppler (brief-aligned) -----------------------------------------
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
    doppler run --project apps-data --config dev -- uv run techdeals acceptance
