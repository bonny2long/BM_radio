from datetime import datetime, timezone
from pathlib import Path
import json, re

from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..media_identity import audiobook_edition_key, audiobook_work_key, duration_bucket, normalize_text
from ..scan_runs import MEDIA_KIND_AUDIOBOOK, complete_scan_run, fail_scan_run, mark_audiobook_seen, start_scan_run
from .archive_assistant_manifest import extract_audiobook_manifest_metadata, load_aa_manifest_context
from .music_scanner import read_metadata
from .path_safety import safe_media_files

AUDIOBOOK_EXTENSIONS = {'.mp3', '.m4b', '.m4a', '.flac', '.aac', '.ogg', '.opus'}


def key(path):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)', path.name)]


def explicit_book_index(path: Path) -> int | None:
    stem = path.stem
    patterns = [r'\bbook\s*(\d{1,3})\b', r'\bpart\s*(\d{1,3})\b', r'\bvol(?:ume)?\.?\s*(\d{1,3})\b', r'#\s*(\d{1,3})\b', r'\((\d{1,3})\)']
    for pattern in patterns:
        match = re.search(pattern, stem, re.I)
        if match:
            return int(match.group(1))
    return None


def audiobook_chapter_sort_key(path: Path):
    book_index = explicit_book_index(path)
    if book_index is not None:
        return (0, book_index, key(path))
    return (1, key(path))


def _read_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _merge_meta(target: dict, source: dict):
    for k, v in source.items():
        if v not in (None, '', [], {}) and target.get(k) in (None, '', [], {}):
            target[k] = v


def load_audiobook_sidecar(book_path: Path, roots: list[Path] | None = None, cache: dict | None = None) -> dict:
    roots = roots or [book_path]
    cache = cache if cache is not None else {}
    aa_context = load_aa_manifest_context(book_path, roots, cache)
    aa_meta = extract_audiobook_manifest_metadata(aa_context, book_path)
    meta_dir = book_path / 'metadata'
    raw = {}
    for name in ('audiobook.json', 'metadata.json', 'move_manifest.json'):
        data = _read_json(meta_dir / name)
        if data:
            raw[name] = data
    out = {'title': aa_meta.get('title'), 'author': aa_meta.get('author'), 'year': aa_meta.get('year'), 'narrator': aa_meta.get('narrator'), 'series': aa_meta.get('series'), 'series_index': aa_meta.get('series_index'), 'contained_books': aa_meta.get('contained_books') or [], 'original_release_name': None, 'metadata_source': aa_meta.get('metadata_source'), 'source_manifest_path': aa_meta.get('source_manifest_path'), 'source_manifest_version': aa_meta.get('source_manifest_version'), 'source_metadata_version': aa_meta.get('source_metadata_version')}
    candidates = []
    for data in raw.values():
        if isinstance(data.get('metadata_json'), dict):
            candidates.append(data['metadata_json'])
        if isinstance(data.get('suggested_metadata'), dict):
            candidates.append(data['suggested_metadata'])
        candidates.append(data)
    for source in candidates:
        _merge_meta(out, source)
    for data in raw.values():
        for key_name in ('contained_books', 'books'):
            value = data.get(key_name)
            if value and not out.get('contained_books'):
                out['contained_books'] = value
        nested = data.get('metadata_json') if isinstance(data.get('metadata_json'), dict) else {}
        value = nested.get('contained_books')
        if value and not out.get('contained_books'):
            out['contained_books'] = value
    if not out.get('title'):
        out['title'] = re.sub(r'^\d{4}\s*-\s*', '', book_path.name)
    if not out.get('author'):
        out['author'] = book_path.parent.name
    out['contained_books'] = out.get('contained_books') or []
    return out


def same_source_basename(a: str | None, b: str | None) -> bool:
    return bool(a and b and normalize_text(Path(a).name) == normalize_text(Path(b).name))


def duration_close(a, b, percent=3.0) -> bool:
    try:
        x = float(a or 0)
        y = float(b or 0)
    except Exception:
        return False
    if x <= 0 or y <= 0:
        return False
    return abs(x - y) / max(x, y) * 100 <= percent


def chapter_title(path, order, contained):
    for item in contained:
        number = str(item.get('series_index', ''))
        if number and re.search(r'(book\s*' + re.escape(number) + r'|part\s*' + re.escape(number) + r'|vol(?:ume)?\.?\s*' + re.escape(number) + r'|#\s*' + re.escape(number) + r'|\(' + re.escape(number) + r'\))', path.stem, re.I):
            return 'Book ' + number + ' - ' + item.get('title', '')
    title = re.sub(r'^\d+[-_.\s]+', '', path.stem).strip()
    if re.fullmatch(r'(track\s*)?\d+', title, re.I):
        return f'Chapter {order}'
    return title or f'Chapter {order}'


def _audiobook_info(book: models.Audiobook, chapter_count: int | None = None) -> dict:
    count = len(book.chapters or []) if chapter_count is None else chapter_count
    return {
        'id': book.id,
        'path': book.path,
        'title': book.title,
        'narrator': book.narrator,
        'duration_bucket': duration_bucket(book.duration_seconds, tolerance=60),
        'duration_seconds': book.duration_seconds,
        'chapter_count': count,
    }


def _set_scan_failed(db: Session, scan_run: models.ScanRun, result: dict, error_summary: str, error_count: int) -> None:
    scan_run.items_discovered = result['audiobooks_scanned']
    scan_run.items_added = result['audiobooks_added']
    scan_run.items_updated = result['audiobooks_updated']
    scan_run.items_unavailable = 0
    fail_scan_run(db, scan_run, error_summary=error_summary, error_count=error_count)
    result['status'] = 'failed'
    result['scan_run_status'] = 'failed'
    result['audiobooks_unavailable'] = 0


def _upsert_chapters(db: Session, audiobook: models.Audiobook, rows: list[tuple[Path, float, int]], root: Path, contained: list[dict]) -> tuple[int, int]:
    existing_by_path = {chapter.path: chapter for chapter in audiobook.chapters or [] if chapter.path}
    chapters_added = 0
    chapters_updated = 0
    for path, duration, order in rows:
        path_text = str(path)
        data = {
            'audiobook_id': audiobook.id,
            'path': path_text,
            'relative_path': str(path.relative_to(root)),
            'title': chapter_title(path, order, contained),
            'chapter_number': order,
            'duration_seconds': duration,
            'sort_order': order,
        }
        chapter = existing_by_path.get(path_text)
        if chapter:
            for key_name, value in data.items():
                setattr(chapter, key_name, value)
            chapters_updated += 1
        else:
            db.add(models.AudiobookChapter(**data))
            chapters_added += 1
    return chapters_added, chapters_updated


def _is_strong_work_duplicate(seen_work: dict | None, book_path: Path, data: dict, chapter_count: int) -> bool:
    if not seen_work or seen_work.get('path') == str(book_path):
        return False
    if normalize_text(seen_work.get('narrator')) != normalize_text(data.get('narrator')):
        return False
    return bool(
        seen_work.get('chapter_count') == chapter_count
        or duration_close(data['duration_seconds'], seen_work.get('duration_seconds'))
        or same_source_basename(str(book_path), seen_work.get('path'))
    )


def scan_audiobooks(db: Session):
    root = Path(settings.AUDIOBOOKS_ROOT)
    existing_roots = [root] if root.is_dir() else []
    result = {
        'status': 'running',
        'scan_run_id': None,
        'scan_run_status': 'running',
        'audiobooks_scanned': 0,
        'audiobooks_added': 0,
        'audiobooks_updated': 0,
        'audiobooks_unavailable': 0,
        'chapters_scanned': 0,
        'chapters_added': 0,
        'chapters_updated': 0,
        'roots_scanned': [str(root)] if existing_roots else [],
        'skipped_roots': [] if existing_roots else [str(root)],
        'errors': [],
        'duplicates_skipped': 0,
        'duplicates_suspected': 0,
        'variants_detected': 0,
        'duplicate_warnings': [],
    }

    scan_run = start_scan_run(db, media_kind=MEDIA_KIND_AUDIOBOOK, roots=[str(r) for r in existing_roots])
    db.commit()
    scan_run_id = scan_run.id
    result['scan_run_id'] = scan_run_id

    if not existing_roots:
        result['errors'].append('Configured audiobook root does not exist; failing closed without reconciliation.')
        _set_scan_failed(db, scan_run, result, result['errors'][0], 1)
        db.commit()
        return result

    try:
        manifest_cache = {}
        exact_path_books = {book.path: book for book in db.query(models.Audiobook).all() if book.path}
        edition_seen = {}
        work_seen = {}
        for existing in exact_path_books.values():
            if existing.library_availability == 'unavailable':
                continue
            chapter_count = len(existing.chapters or [])
            ekey = audiobook_edition_key(existing.title, existing.author, existing.narrator, existing.duration_seconds, chapter_count)
            wkey = audiobook_work_key(existing.title, existing.author)
            info = _audiobook_info(existing, chapter_count)
            edition_seen.setdefault(ekey, info)
            work_seen.setdefault(wkey, info)

        groups = {}
        for path in safe_media_files(root, AUDIOBOOK_EXTENSIONS, [root]):
            parts = path.relative_to(root).parts
            book = root / parts[0] / parts[1] if len(parts) > 1 else root / parts[0]
            groups.setdefault(book, []).append(path)

        for book, chapters in groups.items():
            try:
                chapters.sort(key=audiobook_chapter_sort_key)
                meta = load_audiobook_sidecar(book, [root], manifest_cache)
                title = meta.get('title') or re.sub(r'^\d{4}\s*-\s*', '', book.name)
                author = meta.get('author') or book.parent.name
                contained = meta.get('contained_books', [])
                data = {
                    'relative_path': str(book.relative_to(root)),
                    'title': title,
                    'author': author,
                    'narrator': meta.get('narrator'),
                    'series': meta.get('series'),
                    'year': meta.get('year'),
                    'duration_seconds': 0.0,
                    'metadata_source': meta.get('metadata_source') or 'path_inference',
                    'source_manifest_path': meta.get('source_manifest_path'),
                    'source_manifest_version': meta.get('source_manifest_version'),
                    'source_metadata_version': meta.get('source_metadata_version'),
                    'last_indexed_at': datetime.now(timezone.utc),
                }
                rows = []
                for order, path in enumerate(chapters, 1):
                    duration = read_metadata(path).get('duration_seconds') or 0
                    data['duration_seconds'] += duration
                    rows.append((path, duration, order))
                chapter_count = len(rows)
                edition_key = audiobook_edition_key(title, author, meta.get('narrator'), data['duration_seconds'], chapter_count)
                work_key = audiobook_work_key(title, author)

                found = exact_path_books.get(str(book))
                if found:
                    for key_name, value in data.items():
                        setattr(found, key_name, value)
                    mark_audiobook_seen(found, scan_run_id=scan_run_id)
                    added, updated = _upsert_chapters(db, found, rows, root, contained)
                    result['chapters_added'] += added
                    result['chapters_updated'] += updated
                    result['audiobooks_updated'] += 1
                else:
                    seen_edition = edition_seen.get(edition_key)
                    if seen_edition and seen_edition.get('path') != str(book):
                        result['duplicates_skipped'] += 1
                        result['audiobooks_scanned'] += 1
                        result['chapters_scanned'] += len(rows)
                        result['duplicate_warnings'].append({'type': 'duplicate_skipped', 'media_kind': 'audiobook', 'title': title, 'existing_id': seen_edition.get('id'), 'candidate_path': str(book), 'reason': 'same audiobook edition key'})
                        continue
                    seen_work = work_seen.get(work_key)
                    if _is_strong_work_duplicate(seen_work, book, data, chapter_count):
                        result['duplicates_skipped'] += 1
                        result['audiobooks_scanned'] += 1
                        result['chapters_scanned'] += len(rows)
                        result['duplicate_warnings'].append({'type': 'duplicate_skipped', 'media_kind': 'audiobook', 'title': title, 'existing_id': seen_work.get('id'), 'candidate_path': str(book), 'reason': 'same audiobook work key and matching chapter count/duration/source basename'})
                        continue
                    if seen_work and seen_work.get('path') != str(book):
                        result['variants_detected'] += 1
                        result['duplicate_warnings'].append({'type': 'variant_detected', 'media_kind': 'audiobook', 'title': title, 'existing_id': seen_work.get('id'), 'candidate_path': str(book), 'reason': 'same audiobook work key with different edition details'})

                    found = models.Audiobook(path=str(book), status='available', favorite=False, **data)
                    db.add(found)
                    db.flush()
                    exact_path_books[str(book)] = found
                    mark_audiobook_seen(found, scan_run_id=scan_run_id)
                    added, updated = _upsert_chapters(db, found, rows, root, contained)
                    result['chapters_added'] += added
                    result['chapters_updated'] += updated
                    result['audiobooks_added'] += 1

                info = _audiobook_info(found, chapter_count)
                edition_seen[edition_key] = info
                work_seen.setdefault(work_key, info)
                result['audiobooks_scanned'] += 1
                result['chapters_scanned'] += len(rows)
            except Exception as exc:
                result['errors'].append(f'{book}: {exc}')

        db.flush()
        if result['errors']:
            _set_scan_failed(db, scan_run, result, '\n'.join(result['errors']), len(result['errors']))
            db.commit()
            return result

        complete_scan_run(
            db,
            scan_run,
            items_discovered=result['audiobooks_scanned'],
            items_added=result['audiobooks_added'],
            items_updated=result['audiobooks_updated'],
            items_unavailable=0,
            error_count=0,
        )
        result['status'] = 'ok'
        result['scan_run_status'] = 'succeeded'
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        scan_run = db.get(models.ScanRun, scan_run_id)
        if scan_run is None:
            scan_run = start_scan_run(db, media_kind=MEDIA_KIND_AUDIOBOOK, roots=[str(r) for r in existing_roots])
            result['scan_run_id'] = scan_run.id
        result['errors'].append(str(exc))
        _set_scan_failed(db, scan_run, result, str(exc), max(1, len(result['errors'])))
        db.commit()
        return result