from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
import random
import statistics
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from . import models
from .perf import collect_perf_segments
from .perf_benchmark import BenchmarkContext, SqlCounter, percentile, stable_checksum
from .queue_contracts import StationQueueRequest
from .routes.stations import get_stations
from .station_candidates import (
    MAX_STATION_CANDIDATE_POOL,
    load_station_candidate_tracks,
    load_station_recording_candidates,
    logical_station_count,
    station_identity_key_for_track,
    station_identity_keys_for_track_ids,
)
from .station_engine import build_station_debug, build_station_queue

PROD4_FIXTURE_SEED = 41041
DEFAULT_LIMIT = 50
STATION_WRITE_TABLES = [
    "tracks",
    "music_recordings",
    "music_recording_preferences",
    "music_recording_participation",
    "track_favorites",
    "track_thumbs",
    "playback_events",
    "stations",
    "track_radio_profiles",
]


@dataclass(frozen=True)
class StationSeeds:
    song_track_id: int
    live_song_track_id: int
    artist_name: str
    genre_name: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "song_track_id": self.song_track_id,
            "live_song_track_id": self.live_song_track_id,
            "artist_name": self.artist_name,
            "genre_name": self.genre_name,
        }


def _seed_int(name: str, size: int, refill_number: int = 0) -> int:
    digest = sha256(f"{PROD4_FIXTURE_SEED}:{size}:{name}:{refill_number}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 3) if values else 0.0


def summarize_phase_runs(runs: list[dict[str, list[float]]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        for name, values in run.items():
            grouped[name].append(sum(values))
    return {
        name: {
            "min": round(min(values), 3),
            "median": _median(values),
            "p95": round(percentile(values, 95), 3),
            "max": round(max(values), 3),
        }
        for name, values in sorted(grouped.items())
    }


def table_counts(db: Session, tables: list[str] | None = None) -> dict[str, int]:
    names = tables or [row[0] for row in db.execute(text("select name from sqlite_master where type='table' and name not like 'sqlite_%'")).all()]
    return {name: int(db.execute(text(f'select count(*) from "{name}"')).scalar_one() or 0) for name in names}


def queue_identities(result: dict[str, Any]) -> list[dict[str, int | None]]:
    identities = []
    for row in result.get("queue") or []:
        identities.append({
            "recording_id": row.get("recording_id"),
            "track_id": row.get("track_id"),
            "effective_track_id": row.get("effective_track_id") or row.get("track_id"),
        })
    return identities


def queue_checksum(result: dict[str, Any]) -> str:
    return stable_checksum(queue_identities(result))


def effective_track_ids_checksum(result: dict[str, Any]) -> str:
    ids = [row.get("effective_track_id") or row.get("track_id") for row in result.get("queue") or []]
    return stable_checksum(ids)


def track_ids_from_queue(result: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    for row in result.get("queue") or []:
        track_id = row.get("track_id")
        if track_id is not None:
            ids.append(int(track_id))
    return ids


def selected_seed_pool(db: Session) -> list[models.Track]:
    return load_station_candidate_tracks(db, limit=MAX_STATION_CANDIDATE_POOL)


def select_station_seeds(db: Session) -> StationSeeds:
    pool = selected_seed_pool(db)
    if not pool:
        raise RuntimeError("station benchmark fixture has no station candidates")
    type_by_track = {track.id: getattr(track, "_station_recording_type", None) for track in pool}
    ordinary = next((track for track in pool if type_by_track.get(track.id) in {"unknown", "radio_edit", None}), pool[0])
    live = next((track for track in pool if type_by_track.get(track.id) == "live"), ordinary)
    artist_counts = Counter(track.artist for track in pool if track.artist)
    genre_counts = Counter(track.primary_genre or track.genre for track in pool if track.primary_genre or track.genre)
    artist = sorted(artist_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    genre = sorted(genre_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return StationSeeds(song_track_id=int(ordinary.id), live_song_track_id=int(live.id), artist_name=str(artist), genre_name=str(genre))


def station_requests(seeds: StationSeeds) -> list[tuple[str, StationQueueRequest, str]]:
    return [
        ("station.song.initial", StationQueueRequest(type="song", seed_track_id=seeds.song_track_id, limit=DEFAULT_LIMIT, shuffle=False), "Song Radio initial generation"),
        ("station.song_live.initial", StationQueueRequest(type="song", seed_track_id=seeds.live_song_track_id, limit=DEFAULT_LIMIT, shuffle=False), "Live Song Radio initial generation"),
        ("station.artist.initial", StationQueueRequest(type="artist", seed_value=seeds.artist_name, limit=DEFAULT_LIMIT, shuffle=False), "Artist Radio initial generation"),
        ("station.genre.initial", StationQueueRequest(type="genre", seed_value=seeds.genre_name, limit=DEFAULT_LIMIT, shuffle=False), "Genre Radio initial generation"),
        ("station.favorites.initial", StationQueueRequest(type="favorites", limit=DEFAULT_LIMIT, shuffle=False), "Favorites Radio initial generation"),
        ("station.recently_added.initial", StationQueueRequest(type="recently_added", limit=DEFAULT_LIMIT, shuffle=False), "Recently Added initial generation"),
        ("station.deep_cuts.initial", StationQueueRequest(type="deep_cuts", limit=DEFAULT_LIMIT, shuffle=False), "Deep Cuts initial generation"),
    ]


def debug_requests(seeds: StationSeeds) -> list[tuple[str, StationQueueRequest, str]]:
    return [
        ("station.song.debug", StationQueueRequest(type="song", seed_track_id=seeds.song_track_id, limit=DEFAULT_LIMIT, shuffle=False), "Song Radio production debug path"),
        ("station.artist.debug", StationQueueRequest(type="artist", seed_value=seeds.artist_name, limit=DEFAULT_LIMIT, shuffle=False), "Artist Radio production debug path"),
        ("station.genre.debug", StationQueueRequest(type="genre", seed_value=seeds.genre_name, limit=DEFAULT_LIMIT, shuffle=False), "Genre Radio production debug path"),
    ]


def listing_operations(seeds: StationSeeds) -> list[tuple[str, Callable[[Session], Any], str]]:
    return [
        ("stations.list", lambda db: asyncio.run(get_stations(db)), "Current station listing route path"),
        ("station_count.favorites", lambda db: {"count": int(logical_station_count(db, station_type="favorites"))}, "Current logical station count path"),
        ("station_count.recently_added", lambda db: {"count": int(logical_station_count(db, station_type="recently_added"))}, "Current logical station count path"),
        ("station_count.deep_cuts", lambda db: {"count": int(logical_station_count(db, station_type="deep_cuts"))}, "Current logical station count path"),
        ("station_count.artist", lambda db: {"count": int(logical_station_count(db, station_type="artist", seed_value=seeds.artist_name))}, "Current logical station count path"),
        ("station_count.genre", lambda db: {"count": int(logical_station_count(db, station_type="genre", seed_value=seeds.genre_name))}, "Current logical station count path"),
    ]


def _request_station_type(req: StationQueueRequest | None, name: str) -> str | None:
    if req is not None:
        return req.type
    if name.startswith("station_count."):
        return name.split(".", 1)[1]
    return None


def candidate_projection_metrics(db: Session, req: StationQueueRequest | None, seeds: StationSeeds | None = None) -> dict[str, Any]:
    if req is None:
        tracks = load_station_candidate_tracks(db, limit=MAX_STATION_CANDIDATE_POOL)
        projection_stats = dict(db.info.get("station_candidate_projection_metrics") or {})
        metrics = {
            "physical_tracks_in_fixture": int(db.query(models.Track).count()),
            "logical_recordings_in_fixture": int(db.query(models.MusicRecording).count()),
            "logical_rows_considered_before_cap": int(db.query(models.MusicTrackIdentity.recording_id).join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id).filter(models.Track.library_availability == "available").distinct().count()),
            "recording_ids_loaded": len({getattr(track, "_station_recording_id", None) for track in tracks if getattr(track, "_station_recording_id", None) is not None}),
            "candidates_after_participation": len(tracks),
            "candidates_after_exclusion": len(tracks),
            "effective_sources_resolved": len([track for track in tracks if getattr(track, "_station_effective_track_id", None) is not None]),
            "profile_tracks_loaded": len({getattr(track, "_station_profile_track_id", track.id) for track in tracks}),
            "legacy_candidates_loaded": len([track for track in tracks if getattr(track, "_station_recording_id", None) is None]),
            "final_candidate_pool_size": len(tracks),
            "candidate_cap_reached": len(tracks) >= MAX_STATION_CANDIDATE_POOL,
        }
        metrics.update(projection_stats)
        return metrics
    exclude_keys = station_identity_keys_for_track_ids(db, req.exclude_track_ids or [])
    if req.type == "song" and req.seed_track_id is not None:
        seed_keys = station_identity_keys_for_track_ids(db, [req.seed_track_id])
        exclude_keys |= seed_keys
    candidates = load_station_recording_candidates(db, limit=MAX_STATION_CANDIDATE_POOL, exclude_keys=exclude_keys)
    tracks = [candidate.effective_track for candidate in candidates]
    full_logical = int(db.query(models.MusicTrackIdentity.recording_id).join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id).filter(models.Track.library_availability == "available").distinct().count())
    projection_stats = dict(db.info.get("station_candidate_projection_metrics") or {})
    metrics = {
        "physical_tracks_in_fixture": int(db.query(models.Track).count()),
        "logical_recordings_in_fixture": int(db.query(models.MusicRecording).count()),
        "logical_rows_considered_before_cap": full_logical,
        "recording_ids_loaded": len({candidate.recording_id for candidate in candidates if candidate.recording_id is not None}),
        "candidates_after_participation": len(candidates),
        "candidates_after_exclusion": len(candidates),
        "effective_sources_resolved": len([candidate for candidate in candidates if candidate.effective_track is not None]),
        "profile_tracks_loaded": len({candidate.profile_track.id for candidate in candidates if candidate.profile_track is not None}),
        "legacy_candidates_loaded": len([candidate for candidate in candidates if candidate.recording_id is None]),
        "final_candidate_pool_size": len(candidates),
        "candidate_cap_reached": len(candidates) >= MAX_STATION_CANDIDATE_POOL,
    }
    metrics.update(projection_stats)
    artist = req.seed_value if req.type == "artist" else seeds.artist_name if seeds else None
    genre = req.seed_value if req.type == "genre" else seeds.genre_name if seeds else None
    if artist:
        artist_full = db.query(models.MusicTrackIdentity.recording_id).join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id).filter(models.Track.library_availability == "available").filter((models.Track.artist == artist) | (models.Track.album_artist == artist)).distinct().count()
        artist_inside = len({station_identity_key_for_track(track) for track in tracks if track.artist == artist or track.album_artist == artist})
        metrics["seed_artist_full_fixture_count"] = int(artist_full)
        metrics["seed_artist_inside_pool_count"] = int(artist_inside)
    if genre:
        genre_token = str(genre).lower()
        genre_full = db.query(models.MusicTrackIdentity.recording_id).join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id).filter(models.Track.library_availability == "available").filter(func.lower(func.coalesce(models.Track.primary_genre, models.Track.genre)).like(f"%{genre_token}%")).distinct().count()
        genre_inside = len({station_identity_key_for_track(track) for track in tracks if genre_token in str(track.primary_genre or track.genre or "").lower()})
        metrics["target_genre_full_fixture_count"] = int(genre_full)
        metrics["target_genre_inside_pool_count"] = int(genre_inside)
    return metrics


def profile_cache_metrics(db: Session, candidate_metrics: dict[str, Any]) -> dict[str, Any]:
    context_metrics = db.info.get("station_request_context_metrics") or {}
    scoped = dict(context_metrics.get("profile_metrics") or {})
    loaded = int(scoped.get("track_profile_rows_loaded", candidate_metrics.get("profile_tracks_loaded", 0)))
    scoped.update({
        "radio_profile_rows_loaded": loaded,
        "profile_cache_wall_time_source": "station.profile_cache",
        "cache_lookup_coverage": round(loaded / max(1, int(candidate_metrics.get("final_candidate_pool_size", 0))), 4),
        "total_track_profile_rows_in_fixture": int(db.query(models.TrackRadioProfile).count()),
    })
    return scoped


def listener_signal_metrics(phase_metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        name: phase_metrics.get(name, {"median": 0.0})
        for name in [
            "station.listener_signals.feedback",
            "station.listener_signals.favorites",
            "station.listener_signals.play_counts",
            "station.listener_signals.recent",
        ]
    }


def measure_station_operation(
    ctx: BenchmarkContext,
    *,
    name: str,
    operation: Callable[[Session], Any],
    req: StationQueueRequest | None,
    seeds: StationSeeds | None,
    iterations: int,
    warmups: int,
    refill_number: int = 0,
    notes: str = "",
) -> dict[str, Any]:
    operation_seed = _seed_int(name, ctx.summary.physical_tracks, refill_number)
    for index in range(max(0, warmups)):
        random.seed(operation_seed - index - 1)
        with collect_perf_segments():
            operation(ctx.db)
        ctx.db.rollback()

    timings: list[float] = []
    peaks: list[int] = []
    phase_runs: list[dict[str, list[float]]] = []
    sql_total = Counter()
    result: Any = None
    for index in range(max(1, iterations)):
        random.seed(operation_seed + index)
        tracemalloc.start()
        with collect_perf_segments() as segments:
            with SqlCounter(ctx.engine) as sql:
                start = time.perf_counter()
                result = operation(ctx.db)
                elapsed_ms = (time.perf_counter() - start) * 1000
                current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        ctx.db.rollback()
        timings.append(elapsed_ms)
        peaks.append(int(peak))
        phase_runs.append({key: list(values) for key, values in segments.items()})
        for key, value in sql.as_dict().items():
            sql_total[key] += int(value)

    sql_avg = {key: int(round(value / max(1, iterations))) for key, value in sql_total.items()}
    result_dict = result if isinstance(result, dict) else {"items": result if isinstance(result, list) else [result]}
    queue = result_dict.get("queue") or []
    output_ids = track_ids_from_queue(result_dict)
    excluded_keys = station_identity_keys_for_track_ids(ctx.db, req.exclude_track_ids if req else []) if req else set()
    output_keys = station_identity_keys_for_track_ids(ctx.db, output_ids) if output_ids else set()
    phase_summary = summarize_phase_runs(phase_runs)
    with collect_perf_segments():
        candidate_metrics = candidate_projection_metrics(ctx.db, req, seeds)
    returned = int(result_dict.get("returned", len(queue) if queue else len(result_dict.get("items") or [])))
    unique_recordings = {row.get("recording_id") or row.get("track_id") for row in queue if row.get("recording_id") or row.get("track_id")}
    metric = {
        "name": name,
        "station_type": _request_station_type(req, name),
        "dataset_size_physical_tracks": ctx.summary.physical_tracks,
        "dataset_size_recordings": ctx.summary.recordings,
        "candidate_cap": MAX_STATION_CANDIDATE_POOL,
        "request_limit": int(req.limit) if req else None,
        "exclude_count": len(req.exclude_track_ids or []) if req else 0,
        "refill_number": int(refill_number),
        "iterations": int(iterations),
        "warmup_iterations": int(warmups),
        "wall_time_ms": {
            "min": round(min(timings), 3),
            "median": _median(timings),
            "p95": round(percentile(timings, 95), 3),
            "max": round(max(timings), 3),
        },
        "sql": sql_avg,
        "python_peak_memory_bytes": int(max(peaks) if peaks else 0),
        "candidate_count": int(candidate_metrics.get("final_candidate_pool_size", 0)),
        "returned": returned,
        "unique_recording_count": len(unique_recordings),
        "excluded_recording_overlap": len(excluded_keys & output_keys),
        "queue_checksum": queue_checksum(result_dict),
        "effective_track_ids_checksum": effective_track_ids_checksum(result_dict),
        "exhausted": bool(result_dict.get("exhausted", False)),
        "remaining_estimate": int(result_dict.get("remaining_estimate", 0) or 0),
        "phase_metrics": phase_summary,
        "candidate_projection_metrics": candidate_metrics,
        "profile_cache_metrics": profile_cache_metrics(ctx.db, candidate_metrics),
        "listener_signal_metrics": listener_signal_metrics(phase_summary),
        "notes": notes,
    }
    if name.endswith(".debug"):
        metric["selected_count"] = int((result_dict.get("summary") or {}).get("selected_count", 0))
        metric["top_rejected_count"] = len(result_dict.get("top_rejected") or [])
        metric["debug_payload_checksum"] = stable_checksum(result_dict)
    return metric


def run_initial_benchmarks(ctx: BenchmarkContext, seeds: StationSeeds, *, iterations: int, warmups: int) -> list[dict[str, Any]]:
    metrics = []
    for name, req, notes in station_requests(seeds):
        metrics.append(measure_station_operation(ctx, name=name, operation=lambda db, req=req: build_station_queue(req, db), req=req, seeds=seeds, iterations=iterations, warmups=warmups, notes=notes))
    return metrics


def _chain_seed_requests(seeds: StationSeeds) -> list[tuple[str, StationQueueRequest]]:
    return [
        ("station.song", StationQueueRequest(type="song", seed_track_id=seeds.song_track_id, limit=DEFAULT_LIMIT, shuffle=False)),
        ("station.artist", StationQueueRequest(type="artist", seed_value=seeds.artist_name, limit=DEFAULT_LIMIT, shuffle=False)),
        ("station.genre", StationQueueRequest(type="genre", seed_value=seeds.genre_name, limit=DEFAULT_LIMIT, shuffle=False)),
        ("station.favorites", StationQueueRequest(type="favorites", limit=DEFAULT_LIMIT, shuffle=False)),
    ]


def request_with_exclusions(req: StationQueueRequest, exclusions: list[int]) -> StationQueueRequest:
    return StationQueueRequest(
        type=req.type,
        seed_value=req.seed_value,
        seed_track_id=req.seed_track_id,
        limit=DEFAULT_LIMIT,
        shuffle=False,
        allow_exploration=req.allow_exploration,
        exclude_track_ids=exclusions[-200:],
    )


def run_refill_benchmarks(ctx: BenchmarkContext, seeds: StationSeeds, *, iterations: int, warmups: int, refill_count: int) -> list[dict[str, Any]]:
    metrics = []
    for prefix, base_req in _chain_seed_requests(seeds):
        random.seed(_seed_int(f"{prefix}.chain.initial", ctx.summary.physical_tracks))
        with collect_perf_segments():
            initial = build_station_queue(base_req, ctx.db)
        ctx.db.rollback()
        history = track_ids_from_queue(initial)
        for refill_number in range(1, max(0, refill_count) + 1):
            req = request_with_exclusions(base_req, history[-200:])
            name = f"{prefix}.refill.{refill_number}"
            metrics.append(measure_station_operation(ctx, name=name, operation=lambda db, req=req: build_station_queue(req, db), req=req, seeds=seeds, iterations=iterations, warmups=warmups, refill_number=refill_number, notes="Frontend refill model: limit 50 with last 200 physical Track IDs excluded"))
            random.seed(_seed_int(name, ctx.summary.physical_tracks, refill_number))
            with collect_perf_segments():
                result = build_station_queue(req, ctx.db)
            ctx.db.rollback()
            history.extend(track_ids_from_queue(result))
    return metrics


def run_debug_benchmarks(ctx: BenchmarkContext, seeds: StationSeeds, *, iterations: int, warmups: int) -> list[dict[str, Any]]:
    metrics = []
    for name, req, notes in debug_requests(seeds):
        metrics.append(measure_station_operation(ctx, name=name, operation=lambda db, req=req: build_station_debug(req, db), req=req, seeds=seeds, iterations=iterations, warmups=warmups, notes=notes))
    return metrics


def run_listing_benchmarks(ctx: BenchmarkContext, seeds: StationSeeds, *, iterations: int, warmups: int) -> list[dict[str, Any]]:
    metrics = []
    for name, operation, notes in listing_operations(seeds):
        metrics.append(measure_station_operation(ctx, name=name, operation=operation, req=None, seeds=seeds, iterations=iterations, warmups=warmups, notes=notes))
    return metrics


def run_station_benchmarks(
    ctx: BenchmarkContext,
    *,
    iterations: int,
    warmups: int,
    refill_count: int,
    include_debug: bool,
    include_listing: bool,
) -> dict[str, Any]:
    with collect_perf_segments():
        seeds = select_station_seeds(ctx.db)
    metrics = []
    metrics.extend(run_initial_benchmarks(ctx, seeds, iterations=iterations, warmups=warmups))
    metrics.extend(run_refill_benchmarks(ctx, seeds, iterations=iterations, warmups=warmups, refill_count=refill_count))
    if include_debug:
        metrics.extend(run_debug_benchmarks(ctx, seeds, iterations=iterations, warmups=warmups))
    if include_listing:
        metrics.extend(run_listing_benchmarks(ctx, seeds, iterations=iterations, warmups=warmups))
    return {
        "fixture_seed": PROD4_FIXTURE_SEED,
        "station_seeds": seeds.as_dict(),
        "summary": ctx.summary.as_dict(),
        "metrics": metrics,
        "scaling_classification": classify_station_scaling(metrics),
    }


def classify_station_scaling(metrics: list[dict[str, Any]]) -> dict[str, str]:
    out = {}
    for metric in metrics:
        cpm = metric.get("candidate_projection_metrics", {})
        if cpm.get("candidate_cap_reached"):
            out[metric["name"]] = "candidate_cap_bounded"
        elif cpm.get("final_candidate_pool_size", 0) < MAX_STATION_CANDIDATE_POOL:
            out[metric["name"]] = "below_cap"
        else:
            out[metric["name"]] = "unknown"
    return out


def grouped_table(metrics: list[dict[str, Any]], kind: str) -> list[str]:
    if kind == "initial":
        chosen = [m for m in metrics if m["name"].endswith(".initial")]
        lines = [f"{'Operation':34} {'Tracks':>8} {'Median ms':>10} {'SELECTs':>8} {'Peak MiB':>9} {'Returned':>8}"]
        for metric in chosen:
            lines.append(f"{metric['name'][:34]:34} {metric['dataset_size_physical_tracks']:8d} {metric['wall_time_ms']['median']:10.1f} {metric['sql']['select_count']:8d} {metric['python_peak_memory_bytes'] / (1024 * 1024):9.1f} {metric['returned']:8d}")
        return lines
    if kind == "refill":
        chosen = [m for m in metrics if ".refill." in m["name"]]
        lines = [f"{'Operation':34} {'Tracks':>8} {'Excludes':>8} {'Median ms':>10} {'SELECTs':>8} {'Returned':>8}"]
        for metric in chosen:
            lines.append(f"{metric['name'][:34]:34} {metric['dataset_size_physical_tracks']:8d} {metric['exclude_count']:8d} {metric['wall_time_ms']['median']:10.1f} {metric['sql']['select_count']:8d} {metric['returned']:8d}")
        return lines
    chosen = [m for m in metrics if m["name"].endswith(".debug") or m["name"].startswith("stations.") or m["name"].startswith("station_count.")]
    lines = [f"{'Operation':34} {'Tracks':>8} {'Median ms':>10} {'SELECTs':>8} {'Peak MiB':>9} {'Returned':>8}"]
    for metric in chosen:
        lines.append(f"{metric['name'][:34]:34} {metric['dataset_size_physical_tracks']:8d} {metric['wall_time_ms']['median']:10.1f} {metric['sql']['select_count']:8d} {metric['python_peak_memory_bytes'] / (1024 * 1024):9.1f} {metric['returned']:8d}")
    return lines


def write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
