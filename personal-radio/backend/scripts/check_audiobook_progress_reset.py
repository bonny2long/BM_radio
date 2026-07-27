from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.routes.audiobooks import as_detail, reset_audiobook


def main() -> None:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    book = models.Audiobook(path="/books/main", relative_path="main", title="Main Book", author="Author", status="in_progress")
    other = models.Audiobook(path="/books/other", relative_path="other", title="Other Book", author="Author", status="available")
    db.add_all([book, other])
    db.flush()
    chapter1 = models.AudiobookChapter(audiobook_id=book.id, path="/books/main/01.mp3", relative_path="main/01.mp3", title="Chapter 1", chapter_number=1, duration_seconds=100, sort_order=1)
    chapter2 = models.AudiobookChapter(audiobook_id=book.id, path="/books/main/02.mp3", relative_path="main/02.mp3", title="Chapter 2", chapter_number=2, duration_seconds=100, sort_order=2)
    other_chapter = models.AudiobookChapter(audiobook_id=other.id, path="/books/other/01.mp3", relative_path="other/01.mp3", title="Other Chapter", chapter_number=1, duration_seconds=100, sort_order=1)
    db.add_all([chapter1, chapter2, other_chapter])
    db.flush()

    now = datetime.now(timezone.utc)
    db.add(models.AudiobookProgress(audiobook_id=book.id, chapter_id=chapter1.id, position_seconds=40, progress_percent=20, status="in_progress", updated_at=now - timedelta(minutes=5)))
    db.add(models.AudiobookProgress(audiobook_id=book.id, chapter_id=other_chapter.id, position_seconds=80, progress_percent=80, status="in_progress", updated_at=now))
    db.commit()
    db.refresh(book)

    detail = as_detail(book)
    assert detail["latest_progress"] is not None, detail
    assert detail["latest_progress"]["chapter_id"] == chapter1.id, detail["latest_progress"]

    db.add(models.AudiobookProgress(audiobook_id=book.id, chapter_id=chapter2.id, position_seconds=0, progress_percent=0, status="available", updated_at=now + timedelta(minutes=1)))
    db.commit()
    db.refresh(book)
    detail = as_detail(book)
    assert detail["latest_progress"]["chapter_id"] == chapter1.id, detail["latest_progress"]

    db.add(models.AudiobookProgress(audiobook_id=book.id, chapter_id=chapter2.id, position_seconds=1, progress_percent=0.1, status="in_progress", updated_at=now + timedelta(minutes=2)))
    db.commit()
    db.refresh(book)
    detail = as_detail(book)
    assert detail["latest_progress"]["chapter_id"] == chapter1.id, detail["latest_progress"]

    response = reset_audiobook(book.id, db)
    assert response["book_status"] == "available", response
    assert response["progress_deleted"] == 4, response
    assert response["latest_progress"] is None, response
    assert db.query(models.AudiobookProgress).filter_by(audiobook_id=book.id).count() == 0
    db.refresh(book)
    assert book.status == "available", book.status
    assert as_detail(book)["latest_progress"] is None
    print("ok: audiobook progress reset")


if __name__ == "__main__":
    main()