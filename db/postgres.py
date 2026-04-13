"""Postgres connection pool singleton."""

import os

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://sudhirabadugu@localhost:5433/ai_twin",
)

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            open=True,
            kwargs={"row_factory": dict_row},
        )
    return _pool


def get_conn():
    return get_pool().connection()
