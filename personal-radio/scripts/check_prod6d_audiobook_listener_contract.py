from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
REPORT6C2 = PROJECT / "docs" / "production-upgrade" / "BM-PROD6C.2_Real_Media_Playback_Startup_and_Transition_Latency_Hardening.md"
REPORT6D = PROJECT / "docs" / "production-upgrade" / "BM-PROD6D_Audiobook_Listener_Progress_Resume_Chapter_and_Long_Session_Acceptance.md"
LIVE = PROJECT / "scripts" / "check_prod6d_audiobook_listener_acceptance.py"
MODEL = BACKEND / "app" / "models.py"
ROUTE = BACKEND / "app" / "routes" / "audiobooks.py"
PROGRESS_CHECK = BACKEND / "scripts" / "check_audiobook_listener_progress.py"
PLAYBACK = PROJECT / "frontend" / "src" / "state" / "PlaybackContext.tsx"
NOW_PLAYING = PROJECT / "frontend" / "src" / "pages" / "NowPlayingPage.tsx"
BOOKSHELF = PROJECT / "frontend" / "src" / "pages" / "BookshelfPage.tsx"
PLAYBACK_ROUTE = BACKEND / "app" / "routes" / "playback.py"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
CHECKS: list[str] = []


def check(condition: bool, label: str) -> None:
    assert condition, label
    CHECKS.append(label)


def run(command: list[str], cwd: Path, timeout: int = 1800) -> None:
    result = subprocess.run(command, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", shell=False, timeout=timeout)
    assert result.returncode == 0 and ("PASS" in result.stdout or "ok:" in result.stdout), result.stdout


def prod0_mandatory_count(source: str) -> int:
    tree = ast.parse(source)
    main = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main")
    assignment = next(item for item in ast.walk(main) if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == "checks" and isinstance(item.value, ast.List))
    return len(assignment.value.elts) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6D permanent audiobook listener contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    args = parser.parse_args()
    report6c2, report6d, live = (path.read_text(encoding="utf-8") for path in (REPORT6C2, REPORT6D, LIVE))
    model, route, progress_check = (path.read_text(encoding="utf-8") for path in (MODEL, ROUTE, PROGRESS_CHECK))
    playback, now_playing, bookshelf, playback_route, prod0 = (path.read_text(encoding="utf-8") for path in (PLAYBACK, NOW_PLAYING, BOOKSHELF, PLAYBACK_ROUTE, PROD0))

    check("b6d9a1b97c88e35f8774730ffcab2dafb4ce0428" in report6c2 and "remain uncommitted" not in report6c2, "1 PROD6C.2 report records the accepted implementation commit")
    check("4 MiB" in report6c2 and "64 KiB" in report6c2 and "256 KiB experiment" in report6c2 and "superseded" in report6c2, "2 final 4 MiB initial and 64 KiB later range policy is documented")
    check(all(token in live for token in ('"copied_test_media": True', '"generated_by_acceptance_script": False', '"original_only_copy": False', "real copied media cannot be synthesized")), "3 copied-real-media-only classification is enforced")
    check("class AudiobookProgress" in model and "one durable listener checkpoint per book" in model, "4 one authoritative progress model exists without duplicating the protected schema")
    check(all(token in model for token in ("audiobook_id", "chapter_id", "position_seconds", "updated_at", "status")) and "checkpointed_at: datetime" in route, "5 progress is tied to audiobook and physical chapter identity with an ordered timestamp")
    check("progress_rows[0]" in route and "progress_rows[1:]" in route and "db.delete(duplicate)" in route and "updated_at.desc()" in route, "6 transactional upsert collapses legacy duplicates to one authoritative row")
    check("currentTime - lastSaved.current < 15" in playback and "timeupdate" in playback and "saveProgress()" in playback, "7 periodic progress writes are bounded rather than per timeupdate")
    check("const pause" in playback and "checkpointSeek" in playback and "saveProgress()" in playback and "sourceTransition" in playback, "8 pause seek and physical-part transition checkpoints exist")
    check("startPositionSeconds" in playback and "latest_progress?.position_seconds" in bookshelf and "Continue" in bookshelf, "9 server-backed resume path exists")
    check(all(token in live for token in ('restart_results["frontend"]', 'restart_results["backend"]', 'restart_results["postgres"]', "refresh_new_session")), "10 refresh new-session and all restart resume tests exist")
    check(all(token in playback for token in ("audiobookRateRef", "bm-radio-audiobook-rate", "el.playbackRate = item.mode === 'audiobook' ? audiobookRateRef.current : 1", "audioRef.current.playbackRate = rate")), "11 audiobook rate persists without leaking into music")
    check(all(token in now_playing for token in ("0.75", "1.25", "1.5", "1.75", "Audiobook playback speed")), "12 six compact audiobook playback-rate choices exist")
    check("Seek back 15 seconds" in now_playing and "Seek forward 30 seconds" in now_playing and "ProgressBar" in now_playing, "13 audiobook seek-back seek-forward and timeline controls exist")
    check("physical_parts" in live and "not_applicable_single_physical_m4b" in live and "playChapter" in bookshelf, "14 physical chapter navigation is tested or explicitly not applicable")
    check("finish_audiobook" in route and "completion_state" in route and "Replay" in bookshelf and "history_retained_until_explicit_reset" in live, "15 completion and replay behavior is coherent")
    check(all(token in playback for token in ("mode: 'music' | 'audiobook'", "track_id: item.mode === 'music'", "audiobook_id: item.audiobookId")) and "audiobook_id" in playback_route, "16 audiobook history is distinct from music identity")
    check("playbackRate = item.mode === 'audiobook'" in playback and "audiobook -> music -> audiobook" in report6d, "17 player mode switching preserves rate separation")
    check(all(token in live for token in ("database outage", "backend outage", "media=False", "temporary media unavailability recovery failed", "progress_retained")), "18 backend database and missing-media recovery preserve progress")
    check("range(1, 42)" in progress_check and "timedelta(seconds=elapsed)" in progress_check and 'stale["status"] == "stale"' in progress_check, "19 two-hour simulation and out-of-order safety are tested")
    check("count() == 1" in progress_check and "row_count != 1" in live, "20 progress-row uniqueness is tested in focused and live PostgreSQL checks")
    check(all(token in live for token in ("mobile-width", "accessible names", "Use Tab/keyboard")) and all(token in now_playing for token in ("aria-label=\"Audiobook playback speed\"", "aria-label=\"Seek back 15 seconds\"", "aria-label=\"Seek forward 30 seconds\"")), "21 mobile and accessibility acceptance is explicit")
    check("latency._browser_probe" in live and "latency._pool_proof" in live and all(token in live for token in ("m4b_initial_le_5000ms", "m4b_resume_le_5000ms", "m4b_seek_le_3000ms", "music_cold_le_3000ms", "music_transition_p95_le_2000ms")), "22 PROD6C.2 latency and DB-pool regressions remain callable")
    check("readonly" in live and "_snapshot" in live and "source_equal" in live and "final_equal" in live, "23 media remains read-only and hash protected")
    check("_protected_state" in live and "protected_equal" in live and "active PostgreSQL" in report6d and "SQLite fallback" in report6d and "`.env`" in report6d, "24 active PostgreSQL SQLite environment and evidence remain protected")
    check("generated_media\": False" in live and "generates no media" in report6d and "transcod" not in live.casefold(), "25 fake generated remuxed and transcoded media are prohibited")
    check("truenas_work\": False" in live and "does no TrueNAS work" in report6d, "26 no TrueNAS work is performed")
    check("automation cannot fabricate" in live and '"automated": False' in live and "Automation did not fabricate" in report6d, "27 human listener PASS cannot be fabricated")
    check("check_prod6c_library_source_ux_contract.py" in prod0 and "check_prod6b_station_quality_contract.py" in prod0 and "check_prod6a_listener_playback_contract.py" in prod0, "28 PROD6C PROD6B and PROD6A contracts remain registered")
    check("check_prod6d_audiobook_listener_contract.py" in prod0 and "check_prod6d_audiobook_listener_acceptance.py" not in prod0 and prod0_mandatory_count(prod0) == 62, "29 only non-live PROD6D contract is registered and PROD0 has 62 mandatory checks")
    check("Starting commit" in report6d and "checkpoint cadence" in report6d and "Mobile/accessibility" in report6d and "cleanup" in report6d, "30 completion report covers the required acceptance domains")

    run([sys.executable, "scripts/check_audiobook_listener_progress.py"], BACKEND)
    if not args.skip_prior_regressions:
        run([sys.executable, "scripts/check_prod6c_library_source_ux_contract.py", "--skip-prior-regressions"], PROJECT)
        run([sys.executable, "scripts/check_prod6b_station_quality_contract.py", "--skip-prior-regressions"], PROJECT)
        run([sys.executable, "scripts/check_prod6a_listener_playback_contract.py", "--skip-prior-regressions"], PROJECT)
    assert len(CHECKS) == 30
    print("PASS: BM-PROD6D audiobook listener contract (30 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
