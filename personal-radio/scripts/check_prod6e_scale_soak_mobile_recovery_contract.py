from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
DOCS = PROJECT / "docs" / "production-upgrade"
REPORT6E1 = DOCS / "BM-PROD6E.1_PostgreSQL_10K_Station_Profile_and_Candidate_Budget_Optimization.md"
REPORT6E = DOCS / "BM-PROD6E_Whole_App_Scale_Soak_Mobile_Recovery_and_Operational_Readiness.md"
OPERATIONS = DOCS / "BM-PROD6E_Local_Operations_Checklist.md"
REPORT6A = DOCS / "BM-PROD6A_Listener_Playback_Queue_and_Media_Delivery_Acceptance.md"
REPORT6B = DOCS / "BM-PROD6B_Radio_Station_Behavior_and_Recommendation_Quality_Acceptance.md"
REPORT6C = DOCS / "BM-PROD6C_Local_NAS_Pipeline_Library_Playlist_Feedback_and_Preferred_Source_UX_Acceptance.md"
REPORT6D = DOCS / "BM-PROD6D_Audiobook_Listener_Progress_Resume_Chapter_and_Long_Session_Acceptance.md"
LIVE = PROJECT / "scripts" / "check_prod6e_whole_app_soak_acceptance.py"
PRIOR_LIVE = PROJECT / "scripts" / "check_prod6d_audiobook_listener_acceptance.py"
BENCHMARK = BACKEND / "scripts" / "benchmark_prod6e2_postgres_listener_api_scale.py"
STATION_ENGINE = BACKEND / "app" / "station_engine.py"
STATION_CANDIDATES = BACKEND / "app" / "station_candidates.py"
PROFILES = BACKEND / "app" / "radio_profiles.py"
LATENCY = PROJECT / "scripts" / "check_prod6c_2_media_latency_acceptance.py"
BACKEND_DOCKERFILE = BACKEND / "Dockerfile"
FRONTEND_DOCKERFILE = PROJECT / "frontend" / "Dockerfile"
COMPOSE = PROJECT / "deploy" / "compose.local-production.example.yml"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
CHECKS: list[str] = []


def check(condition: bool, label: str) -> None:
    assert condition, label
    CHECKS.append(label)


def run(command: list[str], cwd: Path, timeout: int = 1800) -> None:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=timeout,
    )
    assert result.returncode == 0 and "PASS" in result.stdout, result.stdout


def prod0_mandatory_count(source: str) -> int:
    tree = ast.parse(source)
    main = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main")
    assignment = next(
        item
        for item in ast.walk(main)
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and item.target.id == "checks"
        and isinstance(item.value, ast.List)
    )
    return len(assignment.value.elts) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6E permanent whole-app readiness contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    args = parser.parse_args()

    report6e1 = REPORT6E1.read_text(encoding="utf-8")
    report6e = REPORT6E.read_text(encoding="utf-8")
    operations = OPERATIONS.read_text(encoding="utf-8")
    live = LIVE.read_text(encoding="utf-8")
    prior_live = PRIOR_LIVE.read_text(encoding="utf-8")
    benchmark = BENCHMARK.read_text(encoding="utf-8")
    station_engine = STATION_ENGINE.read_text(encoding="utf-8")
    station_candidates = STATION_CANDIDATES.read_text(encoding="utf-8")
    profiles = PROFILES.read_text(encoding="utf-8")
    latency = LATENCY.read_text(encoding="utf-8")
    backend_dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    frontend_dockerfile = FRONTEND_DOCKERFILE.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")
    prior_reports = {
        "PROD6A": REPORT6A.read_text(encoding="utf-8"),
        "PROD6B": REPORT6B.read_text(encoding="utf-8"),
        "PROD6C": REPORT6C.read_text(encoding="utf-8"),
        "PROD6D": REPORT6D.read_text(encoding="utf-8"),
    }

    check(all(sha in report6e1 for sha in ("0189dbaa8caf5f5a2a3ac6a140d19887b4dd507e", "fa384a007cadd80d3195035e6d01f5b2bf29fdfb")), "1 PROD6E.1 report records implementation and report commits")
    check("production acceptance source is a task-scoped PostgreSQL 16" in report6e1 and "PostgreSQL 16 is the production station-performance acceptance source" in report6e, "2 PostgreSQL remains the station-performance acceptance source")
    check("budget = max(500, requested_limit * 10)" in station_engine and "normal 50-track request uses 500 candidates" in report6e, "3 normal candidate budget 500 remains")
    check("MAX_STATION_CANDIDATE_POOL = 5000" in station_candidates and "hard ceiling remains 5,000" in report6e, "4 candidate ceiling 5000 remains")
    check("load_radio_profile_cache_for_tracks" in profiles and all(token in profiles for token in ("requested_candidate_tracks", "requested_artist_keys", "requested_album_keys")), "5 candidate-scoped profile loading remains")
    check(all(token in profiles for token in ("ArtistRadioProfile.artist).in_(chunk)", "AlbumRadioProfile.artist).in_(artist_chunk)", "TrackRadioProfile.track_id.in_(chunk)")) and "do not load full profile tables" in report6e, "6 full listener-path profile-table loads remain prohibited")
    check(all(token in prior_live for token in ('"copied_test_media": True', '"generated_by_acceptance_script": False', '"original_only_copy": False')) and "real copied media cannot be synthesized" in prior_live and "COPIED_SOURCE_MEDIA_SUFFIXES" in live, "7 real-media-only live acceptance remains")
    check("DEFAULT_OUTPUT" in benchmark and "physical-tracks" in benchmark and "10k_api_acceptance" in benchmark and "10,000-physical-track benchmark" in report6e, "8 10k library API benchmark exists")
    check("search.global" in benchmark and "Search | 333.823 ms" in report6e, "9 search benchmark exists")
    check("--smoke-only" in benchmark and "larger_scale_smoke" in benchmark and "50,000 physical tracks" in report6e, "10 larger-scale smoke exists")
    check("AUTOMATED_DURATION_MINUTES = 60" in live and "Duration: 60 minutes; PASS" in report6e, "11 60-minute soak exists")
    check("TELEMETRY_INTERVAL_SECONDS = 60" in live and "_resource_sample" in live and "Resource trend: bounded" in report6e, "12 resource telemetry exists")
    check("BROWSER_MUSIC_DURATION_MINUTES = 30" in live and "Duration: 30 minutes in real Google Chrome" in report6e, "13 30-minute browser music soak exists")
    check("def _two_client_proof" in live and "Two clients: PASS" in report6e, "14 two-client concurrency exists")
    check("(360, 800)" in live and "360x800: PASS" in report6e, "15 360 viewport coverage exists")
    check("(390, 844)" in live and "390x844: PASS" in report6e, "16 390 viewport coverage exists")
    check("(768, 1024)" in live and "768x1024: PASS" in report6e, "17 768 viewport coverage exists")
    check("(1366, 900)" in live and "Desktop 1366+: PASS" in report6e, "18 desktop coverage exists")
    check("player overlap" in live.casefold() and "Player overlap controls: PASS" in report6e, "19 player overlap controls are covered")
    check("source-action sheet" in live and "Source-action sheet mobile behavior: PASS" in report6e, "20 source-action sheet mobile coverage exists")
    check("audiobook seek/speed" in live and "Audiobook mobile progress, seek, and speed controls: PASS" in report6e, "21 audiobook mobile controls are covered")
    check("restart_results[\"frontend\"]" in prior_live and "Frontend restart: PASS" in report6e, "22 frontend restart recovery is covered")
    check("restart_results[\"backend\"]" in prior_live and "Backend restart: PASS" in report6e, "23 backend restart recovery is covered")
    check("restart_results[\"postgres\"]" in prior_live and "PostgreSQL restart: PASS" in report6e, "24 PostgreSQL restart recovery is covered")
    check("def _whole_stack_recovery" in live and "Whole-stack restart: PASS" in report6e, "25 whole-stack recovery is covered")
    check("def _bounded_outage" in live and "Temporary outage: PASS" in report6e, "26 temporary outage recovery is covered")
    check("def _rescan_during_use" in live and "Music rescan during use: PASS" in report6e and "Audiobook rescan during use: PASS" in report6e, "27 rescan-during-use is covered")
    check("def _state_assertions" in live and all(token in live for token in ("playlist", "favorite", "latest_progress")) and "State preservation: playlist, favorite, and audiobook progress all PASS" in report6e, "28 playlist favorite and progress preservation is covered")
    check("def _log_privacy_audit" in live and "Log/privacy audit: PASS" in report6e, "29 log/privacy audit exists")
    check("backend image regression: pass" in report6e.casefold() and "USER 10001:10001" in backend_dockerfile, "30 backend image regression exists")
    check("frontend image regression: pass" in report6e.casefold() and "USER 101:101" in frontend_dockerfile, "31 frontend image regression exists")
    check("read_only: true" in compose and "read_only_root" in live and all(token in compose for token in ('user: "10001:10001"', 'user: "101:101"')), "32 non-root and read-only policies remain")
    check("latency._browser_probe" in live and all(token in live for token in ("music_cold_le_3000ms", "music_transition_p95_le_2000ms", "m4b_initial_le_5000ms", "m4b_seek_le_3000ms")), "33 real-media latency regression exists")
    check("check_prod6d_audiobook_listener_contract.py" in prod0 and "audiobook progress rows: 1 authoritative row" in report6e.casefold(), "34 audiobook progress regression exists")
    check("def _pool_proof" in latency and "count: int = 18" in latency and "database_pool_exhausted" in latency and "18 concurrent unconsumed range streams" in report6e, "35 open-stream DB-pool regression exists")
    check("source_equal" in live and "final_equal" in live and "Copied source and final media equality: PASS" in report6e, "36 copied-media equality is required")
    check("_protected_state" in live and "Active PostgreSQL" in report6e, "37 active PostgreSQL protection is required")
    check("SQLite fallback" in report6e and "protected_state" in benchmark, "38 SQLite fallback protection is required")
    check("`.env`, and durable evidence protection: PASS" in report6e and "protected_equal" in live, "39 environment and durable evidence protection is required")
    check("'truenas_work': False" in live and "no truenas commands" in operations.casefold() and "TrueNAS work: none" in report6e, "40 no TrueNAS work is performed")
    check("PASS" in prior_reports["PROD6D"] and "check_prod6d_audiobook_listener_contract.py" in prod0 and "PROD6D: PASS" in report6e, "41 PROD6D remains passing")
    check("PASS" in prior_reports["PROD6C"] and "check_prod6c_library_source_ux_contract.py" in prod0 and "PROD6C: PASS" in report6e, "42 PROD6C remains passing")
    check("PASS" in prior_reports["PROD6B"] and "check_prod6b_station_quality_contract.py" in prod0 and "PROD6B: PASS" in report6e, "43 PROD6B remains passing")
    check("PASS" in prior_reports["PROD6A"] and "check_prod6a_listener_playback_contract.py" in prod0 and "PROD6A: PASS" in report6e, "44 PROD6A remains passing")
    check("check_prod6e_scale_soak_mobile_recovery_contract.py" in prod0 and "check_prod6e_whole_app_soak_acceptance.py" not in prod0 and prod0_mandatory_count(prod0) == 63 and "63 passed / 0 failed / 4 skipped" in report6e, "45 full PROD0 remains required at 63 mandatory checks")

    if not args.skip_prior_regressions:
        for script in (
            "check_prod6d_audiobook_listener_contract.py",
            "check_prod6c_library_source_ux_contract.py",
            "check_prod6b_station_quality_contract.py",
            "check_prod6a_listener_playback_contract.py",
        ):
            run([sys.executable, f"scripts/{script}", "--skip-prior-regressions"], PROJECT)

    assert len(CHECKS) == 45
    print("PASS: BM-PROD6E scale soak mobile recovery contract (45 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
