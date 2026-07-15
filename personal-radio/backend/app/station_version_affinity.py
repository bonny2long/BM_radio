from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.orm import Session

from . import models

FOCUSED_MODES = {"live", "acoustic", "remix", "instrumental"}
NEUTRAL_TYPES = {"unknown", "radio_edit", "studio", "standard", ""}

PRIMARY_BOOST = 1.2
ADJACENT_BOOST = 0.55
NEUTRAL_ADJUSTMENT = 0.0
OTHER_PENALTY = -0.2
LEGACY_ADJUSTMENT = 0.0

AFFINITY_MATRIX: dict[str, dict[str, tuple[str, ...]]] = {
    "live": {
        "primary": ("live",),
        "adjacent": ("acoustic",),
        "neutral": ("unknown", "radio_edit", "studio", "standard", ""),
        "other": ("remix", "instrumental"),
    },
    "acoustic": {
        "primary": ("acoustic",),
        "adjacent": ("live",),
        "neutral": ("unknown", "radio_edit", "studio", "standard", ""),
        "other": ("remix", "instrumental"),
    },
    "remix": {
        "primary": ("remix",),
        "adjacent": (),
        "neutral": ("unknown", "radio_edit", "studio", "standard", ""),
        "other": ("live", "acoustic", "instrumental"),
    },
    "instrumental": {
        "primary": ("instrumental",),
        "adjacent": ("acoustic",),
        "neutral": ("unknown", "radio_edit", "studio", "standard", ""),
        "other": ("live", "remix"),
    },
}

TIER_SCORE = {
    "primary": PRIMARY_BOOST,
    "adjacent": ADJACENT_BOOST,
    "neutral": NEUTRAL_ADJUSTMENT,
    "other": OTHER_PENALTY,
    "legacy_unknown": LEGACY_ADJUSTMENT,
}

TIER_LABEL = {
    "primary": "version_affinity_primary",
    "adjacent": "version_affinity_adjacent",
    "neutral": "version_affinity_neutral",
    "other": "version_affinity_other",
    "legacy_unknown": "version_affinity_legacy",
}

TIER_ORDER = ["primary", "adjacent", "neutral", "other", "legacy_unknown"]
FOCUSED_TARGETS = [
    "primary", "primary", "primary", "primary", "primary", "primary",
    "adjacent", "adjacent",
    "neutral", "neutral",
    "other",
    "legacy_unknown",
]


@dataclass(frozen=True)
class VersionAffinityIntent:
    mode: str
    source: str
    seed_recording_id: int | None
    seed_recording_type: str | None
    primary_types: tuple[str, ...]
    adjacent_types: tuple[str, ...]
    neutral_types: tuple[str, ...]

    def to_debug_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_recording_type(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", "_").split())


def _has_table(db: Session, table_name: str) -> bool:
    return sqlalchemy_inspect(db.get_bind()).has_table(table_name)


def seed_recording_type(db: Session, seed_track: models.Track | None) -> tuple[int | None, str | None]:
    if seed_track is None or not _has_table(db, "music_track_identities") or not _has_table(db, "music_recordings"):
        return None, None
    row = (
        db.query(models.MusicTrackIdentity.recording_id, models.MusicRecording.recording_type)
        .join(models.MusicRecording, models.MusicRecording.id == models.MusicTrackIdentity.recording_id)
        .filter(models.MusicTrackIdentity.track_id == seed_track.id)
        .one_or_none()
    )
    if row is None:
        return None, None
    return int(row.recording_id), row.recording_type


def derive_version_affinity_intent(db: Session, seed_track: models.Track | None) -> VersionAffinityIntent:
    recording_id, recording_type = seed_recording_type(db, seed_track)
    normalized = normalize_recording_type(recording_type)
    if normalized in FOCUSED_MODES:
        matrix = AFFINITY_MATRIX[normalized]
        return VersionAffinityIntent(
            mode=normalized,
            source="seed_recording_type",
            seed_recording_id=recording_id,
            seed_recording_type=normalized,
            primary_types=matrix["primary"],
            adjacent_types=matrix["adjacent"],
            neutral_types=matrix["neutral"],
        )
    return VersionAffinityIntent(
        mode="balanced",
        source="default",
        seed_recording_id=recording_id,
        seed_recording_type=normalized or None,
        primary_types=(),
        adjacent_types=(),
        neutral_types=tuple(sorted(NEUTRAL_TYPES)),
    )


def candidate_recording_type(track: models.Track | None) -> str | None:
    value = getattr(track, "_station_recording_type", None)
    normalized = normalize_recording_type(value)
    return normalized or None


def classify_affinity_tier(track: models.Track | None, intent: VersionAffinityIntent) -> str:
    recording_id = getattr(track, "_station_recording_id", None)
    recording_type = candidate_recording_type(track)
    if recording_id is None:
        return "legacy_unknown"
    if intent.mode == "balanced":
        return "neutral"
    matrix = AFFINITY_MATRIX.get(intent.mode, {})
    if recording_type in matrix.get("primary", ()):
        return "primary"
    if recording_type in matrix.get("adjacent", ()):
        return "adjacent"
    if recording_type in matrix.get("neutral", ()) or recording_type is None:
        return "neutral"
    return "other"


def explain_score_part(label: str, value: float, detail: str | None = None) -> dict[str, Any]:
    part: dict[str, Any] = {"label": label, "value": round(value, 3)}
    if detail:
        part["detail"] = detail
    return part


def apply_version_affinity(track: models.Track, intent: VersionAffinityIntent) -> dict[str, Any]:
    tier = classify_affinity_tier(track, intent)
    value = 0.0 if intent.mode == "balanced" else TIER_SCORE[tier]
    label = TIER_LABEL[tier]
    detail = intent.mode if intent.mode != "balanced" else "balanced"
    setattr(track, "_station_version_affinity_mode", intent.mode)
    setattr(track, "_station_version_affinity_tier", tier)
    setattr(track, "_station_version_affinity_score", value)
    return explain_score_part(label, value, detail)


def distribution_for_tracks(tracks: Iterable[models.Track], intent: VersionAffinityIntent) -> dict[str, int]:
    counts = Counter(classify_affinity_tier(track, intent) for track in tracks)
    return {tier: int(counts.get(tier, 0)) for tier in TIER_ORDER}


def affinity_summary(intent: VersionAffinityIntent, candidates: list[models.Track], selected: list[models.Track]) -> dict[str, Any]:
    candidate_distribution = distribution_for_tracks(candidates, intent)
    selected_distribution = distribution_for_tracks(selected, intent)
    fallback_selected = selected_distribution["neutral"] + selected_distribution["other"] + selected_distribution["legacy_unknown"]
    focused_selected = selected_distribution["primary"] + selected_distribution["adjacent"]
    summary = intent.to_debug_dict()
    summary.update({
        "candidate_distribution": candidate_distribution,
        "selected_distribution": selected_distribution,
        "fallback_used": bool(intent.mode != "balanced" and fallback_selected > 0),
        "focused_selected": focused_selected,
        "fallback_selected": fallback_selected,
    })
    return summary


def affinity_warnings(summary: dict[str, Any]) -> list[str]:
    if summary.get("mode") == "balanced":
        return []
    candidate_distribution = summary.get("candidate_distribution") or {}
    selected_distribution = summary.get("selected_distribution") or {}
    warnings: list[str] = []
    primary_candidates = int(candidate_distribution.get("primary", 0) or 0)
    if primary_candidates == 0:
        warnings.append("version_affinity_no_primary_candidates")
    elif primary_candidates < 3:
        warnings.append("version_affinity_primary_sparse")
    selected_total = sum(int(selected_distribution.get(tier, 0) or 0) for tier in TIER_ORDER)
    fallback = int(summary.get("fallback_selected", 0) or 0)
    if selected_total and fallback / selected_total >= 0.5:
        warnings.append("version_affinity_fallback_heavy")
    return warnings[:3]


def _entry_score(entry: tuple[float, models.Track]) -> float:
    return float(entry[0])


def _entry_track(entry: tuple[float, models.Track]) -> models.Track:
    return entry[1]


def affinity_sort_entries(entries: list[tuple[float, models.Track]], intent: VersionAffinityIntent) -> list[tuple[float, models.Track]]:
    if intent.mode == "balanced" or not entries:
        return entries
    groups: dict[str, list[tuple[float, models.Track]]] = {tier: [] for tier in TIER_ORDER}
    for entry in entries:
        groups[classify_affinity_tier(_entry_track(entry), intent)].append(entry)
    for tier in TIER_ORDER:
        groups[tier].sort(key=_entry_score, reverse=True)

    out: list[tuple[float, models.Track]] = []
    used_ids: set[int] = set()
    cursor = 0
    while len(out) < len(entries) and any(groups.values()):
        wanted = FOCUSED_TARGETS[cursor % len(FOCUSED_TARGETS)]
        cursor += 1
        order = [wanted] + [tier for tier in TIER_ORDER if tier != wanted]
        for tier in order:
            if groups[tier]:
                entry = groups[tier].pop(0)
                track_id = getattr(_entry_track(entry), "id", None)
                if track_id in used_ids:
                    continue
                if track_id is not None:
                    used_ids.add(track_id)
                out.append(entry)
                break
    return out


def apply_affinity_to_tiers(tiers: dict[str, list[tuple[float, models.Track]]], intent: VersionAffinityIntent) -> dict[str, list[tuple[float, models.Track]]]:
    if intent.mode == "balanced":
        return tiers
    return {tier: affinity_sort_entries(entries, intent) for tier, entries in tiers.items()}