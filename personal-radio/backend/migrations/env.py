from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path
import sys

from alembic import context
from sqlalchemy import create_engine, pool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import models  # noqa: E402
from app.database_dialect import engine_options, require_supported_database_url  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models.Base.metadata


def _explicit_database_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    db_url = x_args.get('db_url') or os.environ.get('BM_RADIO_DB_URL')
    if not db_url:
        raise RuntimeError('Alembic requires an explicit database URL via -x db_url=... or BM_RADIO_DB_URL')
    require_supported_database_url(db_url)
    return db_url


def run_migrations_offline() -> None:
    url = _explicit_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _explicit_database_url()
    connectable = create_engine(url, poolclass=pool.NullPool, **engine_options(url))
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
