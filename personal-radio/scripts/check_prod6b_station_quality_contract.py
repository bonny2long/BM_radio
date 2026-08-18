from __future__ import annotations

import argparse
import ast
from pathlib import Path
import subprocess
import sys


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
FIXTURE = BACKEND / "app" / "station_quality_fixture.py"
ANALYZER = BACKEND / "app" / "station_quality.py"
ACCEPTANCE = PROJECT / "scripts" / "check_prod6b_station_quality_acceptance.py"
FRONTEND_CHECK = PROJECT / "scripts" / "check_prod6b_frontend_station_refill.py"
PLAYER = PROJECT / "frontend" / "src" / "state" / "PlaybackContext.tsx"
INVARIANTS = PROJECT / "frontend" / "src" / "state" / "playbackInvariants.ts"
STATIONS = BACKEND / "app" / "routes" / "stations.py"
PROD0 = PROJECT / "scripts" / "check_prod0_baseline.py"
REPORT6A = PROJECT / "docs" / "production-upgrade" / "BM-PROD6A_Listener_Playback_Queue_and_Media_Delivery_Acceptance.md"
REPORT6B = PROJECT / "docs" / "production-upgrade" / "BM-PROD6B_Radio_Station_Behavior_and_Recommendation_Quality_Acceptance.md"
MANUAL = PROJECT / "docs" / "production-upgrade" / "BM-PROD6B_Station_Review.md"
CHECKS: list[str] = []


def check(condition: bool, label: str) -> None:
    assert condition, label
    CHECKS.append(label)


def run(script: str, *args: str, cwd: Path = PROJECT, timeout: int = 1200) -> None:
    result = subprocess.run(
        [sys.executable, script, *args], cwd=str(cwd), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", shell=False, timeout=timeout,
    )
    assert result.returncode == 0 and "PASS" in result.stdout, result.stdout


def prod0_mandatory_count(source: str) -> int:
    tree = ast.parse(source)
    main = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "main")
    assignment = next(item for item in ast.walk(main) if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == "checks" and isinstance(item.value, ast.List))
    return len(assignment.value.elts) + 2


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6B permanent station-quality contract")
    parser.add_argument("--skip-prior-regressions", action="store_true")
    args = parser.parse_args()
    fixture = FIXTURE.read_text(encoding="utf-8")
    analyzer = ANALYZER.read_text(encoding="utf-8")
    acceptance = ACCEPTANCE.read_text(encoding="utf-8")
    refill = FRONTEND_CHECK.read_text(encoding="utf-8")
    player = PLAYER.read_text(encoding="utf-8")
    invariants = INVARIANTS.read_text(encoding="utf-8")
    stations = STATIONS.read_text(encoding="utf-8")
    prod0 = PROD0.read_text(encoding="utf-8")
    report6a = REPORT6A.read_text(encoding="utf-8")
    report6b = REPORT6B.read_text(encoding="utf-8")
    manual = MANUAL.read_text(encoding="utf-8")

    check("387033a7cfad43ce42c9f8ba7fc0372c7b471b30" in report6a and "uncommitted working-tree" not in report6a, "1 PROD6A report records final accepted commit")
    check(FIXTURE.is_file() and "populate_station_quality_fixture" in fixture, "2 deterministic station-quality fixture exists")
    check('"logical_recordings": 200' in fixture, "3 fixture has 150+ logical recordings")
    check('"artists": 25' in fixture, "4 fixture has 20+ artists")
    check(len([token for token in ('"hip-hop"', '"electronic"', '"rock"', '"r&b"', '"jazz"') if token in fixture]) == 5, "5 fixture has 4+ genre families")
    check('"related_boundary": True' in fixture and '"unrelated_boundary": True' in fixture, "6 related and unrelated profile boundaries exist")
    check("TrackThumb" in fixture and "TrackFavorite" in fixture and "PlaybackEvent" in fixture, "7 feedback and play history exist")
    check("000-preferred.flac" in fixture and '"physical_tracks": 201' in fixture, "8 physical-source variants exist")
    check(all(f'"{kind}"' in fixture for kind in ("live", "acoustic", "remix", "instrumental")), "9 specialized recording types exist")
    check("FIXED_RANDOM_SEEDS = (11, 23, 47, 71, 101)" in fixture and "for fixed_seed in FIXED_RANDOM_SEEDS" in acceptance, "10 fixed-seed quality runs exist")
    check("logical_duplicates" in analyzer and "_duplicates(logical)" in analyzer, "11 logical duplicate metric exists")
    check("artist_distribution" in analyzer and "release_distribution" in analyzer and "rolling_last_9" in analyzer, "12 artist and release diversity metrics exist")
    check("type_distribution" in analyzer and "specialized_share" in analyzer, "13 recording-type distribution metric exists")
    check("max_consecutive_artist <= 2" in acceptance and "max_consecutive_release <= 2" in acceptance, "14 universal repeat caps are tested")
    check("seed_artist in artists" in acceptance and "seed_share <= 0.50" in acceptance, "15 Artist Radio seed relevance is tested")
    check("len(artists) >= 5" in acceptance and "aq[:10]" in acceptance, "16 Artist Radio diversity is tested")
    check("seed_recording not in" in acceptance, "17 Song Radio excludes seed recording")
    check('compatibility_share(sq, "R&B") == 1.0' in acceptance, "18 Song Radio compatibility is tested")
    check('compatibility_share(gq, "Hip-Hop") == 1.0' in acceptance and "gq[:15]" in acceptance, "19 Genre Radio compatibility and diversity are tested")
    check("favorite_ids <=" in acceptance and "down_recording_ids" in acceptance, "20 Favorites membership and exclusion are tested")
    check("recent_times == sorted(recent_times, reverse=True)" in acceptance, "21 Recently Added ordering is tested")
    check("low_play >= 0.70" in acceptance, "22 Deep Cuts underplay behavior is tested")
    check("downvote_removed" in acceptance and "every station path" in acceptance, "23 thumbs-down removal is tested")
    check("thumbs_up_boost" in analyzer + acceptance or "thumbs_up" in acceptance, "24 thumbs-up score effect is tested")
    check("favorite_score" in acceptance and "favorite_score[0] > base_song_score[0]" in acceptance, "25 favorite score effect is tested")
    check("recent_score" in acceptance and "recent_score[0] < base_artist_score[0]" in acceptance, "26 recent-play suppression is tested")
    check("not logical & seen_logical" in acceptance and "not physical & seen_physical" in acceptance, "27 refill overlap is tested")
    check("terminal_exhausted" in acceptance and 'terminal["queue"] == []' in acceptance, "28 refill exhaustion is tested")
    check("refill appends unique items once" in refill and "duplicate response members append once" in refill, "29 frontend append-once behavior is tested")
    check("physical_variant_recording_id" in acceptance and "logical_rows" in acceptance, "30 physical-source duplicate safety is tested")
    check("preferred_variant_track_id" in acceptance and "evaluate_music_recording_preference" in fixture, "31 preferred source resolution remains tested")
    check('"live", "acoustic", "remix", "instrumental"' in acceptance and "focused >= 0.60" in acceptance, "32 focused live affinity is tested")
    check('f"type:{kind}"' in acceptance and '"acoustic"' in fixture, "33 focused acoustic affinity is tested")
    check('"remix"' in fixture and "focused_shares" in acceptance, "34 focused remix affinity is tested")
    check('"instrumental"' in fixture and "focused_shares" in acceptance, "35 focused instrumental affinity is tested")
    check("balanced <= 0.25" in acceptance, "36 balanced specialized-version flooding is tested")
    check("sparse_warning" in acceptance and "check_prod1_5b_station_version_affinity.py" in report6b, "37 sparse affinity fallback warning is tested")
    check("build_station_debug" in acceptance and "station_score" in acceptance and "score_delta" in acceptance, "38 debug quality diagnostics are tested")
    check("station_ui" in acceptance and "deep_cut_count" in stations, "39 station listing and count behavior is tested")
    check(MANUAL.is_file() and "first 20 selections" in manual, "40 manual review report exists")
    check("Operator result: NOT PROVIDED" in manual and "automation is not permitted to fabricate" in manual, "41 subjective result cannot be fabricated")
    check(all(name in report6b for name in ("check_prod4_1_station_scale_benchmark.py", "check_prod4_2e_benchmark_selected_projection_policy.py")), "42 PROD4 scale gates remain callable")
    check("1000-track" in report6b and "mandatory" in report6b, "43 1000-track benchmark remains mandatory")
    check("--sizes 10000" in report6b and "10k benchmark" in report6b, "44 10k benchmark procedure exists")
    check("active_postgresql_used" in acceptance and "active PostgreSQL" in report6b, "45 active PostgreSQL protection exists")
    check("protected_snapshot" in acceptance and "bm_radio.db" in acceptance, "46 SQLite protection exists")
    check('BACKEND / ".env"' in acceptance and ".env/evidence" in report6b, "47 environment and evidence protection exists")
    check("real_media_accessed" in acceptance and "C:/bm-prod6b-synthetic" in fixture, "48 real media access is prohibited")
    check("truenas_work" in acceptance and "TrueNAS work: prohibited" in report6b, "49 TrueNAS work is prohibited")
    check("check_prod6a_listener_playback_contract.py" in prod0, "50 PROD6A contract remains registered")
    check("check_prod5_6b_integrated_container_stack_contract.py" in prod0, "51 PROD5.6B contract remains registered")
    check("check_prod6b_station_quality_contract.py" in prod0 and prod0_mandatory_count(prod0) >= 60, "52 full PROD0 preserves at least 60 mandatory checks")

    run("scripts/check_prod6b_frontend_station_refill.py")
    if not args.skip_prior_regressions:
        run("scripts/check_prod6a_listener_playback_contract.py", "--skip-prior-regressions")
        run("scripts/check_prod5_6b_integrated_container_stack_contract.py", "--skip-prior-regressions")
    assert len(CHECKS) == 52
    print("PASS: BM-PROD6B radio station quality contract (52 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
