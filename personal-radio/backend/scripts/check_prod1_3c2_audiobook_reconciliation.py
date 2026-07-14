from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models
from app.config import settings
from app.schema_maintenance import ensure_scan_reconciliation_columns
from app.scanner import audiobook_scanner


ROOT_SETTING_NAMES = ("AUDIOBOOKS_ROOT", "BM_RADIO_AUDIOBOOK_ROOT")
REQUIRED_CHAPTER_COLUMNS = {"library_availability", "last_seen_scan_id", "unavailable_since"}
REQUIRED_CHAPTER_INDEXES = {"ix_audiobook_chapters_library_availability", "ix_audiobook_chapters_last_seen_scan_id"}


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


def book_path(root: Path, author: str = "Author", title: str = "Book") -> Path:
    return root / author / title


def create_book(root: Path, author: str = "Author", title: str = "Book", chapters: int = 2, *, narrator: str | None = None, sidecar_title: str | None = None) -> tuple[Path, list[Path]]:
    book = book_path(root, author, title)
    files = []
    for index in range(1, chapters + 1):
        files.append(write_chapter(book / f"{index:02d} Track {index}.mp3", f"{author}-{title}-{index}".encode("utf-8")))
    if narrator is not None or sidecar_title is not None:
        payload = {}
        if sidecar_title is not None:
            payload["title"] = sidecar_title
            payload["author"] = author
        if narrator is not None:
            payload["narrator"] = narrator
        write_sidecar(book, **payload)
    return book, files


def scan(db):
    result = audiobook_scanner.scan_audiobooks(db)
    assert result["scan_run_id"], result
    db.expire_all()
    return result, db.get(models.ScanRun, result["scan_run_id"])


def audiobook_by_path(db, path: Path) -> models.Audiobook:
    row = db.query(models.Audiobook).filter_by(path=str(path)).one_or_none()
    assert row is not None, str(path)
    return row


def chapters(db, audiobook_id: int) -> list[models.AudiobookChapter]:
    return db.query(models.AudiobookChapter).filter_by(audiobook_id=audiobook_id).order_by(models.AudiobookChapter.sort_order, models.AudiobookChapter.path).all()


def chapter_by_path(db, path: Path) -> models.AudiobookChapter:
    row = db.query(models.AudiobookChapter).filter_by(path=str(path)).one_or_none()
    assert row is not None, str(path)
    return row


def add_progress_state(db, audiobook: models.Audiobook, chapter: models.AudiobookChapter | None = None):
    audiobook.status = "in_progress"
    audiobook.favorite = True
    progress = models.AudiobookProgress(audiobook_id=audiobook.id, chapter_id=chapter.id if chapter else None, position_seconds=55, progress_percent=44, status="in_progress")
    event = models.PlaybackEvent(audiobook_id=audiobook.id, event_type="start", position_seconds=55)
    db.add_all([progress, event])
    db.commit()
    return progress.id, event.id


def table_columns(engine, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table_name)}


def table_indexes(engine, table_name: str) -> set[str]:
    return {index["name"] for index in inspect(engine).get_indexes(table_name)}


def case_a_fresh_chapter_schema(tmp: Path) -> None:
    engine, Session = make_db(tmp, "case_a")
    assert REQUIRED_CHAPTER_COLUMNS.issubset(table_columns(engine, "audiobook_chapters"))
    db = Session()
    try:
        book = models.Audiobook(path="/tmp/book", title="Book", author="Author")
        db.add(book)
        db.flush()
        chapter = models.AudiobookChapter(audiobook_id=book.id, path="/tmp/book/01.mp3", title="Chapter", sort_order=1)
        db.add(chapter)
        db.commit()
        db.refresh(chapter)
        assert chapter.library_availability == "available"
        assert chapter.last_seen_scan_id is None
        assert chapter.unavailable_since is None
    finally:
        db.close()


def case_b_additive_legacy_chapter_upgrade(tmp: Path) -> None:
    db_path = tmp / "case_b_legacy.db"
    con = sqlite3.connect(db_path)
    try:
        cur = con.cursor()
        cur.execute("CREATE TABLE audiobooks (id INTEGER PRIMARY KEY, path VARCHAR, title VARCHAR, author VARCHAR, status VARCHAR)")
        cur.execute("CREATE TABLE audiobook_chapters (id INTEGER PRIMARY KEY, audiobook_id INTEGER, path VARCHAR, relative_path VARCHAR, title VARCHAR, chapter_number INTEGER, duration_seconds FLOAT, sort_order INTEGER)")
        cur.execute("INSERT INTO audiobooks (id, path, title, author, status) VALUES (1, '/legacy/book', 'Legacy', 'Author', 'in_progress')")
        cur.execute("INSERT INTO audiobook_chapters (id, audiobook_id, path, relative_path, title, chapter_number, duration_seconds, sort_order) VALUES (7, 1, '/legacy/book/01.mp3', 'book/01.mp3', 'One', 1, 10, 1)")
        con.commit()
    finally:
        con.close()
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    ensure_scan_reconciliation_columns(engine)
    ensure_scan_reconciliation_columns(engine)
    assert REQUIRED_CHAPTER_COLUMNS.issubset(table_columns(engine, "audiobook_chapters"))
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id, path, library_availability, last_seen_scan_id, unavailable_since FROM audiobook_chapters WHERE id = 7")).one()
    assert row.id == 7
    assert row.path == "/legacy/book/01.mp3"
    assert row.library_availability == "available"
    assert row.last_seen_scan_id is None
    assert row.unavailable_since is None


def case_c_first_scan_marks_seen(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_c")
    with temporary_settings():
        root = configure_root(tmp / "case_c_root")
        book, files = create_book(root, chapters=2)
        db = Session()
        try:
            result, run = scan(db)
            audio = audiobook_by_path(db, book)
            assert audio.library_availability == "available"
            assert audio.last_seen_scan_id == run.id
            for file in files:
                chapter = chapter_by_path(db, file)
                assert chapter.library_availability == "available"
                assert chapter.last_seen_scan_id == run.id
                assert chapter.unavailable_since is None
            assert result["audiobooks_unavailable"] == 0
            assert result["chapters_unavailable"] == 0
        finally:
            db.close()


def case_d_missing_whole_audiobook_unavailable(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_d")
    with temporary_settings():
        root = configure_root(tmp / "case_d_root")
        book, _ = create_book(root, chapters=2)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            chapter_rows = chapters(db, audio.id)
            progress_id, event_id = add_progress_state(db, audio, chapter_rows[0])
            audiobook_id = audio.id
            chapter_ids = [chapter.id for chapter in chapter_rows]
            shutil.rmtree(book)
            result, run = scan(db)
            audio = db.get(models.Audiobook, audiobook_id)
            assert audio.library_availability == "unavailable"
            assert audio.unavailable_since is not None
            assert audio.status == "in_progress"
            assert audio.favorite is True
            assert [chapter.id for chapter in chapters(db, audiobook_id)] == chapter_ids
            assert all(chapter.library_availability == "unavailable" for chapter in chapters(db, audiobook_id))
            assert db.get(models.AudiobookProgress, progress_id) is not None
            assert db.get(models.PlaybackEvent, event_id) is not None
            assert result["audiobooks_unavailable"] == 1
            assert result["chapters_unavailable"] == 2
            assert run.items_unavailable == 1
        finally:
            db.close()


def case_e_returning_whole_audiobook_restores(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_e")
    with temporary_settings():
        root = configure_root(tmp / "case_e_root")
        book, files = create_book(root, chapters=2)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            chapter_ids = [chapter.id for chapter in chapters(db, audio.id)]
            progress_id, event_id = add_progress_state(db, audio, chapters(db, audio.id)[0])
            shutil.rmtree(book)
            scan(db)
            book.mkdir(parents=True)
            for file in files:
                write_chapter(file)
            _, run = scan(db)
            audio = audiobook_by_path(db, book)
            assert audio.library_availability == "available"
            assert audio.unavailable_since is None
            assert audio.last_seen_scan_id == run.id
            assert [chapter.id for chapter in chapters(db, audio.id)] == chapter_ids
            assert all(chapter.library_availability == "available" and chapter.unavailable_since is None for chapter in chapters(db, audio.id))
            assert db.get(models.AudiobookProgress, progress_id) is not None
            assert db.get(models.PlaybackEvent, event_id) is not None
        finally:
            db.close()


def case_f_one_missing_chapter(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_f")
    with temporary_settings():
        root = configure_root(tmp / "case_f_root")
        book, files = create_book(root, chapters=3)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            middle = chapter_by_path(db, files[1])
            files[1].unlink()
            result, _ = scan(db)
            audio = audiobook_by_path(db, book)
            assert audio.library_availability == "available"
            assert chapter_by_path(db, files[0]).library_availability == "available"
            assert db.get(models.AudiobookChapter, middle.id).library_availability == "unavailable"
            assert chapter_by_path(db, files[2]).library_availability == "available"
            assert result["chapters_unavailable"] == 1
            assert result["audiobooks_unavailable"] == 0
        finally:
            db.close()


def case_g_progress_pointing_to_missing_chapter_preserved(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_g")
    with temporary_settings():
        root = configure_root(tmp / "case_g_root")
        book, files = create_book(root, chapters=3)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            middle = chapter_by_path(db, files[1])
            audio.status = "in_progress"
            progress = models.AudiobookProgress(audiobook_id=audio.id, chapter_id=middle.id, position_seconds=123, progress_percent=50, status="in_progress")
            db.add(progress)
            db.commit()
            progress_id = progress.id
            files[1].unlink()
            scan(db)
            saved = db.get(models.AudiobookProgress, progress_id)
            assert saved.chapter_id == middle.id
            assert saved.position_seconds == 123
            assert saved.progress_percent == 50
            assert audiobook_by_path(db, book).status == "in_progress"
            assert db.get(models.AudiobookChapter, middle.id).library_availability == "unavailable"
        finally:
            db.close()


def case_h_returning_missing_chapter_restores_same_id(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_h")
    with temporary_settings():
        root = configure_root(tmp / "case_h_root")
        book, files = create_book(root, chapters=3)
        db = Session()
        try:
            scan(db)
            middle = chapter_by_path(db, files[1])
            progress = models.AudiobookProgress(audiobook_id=middle.audiobook_id, chapter_id=middle.id, position_seconds=12, progress_percent=8, status="in_progress")
            db.add(progress)
            db.commit()
            files[1].unlink()
            scan(db)
            write_chapter(files[1])
            _, run = scan(db)
            restored = chapter_by_path(db, files[1])
            assert restored.id == middle.id
            assert restored.library_availability == "available"
            assert restored.unavailable_since is None
            assert restored.last_seen_scan_id == run.id
            assert db.get(models.AudiobookProgress, progress.id).chapter_id == middle.id
        finally:
            db.close()


def case_i_missing_root_fails_closed(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_i")
    with temporary_settings():
        root = configure_root(tmp / "case_i_root")
        book, _ = create_book(root, chapters=2)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            chapter_rows = chapters(db, audio.id)
            shutil.rmtree(root)
            result, run = scan(db)
            assert result["status"] == "failed"
            assert run.status == "failed"
            assert audiobook_by_path(db, book).library_availability == "available"
            assert all(db.get(models.AudiobookChapter, chapter.id).library_availability == "available" for chapter in chapter_rows)
            assert result["audiobooks_unavailable"] == 0
            assert result["chapters_unavailable"] == 0
        finally:
            db.close()


def case_j_processing_error_prevents_reconciliation(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_j")
    with temporary_settings():
        root = configure_root(tmp / "case_j_root")
        present, files = create_book(root, author="Author", title="Present", chapters=1)
        absent = book_path(root, "Author", "Absent")
        db = Session()
        original_read_metadata = audiobook_scanner.read_metadata
        try:
            absent_book = models.Audiobook(path=str(absent), relative_path="Author/Absent", title="Absent", author="Author", library_availability="available")
            db.add(absent_book)
            db.flush()
            absent_chapter = models.AudiobookChapter(audiobook_id=absent_book.id, path=str(absent / "01.mp3"), title="Absent", sort_order=1, library_availability="available")
            db.add(absent_chapter)
            db.commit()

            def broken_read_metadata(path: Path):
                if path == files[0]:
                    raise RuntimeError("deterministic audiobook metadata failure")
                return original_read_metadata(path)

            audiobook_scanner.read_metadata = broken_read_metadata
            result, run = scan(db)
            assert result["status"] == "failed"
            assert run.status == "failed"
            assert db.get(models.Audiobook, absent_book.id).library_availability == "available"
            assert db.get(models.AudiobookChapter, absent_chapter.id).library_availability == "available"
            assert result["audiobooks_unavailable"] == 0
            assert result["chapters_unavailable"] == 0
        finally:
            audiobook_scanner.read_metadata = original_read_metadata
            db.close()


def case_k_outside_root_untouched(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_k")
    with temporary_settings():
        root = configure_root(tmp / "case_k_root")
        create_book(root, chapters=1)
        outside = tmp / "outside" / "Author" / "Book"
        db = Session()
        try:
            db.add(models.Audiobook(path=str(outside), title="Outside", author="Author", library_availability="available"))
            db.commit()
            scan(db)
            assert audiobook_by_path(db, outside).library_availability == "available"
        finally:
            db.close()


def case_l_root_boundary_blocked(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_l")
    with temporary_settings():
        root = configure_root(tmp / "case_l_root")
        create_book(root, chapters=1)
        boundary = root.parent / "Library-OLD" / "Author" / "Book"
        db = Session()
        try:
            db.add(models.Audiobook(path=str(boundary), title="Boundary", author="Author", library_availability="available"))
            db.commit()
            scan(db)
            assert audiobook_by_path(db, boundary).library_availability == "available"
        finally:
            db.close()


def case_m_empty_existing_book_folder_unavailable(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_m")
    with temporary_settings():
        root = configure_root(tmp / "case_m_root")
        book, _ = create_book(root, chapters=2)
        db = Session()
        try:
            scan(db)
            audio = audiobook_by_path(db, book)
            for file in book.glob("*.mp3"):
                file.unlink()
            result, _ = scan(db)
            assert book.exists()
            assert audiobook_by_path(db, book).library_availability == "unavailable"
            assert all(chapter.library_availability == "unavailable" for chapter in chapters(db, audio.id))
            assert result["audiobooks_unavailable"] == 1
        finally:
            db.close()


def case_n_renamed_chapter_non_destructive(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_n")
    with temporary_settings():
        root = configure_root(tmp / "case_n_root")
        book, files = create_book(root, chapters=1)
        db = Session()
        try:
            scan(db)
            old = chapter_by_path(db, files[0])
            progress = models.AudiobookProgress(audiobook_id=old.audiobook_id, chapter_id=old.id, position_seconds=1, progress_percent=1, status="in_progress")
            db.add(progress)
            db.commit()
            renamed = files[0].with_name("01 Track 1 Renamed.mp3")
            files[0].rename(renamed)
            scan(db)
            old_row = db.get(models.AudiobookChapter, old.id)
            new_row = chapter_by_path(db, renamed)
            assert old_row.path == str(files[0])
            assert old_row.library_availability == "unavailable"
            assert new_row.id != old.id
            assert new_row.library_availability == "available"
            assert db.get(models.AudiobookProgress, progress.id).chapter_id == old.id
        finally:
            db.close()


def case_o_variant_independence(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_o")
    with temporary_settings():
        root = configure_root(tmp / "case_o_root")
        book_a, _ = create_book(root, author="Author", title="Variant A", chapters=1, narrator="Narrator A", sidecar_title="Shared Work")
        book_b, _ = create_book(root, author="Author", title="Variant B", chapters=1, narrator="Narrator B", sidecar_title="Shared Work")
        db = Session()
        try:
            scan(db)
            shutil.rmtree(book_a)
            result, _ = scan(db)
            assert audiobook_by_path(db, book_a).library_availability == "unavailable"
            assert audiobook_by_path(db, book_b).library_availability == "available"
            assert result["audiobooks_unavailable"] == 1
        finally:
            db.close()


def case_p_no_media_file_mutation(tmp: Path) -> None:
    _, Session = make_db(tmp, "case_p")
    with temporary_settings():
        root = configure_root(tmp / "case_p_root")
        _, files = create_book(root, chapters=2)
        before = {file: digest(file) for file in files}
        db = Session()
        try:
            scan(db)
            scan(db)
            for file, value in before.items():
                assert file.exists()
                assert digest(file) == value
        finally:
            db.close()


def case_q_chapter_indexes_exist(tmp: Path) -> None:
    engine, _ = make_db(tmp, "case_q")
    actual = table_indexes(engine, "audiobook_chapters")
    assert REQUIRED_CHAPTER_INDEXES.issubset(actual), actual


def main() -> None:
    tmp = Path(__file__).resolve().parents[1] / "tmp_tests" / "prod1_3c2_audiobook_reconciliation"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    try:
        case_a_fresh_chapter_schema(tmp)
        case_b_additive_legacy_chapter_upgrade(tmp)
        case_c_first_scan_marks_seen(tmp)
        case_d_missing_whole_audiobook_unavailable(tmp)
        case_e_returning_whole_audiobook_restores(tmp)
        case_f_one_missing_chapter(tmp)
        case_g_progress_pointing_to_missing_chapter_preserved(tmp)
        case_h_returning_missing_chapter_restores_same_id(tmp)
        case_i_missing_root_fails_closed(tmp)
        case_j_processing_error_prevents_reconciliation(tmp)
        case_k_outside_root_untouched(tmp)
        case_l_root_boundary_blocked(tmp)
        case_m_empty_existing_book_folder_unavailable(tmp)
        case_n_renamed_chapter_non_destructive(tmp)
        case_o_variant_independence(tmp)
        case_p_no_media_file_mutation(tmp)
        case_q_chapter_indexes_exist(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS: BM-PROD1.3C2 audiobook reconciliation")


if __name__ == "__main__":
    main()