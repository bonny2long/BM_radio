from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.config import settings
from app.schema_maintenance import ensure_scan_reconciliation_columns
from app.scanner import audiobook_scanner


ROOT_SETTING_NAMES = ("AUDIOBOOKS_ROOT", "BM_RADIO_AUDIOBOOK_ROOT")


@contextmanager
def temporary_settings(**overrides: object) -> Iterator[None]:
    original = {name: getattr(settings, name) for name in ROOT_SETTING_NAMES if hasattr(settings, name)}
    try:
        for name, value in overrides.items():
            setattr(settings, name, value)
        yield
    finally:
        for name, value in original.items():
            setattr(settings, name, value)


def make_db(base: Path, name: str):
    db_path = base / f"{name}.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    models.Base.metadata.create_all(bind=engine)
    ensure_scan_reconciliation_columns(engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return engine, Session


def configure_root(base: Path, *, exists: bool = True) -> Path:
    root = base / "Audiobooks" / "Library"
    if exists:
        root.mkdir(parents=True, exist_ok=True)
    settings.AUDIOBOOKS_ROOT = str(root)
    settings.BM_RADIO_AUDIOBOOK_ROOT = str(root)
    return root


def write_chapter(path: Path, data: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if data is not None else b"synthetic audiobook fixture")
    return path


def write_sidecar(book: Path, **values: object) -> None:
    meta = book / "metadata"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "audiobook.json").write_text(json.dumps(values), encoding="utf-8")


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def scan(db):
    result = audiobook_scanner.scan_audiobooks(db)
    assert result["scan_run_id"], result
    db.expire_all()
    return result, db.get(models.ScanRun, result["scan_run_id"])


def book_path(root: Path, author: str = "Author", title: str = "Book") -> Path:
    return root / author / title


def create_book(root: Path, author: str = "Author", title: str = "Book", chapters: int = 2, *, narrator: str | None = None, data_prefix: bytes = b"chapter") -> tuple[Path, list[Path]]:
    book = book_path(root, author, title)
    files = []
    for index in range(1, chapters + 1):
        files.append(write_chapter(book / f"{index:02d} Track {index}.mp3", data_prefix + str(index).encode("ascii")))
    if narrator is not None:
        write_sidecar(book, narrator=narrator)
    return book, files


def audiobook_by_path(db, path: Path) -> models.Audiobook:
    row = db.query(models.Audiobook).filter_by(path=str(path)).one_or_none()
    assert row is not None, str(path)
    return row


def chapter_ids(db, audiobook_id: int) -> list[int]:
    return [row.id for row in db.query(models.AudiobookChapter).filter_by(audiobook_id=audiobook_id).order_by(models.AudiobookChapter.sort_order).all()]


def chapters(db, audiobook_id: int) -> list[models.AudiobookChapter]:
    return db.query(models.AudiobookChapter).filter_by(audiobook_id=audiobook_id).order_by(models.AudiobookChapter.sort_order).all()


def case_a_first_successful_scan(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_a")
    with temporary_settings():
        root = configure_root(tmp / "case_a_root")
        book, _ = create_book(root, chapters=2)
        db = Session()
        try:
            result, run = scan(db)
            audio = audiobook_by_path(db, book)
            assert result["status"] == "ok", result
            assert run.status == "succeeded"
            assert db.query(models.Audiobook).count() == 1
            assert audio.library_availability == "available"
            assert audio.last_seen_scan_id == run.id
            assert audio.unavailable_since is None
            assert len(chapter_ids(db, audio.id)) == 2
            assert run.items_discovered == 1
            assert run.items_added == 1
            assert run.items_unavailable == 0
            assert result["audiobooks_unavailable"] == 0
        finally:
            db.close()


def case_b_identical_rescan_preserves_audiobook_id(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_b")
    with temporary_settings():
        root = configure_root(tmp / "case_b_root")
        book, _ = create_book(root)
        db = Session()
        try:
            scan(db)
            first = audiobook_by_path(db, book)
            first_id = first.id
            result, run = scan(db)
            second = audiobook_by_path(db, book)
            assert result["status"] == "ok", result
            assert second.id == first_id
            assert db.query(models.Audiobook).count() == 1
            assert second.last_seen_scan_id == run.id
            assert second.library_availability == "available"
        finally:
            db.close()


def case_c_identical_rescan_preserves_chapter_ids(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_c")
    with temporary_settings():
        root = configure_root(tmp / "case_c_root")
        book, _ = create_book(root)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            first_ids = chapter_ids(db, audio.id)
            scan(db)
            assert chapter_ids(db, audio.id) == first_ids
            assert db.query(models.AudiobookChapter).filter_by(audiobook_id=audio.id).count() == 2
        finally:
            db.close()


def case_d_progress_survives_identical_rescan(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_d")
    with temporary_settings():
        root = configure_root(tmp / "case_d_root")
        book, _ = create_book(root)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            first_chapter = chapters(db, audio.id)[0]
            audio.status = "in_progress"
            progress = models.AudiobookProgress(audiobook_id=audio.id, chapter_id=first_chapter.id, position_seconds=42, progress_percent=21, status="in_progress", updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
            db.add(progress)
            db.commit()
            progress_id = progress.id
            scan(db)
            audio = audiobook_by_path(db, book)
            saved = db.get(models.AudiobookProgress, progress_id)
            assert audio.status == "in_progress"
            assert saved is not None
            assert saved.chapter_id == first_chapter.id
            assert saved.position_seconds == 42
            assert saved.progress_percent == 21
            assert db.get(models.AudiobookChapter, first_chapter.id) is not None
        finally:
            db.close()


def case_e_favorite_survives_rescan(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_e")
    with temporary_settings():
        root = configure_root(tmp / "case_e_root")
        book, _ = create_book(root)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            audio.favorite = True
            db.commit()
            scan(db)
            assert audiobook_by_path(db, book).favorite is True
        finally:
            db.close()


def case_f_playback_event_survives_rescan(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_f")
    with temporary_settings():
        root = configure_root(tmp / "case_f_root")
        book, _ = create_book(root)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            event = models.PlaybackEvent(audiobook_id=audio.id, event_type="start", position_seconds=5)
            db.add(event)
            db.commit()
            event_id = event.id
            scan(db)
            saved = db.get(models.PlaybackEvent, event_id)
            assert saved is not None
            assert saved.audiobook_id == audio.id
        finally:
            db.close()


def case_g_metadata_refresh_preserves_user_state(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_g")
    with temporary_settings():
        root = configure_root(tmp / "case_g_root")
        book, _ = create_book(root, narrator="Narrator One")
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            audio.favorite = True
            audio.status = "in_progress"
            first_ids = chapter_ids(db, audio.id)
            first_chapter = chapters(db, audio.id)[0]
            progress = models.AudiobookProgress(audiobook_id=audio.id, chapter_id=first_chapter.id, position_seconds=88, progress_percent=44, status="in_progress")
            db.add(progress)
            db.commit()
            progress_id = progress.id
            write_sidecar(book, narrator="Narrator Two", series="Series A", year=2026)
            scan(db)
            audio = audiobook_by_path(db, book)
            saved = db.get(models.AudiobookProgress, progress_id)
            assert audio.narrator == "Narrator Two"
            assert audio.series == "Series A"
            assert audio.year == 2026
            assert audio.favorite is True
            assert audio.status == "in_progress"
            assert saved.chapter_id == first_chapter.id
            assert chapter_ids(db, audio.id) == first_ids
        finally:
            db.close()


def case_h_new_chapter_added_without_rebuild(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_h")
    with temporary_settings():
        root = configure_root(tmp / "case_h_root")
        book, _ = create_book(root, chapters=2)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            old_ids = chapter_ids(db, audio.id)
            progress = models.AudiobookProgress(audiobook_id=audio.id, chapter_id=old_ids[0], position_seconds=10, progress_percent=5, status="in_progress")
            db.add(progress)
            db.commit()
            write_chapter(book / "03 Track 3.mp3")
            scan(db)
            new_ids = chapter_ids(db, audio.id)
            assert new_ids[:2] == old_ids
            assert len(new_ids) == 3
            assert db.get(models.AudiobookProgress, progress.id).chapter_id == old_ids[0]
            assert [c.sort_order for c in chapters(db, audio.id)] == [1, 2, 3]
        finally:
            db.close()


def case_i_missing_chapter_not_deleted_yet(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_i")
    with temporary_settings():
        root = configure_root(tmp / "case_i_root")
        book, files = create_book(root, chapters=3)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            ids = chapter_ids(db, audio.id)
            progress = models.AudiobookProgress(audiobook_id=audio.id, chapter_id=ids[1], position_seconds=10, progress_percent=5, status="in_progress")
            db.add(progress)
            db.commit()
            files[1].unlink()
            result, run = scan(db)
            assert result["status"] == "ok", result
            assert run.status == "succeeded"
            assert chapter_ids(db, audio.id) == ids
            assert db.get(models.AudiobookProgress, progress.id) is not None
        finally:
            db.close()


def case_j_exact_path_not_deleted_by_duplicate_suppression(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_j")
    with temporary_settings():
        root = configure_root(tmp / "case_j_root")
        other_book, _ = create_book(root, author="Author", title="Other Copy", chapters=2)
        exact_book, _ = create_book(root, author="Author", title="Exact Copy", chapters=2)
        db = Session()
        try:
            other = models.Audiobook(path=str(other_book), relative_path="Author/Other Copy", title="Same Work", author="Author", narrator="Narrator", library_availability="available")
            exact = models.Audiobook(path=str(exact_book), relative_path="Author/Exact Copy", title="Same Work", author="Author", narrator="Narrator", status="in_progress", favorite=True, library_availability="available")
            db.add_all([other, exact])
            db.flush()
            chapter = models.AudiobookChapter(audiobook_id=exact.id, path=str(exact_book / "01 Track 1.mp3"), relative_path="Author/Exact Copy/01 Track 1.mp3", title="Chapter 1", chapter_number=1, duration_seconds=0, sort_order=1)
            db.add(chapter)
            db.flush()
            progress = models.AudiobookProgress(audiobook_id=exact.id, chapter_id=chapter.id, position_seconds=11, progress_percent=7, status="in_progress")
            db.add(progress)
            db.commit()
            exact_id = exact.id
            progress_id = progress.id
            scan(db)
            saved = db.get(models.Audiobook, exact_id)
            assert saved is not None
            assert saved.path == str(exact_book)
            assert saved.favorite is True
            assert saved.status == "in_progress"
            assert db.get(models.AudiobookProgress, progress_id) is not None
            assert db.query(models.AudiobookChapter).filter_by(audiobook_id=exact_id).count() >= 1
        finally:
            db.close()


def case_k_new_duplicate_may_skip_without_deleting_existing(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_k")
    with temporary_settings():
        root = configure_root(tmp / "case_k_root")
        existing_book, _ = create_book(root, author="Author", title="Same Book", chapters=2)
        candidate, _ = create_book(root, author="Author", title="Same Book Copy", chapters=2)
        write_sidecar(candidate, title="Same Book", author="Author")
        db = Session()
        try:
            scan(db)
            existing = audiobook_by_path(db, existing_book)
            progress = models.AudiobookProgress(audiobook_id=existing.id, chapter_id=chapters(db, existing.id)[0].id, position_seconds=1, progress_percent=1, status="in_progress")
            db.add(progress)
            db.commit()
            before_books = db.query(models.Audiobook).count()
            result, _ = scan(db)
            assert result["duplicates_skipped"] >= 1, result
            assert db.get(models.Audiobook, existing.id) is not None
            assert db.query(models.AudiobookChapter).filter_by(audiobook_id=existing.id).count() == 2
            assert db.get(models.AudiobookProgress, progress.id) is not None
            assert db.query(models.Audiobook).count() == before_books
        finally:
            db.close()


def case_l_narrator_variants_remain_distinct(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_l")
    with temporary_settings():
        root = configure_root(tmp / "case_l_root")
        book_a, _ = create_book(root, author="Author", title="Variant A", chapters=2, narrator="Narrator A")
        write_sidecar(book_a, title="Shared Work", author="Author", narrator="Narrator A")
        book_b, _ = create_book(root, author="Author", title="Variant B", chapters=2, narrator="Narrator B")
        write_sidecar(book_b, title="Shared Work", author="Author", narrator="Narrator B")
        db = Session()
        try:
            result, _ = scan(db)
            assert result["variants_detected"] >= 1, result
            assert db.query(models.Audiobook).count() == 2
            narrators = {book.narrator for book in db.query(models.Audiobook).all()}
            assert narrators == {"Narrator A", "Narrator B"}
        finally:
            db.close()


def case_m_unavailable_old_identity_does_not_suppress_new(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_m")
    with temporary_settings():
        root = configure_root(tmp / "case_m_root")
        old_path = book_path(root, "Author", "Old Missing")
        new_path, _ = create_book(root, author="Author", title="New Present", chapters=2)
        write_sidecar(new_path, title="Same Work", author="Author", narrator="Narrator")
        db = Session()
        try:
            db.add(models.Audiobook(path=str(old_path), relative_path="Author/Old Missing", title="Same Work", author="Author", narrator="Narrator", library_availability="unavailable"))
            db.commit()
            result, _ = scan(db)
            assert result["audiobooks_added"] == 1, result
            assert db.query(models.Audiobook).count() == 2
            assert audiobook_by_path(db, new_path).library_availability == "available"
        finally:
            db.close()


def case_n_zero_root_fails_closed(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_n")
    with temporary_settings():
        root = configure_root(tmp / "case_n_root", exists=False)
        existing_path = root / "Author" / "Book"
        db = Session()
        try:
            book = models.Audiobook(path=str(existing_path), relative_path="Author/Book", title="Book", author="Author", status="in_progress", favorite=True, library_availability="available")
            db.add(book)
            db.flush()
            progress = models.AudiobookProgress(audiobook_id=book.id, position_seconds=9, progress_percent=4, status="in_progress")
            db.add(progress)
            db.commit()
            result, run = scan(db)
            saved = db.get(models.Audiobook, book.id)
            assert result["status"] == "failed", result
            assert run.status == "failed"
            assert run.items_unavailable == 0
            assert saved.status == "in_progress"
            assert saved.favorite is True
            assert saved.library_availability == "available"
            assert db.get(models.AudiobookProgress, progress.id) is not None
        finally:
            db.close()


def case_o_processing_error_fails_without_deleting_state(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_o")
    with temporary_settings():
        root = configure_root(tmp / "case_o_root")
        book, files = create_book(root, chapters=2)
        db = Session()
        original_read_metadata = audiobook_scanner.read_metadata
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            progress = models.AudiobookProgress(audiobook_id=audio.id, chapter_id=chapters(db, audio.id)[0].id, position_seconds=12, progress_percent=6, status="in_progress")
            db.add(progress)
            db.commit()

            def broken_read_metadata(path: Path):
                if path == files[0]:
                    raise RuntimeError("deterministic audiobook metadata failure")
                return original_read_metadata(path)

            audiobook_scanner.read_metadata = broken_read_metadata
            result, run = scan(db)
            assert result["status"] == "failed", result
            assert run.status == "failed"
            assert run.items_unavailable == 0
            assert db.get(models.Audiobook, audio.id) is not None
            assert db.query(models.AudiobookChapter).filter_by(audiobook_id=audio.id).count() == 2
            assert db.get(models.AudiobookProgress, progress.id) is not None
        finally:
            audiobook_scanner.read_metadata = original_read_metadata
            db.close()


def case_p_multi_book_ordering_remains_correct(tmp: Path) -> None:
    files = [
        Path("Star Wars Darth Bane Dynasty Of Evil (Book 3) [Unabridged].mp3"),
        Path("Star Wars Darth Bane Path Of Destruction (Book 1) [Unabridged].mp3"),
        Path("Star Wars Darth Bane Rule Of Two (Book 2) [Unabridged].mp3"),
    ]
    ordered = sorted(files, key=audiobook_scanner.audiobook_chapter_sort_key)
    assert "Book 1" in ordered[0].name
    assert "Book 2" in ordered[1].name
    assert "Book 3" in ordered[2].name


def case_q_aa_manifest_input_remains_correct(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_q")
    with temporary_settings():
        root = configure_root(tmp / "case_q_root")
        book = root / "Wrong Author" / "Wrong Folder"
        write_chapter(book / "01 Chapter.mp3")
        metadata = book / "metadata"
        metadata.mkdir(parents=True, exist_ok=True)
        metadata_payload = {
            "metadata_version": "test-1",
            "metadata_contract": {"fields": {
                "title": {"approval_state": "approved", "value": "Manifest Title"},
                "author": {"approval_state": "approved", "value": "Manifest Author"},
                "narrator": {"approval_state": "approved", "value": "Manifest Narrator"},
            }},
        }
        (metadata / "audiobook.json").write_text(json.dumps(metadata_payload), encoding="utf-8")
        db = Session()
        try:
            scan(db)
            audio = db.query(models.Audiobook).one()
            assert audio.title == "Manifest Title"
            assert audio.author == "Manifest Author"
            assert audio.narrator == "Manifest Narrator"
            assert audio.metadata_source == "archive_assistant_manifest"
        finally:
            db.close()


def case_r_no_media_file_mutation(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_r")
    with temporary_settings():
        root = configure_root(tmp / "case_r_root")
        _, files = create_book(root, chapters=2, data_prefix=b"preserve")
        before = {path: digest(path) for path in files}
        db = Session()
        try:
            scan(db)
            scan(db)
            for path, value in before.items():
                assert path.exists()
                assert digest(path) == value
        finally:
            db.close()


def main() -> None:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_3c1_audiobook_scan_progress_safety"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_first_successful_scan(tmp)
        case_b_identical_rescan_preserves_audiobook_id(tmp)
        case_c_identical_rescan_preserves_chapter_ids(tmp)
        case_d_progress_survives_identical_rescan(tmp)
        case_e_favorite_survives_rescan(tmp)
        case_f_playback_event_survives_rescan(tmp)
        case_g_metadata_refresh_preserves_user_state(tmp)
        case_h_new_chapter_added_without_rebuild(tmp)
        case_i_missing_chapter_not_deleted_yet(tmp)
        case_j_exact_path_not_deleted_by_duplicate_suppression(tmp)
        case_k_new_duplicate_may_skip_without_deleting_existing(tmp)
        case_l_narrator_variants_remain_distinct(tmp)
        case_m_unavailable_old_identity_does_not_suppress_new(tmp)
        case_n_zero_root_fails_closed(tmp)
        case_o_processing_error_fails_without_deleting_state(tmp)
        case_p_multi_book_ordering_remains_correct(tmp)
        case_q_aa_manifest_input_remains_correct(tmp)
        case_r_no_media_file_mutation(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.3C1 audiobook scan progress safety")


if __name__ == "__main__":
    main()