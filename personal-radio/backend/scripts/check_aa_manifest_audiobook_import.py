from __future__ import annotations

import json
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.config import settings
from app.scanner.audiobook_scanner import scan_audiobooks


def approved(value):
    return {"approval_state": "approved", "value": value}


def main() -> None:
    tmp_base = Path(__file__).resolve().parents[1] / "tmp_tests"
    tmp_base.mkdir(exist_ok=True)
    base = tmp_base / "audiobook_manifest"
    if base.exists():
        shutil.rmtree(base)
    root = base / "Audiobooks" / "Library"
    book = root / "Wrong Author" / "Wrong Folder"
    metadata = book / "metadata"
    metadata.mkdir(parents=True)
    (book / "01 Chapter.mp3").write_bytes(b"not real audio")
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
    result = scan_audiobooks(db)
    assert result["errors"] == [], result["errors"]
    audiobook = db.query(models.Audiobook).one()
    assert audiobook.title == "Star Wars Darth Bane Trilogy", audiobook.title
    assert audiobook.author == "Drew Karpyshyn", audiobook.author
    assert audiobook.year == 2012, audiobook.year
    assert audiobook.narrator == "Jonathan Davis", audiobook.narrator
    assert audiobook.metadata_source == "archive_assistant_manifest", audiobook.metadata_source
    print("ok: AA audiobook manifest import")


if __name__ == "__main__":
    main()