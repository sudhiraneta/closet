"""Postgres connection pool singleton."""

import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def _build_url() -> str:
    """Resolve DATABASE_URL from env, with fallbacks for Railway's variable formats."""
    raw = os.environ.get("DATABASE_URL", "")

    # Railway also exposes individual PG* vars — build URL from those if DATABASE_URL missing
    if not raw or raw.startswith("${{") or raw.startswith("$("):
        pghost = os.environ.get("PGHOST", "")
        pgport = os.environ.get("PGPORT", "5432")
        pguser = os.environ.get("PGUSER", os.environ.get("POSTGRES_USER", "postgres"))
        pgpass = os.environ.get("PGPASSWORD", os.environ.get("POSTGRES_PASSWORD", ""))
        pgdb   = os.environ.get("PGDATABASE", os.environ.get("POSTGRES_DB", "railway"))
        if pghost:
            raw = f"postgresql://{pguser}:{pgpass}@{pghost}:{pgport}/{pgdb}"

    # Last-resort local dev fallback
    if not raw or raw.startswith("${{") or raw.startswith("$("):
        raw = "postgresql://sudhirabadugu@localhost:5433/ai_twin"

    # Normalise scheme — psycopg3 requires postgresql://, Railway often gives postgres://
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]

    # Log the URL (mask password) so Railway logs show what's actually being used
    masked = raw
    import re
    masked = re.sub(r"(postgresql://[^:]+:)[^@]+(@)", r"\1***\2", masked)
    print(f"[db] Connecting to: {masked}")

    return raw


DATABASE_URL = _build_url()

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=1,
            max_size=10,
            max_lifetime=300,   # recycle connections every 5 min
            max_idle=60,        # drop idle connections after 60 s
            reconnect_timeout=10,
            open=True,
            check=ConnectionPool.check_connection,
            kwargs={"row_factory": dict_row},
        )
    return _pool


def get_conn():
    return get_pool().connection()
