from datetime import datetime, timezone
from pathlib import Path
import re
from sqlalchemy.orm import Session
from .. import models
from ..config import settings
from .music_scanner import read_metadata
from .path_safety import safe_media_files

AUDIOBOOK_EXTENSIONS = {".mp3", ".m4b", ".m4a", ".flac", ".aac", ".ogg", ".opus"}


def _natural_key(path: Path):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name)]


def scan_audiobooks(db: Session) -> dict:
    root = Path(settings.AUDIOBOOKS_ROOT)
    result = {"status": "ok", "audiobooks_scanned": 0, "audiobooks_added": 0, "audiobooks_updated": 0, "chapters_scanned": 0, "roots_scanned": [], "skipped_roots": [], "errors": []}
    if not root.is_dir():
        result["skipped_roots"].append(str(root)); return result
    result["roots_scanned"].append(str(root))
    groups: dict[Path, list[Path]] = {}
    for path in safe_media_files(root, AUDIOBOOK_EXTENSIONS, [root]):
        groups.setdefault(root / path.relative_to(root).parts[0], []).append(path)
    for book_path, chapters in groups.items():
        try:
            chapters.sort(key=_natural_key); first_meta = read_metadata(chapters[0])
            data = {"relative_path": str(book_path.relative_to(root)), "title": book_path.name, "author": book_path.parent.name if book_path.parent != root else "Unknown Author", "narrator": None, "series": None, "year": first_meta.get("year"), "duration_seconds": 0.0, "last_indexed_at": datetime.now(timezone.utc)}
            chapter_data = []
            for order, chapter_path in enumerate(chapters, 1):
                metadata = read_metadata(chapter_path); duration = metadata.get("duration_seconds") or 0.0
                data["duration_seconds"] += duration; chapter_data.append((chapter_path, metadata, duration, order))
            book = db.query(models.Audiobook).filter(models.Audiobook.path == str(book_path)).one_or_none()
            if book:
                for key, value in data.items(): setattr(book, key, value)
                db.query(models.AudiobookChapter).filter(models.AudiobookChapter.audiobook_id == book.id).delete(); result["audiobooks_updated"] += 1
            else:
                book = models.Audiobook(path=str(book_path), status="available", favorite=False, **data); db.add(book); db.flush(); result["audiobooks_added"] += 1
            for chapter_path, metadata, duration, order in chapter_data:
                db.add(models.AudiobookChapter(audiobook_id=book.id, path=str(chapter_path), relative_path=str(chapter_path.relative_to(root)), title=metadata.get("title") or chapter_path.stem, chapter_number=order, duration_seconds=duration, sort_order=order))
            result["audiobooks_scanned"] += 1; result["chapters_scanned"] += len(chapters)
        except Exception as exc:
            result["errors"].append(f"{book_path}: {exc}")
    db.commit(); return result
