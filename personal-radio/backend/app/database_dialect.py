from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine import URL, make_url

SQLITE = 'sqlite'
POSTGRESQL = 'postgresql'
UNSUPPORTED = 'unsupported'
SUPPORTED_SQLITE_DRIVERS = {None, '', 'pysqlite'}
SUPPORTED_POSTGRESQL_DRIVERS = {'psycopg'}


@dataclass(frozen=True)
class DatabaseTarget:
    dialect: str
    driver: str | None
    is_sqlite: bool
    is_postgresql: bool
    safe_display: str


def _driver_name(url: URL) -> str | None:
    return url.drivername.split('+', 1)[1] if '+' in url.drivername else None


def _safe_display(url: URL, dialect: str) -> str:
    query = {key: '<redacted>' for key in url.query}
    if dialect == SQLITE:
        database = url.database or ''
        if database == ':memory:':
            return 'sqlite:///:memory:'
        if database and (Path(database).is_absolute() or '/' in database or '\\' in database):
            database = '<redacted-path>'
        return url.set(database=database, query=query).render_as_string(hide_password=True)
    return url.set(query=query).render_as_string(hide_password=True)


def classify_database_url(database_url: str) -> DatabaseTarget:
    try:
        url = make_url(str(database_url))
    except Exception as exc:
        raise ValueError('BM Radio database URL is invalid') from exc
    backend = url.get_backend_name().lower()
    dialect = backend if backend in {SQLITE, POSTGRESQL} else UNSUPPORTED
    driver = _driver_name(url)
    return DatabaseTarget(
        dialect=dialect,
        driver=driver,
        is_sqlite=dialect == SQLITE,
        is_postgresql=dialect == POSTGRESQL,
        safe_display=_safe_display(url, dialect),
    )


def require_supported_database_url(database_url: str) -> DatabaseTarget:
    target = classify_database_url(database_url)
    if target.dialect == UNSUPPORTED:
        raise ValueError(f'unsupported BM Radio database dialect: {target.safe_display}')
    if target.is_sqlite and target.driver not in SUPPORTED_SQLITE_DRIVERS:
        raise ValueError(f'unsupported SQLite driver: {target.driver}')
    if target.is_postgresql and target.driver not in SUPPORTED_POSTGRESQL_DRIVERS:
        raise ValueError('PostgreSQL URLs must use the postgresql+psycopg driver')
    return target


def engine_options(database_url: str) -> dict[str, Any]:
    target = require_supported_database_url(database_url)
    if target.is_sqlite:
        return {'connect_args': {'check_same_thread': False}}
    return {
        'connect_args': {'connect_timeout': 5},
        'pool_pre_ping': True,
    }


def require_sqlite_path(path: str | Path) -> Path:
    raw = str(path)
    if raw.lower().replace(chr(92), '/').startswith(('postgresql:', 'postgresql+')):
        raise ValueError('SQLite utility requires a local SQLite path, not a PostgreSQL target')
    if '://' in raw:
        target = classify_database_url(raw)
        if not target.is_sqlite:
            raise ValueError('SQLite utility requires a local SQLite path, not a database URL')
        raise ValueError('SQLite utility requires a filesystem path, not a SQLite URL')
    return Path(path)
