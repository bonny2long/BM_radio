from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import statistics
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import event
from sqlalchemy.orm import Session

from . import models
from .listener_library import global_music_search, library_search, listener_albums, listener_artists, listener_summary, listener_tracks_page
from .music_recording_feedback import smart_music_candidate_track_ids
from .perf_fixtures import SyntheticLibrarySummary
from .scanner import music_scanner
from .scanner.music_scanner import _existing_track_identity, scan_music
from .station_engine import build_station_queue
from .queue_contracts import StationQueueRequest


@dataclass
class BenchmarkContext:
    db: Session
    engine: Any
    temp_root: Path
    summary: SyntheticLibrarySummary


def stable_checksum(value: Any) -> str:
    payload = json.dumps(_compact(value), sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()[:16]


def _compact(value: Any) -> Any:
    if isinstance(value, list):
        return [_compact(item) for item in value[:25]] + ([{"truncated_count": len(value) - 25}] if len(value) > 25 else [])
    if isinstance(value, dict):
        out = {}
        for key in sorted(value.keys()):
            if key in {"stream_url", "cover_url", "path", "relative_path"}:
                continue
            out[key] = _compact(value[key])
        return out
    return value


def rows_returned(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, dict):
        if isinstance(value.get("items"), list):
            return len(value["items"])
        if isinstance(value.get("queue"), list):
            return len(value["queue"])
        return sum(len(item) for item in value.values() if isinstance(item, list)) or len(value)
    return 1 if value is not None else 0


class SqlCounter:
    def __init__(self, engine):
        self.engine = engine
        self.counts = Counter()
        self.total = 0

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        self.total += 1
        verb = str(statement or "").lstrip().split(None, 1)[0].lower() if statement else "unknown"
        if verb in {"select", "insert", "update", "delete"}:
            self.counts[verb] += 1
        else:
            self.counts["other"] += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._before)
        return self

    def __exit__(self, exc_type, exc, tb):
        event.remove(self.engine, "before_cursor_execute", self._before)

    def as_dict(self) -> dict[str, int]:
        return {
            "select_count": int(self.counts.get("select", 0)),
            "insert_count": int(self.counts.get("insert", 0)),
            "update_count": int(self.counts.get("update", 0)),
            "delete_count": int(self.counts.get("delete", 0)),
            "total_statement_count": int(self.total),
        }


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[index]


def measure_operation(
    ctx: BenchmarkContext,
    *,
    name: str,
    operation: Callable[[Session], Any],
    iterations: int,
    warmups: int,
    notes: str = "",
) -> dict[str, Any]:
    for _ in range(max(0, warmups)):
        operation(ctx.db)
        ctx.db.rollback()

    timings: list[float] = []
    peaks: list[int] = []
    sql_total = Counter()
    total_rows = 0
    checksum = ""
    for _ in range(max(1, iterations)):
        tracemalloc.start()
        with SqlCounter(ctx.engine) as sql:
            start = time.perf_counter()
            result = operation(ctx.db)
            elapsed_ms = (time.perf_counter() - start) * 1000
            current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        ctx.db.rollback()
        timings.append(elapsed_ms)
        peaks.append(int(peak))
        for key, value in sql.as_dict().items():
            sql_total[key] += int(value)
        total_rows = rows_returned(result)
        checksum = stable_checksum(result)

    sql_avg = {key: int(round(value / max(1, iterations))) for key, value in sql_total.items()}
    return {
        "name": name,
        "dataset_size_physical_tracks": ctx.summary.physical_tracks,
        "dataset_size_recordings": ctx.summary.recordings,
        "dataset_size_releases": ctx.summary.releases,
        "dataset_size_artists": ctx.summary.artists,
        "iterations": int(iterations),
        "warmup_iterations": int(warmups),
        "wall_time_ms": {
            "min": round(min(timings), 3),
            "median": round(statistics.median(timings), 3),
            "p95": round(percentile(timings, 95), 3),
            "max": round(max(timings), 3),
        },
        "sql": sql_avg,
        "python_peak_memory_bytes": int(max(peaks) if peaks else 0),
        "rows_returned": int(total_rows),
        "result_checksum": checksum,
        "notes": notes,
    }


def listener_operations(ctx: BenchmarkContext) -> list[tuple[str, Callable[[Session], Any], str]]:
    size = ctx.summary.physical_tracks
    deep_track_offset = max(0, min(size - 50, size // 2))
    deep_artist_offset = max(0, min(ctx.summary.artists - 50, ctx.summary.artists // 2))
    deep_album_offset = max(0, min(ctx.summary.releases - 50, ctx.summary.releases // 2))
    return [
        ("library.summary", lambda db: listener_summary(db), "Q1 library summary"),
        ("library.tracks.first", lambda db: listener_tracks_page(db, limit=50, offset=0), "Q2 first Track page"),
        ("library.tracks.deep", lambda db: listener_tracks_page(db, limit=50, offset=deep_track_offset), "Q3 deep Track page"),
        ("library.artists.first", lambda db: listener_artists(db, limit=50, offset=0), "Q4 first artist page"),
        ("library.artists.deep", lambda db: listener_artists(db, limit=50, offset=deep_artist_offset), "Q5 deep artist page"),
        ("library.albums.first", lambda db: listener_albums(db, limit=50, offset=0), "Q6 first album page"),
        ("library.albums.deep", lambda db: listener_albums(db, limit=50, offset=deep_album_offset), "Q7 deep album page"),
        ("library.search.selective", lambda db: library_search(db, q="Track 000042"), "Q8 selective search"),
        ("library.search.broad", lambda db: global_music_search(db, q="Artist"), "Q9 broad bounded search"),
        ("library.recent_playback", lambda db: smart_music_candidate_track_ids(db, key="recently_played", limit=100), "Q10 recording-aware recent playback"),
    ]


def scanner_startup_state(db: Session) -> dict[str, Any]:
    tracks = db.query(models.Track).all()
    exact_path_tracks = {track.path: track.id for track in tracks if track.path}
    release_seen: dict[str, int] = {}
    recording_seen: dict[str, int] = {}
    for track in tracks:
        if track.library_availability == "unavailable":
            continue
        release_key, recording_key, _duration = _existing_track_identity(track)
        release_seen.setdefault(release_key, track.id)
        recording_seen.setdefault(recording_key, track.id)
    return {
        "tracks_loaded": len(tracks),
        "exact_path_tracks": len(exact_path_tracks),
        "release_seen": len(release_seen),
        "recording_seen": len(recording_seen),
        "checksum": stable_checksum({"paths": sorted(exact_path_tracks)[:25], "release_seen": len(release_seen), "recording_seen": len(recording_seen)}),
    }


def _dummy_metadata(path: Path) -> dict[str, Any]:
    stem = path.stem
    return {
        "duration_seconds": 180.0,
        "title": stem,
        "artist": "Incremental Artist",
        "album": "Incremental Release",
        "album_artist": "Incremental Artist",
        "genre": "Soul",
        "year": 2026,
        "technical": {
            "probe_status": "ok",
            "probe_source": "synthetic",
            "probe_version": 1,
            "codec": path.suffix.lower().lstrip("."),
            "container": path.suffix.lower().lstrip("."),
            "is_lossless": path.suffix.lower() == ".flac",
            "sample_rate_hz": 44100,
            "bit_depth_bits": 16 if path.suffix.lower() == ".flac" else None,
            "bitrate_bps": None if path.suffix.lower() == ".flac" else 320000,
            "channel_count": 2,
            "file_size_bytes": 4096,
        },
    }


@contextmanager
def patched_scanner_root(root: Path):
    old_roots = music_scanner.configured_music_scan_roots
    old_read = music_scanner.read_metadata
    old_music_root = music_scanner.settings.MUSIC_ROOT
    old_flac_root = music_scanner.settings.MUSIC_FLAC_ROOT
    old_mp3_root = music_scanner.settings.MUSIC_MP3_ROOT
    old_legacy = music_scanner.settings.BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN
    music_scanner.configured_music_scan_roots = lambda: [root]
    music_scanner.read_metadata = _dummy_metadata
    object.__setattr__(music_scanner.settings, "MUSIC_ROOT", str(root))
    object.__setattr__(music_scanner.settings, "MUSIC_FLAC_ROOT", str(root))
    object.__setattr__(music_scanner.settings, "MUSIC_MP3_ROOT", str(root))
    object.__setattr__(music_scanner.settings, "BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN", False)
    try:
        yield
    finally:
        music_scanner.configured_music_scan_roots = old_roots
        music_scanner.read_metadata = old_read
        object.__setattr__(music_scanner.settings, "MUSIC_ROOT", old_music_root)
        object.__setattr__(music_scanner.settings, "MUSIC_FLAC_ROOT", old_flac_root)
        object.__setattr__(music_scanner.settings, "MUSIC_MP3_ROOT", old_mp3_root)
        object.__setattr__(music_scanner.settings, "BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN", old_legacy)


def scanner_incremental_50(ctx: BenchmarkContext, db: Session) -> dict[str, Any]:
    root = ctx.temp_root / "scanner_incremental_root"
    root.mkdir(parents=True, exist_ok=True)
    for index in range(50):
        path = root / f"{index + 1:02d} Incremental Track {index + 1:02d}.mp3"
        if not path.exists():
            path.write_bytes(b"")
    with patched_scanner_root(root):
        result = scan_music(db)
    return {
        "status": result.get("status"),
        "tracks_scanned": result.get("tracks_scanned"),
        "tracks_added": result.get("tracks_added"),
        "tracks_updated": result.get("tracks_updated"),
        "tracks_unavailable": result.get("tracks_unavailable"),
        "errors": len(result.get("errors") or []),
        "roots_temp_only": all(str(root) in item for item in result.get("roots_scanned") or []),
    }


def station_observation_operations(ctx: BenchmarkContext) -> list[tuple[str, Callable[[Session], Any], str]]:
    return [
        ("station.artist.observation", lambda db: build_station_queue(StationQueueRequest(type="artist", seed_value="Artist 0001", limit=25, shuffle=False), db), "observational Artist Radio baseline"),
        ("station.favorites.observation", lambda db: build_station_queue(StationQueueRequest(type="favorites", limit=25, shuffle=False), db), "observational Favorites Radio baseline"),
    ]


def run_benchmarks(
    ctx: BenchmarkContext,
    *,
    iterations: int,
    warmups: int,
    include_scanner: bool = False,
    include_station_observation: bool = False,
) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for name, operation, notes in listener_operations(ctx):
        metrics.append(measure_operation(ctx, name=name, operation=operation, iterations=iterations, warmups=warmups, notes=notes))
    if include_scanner:
        metrics.append(measure_operation(ctx, name="scanner.startup_state", operation=scanner_startup_state, iterations=iterations, warmups=warmups, notes="S1 existing-index startup state"))
        metrics.append(measure_operation(ctx, name="scanner.incremental.50", operation=lambda db: scanner_incremental_50(ctx, db), iterations=1, warmups=0, notes="S2 temp-root deterministic 50-file incremental scan"))
    if include_station_observation and ctx.summary.physical_tracks <= 10000:
        for name, operation, notes in station_observation_operations(ctx):
            metrics.append(measure_operation(ctx, name=name, operation=operation, iterations=iterations, warmups=warmups, notes=notes))
    return metrics


def classify_scaling(metrics_by_size: dict[int, list[dict[str, Any]]]) -> dict[str, str]:
    names = sorted({metric["name"] for metrics in metrics_by_size.values() for metric in metrics})
    out: dict[str, str] = {}
    for name in names:
        points = []
        for size, metrics in sorted(metrics_by_size.items()):
            found = next((metric for metric in metrics if metric["name"] == name), None)
            if found:
                points.append((size, float(found["wall_time_ms"]["median"])))
        if len(points) < 2:
            out[name] = "unknown"
            continue
        first_size, first_ms = points[0]
        last_size, last_ms = points[-1]
        if "station" in name:
            out[name] = "candidate_cap_bounded"
        elif last_ms <= max(first_ms * 2.5, first_ms + 5):
            out[name] = "bounded"
        else:
            size_ratio = last_size / max(first_size, 1)
            time_ratio = last_ms / max(first_ms, 0.001)
            out[name] = "superlinear" if time_ratio > size_ratio * 1.5 else "approximately_linear"
    return out


def table_rows(metrics: list[dict[str, Any]]) -> list[str]:
    lines = [f"{'Operation':30} {'Tracks':>8} {'Median ms':>10} {'p95 ms':>8} {'SELECTs':>8} {'Peak MiB':>9}"]
    for metric in metrics:
        peak_mib = metric["python_peak_memory_bytes"] / (1024 * 1024)
        lines.append(f"{metric['name'][:30]:30} {metric['dataset_size_physical_tracks']:8d} {metric['wall_time_ms']['median']:10.1f} {metric['wall_time_ms']['p95']:8.1f} {metric['sql']['select_count']:8d} {peak_mib:9.1f}")
    return lines