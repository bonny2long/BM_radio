from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
FRONTEND = PROJECT / "frontend"
LIVE = PROJECT / "scripts" / "check_prod6a_listener_playback_acceptance.py"
PLAYER_REGRESSION = PROJECT / "scripts" / "check_prod6a_player_state_regressions.py"
PLAYER = FRONTEND / "src" / "state" / "PlaybackContext.tsx"
INVARIANTS = FRONTEND / "src" / "state" / "playbackInvariants.ts"
NOW_PLAYING = FRONTEND / "src" / "pages" / "NowPlayingPage.tsx"
QUEUE_PAGE = FRONTEND / "src" / "pages" / "QueuePage.tsx"
MEDIA_ROUTE = BACKEND / "app" / "routes" / "media.py"
PLAYBACK_POLICY = BACKEND / "app" / "music_playback_policy.py"
REPORT_5_6B = PROJECT / "docs" / "production-upgrade" / "BM-PROD5.6B_Production_Frontend_Image_and_Integrated_Local_Stack_Proof.md"
REPORT_6A = PROJECT / "docs" / "production-upgrade" / "BM-PROD6A_Listener_Playback_Queue_and_Media_Delivery_Acceptance.md"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
CHECKS: list[str] = []


def check(condition: bool, label: str) -> None:
    assert condition, label
    CHECKS.append(label)


def run_prior(script: str, *arguments: str, cwd: Path = PROJECT, timeout: int = 1200) -> None:
    result = subprocess.run(
        [sys.executable, script, *arguments],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )
    assert result.returncode == 0 and "PASS" in result.stdout, result.stdout


def prod0_mandatory_count(source: str) -> int:
    tree = ast.parse(source)
    main = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main")
    assignment = next(
        item for item in ast.walk(main)
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and item.target.id == "checks"
        and isinstance(item.value, ast.List)
    )
    return len(assignment.value.elts) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6A permanent listener-playback contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    arguments = parser.parse_args()

    live = LIVE.read_text(encoding="utf-8")
    player = PLAYER.read_text(encoding="utf-8")
    invariants = INVARIANTS.read_text(encoding="utf-8")
    now_playing = NOW_PLAYING.read_text(encoding="utf-8")
    queue_page = QUEUE_PAGE.read_text(encoding="utf-8")
    media_route = MEDIA_ROUTE.read_text(encoding="utf-8")
    playback_policy = PLAYBACK_POLICY.read_text(encoding="utf-8")
    report_5_6b = REPORT_5_6B.read_text(encoding="utf-8")
    report_6a = REPORT_6A.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")

    check("100d81e730ad24b58ec294a73e3bec061024cb0d" in report_5_6b and "intentional uncommitted working-tree changes" not in report_5_6b, "1 5.6B report records accepted implementation commit")
    check(LIVE.is_file() and all(token in live for token in ("--preflight-only", "--run-automated", "--manual-url", "--cleanup")), "2 live 6A acceptance script exists with required modes")
    check(all(token in live for token in ("PROD6C_COPIED_MEDIA_SOURCE", '"copied_test_media": True', '"generated_by_acceptance_script": False', '"original_only_copy": False')) and "_write_fixture" not in live, "3 copied-real-media guard and classification exist")
    check("media_after != media_before" in live and "media_hash_size_mtime_equal" in live, "4 source media mutation is prohibited")
    check('RESOURCE_PREFIX = "bm-prod6a-"' in live and 'POSTGRES_IMAGE = "postgres:16"' in live and "active_target_used\": False" in live, "5 disposable PostgreSQL 16 is used")
    check('BACKEND_IMAGE = "bm-radio-backend:prod5.6a-bc444f3"' in live and 'FRONTEND_DOCKERFILE = FRONTEND / "Dockerfile"' in live, "6 accepted production backend/frontend contracts are used")
    check('"/api/library/scan/music", method="POST"' in live and '"real_scanner": True' in live, "7 real scanner path is used")
    check(all(token in live for token in ("target=/media/Music,readonly", "target=/media/Audiobooks/Library,readonly", "target=/media/Books,readonly", 'item.get("RW") is not False')), "8 all media mounts are read-only")
    check("full media stream" in live and 'full_status != 200' in live and 'content-length' in live and media_route.count('Depends(get_db, scope="function")') == 4 and all(token in media_route for token in ("resolve_audiobook_file_metadata", "with SessionLocal() as db", "await run_in_threadpool(resolve_audiobook_file_metadata")), "9 full stream regression exists and DB sessions close before file streaming")
    check('"Range": "bytes=0-127"' in live and "range_status != 206" in live and "content-range" in live, "10 byte-range regression exists")
    check("invalid_status != 416" in live and "invalid range" in live, "11 invalid-range behavior is tested")
    check("missing_path" in live and "missing-file response" in live and "restored copied fixture" in live, "12 missing-file behavior is tested and restored")
    check("path_disclosure\": False" in live and 'str(source.parent).lower() in decoded.lower()' in live, "13 filesystem-path disclosure is prohibited")
    check("itemRef = useRef<NowPlaying | null>(null)" in player and "one logical current item" in report_6a, "14 single-current-item invariant is documented and tested")
    check("shouldAdvanceForEnded" in player and "duplicate ended event cannot advance twice" in PLAYER_REGRESSION.read_text(encoding="utf-8"), "15 ended advances exactly once")
    check("nextQueueIndex" in player and "next advances exactly once" in PLAYER_REGRESSION.read_text(encoding="utf-8"), "16 next advances exactly once")
    check("previousQueueIndex" in player and "previous uses prior queue item" in PLAYER_REGRESSION.read_text(encoding="utf-8"), "17 previous semantics are explicitly tested")
    check("Unable to play this file" in player and "no automatic retry or queue loop" in live, "18 failed media cannot infinite-loop")
    check("playlist_projected_items" in live or "logical queue identity" in report_6a, "19 logical queue identity is preserved")
    check("validate_music_playback_context" in media_route and "PARTICIPATION_BLOCKED" in playback_policy and "Recording is blocked from playback" in playback_policy, "20 blocked recording playback is prohibited")
    check("playEventForIdentity" in player and "pause/resume is not a duplicate start" in PLAYER_REGRESSION.read_text(encoding="utf-8") and "event_types.count(\"start\") != 1" in live, "21 history duplicate protection exists")
    check('f"/api/search?q={quote(str(track[' in live and "search_to_play" in live, "22 search-to-play acceptance exists")
    check('"/api/queue/album"' in live and "album_to_play" in live and "album first track" in live, "23 album-to-play acceptance exists")
    check(all(token in live for token in ("/api/playlists/from-track-list", "/api/queue/playlist", "/tracks/reorder", "playlist middle item", "playlist remove")), "24 playlist playback/order acceptance exists")
    check("source_selection\": \"not_applicable" in live and "no alternate physical sources" in live, "25 source-selection proof has explicit not-applicable handling")
    check('"stop", api_name' in live and '"start", api_name' in live and "frontend did not stay available" in live, "26 backend restart acceptance exists")
    check('"restart", db_name' in live and "playback did not recover after restarts" in live and "schema_repair_after_restart\": False" in live, "27 PostgreSQL restart acceptance exists")
    check(all(token in live for token in ("audio is audible", "pause actually pauses", "seek forward", "volume control", "natural track end", "Previous")), "28 manual audible play/pause/seek checklist exists")
    check("automated\": False" in live and "an operator-supplied note is required" in live and "manual_result\": None" in live, "29 automated code cannot fabricate the manual result")
    check(all(token in live for token in ("narrow mobile viewport", "player, queue, search", "album-to-play")), "30 mobile listener checklist exists")
    check(all(token in live for token in ("accessible names", "keyboard focus", "keyboard activation", "disabled states")) and 'aria-label="Playback volume"' in now_playing, "31 basic accessibility checklist and volume name exist")
    check("sha256" in live and "size" in live and "mtime_ns" in live and "media_after != media_before" in live, "32 before/after media equality is required")
    check("name.startswith(RESOURCE_PREFIX)" in live and "name != CONTAINER_NAME" in live and "volume != VOLUME_NAME" in live, "33 cleanup only targets task resources")
    check("active PostgreSQL" in live and "protected_after != protected_before" in live, "34 active PostgreSQL is protected")
    check("SQLite fallback" in live and "protected_after != protected_before" in live, "35 SQLite fallback is protected")
    check("environment, or evidence changed" in live and "protected_before_sha256" in live, "36 active environment and durable evidence are protected")
    check("station_quality\": \"deferred to BM-PROD6B" in live and "Station recommendation quality is deferred to BM-PROD6B" in report_6a, "37 station quality is explicitly deferred")
    check("truenas_work\": False" in live and "TrueNAS work: prohibited" in report_6a, "38 TrueNAS work is prohibited")
    check("check_prod5_6b_integrated_container_stack_contract.py" in prod0, "39 5.6B contract remains registered")
    check("check_prod6a_listener_playback_contract.py" in prod0 and "check_prod6b_station_quality_contract.py" in prod0 and prod0_mandatory_count(prod0) >= 60, "40 full PROD0 preserves at least 60 mandatory checks through PROD6B")

    run_prior("scripts/check_prod6a_player_state_regressions.py")
    if not arguments.skip_prior_regressions:
        run_prior("scripts/check_prod5_6b_integrated_container_stack_contract.py", "--skip-prior-regressions")

    assert len(CHECKS) == 40, len(CHECKS)
    print("PASS: BM-PROD6A listener playback contract (40 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
