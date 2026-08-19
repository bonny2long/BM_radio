from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
LIVE = PROJECT / "scripts" / "check_prod6c_library_source_ux_acceptance.py"
CHECKLIST = PROJECT / "docs" / "production-upgrade" / "BM-PROD6C_Local_NAS_Pipeline_Operator_Checklist.md"
REPORT6B = PROJECT / "docs" / "production-upgrade" / "BM-PROD6B_Radio_Station_Behavior_and_Recommendation_Quality_Acceptance.md"
REPORT6C = PROJECT / "docs" / "production-upgrade" / "BM-PROD6C_Local_NAS_Pipeline_Library_Playlist_Feedback_and_Preferred_Source_UX_Acceptance.md"
API = PROJECT / "frontend" / "src" / "api.ts"
SHEET = PROJECT / "frontend" / "src" / "components" / "TrackActionSheet.tsx"
PROD6A_LIVE = PROJECT / "scripts" / "check_prod6a_listener_playback_acceptance.py"
LATENCY_LIVE = PROJECT / "scripts" / "check_prod6c_2_media_latency_acceptance.py"
MEDIA_ROUTES = PROJECT / "backend" / "app" / "routes" / "media.py"
NGINX = PROJECT / "frontend" / "nginx.conf"
COMPOSE = PROJECT / "deploy" / "compose.local-production.example.yml"
AA_MUSIC = PROJECT / "backend" / "scripts" / "check_aa_manifest_music_import.py"
AA_AUDIOBOOK = PROJECT / "backend" / "scripts" / "check_aa_manifest_audiobook_import.py"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
CHECKS: list[str] = []


def check(condition: bool, label: str) -> None:
    assert condition, label
    CHECKS.append(label)


def run(script: str, *args: str, timeout: int = 1800) -> None:
    result = subprocess.run(
        [sys.executable, script, *args], cwd=str(PROJECT), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", shell=False, timeout=timeout,
    )
    assert result.returncode == 0 and "PASS" in result.stdout, result.stdout


def prod0_mandatory_count(source: str) -> int:
    tree = ast.parse(source)
    main = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main")
    assignment = next(
        item for item in ast.walk(main)
        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
        and item.target.id == "checks" and isinstance(item.value, ast.List)
    )
    return len(assignment.value.elts) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6C permanent local-library/source UX contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    args = parser.parse_args()
    live = LIVE.read_text(encoding="utf-8")
    checklist = CHECKLIST.read_text(encoding="utf-8")
    report6b = REPORT6B.read_text(encoding="utf-8")
    report6c = REPORT6C.read_text(encoding="utf-8")
    api = API.read_text(encoding="utf-8")
    sheet = SHEET.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")
    prod6a_live = PROD6A_LIVE.read_text(encoding="utf-8")
    latency_live = LATENCY_LIVE.read_text(encoding="utf-8")
    media_routes = MEDIA_ROUTES.read_text(encoding="utf-8")
    nginx = NGINX.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    aa_music = AA_MUSIC.read_text(encoding="utf-8")
    aa_audiobook = AA_AUDIOBOOK.read_text(encoding="utf-8")
    combined = "\n".join((live, checklist, report6c, api, sheet))

    check("5e3b2be2e5163c37297881dd9d1fcd33d55bd129" in report6b and "remain uncommitted" not in report6b, "1 PROD6B report records accepted implementation commit")
    check(all(token in checklist for token in ("BM Radio remains PostgreSQL", "Archive Assistant remains SQLite", "lightweight filesystem/report")), "2 database architecture lock documented")
    check("NAS_LOCAL_ROOT" in live and "NAS_LOCAL_ROOT" in checklist and "def nas_root" in live, "3 local NAS root is configurable")
    check(not re.search(r"[A-Za-z]:\\\\Users\\\\", combined) and "BonnyMakaniankhondo" not in combined, "4 no personal absolute path or username committed")
    check("PROD6C_COPIED_MEDIA_SOURCE" in live and "_source_snapshot" in live and "copied source" in checklist, "5 copied source fixture protection exists")
    check(all(token in checklist for token in ("not promoted early", "no metadata edits", "no final-library writes", "no deletion")), "6 Intake acceptance checklist exists")
    check(all(token in checklist for token in ("normal scan", "Review metadata", "Explicitly approve", "approved task batch moves")), "7 AA classification review approval and move checklist exists")
    check("Never reset Archive Assistant" in checklist and "Do not use a reset" in checklist, "8 AA reset is prohibited")
    check("Cleaner is report/dry-run only" in checklist and "deletion is prohibited" in checklist, "9 Cleaner deletion is prohibited")
    check('POSTGRES_IMAGE = "postgres:16"' in live and "Alembic upgrade head" in live, "10 isolated PostgreSQL 16 and Alembic head are required")
    check("active target used" not in live.casefold() or '"active_target_used": False' in live, "11 active PostgreSQL scan is prohibited")
    check(all(token in live for token in ("target=/media/Music,readonly", "target=/media/Audiobooks/Library,readonly", "target=/media/Books,readonly")), "12 final media is read-only to BM Radio")
    check("movies_tv_excluded" in live and "Movies and TV are excluded" in checklist, "13 Movies and TV are excluded from BM Radio")
    latency_readiness = all(token in latency_live for token in (
        'target_url = f"http://127.0.0.1:{web_port}/?bm_latency_acceptance=1"',
        'item.get("url") == "about:blank"', 'cdp.call("Page.enable", {})', 'cdp.call("Runtime.enable", {})',
        'cdp.call("Network.enable", {})', '_browser_network_trace(',
        'cdp.call("Page.navigate", {"url": target_url})', '_wait_for_browser_ready(cdp, target_url)',
        'probe.get("readyState") in {"interactive", "complete"}', 'probe.get("control") is True',
        'error.code == -32000', '"execution context was destroyed" in error.message.casefold()',
        'if not _is_pre_measurement_context_race(exc):\n                raise',
        '"status": "PARTIAL; BROWSER MEASUREMENT PENDING; NOT A PASS"', '"partial": True',
        '"full_metadata_ranges": full_metadata_ranges', '"m4b_atom_inventory": _atom_inventory(m4b)',
        '"ffprobe": ffprobe', 'minimal_comparison = _minimal_server_comparison(m4b)', '"minimal_range_server": minimal_comparison',
        '"read_only_source": True', '"attachment": attachment', '"inline": inline',
    )) and latency_live.index('_wait_for_browser_ready(cdp, target_url)') < latency_live.index('"awaitPromise": True')
    audiobook_delivery = all(token in media_routes for token in (
        "AUDIOBOOK_ACCEL_PREFIX = '/__bm_audiobooks/'", "accel_prefix: str | None = None",
        "'X-Accel-Redirect': accel_prefix + quote(relative, safe='/')", "accel_redirect=AUDIOBOOK_ACCEL_PREFIX + quote(relative, safe='/')",
        "AUDIOBOOK_AUTH_CACHE_TTL_SECONDS = 2.0", "AUDIOBOOK_AUTH_CACHE_MAX_ENTRIES = 128",
        "AUDIOBOOK_OPEN_RANGE_INITIAL_BYTES = 4 * 1024 * 1024", "AUDIOBOOK_OPEN_RANGE_BYTES = 64 * 1024",
        "OPEN_ENDED_BYTE_RANGE.fullmatch", "safe_audiobook_file(cached_metadata, request)", "safe_audiobook_file(metadata, request)",
        "'Content-Range': f'bytes {start}-{end}/{metadata.size}'", "'Accept-Ranges': 'bytes'",
        "cached_audiobook_file_metadata(audiobook_id, chapter_id)", "cache_audiobook_file_metadata(audiobook_id, chapter_id, metadata)",
        "validated_audiobook_file_metadata(chapter.path)", "with metadata.path.open('rb') as stream",
        "path.is_file()", "is_approved_path(path, [root])", "resolved.relative_to(root.resolve())", "filename=path.name",
    )) and all(token in nginx for token in (
        "location ^~ /__bm_audiobooks/", "internal;", "alias /media/Audiobooks/Library/;", "sendfile on;",
    )) and "bm-radio-audiobooks:/media/Audiobooks/Library:ro" in compose and all(
        "target=/media/Audiobooks/Library,readonly" in source for source in (latency_live, live, prod6a_live)
    ) and "content_disposition_type=" not in media_routes
    check('"/api/library/scan/music"' in live and '"/api/audiobooks/scan"' in live and "real_scanners" in live and "concurrent_unconsumed_range_streams" in live and "database_pool_exhausted" in live and latency_readiness and audiobook_delivery, "14 real scanners, media-session release, synchronized latency harness, and bounded audiobook delivery are required")
    check(all(token in live for token in ("recording_id", "effective_track_id", "physical_occurrences", "logical_recordings")), "15 logical and physical identity checks exist")
    check(all(token in live for token in ("listener library exposes", "duplicate logical album", "song search", "album tracks")), "16 listener search and album duplicate checks exist")
    check("unique lossless source" in live and "lossless_vs_lossy" in live, "17 lossless versus lossy preferred source check exists")
    check("single-source fallback" in live and "single_source_fallback" in live, "18 single-source fallback exists")
    check("manual preferred-source override" in live and "unset override" in live, "19 override and unset checks exist")
    check("one song" in sheet and "physical" in sheet and "Source details" in sheet, "20 listener source UX stays one logical song")
    check(all(token in live for token in ("favorite", "unfavorite", "thumbs_up", "thumbs_down")), "21 favorite and thumb UX checks exist")
    check("feedback refresh persistence" in live and "refresh_persistence" in live, "22 refresh persistence exists")
    check("feedback was lost across source switch" in live and "recording_level_across_source" in live, "23 feedback remains recording-level across source change")
    check("later thumbs-down" in live and "scoring bridge" in live and "up_favorite_score_delta" in live, "24 feedback-to-radio causal bridge exists")
    check(all(token in live for token in ("from-track-list", "tracks/reorder", "playlist rename", "playlist remove", "playlist first/middle")), "25 playlist end-to-end acceptance exists")
    check("queue_source_continuity" in live and "source override corrupted logical album queue identity" in live, "26 queue/source continuity exists")
    check("artwork = \"not_applicable\"" in live and "artwork = \"PASS\"" in live, "27 artwork acceptance and not-applicable handling exist")
    check("Human real-library review" in checklist and "human_checklist" in live, "28 human library review exists")
    check("automation cannot fabricate" in live and '"automated": False' in live and "Automation did not fabricate" in report6c, "29 human result cannot be fabricated")
    check("Rerun Intake" in checklist and "no duplicate promoted fixture" in checklist, "30 Intake rerun duplicate check exists")
    check("Rescan/restart Archive Assistant" in checklist and "no duplicate final media" in checklist, "31 AA rescan duplicate check exists")
    check("BM Radio rescan changed" in live and "logical_equal" in live and "physical_equal" in live, "32 BM Radio rescan duplicate check exists")
    check("_source_snapshot(copied_source) != source_before" in live and "source_hashes_equal" in live, "33 source fixture hash equality is required")
    check("active PostgreSQL" in live and "protected_after != protected_before" in live, "34 active PostgreSQL is protected")
    check("SQLite" in live and "protected_after != protected_before" in live, "35 SQLite fallback is protected")
    check(".env/durable evidence" in live and "protected_before_sha256" in live, "36 environment and durable evidence are protected")
    check("$NAS_LOCAL_ROOT/" in live and '"nas_root": "$NAS_LOCAL_ROOT"' in live, "37 evidence privacy guard exists")
    check('"truenas_work": False' in live and "TrueNAS work" in checklist, "38 TrueNAS work is prohibited")
    prohibited = ("not real audio", "wave.open", "math.sin", "Acceptance Tone", "_write_fixture")
    applicable = "\n".join((live, prod6a_live, aa_music, aa_audiobook))
    check(not any(token in applicable for token in prohibited) and ".write_bytes(" not in aa_music and ".write_bytes(" not in aa_audiobook and all(token in live for token in ('"copied_test_media": True', '"generated_by_acceptance_script": False', '"original_only_copy": False')), "39 fake/generated live media is prohibited and copied-real classification is enforced")
    check("check_prod6b_station_quality_contract.py" in prod0 and "check_prod6a_listener_playback_contract.py" in prod0, "40 PROD6B and PROD6A contracts remain registered")
    check("check_prod6c_library_source_ux_contract.py" in prod0 and prod0_mandatory_count(prod0) >= 61, "41 full PROD0 preserves the non-live 6C contract and at least 61 mandatory checks")

    if not args.skip_prior_regressions:
        run("scripts/check_prod6b_station_quality_contract.py", "--skip-prior-regressions")
        run("scripts/check_prod6a_listener_playback_contract.py", "--skip-prior-regressions")
    assert len(CHECKS) == 41
    print("PASS: BM-PROD6C local NAS library/source UX contract (41 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
