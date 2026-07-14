# BM-PROD1.2B API Exposure and Runtime Safety

Owner: Bonny Makaniankhondo
Project: BM Radio Production Upgrade
Date: 2026-07-14
Scope: API documentation exposure, CORS runtime policy, and fail-closed private runtime flags

## Baseline

| Item | Value |
| --- | --- |
| Starting commit | `aba629754834edd71cdc2233a31690b1a72b88ca` |
| Starting worktree | Clean |
| Ending state | Pending working-tree changes |

Pre-change gate result:

```text
python scripts/check_prod0_baseline.py
PASS when rerun outside the Windows sandbox Vite spawn restriction
11 mandatory passed, 0 failed, 4 integration checks skipped
```

## API Documentation Exposure

`BM_RADIO_API_DOCS_ENABLED` defaults to `false` in application settings and `backend/.env.example`.

Default FastAPI documentation endpoints are disabled:

```text
/docs
/redoc
/openapi.json
```

Explicit opt-in restores the normal endpoints:

```text
BM_RADIO_API_DOCS_ENABLED=true
```

## CORS Runtime Policy

FastAPI CORS setup now comes from the resolved production settings instead of a wildcard middleware block.

Allowed origins are exactly `settings.BM_RADIO_CORS_ORIGINS`.

Rejected origin configuration includes:

```text
*
null
empty origin entries
origins containing wildcard characters
non-http/non-https schemes
origins without hosts
origins with paths, queries, or fragments
```

Accepted origins are explicit `http` or `https` origins, including local development origins and Tailscale-style names such as:

```text
http://127.0.0.1:5174
http://localhost:5174
https://example-name.ts.net
```

Credentialed browser CORS is disabled:

```text
allow_credentials=False
```

Allowed methods are explicit:

```text
GET
POST
PUT
PATCH
DELETE
OPTIONS
```

Allowed headers are explicit:

```text
Accept
Authorization
Content-Type
Range
```

## Runtime Fail-Closed Flags

Startup/runtime safety validation fails closed if any of these private-read-only invariants are violated:

```text
PUBLIC_ACCESS=true
ALLOW_FILE_MUTATION=true
ALLOW_DELETE=true
ALLOW_TAG_WRITES=true
SCAN_INGEST_FOLDERS=true
```

`BM_RADIO_API_HOST=0.0.0.0` is allowed by itself so the API can bind inside a private container or private network. Public exposure remains a deployment and reverse-proxy decision for later work.

## Centralized Policy

Runtime exposure policy is centralized in:

```text
personal-radio/backend/app/runtime_security.py
```

It owns:

```text
fastapi_docs_config(settings)
configure_cors(app, settings)
validate_runtime_safety(settings)
```

`app/main.py` validates runtime safety before startup database side effects, then applies the FastAPI docs and CORS helpers before routes are included.

## Files Changed

```text
personal-radio/backend/app/config.py
personal-radio/backend/app/main.py
personal-radio/backend/app/runtime_security.py
personal-radio/backend/.env.example
personal-radio/backend/scripts/check_prod1_2a_config_contract.py
personal-radio/backend/scripts/check_prod1_2b_runtime_safety.py
personal-radio/scripts/check_prod0_baseline.py
personal-radio/docs/production-upgrade/BM-PROD1.2B_API_Exposure_and_Runtime_Safety.md
```

## Tests Run

| Command | Result | Notes |
| --- | --- | --- |
| `python scripts/check_prod0_baseline.py` | PASS before implementation | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 11 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python scripts/check_prod1_2b_runtime_safety.py` | PASS | Proves docs default-off, docs opt-in, configured CORS origins, rejected wildcard/malformed origins, credential policy, explicit methods/headers, unsafe flag failures, and private `0.0.0.0` bind allowance. |
| `cd backend; python scripts/check_prod1_2a_config_contract.py` | PASS | BM-PROD1.2A configuration contract preserved. |
| `cd backend; python scripts/check_prod1_1_canonical_music_roots.py` | PASS | BM-PROD1.1 canonical music roots preserved. |
| `cd backend; python scripts/check_aa_manifest_audiobook_import.py` | PASS | Audiobook manifest import preserved. |
| `cd backend; python scripts/check_audiobook_multibook_ordering.py` | PASS | Audiobook ordering preserved. |
| `cd backend; python scripts/check_audiobook_progress_reset.py` | PASS | Audiobook progress reset preserved. |
| `python scripts/check_prod0_baseline.py` | PASS | Required escalation for known Windows sandbox/Vite `spawn EPERM`; 12 mandatory passed, 0 failed, 4 skipped. |
| `cd backend; python -m compileall app scripts` | PASS | Backend app and scripts compiled. |
| `cd frontend; npm run build` | PASS | TypeScript and Vite production build completed. |
| `cd frontend; npm run lint` | PASS | 0 errors, 8 existing baseline warnings. |

## Explicit Non-Goals

BM-PROD1.2B does not add authentication.

BM-PROD1.2B does not make public-exposure or reverse-proxy deployment decisions.

BM-PROD1.2B does not migrate the database to PostgreSQL.

BM-PROD1.2B does not implement scan-run reconciliation.

BM-PROD1.2B does not add media-file mutation, deletion, tag writes, or ingest-folder scanning.