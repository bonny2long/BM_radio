from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import radio_genres
from app.db import SessionLocal
from app.models import Track
from app.queue_contracts import StationQueueRequest
from app.station_engine import build_station_debug

BAD_ARTISTS = {"aphex twin", "john coltrane", "michael jackson", "pink floyd", "daft punk"}
TARGET_GENRE = "Hip-Hop"


def norm(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def selected_tracks(db, debug: dict) -> list[Track]:
    tracks: list[Track] = []
    for row in debug.get("selected", []):
        track = db.get(Track, row.get("track_id"))
        if track:
            tracks.append(track)
    return tracks


def assert_no_bad_artists(debug: dict, label: str) -> None:
    artists = {norm(row.get("artist")) for row in debug.get("selected", [])}
    offenders = sorted(artists & BAD_ARTISTS)
    assert not offenders, f"{label}: unrelated artists selected: {offenders}"


def assert_hiphop_compatible(debug: dict, label: str) -> None:
    offenders = []
    for row in debug.get("selected", []):
        profile = row.get("profile") or {}
        genre = profile.get("primary_genre")
        if not radio_genres.same_genre_family(TARGET_GENRE, genre):
            offenders.append((row.get("artist"), row.get("title"), genre))
    assert not offenders, f"{label}: non-compatible genres selected: {offenders[:8]}"


def assert_not_album_order(tracks: list[Track], label: str) -> None:
    run: list[Track] = []
    last_key: tuple[str, str] | None = None
    for track in tracks:
        key = (norm(track.artist), norm(track.album))
        if key == last_key:
            run.append(track)
        else:
            run = [track]
            last_key = key
        if len(run) >= 4:
            nums = [getattr(t, "track_number", None) for t in run[-4:]]
            if all(isinstance(n, int) for n in nums) and nums == sorted(nums) and len(set(nums)) == len(nums):
                names = [t.title for t in run[-4:]]
                raise AssertionError(f"{label}: strict album order run detected: {names}")


def skew_it_track(db) -> Track:
    track = (
        db.query(Track)
        .filter(Track.artist == "OutKast", Track.title.ilike("%Skew It On The Bar-B%"))
        .order_by(Track.id)
        .first()
    )
    assert track is not None, "Missing OutKast - Skew It On The Bar-B seed track"
    return track


def main() -> None:
    db = SessionLocal()
    try:
        artist_debug = build_station_debug(StationQueueRequest(type="artist", seed_value="OutKast", limit=25), db)
        artist_tracks = selected_tracks(db, artist_debug)
        artist_names = {norm(t.artist) for t in artist_tracks}
        assert "outkast" in artist_names, "artist radio did not include OutKast"
        assert_no_bad_artists(artist_debug, "OutKast artist radio")
        assert_hiphop_compatible(artist_debug, "OutKast artist radio")
        assert_not_album_order(artist_tracks, "OutKast artist radio")

        genre_debug = build_station_debug(StationQueueRequest(type="genre", seed_value="Hip-Hop", limit=25), db)
        assert_no_bad_artists(genre_debug, "Hip-Hop genre radio")
        assert_hiphop_compatible(genre_debug, "Hip-Hop genre radio")

        seed = skew_it_track(db)
        song_debug = build_station_debug(StationQueueRequest(type="song", seed_track_id=seed.id, limit=25), db)
        song_tracks = selected_tracks(db, song_debug)
        assert seed.id not in {t.id for t in song_tracks}, "song radio selected the seed track"
        assert song_tracks, "song radio returned no coherent tracks"
        assert_no_bad_artists(song_debug, "Skew It song radio")
        assert_hiphop_compatible(song_debug, "Skew It song radio")
        assert float(song_debug.get("summary", {}).get("exploration_percent", 0)) <= 15, song_debug.get("summary")
        assert_not_album_order(song_tracks, "Skew It song radio")

        print("ok: station logic M5")
        print("artist_warnings", sorted(artist_debug.get("warnings", [])))
        print("genre_warnings", sorted(genre_debug.get("warnings", [])))
        print("song_warnings", sorted(song_debug.get("warnings", [])))
    finally:
        db.close()


if __name__ == "__main__":
    main()
