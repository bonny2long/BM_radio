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
    combined = "\n".join((live, checklist, report6c, api, sheet))

    check("5e3b2be2e5163c37297881dd9d1fcd33d55bd129" in report6b and "remain uncommitted" not in report6b, "1 PROD6B report records accepted implementation commit")
    check(all(token in checklist for token in ("BM Radio remains PostgreSQL", "Archive Assistant remains SQLite", "lightweight filesystem/report")), "2 database architecture lock documented")
    check("NAS_LOCAL_ROOT" in live and "NAS_LOCAL_ROOT" in checklist and "def nas_root" in live, "3 local NAS root is configurable")
    check(not re.search(r"[A-Za-z]:\\\\Users\\\\", combined) and "BonnyMakaniankhondo" not in combined, "4 no personal absolute path or username committed")
    check("_TEST_FIXTURES" in live and "_source_snapshot" in live and "immutable source" in checklist, "5 copied source fixture protection exists")
    check(all(token in checklist for token in ("not promoted early", "no metadata edits", "no final-library writes", "no deletion")), "6 Intake acceptance checklist exists")
    check(all(token in checklist for token in ("normal scan", "Review metadata", "Explicitly approve", "approved task batch moves")), "7 AA classification review approval and move checklist exists")
    check("Never reset Archive Assistant" in checklist and "Do not use a reset" in checklist, "8 AA reset is prohibited")
    check("Cleaner is report/dry-run only" in checklist and "deletion is prohibited" in checklist, "9 Cleaner deletion is prohibited")
    check('POSTGRES_IMAGE = "postgres:16"' in live and "Alembic upgrade head" in live, "10 isolated PostgreSQL 16 and Alembic head are required")
    check("active target used" not in live.casefold() or '"active_target_used": False' in live, "11 active PostgreSQL scan is prohibited")
    check(all(token in live for token in ("target=/media/Music,readonly", "target=/media/Audiobooks/Library,readonly", "target=/media/Books,readonly")), "12 final media is read-only to BM Radio")
    check("movies_tv_excluded" in live and "Movies and TV are excluded" in checklist, "13 Movies and TV are excluded from BM Radio")
    check('"/api/library/scan/music"' in live and '"/api/audiobooks/scan"' in live and "real_scanners" in live, "14 real BM Radio scanners are required")
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
    check("automation cannot fabricate" in live and '"automated": False' in live and "NOT PROVIDED" in report6c, "29 human result cannot be fabricated")
    check("Rerun Intake" in checklist and "no duplicate promoted fixture" in checklist, "30 Intake rerun duplicate check exists")
    check("Rescan/restart Archive Assistant" in checklist and "no duplicate final media" in checklist, "31 AA rescan duplicate check exists")
    check("BM Radio rescan changed" in live and "logical_equal" in live and "physical_equal" in live, "32 BM Radio rescan duplicate check exists")
    check("_source_snapshot(root) != source_before" in live and "source_hashes_equal" in live, "33 source fixture hash equality is required")
    check("active PostgreSQL" in live and "protected_after != protected_before" in live, "34 active PostgreSQL is protected")
    check("SQLite" in live and "protected_after != protected_before" in live, "35 SQLite fallback is protected")
    check(".env/durable evidence" in live and "protected_before_sha256" in live, "36 environment and durable evidence are protected")
    check("$NAS_LOCAL_ROOT/" in live and '"nas_root": "$NAS_LOCAL_ROOT"' in live, "37 evidence privacy guard exists")
    check('"truenas_work": False' in live and "TrueNAS work" in checklist, "38 TrueNAS work is prohibited")
    check("Production/original media is prohibited" in checklist and "real production import" in checklist, "39 production/original media is prohibited")
    check("check_prod6b_station_quality_contract.py" in prod0 and "check_prod6a_listener_playback_contract.py" in prod0, "40 PROD6B and PROD6A contracts remain registered")
    check("check_prod6c_library_source_ux_contract.py" in prod0 and prod0_mandatory_count(prod0) == 61, "41 full PROD0 registers only the non-live 6C contract and has 61 mandatory checks")

    if not args.skip_prior_regressions:
        run("scripts/check_prod6b_station_quality_contract.py", "--skip-prior-regressions")
        run("scripts/check_prod6a_listener_playback_contract.py", "--skip-prior-regressions")
    assert len(CHECKS) == 41
    print("PASS: BM-PROD6C local NAS library/source UX contract (41 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
