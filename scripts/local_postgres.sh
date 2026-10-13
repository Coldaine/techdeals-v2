#!/usr/bin/env bash
# Stand up a throwaway Postgres for local development / verification.
#
# The project needs a Postgres to run migrations, the pipeline and the acceptance
# queries. This installs PostgreSQL 18 + pgcrypto into $HOME (no root required) via
# micromamba and starts it on 127.0.0.1:55432. Everything it creates is disposable.
#
#   ./scripts/local_postgres.sh up      # install (if needed) + start + create DBs
#   ./scripts/local_postgres.sh stop    # stop the server
#   ./scripts/local_postgres.sh psql    # open a psql shell on /techdeals
set -euo pipefail

PORT="${PGPORT:-55432}"
PREFIX="${PG_PREFIX:-$HOME/pg}"
PGDATA="${PGDATA:-$HOME/pgdata}"
export MAMBA_ROOT_PREFIX="${MAMBA_ROOT_PREFIX:-$HOME/mamba}"
export PATH="$HOME/.local/bin:$PREFIX/bin:$PATH"

install_pg() {
  if [ ! -x "$PREFIX/bin/postgres" ]; then
    if [ ! -x "$HOME/.local/bin/micromamba" ]; then
      echo "installing micromamba..."
      curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
        | tar -xj -C /tmp bin/micromamba
      mkdir -p "$HOME/.local/bin" && mv /tmp/bin/micromamba "$HOME/.local/bin/" \
        && chmod +x "$HOME/.local/bin/micromamba"
    fi
    echo "installing postgresql (conda-forge) into $PREFIX ..."
    micromamba create -y -p "$PREFIX" -c conda-forge postgresql
  fi
}

case "${1:-up}" in
  up)
    install_pg
    if ! pg_ctl -D "$PGDATA" status >/dev/null 2>&1; then
      [ -d "$PGDATA" ] || initdb -D "$PGDATA" -U postgres -A trust
      pg_ctl -D "$PGDATA" \
        -o "-p $PORT -c listen_addresses=127.0.0.1 -c unix_socket_directories=/tmp" \
        -l /tmp/pg.log start
    fi
    for db in techdeals techdeals_test; do
      psql -h 127.0.0.1 -p "$PORT" -U postgres -d postgres -tc \
        "SELECT 1 FROM pg_database WHERE datname='$db'" | grep -q 1 \
        || createdb -h 127.0.0.1 -p "$PORT" -U postgres "$db"
    done
    echo "postgres up on 127.0.0.1:$PORT"
    echo "  NEON_DATABASE_URL=postgresql://postgres@127.0.0.1:$PORT/techdeals"
    ;;
  stop)  pg_ctl -D "$PGDATA" stop ;;
  psql)  psql -h 127.0.0.1 -p "$PORT" -U postgres -d techdeals ;;
  *)     echo "usage: $0 {up|stop|psql}"; exit 1 ;;
esac
