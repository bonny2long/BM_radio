# BM Radio Migrations

Alembic is the schema authority for BM Radio databases. Application startup validates migration readiness and schema compatibility, but it never creates tables, adds columns, stamps, upgrades, downgrades, or repairs schemas.

Every migration command requires an explicit database URL. The application must reject databases that are uninitialized, unversioned, behind, unknown, unreachable, or drifted.

## Fresh Database

```powershell
python -m alembic -x db_url=<EXPLICIT_DATABASE_URL> upgrade head
python scripts/migration_status.py check --db-url <EXPLICIT_DATABASE_URL>
python scripts/database_readiness.py --db-url <EXPLICIT_DATABASE_URL>
```

## Compatible Unversioned Database

First run the read-only compatibility verifier:

```powershell
python scripts/check_migration_schema_compatibility.py --db-url <EXPLICIT_DATABASE_URL>
```

Only after it passes, perform the explicit reviewed adoption step:

```powershell
python -m alembic -x db_url=<EXPLICIT_DATABASE_URL> stamp 0001_current_schema_baseline
python scripts/migration_status.py check --db-url <EXPLICIT_DATABASE_URL>
python scripts/database_readiness.py --db-url <EXPLICIT_DATABASE_URL>
```

## Versioned Database Behind Head

```powershell
python -m alembic -x db_url=<EXPLICIT_DATABASE_URL> upgrade head
python scripts/migration_status.py check --db-url <EXPLICIT_DATABASE_URL>
```

Do not run adoption, stamp, upgrade, or downgrade commands against the real local `bm_radio.db` unless that has been separately reviewed and approved.
