from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from sqlalchemy.orm import Session
from .. import models
from ..config import settings
from .path_safety import safe_media_files

MUSIC_EXTENSIONS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav"}


def _tag_value(tags: Any, *keys: str) -> str | None:
    if not tags:
        return None
    for key in keys:
        value = tags.get(key) if hasattr(tags, "get") else None
        if value:
            if isinstance(value, (list, tuple)):
                value = value[0]
            text = str(value).strip()
            if text:
                return text
    return None


def read_metadata(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"duration_seconds": None}
    try:
        from mutagen import File
        media = File(path, easy=True)
        if media is None:
            return result
        result["duration_seconds"] = getattr(getattr(media, "info", None), "length", None)
        tags = media.tags
        result.update({"title": _tag_value(tags, "title"), "artist": _tag_value(tags, "artist"), "album": _tag_value(tags, "album"), "album_artist": _tag_value(tags, "albumartist", "album artist"), "genre": _tag_value(tags, "genre"), "year": _tag_value(tags, "date", "year")})
    except Exception:
        pass
    if result.get("year"):
        try:
            result["year"] = int(str(result["year"])[:4])
        except ValueError:
            result["year"] = None
    return result


def scan_music(db: Session) -> dict[str, Any]:
    roots = [Path(settings.MUSIC_MP3_ROOT), Path(settings.MUSIC_FLAC_ROOT), Path(settings.MUSIC_DISCOGRAPHIES_ROOT)]
    existing_roots = [root for root in roots if root.is_dir()]
    result: dict[str, Any] = {"status": "ok", "tracks_scanned": 0, "tracks_added": 0, "tracks_updated": 0, "roots_scanned": [str(root) for root in existing_roots], "skipped_roots": [str(root) for root in roots if not root.is_dir()], "errors": []}
    music_root = Path(settings.MUSIC_ROOT)
    for root in existing_roots:
        for path in safe_media_files(root, MUSIC_EXTENSIONS, existing_roots):
            try:
                metadata = read_metadata(path)
                relative_path = str(path.relative_to(music_root)) if path.is_relative_to(music_root) else str(path.relative_to(root))
                data = {"relative_path": relative_path, "title": metadata.get("title") or path.stem, "artist": metadata.get("artist") or path.parent.name or "Unknown Artist", "album": metadata.get("album") or path.parent.name or "Unknown Album", "album_artist": metadata.get("album_artist"), "genre": metadata.get("genre"), "year": metadata.get("year"), "duration_seconds": metadata.get("duration_seconds"), "file_ext": path.suffix.lower(), "library_area": "Discographies" if root == Path(settings.MUSIC_DISCOGRAPHIES_ROOT) else "Library", "last_indexed_at": datetime.now(timezone.utc)}
                track = db.query(models.Track).filter(models.Track.path == str(path)).one_or_none()
                if track:
                    for key, value in data.items(): setattr(track, key, value)
                    result["tracks_updated"] += 1
                else:
                    db.add(models.Track(path=str(path), **data)); result["tracks_added"] += 1
                result["tracks_scanned"] += 1
            except Exception as exc:
                result["errors"].append(f"{path}: {exc}")
    db.commit()
    return result
