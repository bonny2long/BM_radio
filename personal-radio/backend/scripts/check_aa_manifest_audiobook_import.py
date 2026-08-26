from __future__ import annotations

import json
import shutil
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.scanner import audiobook_scanner


def approved(value):
    return {"approval_state": "approved", "value": value}


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="bm-aa-audiobook-manifest-"))
    if base.exists():
        shutil.rmtree(base)
    root = base / "Audiobooks" / "Library"
    book = root / "Wrong Author" / "Wrong Folder"
    metadata = book / "metadata"
    metadata.mkdir(parents=True)
    virtual_chapter = book / "01 Chapter.mp3"
    (metadata / "audiobook.json").write_text(json.dumps({
        "metadata_version": "test-1",
        "metadata_contract": {"fields": {
            "title": approved("Star Wars Darth Bane Trilogy"),
            "author": approved("Drew Karpyshyn"),
            "year": approved("2012"),
            "narrator": approved("Jonathan Davis"),
        }},
    }), encoding="utf-8")

    settings.AUDIOBOOKS_ROOT = str(root)
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    original_safe_media_files = audiobook_scanner.safe_media_files
    original_read_metadata = audiobook_scanner.read_metadata
    audiobook_scanner.safe_media_files = lambda scan_root, _extensions, _roots: [virtual_chapter] if scan_root == root else []
    audiobook_scanner.read_metadata = lambda _path: {
        "duration_seconds": 3600.0,
        "title": "Chapter 1",
        "artist": "Wrong Author",
        "album": "Wrong Folder",
        "year": None,
    }
    try:
        result = audiobook_scanner.scan_audiobooks(db)
    finally:
        audiobook_scanner.safe_media_files = original_safe_media_files
        audiobook_scanner.read_metadata = original_read_metadata
    assert result["errors"] == [], result["errors"]
    audiobook = db.query(models.Audiobook).one()
    assert audiobook.title == "Star Wars Darth Bane Trilogy", audiobook.title
    assert audiobook.author == "Drew Karpyshyn", audiobook.author
    assert audiobook.year == 2012, audiobook.year
    assert audiobook.narrator == "Jonathan Davis", audiobook.narrator
    assert audiobook.metadata_source == "archive_assistant_manifest", audiobook.metadata_source
    assert not virtual_chapter.exists()
    db.close()
    engine.dispose()
    shutil.rmtree(base, ignore_errors=True)
    print("ok: AA audiobook manifest import")


if __name__ == "__main__":
    main()
