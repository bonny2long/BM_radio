from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Iterable

from sqlalchemy.orm import Session

from . import models

PROBE_SOURCE = "mutagen"
PROBE_VERSION = 1
PROFILE_BATCH_CHUNK_SIZE = 500
PROBE_STATUS_OK = "ok"
PROBE_STATUS_PARTIAL = "partial"
PROBE_STATUS_FAILED = "failed"

LOSSLESS_CODECS = {"flac", "alac", "pcm"}
LOSSY_CODECS = {"mp3", "aac", "vorbis", "opus"}

PROFILE_FIELDS = [
    "probe_status",
    "probe_source",
    "probe_version",
    "codec",
    "container",
    "is_lossless",
    "sample_rate_hz",
    "bit_depth_bits",
    "bitrate_bps",
    "channel_count",
    "file_size_bytes",
    "replaygain_track_gain_db",
    "replaygain_album_gain_db",
    "replaygain_track_peak",
    "replaygain_album_peak",
    "probe_error_code",
    "probed_at",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def chunked(values: Iterable, size: int = PROFILE_BATCH_CHUNK_SIZE):
    chunk = []
    for value in values:
        chunk.append(value)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def positive_int(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def bounded_error_code(exc: BaseException | str | None) -> str | None:
    if exc is None:
        return None
    if isinstance(exc, BaseException):
        code = exc.__class__.__name__
    else:
        code = str(exc).strip() or "UnknownProbeError"
    code = re.sub(r"[^A-Za-z0-9_]+", "", code) or "UnknownProbeError"
    return code[:100]


def tag_value(tags: Any, *keys: str) -> Any:
    if not tags or not hasattr(tags, "get"):
        return None
    for key in keys:
        value = tags.get(key)
        if value is not None:
            return value
    return None


def file_size_bytes(path: Path | str | None) -> int | None:
    if path is None:
        return None
    try:
        return positive_int(Path(path).stat().st_size)
    except OSError:
        return None


def normalize_container(path: Path | str | None, media: Any = None) -> str:
    ext = Path(path).suffix.lower().lstrip(".") if path is not None else ""
    if ext == "m4a":
        return "mp4"
    if ext in {"flac", "mp3", "wav", "ogg", "opus", "aac"}:
        return ext
    mime_values = getattr(media, "mime", None) or []
    mime_text = " ".join(str(value).lower() for value in mime_values)
    if "flac" in mime_text:
        return "flac"
    if "mpeg" in mime_text or "mp3" in mime_text:
        return "mp3"
    if "mp4" in mime_text or "m4a" in mime_text:
        return "mp4"
    if "wave" in mime_text or "wav" in mime_text:
        return "wav"
    if "ogg" in mime_text:
        return "ogg"
    return ext or "unknown"


def _info_text(info: Any, media: Any = None) -> str:
    parts = [info.__class__.__name__ if info is not None else ""]
    for attr in ["codec", "codec_description", "encoder_info", "encoder_settings"]:
        value = getattr(info, attr, None)
        if value:
            parts.append(str(value))
    mime_values = getattr(media, "mime", None) or []
    parts.extend(str(value) for value in mime_values)
    return " ".join(parts).lower()


def normalize_codec(path: Path | str | None, info: Any = None, media: Any = None) -> str:
    text = _info_text(info, media)
    ext = Path(path).suffix.lower().lstrip(".") if path is not None else ""
    container = normalize_container(path, media)

    if "alac" in text or "apple lossless" in text:
        return "alac"
    if "aac" in text or "mp4a" in text or "advanced audio" in text:
        return "aac"
    if "flac" in text or ext == "flac":
        return "flac"
    if "mp3" in text or "mpeg audio" in text or ext == "mp3":
        return "mp3"
    if "opus" in text or ext == "opus":
        return "opus"
    if "vorbis" in text or (container == "ogg" and ext == "ogg"):
        return "vorbis"
    if "pcm" in text or "wave" in text or "wav" in text or ext == "wav":
        return "pcm"
    if ext == "aac":
        return "aac"
    if container == "mp4":
        return "unknown"
    return "unknown"


def classify_lossless(codec: str | None) -> bool | None:
    normalized = (codec or "unknown").lower()
    if normalized in LOSSLESS_CODECS:
        return True
    if normalized in LOSSY_CODECS:
        return False
    return None


def stream_properties(info: Any) -> dict[str, int | None]:
    return {
        "sample_rate_hz": positive_int(getattr(info, "sample_rate", None)),
        "bit_depth_bits": positive_int(getattr(info, "bits_per_sample", None) or getattr(info, "bit_depth", None)),
        "bitrate_bps": positive_int(getattr(info, "bitrate", None)),
        "channel_count": positive_int(getattr(info, "channels", None)),
    }


def replaygain_values(tags: Any) -> dict[str, float | None]:
    return {
        "replaygain_track_gain_db": parse_float(tag_value(tags, "replaygain_track_gain", "REPLAYGAIN_TRACK_GAIN")),
        "replaygain_album_gain_db": parse_float(tag_value(tags, "replaygain_album_gain", "REPLAYGAIN_ALBUM_GAIN")),
        "replaygain_track_peak": parse_float(tag_value(tags, "replaygain_track_peak", "REPLAYGAIN_TRACK_PEAK")),
        "replaygain_album_peak": parse_float(tag_value(tags, "replaygain_album_peak", "REPLAYGAIN_ALBUM_PEAK")),
    }


def probe_status(codec: str, container: str, fields: dict[str, int | None]) -> str:
    meaningful = any(fields.get(key) is not None for key in ["sample_rate_hz", "bit_depth_bits", "bitrate_bps", "channel_count"])
    if codec != "unknown" and container != "unknown" and meaningful:
        return PROBE_STATUS_OK
    return PROBE_STATUS_PARTIAL


def technical_profile_from_media(path: Path | str, media: Any = None, error: BaseException | str | None = None) -> dict[str, Any]:
    size = file_size_bytes(path)
    if error is not None or media is None:
        return {
            "probe_status": PROBE_STATUS_FAILED if error is not None else PROBE_STATUS_PARTIAL,
            "probe_source": PROBE_SOURCE,
            "probe_version": PROBE_VERSION,
            "codec": "unknown",
            "container": normalize_container(path, media),
            "is_lossless": None,
            "sample_rate_hz": None,
            "bit_depth_bits": None,
            "bitrate_bps": None,
            "channel_count": None,
            "file_size_bytes": size,
            "replaygain_track_gain_db": None,
            "replaygain_album_gain_db": None,
            "replaygain_track_peak": None,
            "replaygain_album_peak": None,
            "probe_error_code": bounded_error_code(error),
            "probed_at": utc_now(),
        }

    info = getattr(media, "info", None)
    tags = getattr(media, "tags", None)
    codec = normalize_codec(path, info, media)
    container = normalize_container(path, media)
    fields = stream_properties(info)
    status = probe_status(codec, container, fields)
    return {
        "probe_status": status,
        "probe_source": PROBE_SOURCE,
        "probe_version": PROBE_VERSION,
        "codec": codec,
        "container": container,
        "is_lossless": classify_lossless(codec),
        **fields,
        "file_size_bytes": size,
        **replaygain_values(tags),
        "probe_error_code": None,
        "probed_at": utc_now(),
    }


def profile_status_counts(profiles_by_track_id: dict[int, dict[str, Any]]) -> dict[str, int]:
    counts = {PROBE_STATUS_OK: 0, PROBE_STATUS_PARTIAL: 0, PROBE_STATUS_FAILED: 0}
    for profile in profiles_by_track_id.values():
        status = profile.get("probe_status") or PROBE_STATUS_PARTIAL
        if status not in counts:
            status = PROBE_STATUS_PARTIAL
        counts[status] += 1
    return counts


def upsert_music_technical_profiles(
    db: Session,
    profiles_by_track_id: dict[int, dict[str, Any]],
) -> dict[str, int]:
    track_ids = list(dict.fromkeys(int(track_id) for track_id in profiles_by_track_id.keys()))
    existing: dict[int, models.MusicTechnicalProfile] = {}
    for chunk in chunked(track_ids):
        for row in db.query(models.MusicTechnicalProfile).filter(models.MusicTechnicalProfile.track_id.in_(chunk)).all():
            existing[row.track_id] = row

    created = 0
    updated = 0
    for track_id in track_ids:
        values = dict(profiles_by_track_id[track_id])
        row = existing.get(track_id)
        if row is None:
            row = models.MusicTechnicalProfile(track_id=track_id)
            db.add(row)
            existing[track_id] = row
            created += 1
        else:
            updated += 1
        for field in PROFILE_FIELDS:
            if field in values:
                setattr(row, field, values[field])
        row.probe_source = row.probe_source or PROBE_SOURCE
        row.probe_version = row.probe_version or PROBE_VERSION
    db.flush()
    counts = profile_status_counts(profiles_by_track_id)
    return {
        "profiles_seen": len(track_ids),
        "profiles_created": created,
        "profiles_updated": updated,
        "technical_probe_ok": counts[PROBE_STATUS_OK],
        "technical_probe_partial": counts[PROBE_STATUS_PARTIAL],
        "technical_probe_failed": counts[PROBE_STATUS_FAILED],
    }