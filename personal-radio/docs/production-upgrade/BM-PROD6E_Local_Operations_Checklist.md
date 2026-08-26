# BM-PROD6E Local Operations Checklist

This checklist covers the current Windows/local-Docker BM Radio deployment. It deliberately contains no TrueNAS commands. Keep passwords and machine-specific paths in an ignored local environment/Compose override, never in Git.

## Start PostgreSQL dependency

1. Start Docker Desktop and wait for the engine to become ready.
2. Start the protected adopted database: `docker start bm-radio-postgres-dev`.
3. Require `docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' bm-radio-postgres-dev` to report `running healthy`.
4. Do not remove `bm-radio-postgres-dev` or `bm-radio-postgres-dev-data`; they contain the adopted local database.

## Start production-style BM Radio

1. From the `personal-radio` directory, prepare an ignored local environment file with `BM_RADIO_POSTGRES_PASSWORD`, `BM_RADIO_POSTGRES_DB`, `BM_RADIO_POSTGRES_USER`, and `BM_RADIO_WEB_PORT`.
2. Prepare an ignored Compose override that bind-mounts the local `Music`, `Audiobooks/Library`, and `Books` directories to the paths in `deploy/compose.local-production.example.yml`, all with `:ro`. Never point a scanner at `_INGEST`, `_STAGING`, or `_QUARANTINE`.
3. Build the reviewed images when needed: `docker build --platform linux/amd64 --tag bm-radio-backend:local --file backend/Dockerfile backend` and `docker build --platform linux/amd64 --build-arg VITE_API_BASE_URL=/api --tag bm-radio-frontend:local --file frontend/Dockerfile frontend`.
4. Update only the ignored local override to select those local tags, then start: `docker compose --env-file .local-production.env -f deploy/compose.local-production.example.yml -f deploy/compose.local-production.override.yml up -d`.

## Verify readiness and open the frontend

1. Run `docker compose --env-file .local-production.env -f deploy/compose.local-production.example.yml -f deploy/compose.local-production.override.yml ps` and require PostgreSQL, backend, and frontend to be healthy.
2. Run `Invoke-RestMethod http://127.0.0.1:8080/api/health` (substitute the configured loopback port) and require `status=ok` and `database=ready`.
3. Open `http://127.0.0.1:8080` in Google Chrome. The VS Code embedded Electron browser is not an M4B codec acceptance target.

## Read logs

- Follow all services with `docker compose --env-file .local-production.env -f deploy/compose.local-production.example.yml -f deploy/compose.local-production.override.yml logs --follow --tail 200`.
- Inspect one service by appending `backend`, `frontend`, or `postgres`.
- Stop and investigate repeating tracebacks, unexpected 5xx responses, credential text, tokens, raw environment dumps, or personal absolute paths.

## Run library scans

- Music: `Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/library/scan/music`.
- Audiobooks: `Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/audiobooks/scan`.
- Require a succeeded scan status with no errors. A scan must preserve stable identities, playlist/favorite/progress state, and the read-only media trees.

## Take a logical backup

1. From `backend`, activate `.venv` if needed.
2. Run `python scripts/manage_postgres_backup.py preflight`.
3. Run `python scripts/manage_postgres_backup.py backup`.
4. Keep the produced archive and manifest together under the configured durable backup root. Verify them with `python scripts/manage_postgres_backup.py verify` before relying on the copy.

## Stop, restart, and recover

- Normal app stop: `docker compose --env-file .local-production.env -f deploy/compose.local-production.example.yml -f deploy/compose.local-production.override.yml stop frontend backend`.
- Normal full-stack stop: use the same command with `stop`; do not use `down --volumes` against the protected database.
- Restart after a normal local reboot: start Docker Desktop, run `docker start bm-radio-postgres-dev`, wait for healthy, then run the production-style `docker compose ... up -d` command above.
- Verify `/api/health`, play one music track and one M4B in Chrome, and confirm playlist, favorite, and audiobook progress survived.
- If the database does not become healthy, stop application containers, retain the volume, inspect logs, and follow the reviewed BM-PROD5.5B cold-recovery procedure. Never initialize a replacement over the protected volume.

## Shutdown safety check

- Confirm no `bm-prod6e-*` disposable resources remain after an acceptance run.
- Confirm copied source, final media, `backend/.env`, SQLite fallback, backup/recovery evidence, and the protected PostgreSQL volume were not changed by cleanup.
- Do not publish images and do not begin TrueNAS deployment from this checklist.
