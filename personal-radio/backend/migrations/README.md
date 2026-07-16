# BM Radio Alembic Migrations

BM-PROD5.3A introduces Alembic as a deterministic schema migration framework while preserving the current runtime startup DDL behavior.

Migration commands must use an explicit database URL:

```powershell
python -m alembic -x db_url=sqlite:///tmp_tests/migrations/example.db upgrade head
```

Allowed URL sources, in order:

1. `-x db_url=...`
2. `BM_RADIO_DB_URL`

Running Alembic without one of those explicit sources fails before connecting. Do not run migrations, stamping, or downgrades against `bm_radio.db` unless a later production phase explicitly authorizes it.
