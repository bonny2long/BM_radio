from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable

from .radio_genres import genre_family, normalize_genre


SPECIALIZED_TYPES = {"live", "acoustic", "remix", "instrumental"}


@dataclass(frozen=True)
class StationQualityMetrics:
    window: int
    logical_duplicates: int
    physical_duplicates: int
    artist_distribution: dict[str, int]
    release_distribution: dict[str, int]
    family_distribution: dict[str, int]
    type_distribution: dict[str, int]
    max_consecutive_artist: int
    max_consecutive_release: int
    rolling_last_9_artist_max: int
    rolling_last_9_release_max: int
    down_selected: int
    favorite_or_up_selected: int
    specialized_share: float

    def to_dict(self) -> dict:
        return asdict(self)


def _duplicates(values: Iterable[object]) -> int:
    materialized = list(values)
    return len(materialized) - len(set(materialized))


def _max_consecutive(values: list[str]) -> int:
    maximum = current = 0
    previous = None
    for value in values:
        current = current + 1 if value == previous else 1
        maximum = max(maximum, current)
        previous = value
    return maximum


def _rolling_max(values: list[str], size: int = 9) -> int:
    if not values:
        return 0
    return max(max(Counter(values[index:index + size]).values()) for index in range(len(values)))


def analyze_station_queue(
    queue: list[dict], *, down_recording_ids: Iterable[int] = (),
    favorite_recording_ids: Iterable[int] = (), up_recording_ids: Iterable[int] = (),
) -> StationQualityMetrics:
    logical = [item.get("recording_id") or f"track:{item.get('id')}" for item in queue]
    physical = [item.get("effective_track_id") or item.get("track_id") or item.get("id") for item in queue]
    artists = [str(item.get("artist") or "") for item in queue]
    releases = [str(item.get("album") or "") for item in queue]
    families = [genre_family(item.get("primary_genre") or item.get("genre")) or "unknown" for item in queue]
    types = [str(item.get("recording_type") or "unknown") for item in queue]
    down = set(down_recording_ids)
    liked = set(favorite_recording_ids) | set(up_recording_ids)
    return StationQualityMetrics(
        window=len(queue),
        logical_duplicates=_duplicates(logical),
        physical_duplicates=_duplicates(physical),
        artist_distribution=dict(Counter(artists)),
        release_distribution=dict(Counter(releases)),
        family_distribution=dict(Counter(families)),
        type_distribution=dict(Counter(types)),
        max_consecutive_artist=_max_consecutive(artists),
        max_consecutive_release=_max_consecutive(releases),
        rolling_last_9_artist_max=_rolling_max(artists),
        rolling_last_9_release_max=_rolling_max(releases),
        down_selected=sum(item.get("recording_id") in down for item in queue),
        favorite_or_up_selected=sum(item.get("recording_id") in liked for item in queue),
        specialized_share=(sum(kind in SPECIALIZED_TYPES for kind in types) / len(types)) if types else 0.0,
    )


def compatibility_share(queue: list[dict], seed_genre: str, *, exact: bool = False) -> float:
    if not queue:
        return 0.0
    if exact:
        seed = normalize_genre(seed_genre)
        matches = sum(normalize_genre(item.get("primary_genre") or item.get("genre")) == seed for item in queue)
    else:
        seed = genre_family(seed_genre)
        matches = sum(genre_family(item.get("primary_genre") or item.get("genre")) == seed for item in queue)
    return matches / len(queue)
