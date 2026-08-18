from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.routes.audiobooks import ProgressUpdate, as_detail, finish_audiobook, reset_audiobook, update_progress


def main() -> None:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    book = models.Audiobook(path="/books/long", relative_path="long", title="Long Book", author="Author", status="available")
    db.add(book)
    db.flush()
    chapters = [
        models.AudiobookChapter(audiobook_id=book.id, path=f"/books/long/{index}.m4b", relative_path=f"long/{index}.m4b", title=f"Part {index}", chapter_number=index, duration_seconds=7200, sort_order=index)
        for index in (1, 2)
    ]
    db.add_all(chapters)
    db.commit()
    base = datetime(2026, 8, 18, 12, tzinfo=timezone.utc)

    first = update_progress(book.id, ProgressUpdate(chapter_id=chapters[0].id, position_seconds=65, progress_percent=1, checkpointed_at=base), db)
    assert first["status"] == "ok"
    assert db.query(models.AudiobookProgress).filter_by(audiobook_id=book.id).count() == 1

    # Simulate more than two hours of listener activity with bounded 3-minute
    # checkpoints. Each save updates the authoritative row rather than adding history.
    for index in range(1, 42):
        elapsed = index * 180
        chapter = chapters[0] if elapsed < 7200 else chapters[1]
        position = elapsed if chapter is chapters[0] else elapsed - 7200
        result = update_progress(book.id, ProgressUpdate(chapter_id=chapter.id, position_seconds=position, progress_percent=min(100, position / 72), checkpointed_at=base + timedelta(seconds=elapsed)), db)
        assert result["status"] in {"ok", "ignored"}, result
    assert db.query(models.AudiobookProgress).filter_by(audiobook_id=book.id).count() == 1
    latest = as_detail(book)["latest_progress"]
    assert latest["chapter_id"] == chapters[1].id and abs(latest["position_seconds"] - 180) < 0.01, latest

    stale = update_progress(book.id, ProgressUpdate(chapter_id=chapters[0].id, position_seconds=20, progress_percent=1, checkpointed_at=base + timedelta(minutes=2)), db)
    assert stale["status"] == "stale", stale
    assert as_detail(book)["latest_progress"]["chapter_id"] == chapters[1].id

    before_missing = as_detail(book)["latest_progress"]
    chapters[1].library_availability = "unavailable"
    db.commit()
    try:
        update_progress(book.id, ProgressUpdate(chapter_id=chapters[1].id, position_seconds=240, progress_percent=3, checkpointed_at=base + timedelta(hours=3)), db)
        raise AssertionError("unavailable chapter update was accepted")
    except HTTPException as exc:
        assert exc.status_code == 409
    chapters[1].library_availability = "available"
    db.commit()
    assert as_detail(book)["latest_progress"]["position_seconds"] == before_missing["position_seconds"]

    finished = finish_audiobook(book.id, db)
    assert finished["book_status"] == "finished"
    assert as_detail(book)["latest_progress"]["completion_state"] == "finished"
    replay = update_progress(book.id, ProgressUpdate(chapter_id=chapters[0].id, position_seconds=20, progress_percent=1, checkpointed_at=datetime.now(timezone.utc) + timedelta(days=1)), db)
    assert replay["book_status"] == "in_progress"
    assert db.query(models.AudiobookProgress).filter_by(audiobook_id=book.id).count() == 1

    reset = reset_audiobook(book.id, db)
    assert reset["progress_deleted"] == 1 and reset["latest_progress"] is None
    print("PASS: authoritative audiobook progress, ordering, long-session, failure, completion, and replay")


if __name__ == "__main__":
    main()
