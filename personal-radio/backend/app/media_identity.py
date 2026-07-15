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

WEAK_MUSIC_IDENTITY_VALUES = {
    "",
    "unknown",
    "unknown artist",
    "unknown album",
    "unknown title",
    "untitled",
    "track",
    "track 1",
    "track 01",
}

RECORDING_TYPE_PATTERNS = [
    ("radio_edit", r"\bradio\s+edit\b"),
    ("instrumental", r"\binstrumental\b"),
    ("acoustic", r"\b(acoustic|unplugged)\b"),
    ("remix", r"\bremix\b"),
    ("live", r"\b(live|live\s+at|live\s+from|live\s+in|concert)\b"),
]

SOURCE_FORMAT_FAMILIES = {
    "flac": "FLAC",
    "mp3": "MP3",
    "m4a": "M4A",
    "aac": "AAC",
    "ogg": "OGG",
    "opus": "OPUS",
    "wav": "WAV",
}


def is_weak_music_identity_value(value: str | None) -> bool:
    normalized = normalize_text(value)
    if normalized in WEAK_MUSIC_IDENTITY_VALUES:
        return True
    return bool(re.fullmatch(r"track\s*0*\d+", normalized))


def _normalized_source_parts(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = str(value).replace("\\", "/")
    normalized = re.sub(r"/+", "/", normalized).strip().strip("/")
    normalized = re.sub(r"^[A-Za-z]:/", "", normalized)
    return [part for part in normalized.split("/") if part and part != "."]


def _source_parent_parts(relative_path: str | None = None, path: str | None = None) -> list[str]:
    parts = _normalized_source_parts(relative_path) or _normalized_source_parts(path)
    if len(parts) <= 1:
        return parts
    return parts[:-1]


def _source_file_stem(relative_path: str | None = None, path: str | None = None) -> str:
    parts = _normalized_source_parts(relative_path) or _normalized_source_parts(path)
    if not parts:
        return ""
    filename = parts[-1]
    return normalize_text(re.sub(r"\.[A-Za-z0-9]{1,8}$", "", filename))


def normalize_music_source_scope(relative_path: str | None = None, path: str | None = None) -> str:
    parts = _source_parent_parts(relative_path, path)
    normalized_parts = [normalize_text(part) for part in parts]
    normalized_parts = [part for part in normalized_parts if part]
    return "/".join(normalized_parts) or "unknown_scope"


def music_source_format_family(file_ext: str | None = None, path: str | None = None) -> str:
    ext = str(file_ext or "").strip().lower().lstrip(".")
    if not ext and path:
        match = re.search(r"\.([A-Za-z0-9]{1,8})$", str(path))
        ext = match.group(1).lower() if match else ""
    return SOURCE_FORMAT_FAMILIES.get(ext, "UNKNOWN")


def infer_music_recording_type(title: str | None = None, album: str | None = None) -> str:
    combined = " ".join(part for part in [title, album] if part)
    normalized = normalize_text(combined)
    for recording_type, pattern in RECORDING_TYPE_PATTERNS:
        if re.search(pattern, normalized):
            return recording_type
    return "unknown"


def music_recording_version_hint(title: str | None = None, album: str | None = None) -> str:
    recording_type = infer_music_recording_type(title, album)
    return "" if recording_type == "unknown" else recording_type


def normalize_music_recording_title(title: str | None) -> str:
    normalized = normalize_text(title)
    replacements = [
        r"\bradio\s+edit\b",
        r"\binstrumental\b",
        r"\b(acoustic|unplugged)\b",
        r"\bremix\b",
        r"\blive\b",
    ]
    for pattern in replacements:
        normalized = re.sub(pattern, " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def music_release_identity_key(
    album_artist: str | None,
    title: str | None,
    *,
    source_scope: str | None = None,
) -> str:
    normalized_artist = normalize_people(album_artist)
    normalized_title = normalize_text(title)
    weak = is_weak_music_identity_value(normalized_artist) or is_weak_music_identity_value(normalized_title)
    parts = [
        "music_release_identity",
        normalized_artist or "unknown_artist",
        normalized_title or "unknown_release",
    ]
    if weak:
        parts.append(f"scope:{normalize_text(source_scope) or 'unknown_scope'}")
    return "|".join(parts)


def music_edition_identity_key(release_identity_key: str, source_scope: str | None) -> str:
    return "|".join([
        "music_edition_identity",
        release_identity_key,
        normalize_text(source_scope) or "unknown_scope",
    ])


def music_recording_identity_key(
    artist: str | None,
    title: str | None,
    recording_type: str | None = None,
    duration_seconds: float | int | None = None,
    *,
    source_scope: str | None = None,
    relative_path: str | None = None,
    path: str | None = None,
) -> str:
    normalized_artist = normalize_people(artist)
    normalized_title = normalize_music_recording_title(title)
    resolved_recording_type = recording_type or infer_music_recording_type(title)
    bucket = duration_bucket(duration_seconds, tolerance=10)
    weak = is_weak_music_identity_value(normalized_artist) or is_weak_music_identity_value(normalized_title)
    parts = [
        "music_recording_identity",
        normalized_artist or "unknown_artist",
        normalized_title or "unknown_recording",
        resolved_recording_type or "unknown",
        bucket,
    ]
    if weak:
        parts.extend([
            f"scope:{normalize_text(source_scope) or 'unknown_scope'}",
            f"file:{_source_file_stem(relative_path, path) or 'unknown_file'}",
        ])
    return "|".join(parts)
