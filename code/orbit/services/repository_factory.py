"""
Orbit — repository factory.

Chooses the storage backend at runtime so the SAME app runs on either the
local JSON file (default, zero dependencies) or PostgreSQL (the SQL plan in
code/migrations/0001_init.sql), with no code changes elsewhere.

Selection rules (in order):
  1. If ``ORBIT_DB_BACKEND=postgres`` OR a ``DATABASE_URL`` is set, AND the
     psycopg driver is importable -> PostgresRepository.
  2. Otherwise -> JsonFileRepository at ``ORBIT_DB`` (default ``orbit.json``).

If Postgres is requested but the driver is missing, we fall back to JSON and
print a clear warning (so the app still runs locally without installs).

Environment variables:
  DATABASE_URL         libpq URL, e.g. postgres://user:pass@host:5432/orbit
  ORBIT_DB_BACKEND     force a backend: "postgres" or "json"
  ORBIT_DB             JSON store path (json backend), default "orbit.json"
"""
from __future__ import annotations

import os
from typing import Any

from .json_repository import JsonFileRepository


def _postgres_available() -> bool:
    try:
        import psycopg  # noqa: F401
        return True
    except ImportError:
        return False


def make_repository() -> Any:
    """Build the repository chosen by environment configuration.

    Returns an object implementing the shared repository interface
    (InMemoryRepository method surface). May be a PostgresRepository or a
    JsonFileRepository.
    """
    backend = os.environ.get("ORBIT_DB_BACKEND", "").lower()
    database_url = os.environ.get("DATABASE_URL", "")

    wants_postgres = backend == "postgres" or (backend == "" and bool(database_url))

    if wants_postgres:
        if not database_url:
            raise RuntimeError(
                "ORBIT_DB_BACKEND=postgres but DATABASE_URL is not set."
            )
        if _postgres_available():
            from .postgres_repository import PostgresRepository

            print(f"[orbit] storage: PostgreSQL ({_redact(database_url)})")
            return PostgresRepository(database_url)
        # Requested Postgres but no driver: fall back so the app still runs.
        print(
            "[orbit] WARNING: DATABASE_URL set but psycopg is not installed; "
            'falling back to JSON file. Install with: pip install "psycopg[binary]>=3.1"'
        )

    path = os.environ.get("ORBIT_DB", "orbit.json")
    print(f"[orbit] storage: JSON file ({path})")
    return JsonFileRepository(path)


def flush_repository(repo: Any) -> None:
    """Persist in-place mutations if the backend needs an explicit flush.

    Called by the API at the end of each write request so mutations made by
    services (which change model objects in place — e.g. subscription status,
    notification delivery, group ownership) are durably persisted:

      * PostgreSQL: uses an identity map -> ``flush()`` writes cached mutations
        back, then ``clear_cache()`` resets per-request state.
      * JSON file: holds live objects, but in-place edits to already-stored
        objects don't auto-save; a single ``save()`` snapshots the whole store.
      * in-memory: neither method exists -> no-op.
    """
    # Postgres identity-map flush.
    flush = getattr(repo, "flush", None)
    if callable(flush):
        flush()
    clear = getattr(repo, "clear_cache", None)
    if callable(clear):
        clear()
    # JSON file: persist in-place mutations (e.g. status changes) to disk.
    # Only the JSON repo has both `save` and a `path`; guard so in-memory and
    # Postgres (no `save`) are unaffected.
    save = getattr(repo, "save", None)
    if callable(save) and hasattr(repo, "path"):
        save()


def _redact(url: str) -> str:
    """Hide credentials in a DB URL for logging."""
    if "@" in url and "//" in url:
        scheme, rest = url.split("//", 1)
        if "@" in rest:
            _creds, host = rest.split("@", 1)
            return f"{scheme}//***@{host}"
    return url
