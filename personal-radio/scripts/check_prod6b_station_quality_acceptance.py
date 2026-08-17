from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile


PROJECT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT / "backend"
sys.path.insert(0, str(BACKEND))

from app import models
from app.queue_contracts import StationQueueRequest
from app.radio_genres import genre_family
from app.station_candidates import logical_station_count
from app.station_engine import build_station_debug, build_station_queue
from app.station_quality import analyze_station_queue, compatibility_share
from app.station_quality_fixture import FIXED_RANDOM_SEEDS, create_fixture_database, fixture_manifest


MANUAL_REPORT = PROJECT / "docs" / "production-upgrade" / "BM-PROD6B_Station_Review.md"
PROTECTED = (BACKEND / ".env", BACKEND / "bm_radio.db")


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def protected_snapshot() -> dict[str, str | None]:
    return {str(path): digest(path) for path in PROTECTED}


def assert_universal(queue: list[dict], fixture, label: str) -> dict:
    metrics = analyze_station_queue(
        queue,
        down_recording_ids=fixture.down_recording_ids,
        favorite_recording_ids=fixture.favorite_recording_ids,
        up_recording_ids=fixture.up_recording_ids,
    )
    assert metrics.logical_duplicates == 0, (label, metrics)
    assert metrics.physical_duplicates == 0, (label, metrics)
    assert metrics.down_selected == 0, (label, metrics)
    if len(queue) >= 25:
        assert metrics.max_consecutive_artist <= 2, (label, metrics)
        assert metrics.max_consecutive_release <= 2, (label, metrics)
        assert metrics.rolling_last_9_artist_max <= 3, (label, metrics)
        assert metrics.rolling_last_9_release_max <= 2, (label, metrics)
    return metrics.to_dict()


def request(db, station_type: str, *, seed_value: str | None = None, seed_track_id: int | None = None, limit: int = 25, excludes: list[int] | None = None, allow_exploration: bool = False):
    return build_station_queue(StationQueueRequest(
        type=station_type, seed_value=seed_value, seed_track_id=seed_track_id,
        limit=limit, shuffle=True, exclude_track_ids=excludes or [], allow_exploration=allow_exploration,
    ), db)


def station_score(debug: dict, recording_id: int) -> tuple[float, int] | None:
    rows = list(debug.get("selected", [])) + list(debug.get("top_rejected", []))
    ranked = sorted(rows, key=lambda row: float(row.get("score", 0)), reverse=True)
    for index, row in enumerate(ranked):
        if row.get("recording_id") == recording_id:
            return float(row.get("score", 0)), index
    return None


def run_acceptance() -> dict:
    before = protected_snapshot()
    with tempfile.TemporaryDirectory(prefix="bm-prod6b-quality-") as raw:
        engine, db, fixture = create_fixture_database(Path(raw) / "station-quality.db")
        try:
            evidence: dict = {"fixture": fixture_manifest(), "random_seeds": list(FIXED_RANDOM_SEEDS)}
            seed_artist = fixture.artists[0]
            artist_runs = []
            song_runs = []
            genre_runs = []
            for fixed_seed in FIXED_RANDOM_SEEDS:
                random.seed(fixed_seed)
                artist = request(db, "artist", seed_value=seed_artist)
                aq = artist["queue"]
                metrics = assert_universal(aq, fixture, f"artist/{fixed_seed}")
                artists = Counter(item["artist"] for item in aq)
                seed_share = artists[seed_artist] / len(aq)
                assert seed_artist in artists and len(artists) >= 5 and len({item["artist"] for item in aq[:10]}) >= 3
                assert seed_share <= 0.50
                assert compatibility_share(aq, "Hip-Hop") >= 0.90
                artist_runs.append({"seed": fixed_seed, "seed_share": seed_share, "artists": len(artists), "metrics": metrics})

                song_seed = fixture.seed_tracks["artist:r&b"]
                seed_recording = fixture.recording_by_track[song_seed]
                random.seed(fixed_seed)
                song = request(db, "song", seed_track_id=song_seed)
                sq = song["queue"]
                metrics = assert_universal(sq, fixture, f"song/{fixed_seed}")
                assert seed_recording not in {item.get("recording_id") for item in sq}
                assert len({item["artist"] for item in sq[:10]}) >= 3
                assert max(Counter(item["artist"] for item in sq).values()) / len(sq) <= 0.40
                assert compatibility_share(sq, "R&B") == 1.0
                explored = request(db, "song", seed_track_id=song_seed, allow_exploration=True)["queue"]
                unrelated_share = 1.0 - compatibility_share(explored, "R&B")
                assert unrelated_share <= 0.10
                song_runs.append({"seed": fixed_seed, "artists": len(set(item["artist"] for item in sq)), "exploration_share": unrelated_share, "metrics": metrics})

                random.seed(fixed_seed)
                genre = request(db, "genre", seed_value="Hip-Hop")
                gq = genre["queue"]
                metrics = assert_universal(gq, fixture, f"genre/{fixed_seed}")
                assert compatibility_share(gq, "Hip-Hop") == 1.0
                assert len({item["artist"] for item in gq[:15]}) >= 4
                assert max(Counter(item["artist"] for item in gq).values()) / len(gq) <= 0.35
                genre_runs.append({"seed": fixed_seed, "artists": len(set(item["artist"] for item in gq)), "metrics": metrics})

            evidence.update(artist_radio=artist_runs, song_radio=song_runs, genre_radio=genre_runs)

            favorites = request(db, "favorites", limit=50)["queue"]
            favorite_ids = {item.get("recording_id") for item in favorites}
            assert favorite_ids and favorite_ids <= (set(fixture.favorite_recording_ids) | set(fixture.up_recording_ids))
            assert not favorite_ids & set(fixture.down_recording_ids)
            assert_universal(favorites, fixture, "favorites")

            recent = request(db, "recently_added", limit=25)["queue"]
            recent_recordings = [int(item["recording_id"]) for item in recent]
            recent_times = [db.get(models.Track, int(item["effective_track_id"])).created_at for item in recent]
            assert recent_times == sorted(recent_times, reverse=True)
            assert_universal(recent, fixture, "recently-added")

            deep = request(db, "deep_cuts", limit=20)["queue"]
            low_play = sum((int(item["recording_id"]) - 1) % 6 <= 2 for item in deep) / len(deep)
            assert low_play >= 0.70
            assert_universal(deep, fixture, "deep-cuts")
            evidence["system_stations"] = {"favorites": len(favorites), "recent": recent_recordings[:5], "deep_low_play_share": low_play}

            # Latest thumbs-down wins even over a favorite, on every station path where eligible.
            for station_type, kwargs in (
                ("artist", {"seed_value": seed_artist}), ("song", {"seed_track_id": fixture.seed_tracks["artist:hip-hop"]}),
                ("genre", {"seed_value": "Hip-Hop"}), ("favorites", {}), ("recently_added", {}), ("deep_cuts", {}),
            ):
                queue = request(db, station_type, limit=50, **kwargs)["queue"]
                assert not ({item.get("recording_id") for item in queue} & set(fixture.down_recording_ids)), station_type

            # Demonstrate actual before/after score and membership transitions.
            target_recording = 13  # synthetic Hip-Hop row with no initial play events
            target_track = db.query(models.MusicTrackIdentity).filter_by(recording_id=target_recording).first().track_id
            hiphop_seed = fixture.seed_tracks["artist:hip-hop"]
            random.seed(101)
            base_song_debug = build_station_debug(StationQueueRequest(type="song", seed_track_id=hiphop_seed, limit=50), db)
            base_song_score = station_score(base_song_debug, target_recording)
            assert base_song_score is not None

            up_savepoint = db.begin_nested()
            db.add(models.TrackThumb(track_id=target_track, recording_id=target_recording, value=models.ThumbValue.up, created_at=datetime(2026, 8, 18, tzinfo=timezone.utc)))
            db.flush()
            random.seed(101)
            up_score = station_score(build_station_debug(StationQueueRequest(type="song", seed_track_id=hiphop_seed, limit=50), db), target_recording)
            assert up_score is not None and up_score[0] > base_song_score[0]
            up_savepoint.rollback()
            db.expire_all()

            favorite_savepoint = db.begin_nested()
            db.add(models.TrackFavorite(track_id=target_track, recording_id=target_recording, created_at=datetime(2026, 8, 18, tzinfo=timezone.utc)))
            db.flush()
            random.seed(101)
            favorite_score = station_score(build_station_debug(StationQueueRequest(type="song", seed_track_id=hiphop_seed, limit=50), db), target_recording)
            assert favorite_score is not None and favorite_score[0] > base_song_score[0]
            favorite_savepoint.rollback()
            db.expire_all()

            random.seed(101)
            base_artist_score = station_score(build_station_debug(StationQueueRequest(type="artist", seed_value=seed_artist, limit=50), db), target_recording)
            assert base_artist_score is not None
            recent_savepoint = db.begin_nested()
            db.add(models.PlaybackEvent(track_id=target_track, recording_id=target_recording, event_type="qualified_play", position_seconds=120, created_at=datetime(2026, 8, 18, tzinfo=timezone.utc)))
            db.flush()
            random.seed(101)
            recent_score = station_score(build_station_debug(StationQueueRequest(type="artist", seed_value=seed_artist, limit=50), db), target_recording)
            assert recent_score is not None and recent_score[0] < base_artist_score[0]
            recent_savepoint.rollback()
            db.expire_all()

            down_savepoint = db.begin_nested()
            db.add(models.TrackFavorite(track_id=target_track, recording_id=target_recording, created_at=datetime(2026, 8, 18, tzinfo=timezone.utc)))
            db.flush()
            transition_paths = (
                ("artist", {"seed_value": seed_artist}), ("song", {"seed_track_id": hiphop_seed}),
                ("genre", {"seed_value": "Hip-Hop"}), ("favorites", {}),
            )
            for station_type, kwargs in transition_paths:
                assert target_recording in {item.get("recording_id") for item in request(db, station_type, limit=50, **kwargs)["queue"]}
            db.add(models.TrackThumb(track_id=target_track, recording_id=target_recording, value=models.ThumbValue.down, created_at=datetime(2026, 8, 19, tzinfo=timezone.utc)))
            db.flush()
            for station_type, kwargs in transition_paths:
                assert target_recording not in {item.get("recording_id") for item in request(db, station_type, limit=50, **kwargs)["queue"]}
            down_savepoint.rollback()
            db.expire_all()
            evidence["feedback_adaptation"] = {
                "downvote_removed": True,
                "downvote_before_after": True,
                "thumbs_up_score_delta": up_score[0] - base_song_score[0],
                "favorite_score_delta": favorite_score[0] - base_song_score[0],
                "recent_score_delta": recent_score[0] - base_artist_score[0],
            }

            # Initial plus three refills must have no logical or physical overlap.
            windows = []
            excludes: list[int] = []
            seen_logical: set[int] = set()
            seen_physical: set[int] = set()
            for refill_index in range(4):
                result = request(db, "recently_added", limit=25, excludes=excludes)
                queue = result["queue"]
                logical = {int(item["recording_id"]) for item in queue}
                physical = {int(item["effective_track_id"]) for item in queue}
                assert not logical & seen_logical and not physical & seen_physical
                seen_logical |= logical
                seen_physical |= physical
                excludes.extend(int(item["effective_track_id"]) for item in queue)
                windows.append({"index": refill_index, "returned": len(queue), "remaining": result["remaining_estimate"], "exhausted": result["exhausted"]})
            while len(excludes) < 200:
                result = request(db, "recently_added", limit=50, excludes=excludes)
                new_ids = [int(item["effective_track_id"]) for item in result["queue"]]
                if not new_ids:
                    break
                excludes.extend(new_ids)
            terminal = request(db, "recently_added", limit=50, excludes=excludes[-200:])
            assert terminal["queue"] == [] and terminal["exhausted"] is True
            evidence["refill"] = {"windows": windows, "logical_overlap": 0, "physical_overlap": 0, "terminal_exhausted": True}

            candidates = request(db, "recently_added", limit=200)["queue"]
            variant = [item for item in candidates if item.get("recording_id") == fixture.physical_variant_recording_id]
            assert len(variant) == 1 and variant[0]["effective_track_id"] == fixture.preferred_variant_track_id
            excluded_variant = request(db, "recently_added", limit=200, excludes=[fixture.physical_variant_track_ids[0]])["queue"]
            assert fixture.physical_variant_recording_id not in {item.get("recording_id") for item in excluded_variant}
            evidence["physical_variant"] = {"logical_rows": 1, "preferred_track_id": fixture.preferred_variant_track_id, "logical_exclusion": True}

            affinity = {}
            for kind in ("live", "acoustic", "remix", "instrumental"):
                seed_id = fixture.seed_tracks[f"type:{kind}"]
                queue = request(db, "song", seed_track_id=seed_id, limit=20)["queue"]
                focused = sum(item.get("version_affinity_tier") in {"primary", "adjacent"} for item in queue) / len(queue)
                assert focused >= 0.60, (kind, focused)
                affinity[kind] = focused
            balanced = analyze_station_queue(recent).specialized_share
            assert balanced <= 0.25
            evidence["version_affinity"] = {"focused_shares": affinity, "balanced_specialized_share": balanced, "sparse_warning": "covered by PROD1.5B contract"}

            # System counts must describe actual logical station membership and every row must be playable.
            from app.routes.stations import get_stations
            import asyncio
            station_rows = asyncio.run(get_stations(db))
            by_type = {row["type"]: row for row in station_rows if row.get("type") in {"favorites", "recently_added", "deep_cuts"}}
            assert by_type["favorites"]["track_count"] == len(favorites)
            assert by_type["deep_cuts"]["track_count"] == logical_station_count(db, station_type="deep_cuts")
            assert by_type["recently_added"]["track_count"] == logical_station_count(db, station_type="recently_added")
            assert all(request(db, kind, limit=1)["queue"] for kind in ("favorites", "recently_added", "deep_cuts"))
            evidence["station_ui"] = {key: value["track_count"] for key, value in by_type.items()}
        finally:
            db.close()
            engine.dispose()

    frontend = subprocess.run(
        [sys.executable, "scripts/check_prod6b_frontend_station_refill.py"], cwd=str(PROJECT),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", shell=False,
    )
    assert frontend.returncode == 0, frontend.stdout
    evidence["frontend_refill"] = frontend.stdout.strip()
    assert protected_snapshot() == before, "protected SQLite/.env state changed"
    evidence["protection"] = {"active_postgresql_used": False, "sqlite_unchanged": True, "environment_unchanged": True, "real_media_accessed": False, "truenas_work": False}
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print("PASS: BM-PROD6B radio station quality acceptance")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD6B deterministic station-quality acceptance")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--manual-report", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        manifest = fixture_manifest()
        assert manifest["logical_recordings"] >= 150 and manifest["artists"] >= 20 and len(manifest["genre_families"]) >= 4
        assert all(path.parent.exists() for path in PROTECTED)
        print(json.dumps({"status": "PREFLIGHT PASS", "fixture": manifest, "protected": protected_snapshot(), "real_media_accessed": False}, indent=2))
        return 0
    if args.manual_report:
        assert MANUAL_REPORT.is_file(), "committed manual review report is missing"
        report = MANUAL_REPORT.read_text(encoding="utf-8")
        assert "ALGORITHMIC PASS — REAL-LIBRARY SUBJECTIVE REVIEW DEFERRED TO PROD6F" in report
        assert "Operator result: NOT PROVIDED" in report
        print(report)
        with tempfile.TemporaryDirectory(prefix="bm-prod6b-review-") as raw:
            engine, db, fixture = create_fixture_database(Path(raw) / "station-review.db")
            try:
                random.seed(FIXED_RANDOM_SEEDS[0])
                stations = {
                    "Artist Radio": request(db, "artist", seed_value=fixture.artists[0]),
                    "Song Radio": request(db, "song", seed_track_id=fixture.seed_tracks["artist:r&b"]),
                    "Genre Radio": request(db, "genre", seed_value="Hip-Hop"),
                    "Favorites Radio": request(db, "favorites"),
                    "Recently Added": request(db, "recently_added"),
                    "Deep Cuts": request(db, "deep_cuts"),
                    "Focused Live": request(db, "song", seed_track_id=fixture.seed_tracks["type:live"], limit=20),
                    "Focused Acoustic": request(db, "song", seed_track_id=fixture.seed_tracks["type:acoustic"], limit=20),
                    "Focused Remix": request(db, "song", seed_track_id=fixture.seed_tracks["type:remix"], limit=20),
                    "Focused Instrumental": request(db, "song", seed_track_id=fixture.seed_tracks["type:instrumental"], limit=20),
                }
                print("\n## Deterministic first-20 review rows\n")
                for label, result in stations.items():
                    rows = [f"R{int(item['recording_id']):03d} {item['artist']} - {item['title']} [{item.get('recording_type')}]" for item in result["queue"][:20]]
                    print(f"### {label}\n\n" + "\n".join(f"{index + 1}. {row}" for index, row in enumerate(rows)) + "\n")
            finally:
                db.close()
                engine.dispose()
        return 0
    run_acceptance()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
