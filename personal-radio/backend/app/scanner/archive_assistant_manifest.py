from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .path_safety import is_approved_path

AA_METADATA_FILENAMES = (
    "music-album.json",
    "discography.json",
    "album.json",
    "audiobook.json",
    "metadata.json",
    "move_manifest.json",
)

PLACEHOLDERS = {
    "",
    "unknown",
    "unknown artist",
    "unknown album",
    "unknown year",
    "missing",
    "none",
    "null",
}


def clean_value(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = " ".join(value.strip().split())
        return None if text.lower() in PLACEHOLDERS else text
    if isinstance(value, (list, tuple)):
        values = [clean_value(item) for item in value]
        values = [item for item in values if item not in (None, "", [], {})]
        return values or None
    if isinstance(value, dict):
        for key in ("value", "name", "title", "display", "text"):
            if key in value:
                nested = clean_value(value.get(key))
                if nested is not None:
                    return nested
        return value or None
    return value


def approved_envelope_value(envelope: dict | None) -> Any | None:
    if not isinstance(envelope, dict):
        return clean_value(envelope)
    approved = envelope.get("approved") is True or envelope.get("approval_state") in {"approved", "inherited"}
    if not approved:
        return None
    return clean_value(envelope.get("value"))


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _inside_any_root(path: Path, roots: list[Path]) -> Path | None:
    try:
        resolved = path.resolve()
    except OSError:
        return None
    for root in roots:
        try:
            root_resolved = root.resolve()
            resolved.relative_to(root_resolved)
            return root_resolved
        except (ValueError, OSError):
            continue
    return None


def find_aa_metadata_files(media_file: Path, final_roots: list[Path]) -> list[Path]:
    root = _inside_any_root(media_file, final_roots)
    if not root or not is_approved_path(media_file, final_roots):
        return []

    files: list[Path] = []
    seen: set[str] = set()
    folder = media_file if media_file.is_dir() else media_file.parent
    for current in [folder, *folder.parents]:
        try:
            current.resolve().relative_to(root)
        except (ValueError, OSError):
            break
        for name in AA_METADATA_FILENAMES:
            for candidate in (current / "metadata" / name, current / name):
                key = str(candidate.resolve()) if candidate.exists() else str(candidate)
                if key in seen:
                    continue
                seen.add(key)
                if candidate.is_file() and is_approved_path(candidate, final_roots):
                    files.append(candidate)
        if current == root:
            break
    return files


def load_aa_manifest_context(media_file: Path, final_roots: list[Path], cache: dict[str, Any] | None = None) -> dict[str, Any]:
    cache = cache if cache is not None else {}
    manifest_files = find_aa_metadata_files(media_file, final_roots)
    manifests: list[dict[str, Any]] = []
    for file in manifest_files:
        key = str(file.resolve())
        data = cache.get(key)
        if data is None:
            data = _load_json(file)
            cache[key] = data
        if data:
            manifests.append({"path": str(file), "name": file.name, "data": data})
    return {
        "media_file": str(media_file),
        "manifest_files": manifest_files,
        "manifests": manifests,
        "source_manifest_path": str(manifest_files[0]) if manifest_files else None,
    }


def _contract_fields(data: dict[str, Any]) -> dict[str, Any]:
    contract = data.get("metadata_contract")
    if isinstance(contract, dict) and isinstance(contract.get("fields"), dict):
        return contract["fields"]
    metadata_json = data.get("metadata_json")
    if isinstance(metadata_json, dict):
        contract = metadata_json.get("metadata_contract")
        if isinstance(contract, dict) and isinstance(contract.get("fields"), dict):
            return contract["fields"]
    return {}


def _approved_field(data: dict[str, Any], *keys: str) -> Any | None:
    fields = _contract_fields(data)
    for key in keys:
        value = approved_envelope_value(fields.get(key))
        if value is not None:
            return value
    return None


def _nested(data: dict[str, Any], *path: str) -> Any | None:
    current: Any = data
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return clean_value(current)


def _first_from_manifests(context: dict[str, Any], getter) -> Any | None:
    for item in context.get("manifests", []):
        value = getter(item.get("data") or {})
        if value is not None:
            return value
    return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"(?:19|20)\d{2}", str(value))
    return int(match.group(0)) if match else None


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _track_number(value: Any) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d{1,3}", str(value))
    return int(match.group(0)) if match else None


def _track_number_from_name(path: Path) -> int | None:
    match = re.match(r"^\D*(\d{1,3})(?:\D|$)", path.stem)
    return int(match.group(1)) if match else None


def _track_title_from_profile(profile: dict[str, Any]) -> Any | None:
    nested = profile.get("track_profile") if isinstance(profile.get("track_profile"), dict) else profile
    if not isinstance(nested, dict):
        return None
    return clean_value(
        nested.get("track_title")
        or nested.get("title")
        or _approved_field({"metadata_contract": nested.get("metadata_contract", {})}, "title")
    )


def _track_profile_number(profile: dict[str, Any]) -> int | None:
    nested = profile.get("track_profile") if isinstance(profile.get("track_profile"), dict) else profile
    if not isinstance(nested, dict):
        return None
    return _track_number(
        nested.get("track_number")
        or nested.get("track")
        or nested.get("number")
        or profile.get("track_number")
        or profile.get("track")
    )


def _track_profiles(data: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for value in (
        data.get("track_profiles"),
        _nested(data, "metadata_json", "track_profiles"),
        _nested(data, "release_profile", "track_profiles"),
    ):
        if isinstance(value, list):
            candidates.extend([item for item in value if isinstance(item, dict)])
    return candidates


def _matching_track_profile(context: dict[str, Any], media_file: Path) -> dict[str, Any] | None:
    stem = _norm(media_file.stem)
    number = _track_number_from_name(media_file)
    for item in context.get("manifests", []):
        for profile in _track_profiles(item.get("data") or {}):
            names = [
                profile.get("file_name"),
                profile.get("filename"),
                _nested(profile, "metadata_json", "source_filename"),
                profile.get("source_filename"),
            ]
            if any(name and Path(str(name)).name == media_file.name for name in names):
                return profile
            if any(name and _norm(Path(str(name)).stem) == stem for name in names):
                return profile
        if number is not None:
            for profile in _track_profiles(item.get("data") or {}):
                if _track_profile_number(profile) == number:
                    return profile
    return None


def extract_music_manifest_metadata(context: dict[str, Any], media_file: Path) -> dict[str, Any]:
    source_manifest_path = context.get("source_manifest_path")
    if not source_manifest_path:
        return {"metadata_source": None}

    def field(*keys: str) -> Any | None:
        return _first_from_manifests(context, lambda data: _approved_field(data, *keys))

    def nested(*paths: tuple[str, ...]) -> Any | None:
        for path in paths:
            value = _first_from_manifests(context, lambda data, p=path: _nested(data, *p))
            if value is not None:
                return value
        return None

    profile = _matching_track_profile(context, media_file)
    track_title = _track_title_from_profile(profile) if profile else None
    track_primary_genre = None
    if profile:
        nested_profile = profile.get("track_profile") if isinstance(profile.get("track_profile"), dict) else profile
        track_primary_genre = clean_value(nested_profile.get("primary_genre") or nested_profile.get("genre"))

    year = (
        field("year")
        or nested(("release_profile", "year"), ("release_profile", "release_date"), ("year",))
    )

    genre = (
        field("genre")
        or nested(
            ("release_profile", "genre"),
            ("release_profile", "primary_genre"),
            ("artist_profile", "primary_genre"),
            ("artist_profile", "genre"),
            ("genre",),
        )
    )

    metadata_version = nested(("metadata_version",), ("metadata_contract", "version"))
    manifest_version = nested(("manifest_version",), ("version",), ("move_manifest_version",))
    track_number = _track_profile_number(profile or {}) or _track_number_from_name(media_file)

    out = {
        "metadata_source": "archive_assistant_manifest",
        "source_manifest_path": source_manifest_path,
        "source_manifest_version": manifest_version,
        "source_metadata_version": metadata_version,
        "artist": field("artist") or field("albumartist") or nested(("artist_profile", "artist"), ("artist",)),
        "album_artist": field("albumartist") or field("artist") or nested(("artist_profile", "artist"), ("albumartist",), ("artist",)),
        "album": field("album") or nested(("release_profile", "release_title"), ("album",)),
        "year": _to_int(year),
        "genre": genre,
        "primary_genre": track_primary_genre or genre,
        "title": track_title or field("title"),
        "track_number": track_number,
        "disc_number": _track_number((profile or {}).get("disc_number") or (profile or {}).get("disc")),
    }
    return {key: value for key, value in out.items() if value not in (None, "", [], {})}


def extract_audiobook_manifest_metadata(context: dict[str, Any], audiobook_root: Path) -> dict[str, Any]:
    source_manifest_path = context.get("source_manifest_path")
    if not source_manifest_path:
        return {"metadata_source": None}

    def field(*keys: str) -> Any | None:
        return _first_from_manifests(context, lambda data: _approved_field(data, *keys))

    def nested(*paths: tuple[str, ...]) -> Any | None:
        for path in paths:
            value = _first_from_manifests(context, lambda data, p=path: _nested(data, *p))
            if value is not None:
                return value
        return None

    year = field("year") or nested(("year",), ("metadata_json", "year"))
    out = {
        "metadata_source": "archive_assistant_manifest",
        "source_manifest_path": source_manifest_path,
        "source_manifest_version": nested(("manifest_version",), ("version",), ("move_manifest_version",)),
        "source_metadata_version": nested(("metadata_version",), ("metadata_contract", "version")),
        "title": field("title") or nested(("title",), ("metadata_json", "title")),
        "author": field("author") or nested(("author",), ("metadata_json", "author")),
        "year": _to_int(year),
        "narrator": field("narrator") or nested(("narrator",), ("metadata_json", "narrator")),
        "series": field("series") or nested(("series",), ("metadata_json", "series")),
        "series_index": field("series_index") or nested(("series_index",), ("metadata_json", "series_index")),
        "contained_books": nested(("contained_books",), ("books",), ("metadata_json", "contained_books")) or [],
    }
    return {key: value for key, value in out.items() if value not in (None, "", [], {})}
