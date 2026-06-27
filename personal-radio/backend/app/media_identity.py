import re
import unicodedata


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[?']", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(the|a|an)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_people(value: str | None) -> str:
    return normalize_text(value)


def normalize_year(value: str | int | None) -> str:
    if value is None:
        return ""
    match = re.search(r"(19|20)\d{2}", str(value))
    return match.group(0) if match else ""


def duration_bucket(seconds: float | int | None, tolerance: int = 10) -> str:
    if not seconds:
        return ""
    try:
        sec = int(float(seconds))
    except Exception:
        return ""
    return str(round(sec / tolerance) * tolerance)


def music_track_release_key(
    artist: str | None,
    album: str | None,
    title: str | None,
    year: str | int | None = None,
    track_number: int | str | None = None,
) -> str:
    return "|".join([
        "music_track_release",
        normalize_people(artist),
        normalize_text(album),
        normalize_year(year),
        str(track_number or "").strip(),
        normalize_text(title),
    ])


def music_duplicate_candidate_key(
    artist: str | None,
    album: str | None,
    title: str | None,
    year: str | int | None = None,
    duration_seconds: float | int | None = None,
) -> str:
    return "|".join([
        "music_duplicate_candidate",
        normalize_people(artist),
        normalize_text(album),
        normalize_year(year),
        normalize_text(title),
        duration_bucket(duration_seconds, tolerance=5),
    ])


def music_possible_duplicate_key(
    artist: str | None,
    album: str | None,
    title: str | None,
    year: str | int | None = None,
) -> str:
    return "|".join([
        "music_possible_duplicate",
        normalize_people(artist),
        normalize_text(album),
        normalize_year(year),
        normalize_text(title),
    ])


def music_recording_key(
    artist: str | None,
    title: str | None,
    duration_seconds: float | int | None = None,
) -> str:
    return "|".join([
        "music_recording",
        normalize_people(artist),
        normalize_text(title),
        duration_bucket(duration_seconds, tolerance=5),
    ])


def music_album_release_key(
    album_artist: str | None,
    album: str | None,
    year: str | int | None = None,
    track_count: int | None = None,
) -> str:
    return "|".join([
        "music_album_release",
        normalize_people(album_artist),
        normalize_text(album),
        normalize_year(year),
        str(track_count or ""),
    ])


def audiobook_work_key(title: str | None, author: str | None) -> str:
    return "|".join(["audiobook_work", normalize_text(title), normalize_people(author)])


def audiobook_edition_key(
    title: str | None,
    author: str | None,
    narrator: str | None = None,
    duration_seconds: float | int | None = None,
    chapter_count: int | None = None,
) -> str:
    return "|".join([
        "audiobook_edition",
        normalize_text(title),
        normalize_people(author),
        normalize_people(narrator),
        duration_bucket(duration_seconds, tolerance=60),
        str(chapter_count or ""),
    ])


def book_work_key(title: str | None, author: str | None) -> str:
    return "|".join(["book_work", normalize_text(title), normalize_people(author)])


def book_edition_key(
    title: str | None,
    author: str | None,
    format: str | None = None,
    year: str | int | None = None,
) -> str:
    return "|".join([
        "book_edition",
        normalize_text(title),
        normalize_people(author),
        normalize_text(format),
        normalize_year(year),
    ])
