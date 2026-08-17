# BM-PROD5.6B — Production Frontend Image and Integrated Local Stack Proof

Date: 2026-08-17  
Owner: Bonny Makaniankhondo  
Status: **INTEGRATED-STACK PASS**

## Phase identity

- Starting SHA: `18775bea08d19ea84bd87364c1bbacf206c7b746`
- Ending SHA / accepted implementation commit: `100d81e730ad24b58ec294a73e3bec061024cb0d`.
- BM-PROD5.6A implementation documentation correction: PASS; the 5.6A report now records implementation commit `18775bea08d19ea84bd87364c1bbacf206c7b746`.

## Frontend API and proxy audit

- `frontend/src/api.ts` now defaults to the relative same-origin base `/api`.
- `VITE_API_BASE_URL=/api` is explicit in the production image build and sanitized environment example.
- Vite has a development-only `/api` proxy to the loopback backend, preserving local development without placing a loopback backend address in the production browser bundle.
- Backend route inspection confirmed that all API routes are under `/api`.
- All current music/audiobook `cover_url` and `stream_url` values use `/api/media/*`; no separate artwork or stream prefix exists.
- Nginx proxies the complete `/api/*` URI to private service `backend:8094` before SPA handling. API/media 404s cannot fall through to `index.html`.

## Frontend production image

- Tag: `bm-radio-frontend:prod5.6b-18775be`
- Image ID: `sha256:5b815aef357de4f2cec2f619e0d77cd88f63707a662a52cfe6958c858e416754`
- Size: `20,926,402` bytes
- OS/architecture: `linux/amd64`
- Runtime user: `101:101`
- Dockerfile SHA-256: `c1ec5e041058e8b1951e08211c78347337c284ee61d1f4178bb4c42cd88cf603`
- Build stage: `node:22.14.0-alpine3.21`
- Resolved Node tag digest: `sha256:9bef0ef1e268f60627da9ba7d7605e8831d5b56ad07487d24d1aa386336d1944`
- Runtime stage: `nginxinc/nginx-unprivileged:1.27.4-alpine`
- Resolved Nginx tag digest: `sha256:62a904036bfc0e4a4f2b556e34cbf17bc136b47fde8cdb4628762725f48c5782`
- Production server: non-root Nginx; no Vite, Vite preview, or Node server at runtime.
- Production API base: `/api`
- Static artifact paths inspected: 9
- Filesystem inspection: PASS; no `node_modules`, `.env`, Git metadata, database, dump, backup, media, backend secret, personal path, or local state.
- Bundle inspection: PASS; no `127.0.0.1:8094`, credential URL, or personal path.
- Image history inspection: PASS.
- Published remotely: **NO**

## Static server policies

- `GET /healthz`: 200 from Nginx.
- SPA fallback: PASS for an unknown frontend route.
- `/api/*`: private backend reverse proxy; excluded from SPA fallback.
- Index cache: `no-cache, must-revalidate`.
- Hashed asset cache: long-lived immutable.
- Security headers: `X-Content-Type-Options: nosniff`, strict origin referrer policy, `X-Frame-Options: DENY`, and a tested same-origin CSP with `frame-ancestors 'none'`.
- HSTS: not enabled for the local HTTP proof.
- Traversal patterns and dot-file paths: explicitly rejected.

## Generic local production template

`deploy/compose.local-production.example.yml` documents:

- private PostgreSQL 16 with a persistent-volume placeholder and externally supplied password;
- accepted backend image on private port 8094, non-root/read-only, writable tmp/cache, and read-only media;
- frontend image as the only host-published service, bound to loopback;
- a private bridge network;
- no real secret, personal Windows path, TrueNAS target, or Docker socket mount.

This is an example local-production template, not a TrueNAS deployment file.

## Integrated network topology

```text
HTTP client
  -> 127.0.0.1:dynamic
  -> frontend:8080
  -> backend:8094 (private network only)
  -> postgres:5432 (private network only)
```

- User-defined bridge: PASS.
- Frontend only host publication: PASS, loopback-only dynamic port.
- Backend host publication: none.
- PostgreSQL host publication: none.
- Host networking: none.
- Privileged containers: none.
- Docker socket mounts: none.

## Runtime hardening

- Frontend non-root/read-only root: PASS, `101:101`, `/tmp` tmpfs.
- Backend non-root/read-only root: PASS, `10001:10001`, `/tmp` tmpfs.
- Backend writable cache: task-scoped `/app-cache`.
- Synthetic Music, Audiobooks, and Books roots: empty and read-only.
- Source-code bind mount: none.
- Real `.env` mount: none.
- Real media mount/access: none.
- Scanner invocation: none.

## Disposable PostgreSQL restore

- Image/version: `postgres:16`, PostgreSQL `16.15`.
- Storage: task-prefixed disposable volume, removed during cleanup.
- Restore input: retained verified custom-format backup.
- Revision: `0001_current_schema_baseline`, at head and ready.
- Application tables: 21.
- Application rows: 1,257.
- Per-table counts: exact accepted-manifest equality.
- Per-table canonical digests: exact accepted-manifest equality.
- Backend startup row/digest delta: zero.
- Active `bm-radio-postgres-dev` target used by stack: **NO**.

## Frontend-origin acceptance

All requests below used the frontend loopback origin; none bypassed the reverse proxy:

- `/`: PASS, production index.
- Built JS, CSS, and SVG assets: PASS with immutable cache policy.
- Unknown SPA route: PASS, returned the production index.
- `/healthz`: PASS.
- `/api/health`: PASS, `database_ready=true`, production environment.
- Library summary: PASS.
- Artists: PASS.
- Albums/releases: PASS.
- Search: PASS.
- Playlists: PASS.
- Stations: PASS.
- Recording controls: PASS.
- Audiobooks: PASS.
- Backend API docs: disabled; proxied `/api/docs` returned 404.

## Media and artwork routing proof

- Representative track cover URL: same-origin `/api/media/tracks/47/cover`.
- Representative track stream URL: same-origin `/api/media/tracks/47/stream`.
- Both requests traversed the frontend proxy and returned controlled backend JSON 404 responses because the task mounted empty synthetic media.
- Neither request returned the SPA index.
- No real file was opened or streamed.

## Reversible proxied write canary

- Create temporary playlist through frontend origin: PASS.
- Verify temporary playlist through frontend origin: PASS.
- Delete temporary playlist through frontend origin: PASS.
- Final rows: exactly 1,257.
- Original per-table counts restored: PASS.
- Original canonical digests restored: PASS.

## Restart and operations proof

- Frontend restart: PASS; loopback binding was re-read, `/healthz` returned, and proxied API recovered.
- Backend restart: PASS; frontend static content remained available and proxied API recovered.
- PostgreSQL restart: PASS; backend query routing recovered, with rows/counts/digests exact.
- Ordered full-stack restart: PASS.
  1. Stopped frontend, backend, PostgreSQL.
  2. Started PostgreSQL and waited healthy.
  3. Started backend and waited healthy.
  4. Started frontend and waited for host-origin health/API.
- Final database rows/counts/digests after all restarts: exact.
- Non-root, read-only, network, mount, and publication policies after restart: unchanged.

## Network and security negatives

- Backend direct host exposure: absent.
- PostgreSQL direct host exposure: absent.
- `/.env`: 404.
- `/.git/config`: 404.
- `/backend/.env`: 404.
- Encoded traversal requests: 400.
- Secret paths did not fall into SPA fallback.
- No filesystem content was exposed.
- Frontend image bundle contained no production backend loopback URL.

## Protected active state and cleanup

- Active PostgreSQL revision/counts/digests: exact before/after equality.
- SQLite bytes/schema/revision/counts/digests: exact before/after equality.
- Backend `.env`: exact SHA before/after equality.
- State, transfer, adoption, backup, recovery rehearsal, and `backend_env.before` evidence: exact SHA before/after equality.
- Remaining `bm-prod5-6b-*` containers: none.
- Remaining `bm-prod5-6b-*` networks: none.
- Remaining `bm-prod5-6b-*` volumes: none.
- Temporary credentials, synthetic roots, cache, and task state: removed.
- Local backend/frontend images retained: YES, permitted.

## Validation

- Python compile (`backend/app`, `backend/scripts`, `backend/migrations`, root scripts): PASS.
- BM-PROD5.6B preflight: PASS.
- BM-PROD5.6B live build/run: INTEGRATED-STACK PASS.
- BM-PROD5.6B contract: PASS, 34 checks.
- BM-PROD5.6A contract: PASS, 61 checks.
- BM-PROD5.5B contract: PASS, 57 checks.
- PROD0: PASS — 58 mandatory passed, 0 failed, 4 skipped.
- Frontend production build: PASS.
- Frontend lint: PASS — 0 errors, 8 existing warnings.
- `git diff --check`: PASS.
- Final Git status at acceptance: clean after commit `100d81e730ad24b58ec294a73e3bec061024cb0d`.

## Next action

BM-PROD5.6B is accepted and BM-PROD5.6 is closed. Begin BM Radio application-production acceptance as a separate reviewed phase.

**STOP: BM-PROD5.6B INTEGRATED-STACK PASS. No TrueNAS deployment, registry push, real-media mount/scan, or application-production acceptance work was performed.**
