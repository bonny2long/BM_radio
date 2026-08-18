# BM-PROD6C.2 Real Media Playback Startup and Transition Latency Hardening

Status: **MEDIA-LATENCY PASS**

## Phase identity and safety boundary

- Starting SHA: `9d7309a8c78ad5383631d37665c608b996b8ae44`.
- Ending SHA: `9d7309a8c78ad5383631d37665c608b996b8ae44` plus the reviewed, uncommitted PROD6C.2 working-tree change described here.
- Fixture classification: `copied_test_media=true`, `generated_by_acceptance_script=false`, `original_only_copy=false`.
- Copied source inventory: 26 files. Final media inventory: 10 files.
- Protected preflight SHA-256: `5fcaf1261e0dd11e5f342a77ed7ea656334c2cef8c9b547cb8cabf6a3e3728a3`.
- Media stayed read-only. No M4B was copied into an image or named volume, remuxed, transcoded, rewritten, or fully downloaded by the application.

## Music baseline and post-fix

| Measurement | Baseline | Post-fix | Gate |
| --- | ---: | ---: | ---: |
| Cold playing | 505.9 ms | 858.8 ms | <= 3,000 ms |
| Transition median | 396.8 ms | 582.8 ms | informational |
| Transition p95 | 711.6 ms | 902.3 ms | <= 2,000 ms |
| Transition maximum | 711.6 ms | 902.3 ms | informational |

Music remained comfortably inside its existing acceptance boundary.

## M4B structure and static delivery

- Size: 287,550,571 bytes.
- Top-level order: `ftyp`, `moov`, `mdat`.
- `moov` size: 3,525,334 bytes at offset 24.
- `moov` before `mdat`: yes.
- Dominant sample tables: `stsz` with 807,532 entries and `stco` with 67,295 entries.

All first, middle, and final 256 KiB probes returned exact `206` ranges:

| Origin/range | First byte | Total |
| --- | ---: | ---: |
| Backend first | 24.752 ms | 32.674 ms |
| Backend middle | 39.122 ms | 46.623 ms |
| Backend end | 39.951 ms | 47.737 ms |
| Frontend first | 22.734 ms | 30.131 ms |
| Frontend middle | 24.354 ms | 30.521 ms |
| Frontend end | 22.868 ms | 29.556 ms |

The complete `moov` range took 173.501 ms through the backend at 19.378 MiB/s and 120.153 ms through the frontend at 27.981 MiB/s. The first 4 MiB took 149.366 ms at 26.780 MiB/s through the backend and 127.528 ms at 31.366 MiB/s through the frontend. These final measurements were taken after the long PROD0 run, under slower host conditions than the diagnosis. Raw static range throughput was still far too fast to explain the original 35-second delay.

## Browser diagnosis

Before the fix, Chromium requested 116 open-ended ranges before metadata. It began with `bytes=0-`, advanced through the file in roughly 2.4-2.5 MiB steps, and finally returned to `bytes=3506176-`. The largest request gap was 559.045 ms. Initial `loadedmetadata` was 34,681.4 ms and initial playing was 34,971.8 ms; resume and seek were already fast at 31.4 ms and 29.1 ms.

The same unchanged read-only M4B and the same 116-request pattern reached playing in about 1.1-1.3 seconds through a minimal Windows-host loopback range server. Attachment and inline disposition produced equivalent results. Connection tracing then showed that Chromium normally cancels the open-ended responses and creates replacement connections; Docker Desktop's published-port path made those repeated canceled-response/connection cycles expensive even though individual explicit ranges were fast.

## Root cause and production correction

The M4B is valid and already fast-start shaped, but its large sample tables cause Chromium to probe many positions before first playback. BM Radio previously answered every `bytes=N-` request through the entire remaining representation. Chromium consumed a small portion, canceled it, and repeated that process through Docker Desktop networking. The accumulated canceled-response and replacement-connection overhead caused the delay.

The production correction is deliberately bounded:

- Backend ownership, availability, file existence, media type, and approved-root checks remain mandatory.
- A two-second, 128-entry cache stores immutable path, size, media type, disposition, and internal-redirect metadata only after database ownership, availability, file existence, media type, and approved-root checks pass. The read-only file is still opened for every bounded response, and all authorization/path metadata is refreshed when the entry expires.
- Explicit and multipart ranges retain Nginx's native internal, read-only `X-Accel-Redirect` delivery.
- Open-ended audiobook ranges return a standards-compliant requested subset: 4 MiB for `bytes=0-` so the complete `moov` is available, then 64 KiB for later probes. Explicit and multipart ranges remain `FileResponse`-backed so direct-backend and frontend origins both retain exact 206 behavior.
- Completed bounded responses allow connection reuse and avoid unnecessary bind-mount I/O. The final trace reused 131 responses across only five connections and observed about 11.7 MB before metadata instead of treating each request as the rest of the 287.6 MB file.
- Music delivery and `Content-Disposition` were not changed.

Rejected experiments are preserved in the evidence trail. A larger backend streaming chunk worsened startup to about 103 seconds. Internal Nginx offload alone improved startup to about 29.8 seconds; offload plus `sendfile` and the authorization cache improved it to about 19.7 seconds. A 1 MiB bounded response passed narrowly at 4.81 seconds. The evidence-based 256 KiB bound produced the accepted margin.

## Post-fix browser acceptance

| Measurement | Result | Gate |
| --- | ---: | ---: |
| Initial `loadedmetadata` | 2,518.2 ms | <= 5,000 ms |
| Initial playing | 2,547.0 ms | <= 5,000 ms |
| Resume to playing | 26.8 ms | <= 5,000 ms |
| Seek completion | 29.2 ms | <= 3,000 ms |

There were 117 requests before metadata, 11,738,178 encoded bytes observed before metadata, and a 292.690 ms largest request gap. The later preload work continued after first playing and did not delay audible startup.

## Metadata tools and comparison controls

- `ffprobe`: unavailable on both the workstation and the existing BM Radio container image; no tool was downloaded and no production image was mutated.
- Read-only fallback: `mutagen.mp4.MP4`, 1.395 ms parse time, duration 68,909.397 seconds.
- ffprobe streams/chapters: unavailable for that reason.
- Minimal attachment: metadata 1,444.0 ms; playing 1,529.9 ms.
- Minimal inline: metadata 1,671.6 ms; playing 1,832.6 ms.
- Content-Disposition decision: attachment was retained because inline did not explain the original delay.
- Second copied M4B: unavailable; result `not_applicable`.

## Safety and operator acceptance

- Database pool: **PASS** with 18 concurrent unconsumed range streams and no exhaustion.
- Copied-media hash/size/mtime equality: **PASS**.
- Final-media hash/size/mtime equality: **PASS**.
- Protected-state equality: **PASS**.
- Manual operator: **PASS**. Bonny confirmed that both the book and music were fast and playback was basically seamless.

## Permanent validation

The first full PROD0 run found a direct-call compatibility regression caused by making `Request` mandatory; the route was corrected to retain FastAPI injection while allowing historical direct policy calls. That policy contract then passed.

Final-source results:

- Python compileall: PASS.
- BM-PROD6C contract: PASS, 41 checks.
- BM-PROD6B contract: PASS, 52 checks.
- BM-PROD6A contract: PASS, 40 checks.
- Frontend production build: PASS.
- Frontend lint: PASS with zero errors and eight existing warnings.
- Full PROD0: **61 passed, 0 failed, 4 skipped**.
- `git diff --check`: PASS.
- Final copied-media, final-media, and protected-state equality: PASS.
- Disposable cleanup: PASS; zero task containers, networks, or volumes remain.

## Final result

**BM-PROD6C.2 MEDIA-LATENCY PASS**

PROD6D was not started.
