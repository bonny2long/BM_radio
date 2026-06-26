from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import re

from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from .path_safety import is_approved_path, safe_media_files

MUSIC_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.wav'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
COVER_STEMS = ('cover', 'folder', 'front', 'artwork', 'album')
RELEASE_SUFFIXES = {'sut', 'flac', 'mp3', 'web', 'cd', 'retail', 'rgf', 'rns', 'dsr', 'cr', 'hhf', 'exe', 'phaze', 'mp3xplosion', 'bbh'}
COLLECTION_DESCRIPTOR_SUFFIXES = [
    'complete discography', 'mixtape collection', 'bootleg collection', 'discography', 'mixtapes',
    'bootlegs', 'collection', 'anthology', 'catalogue', 'catalog', 'box set', 'albums', 'singles', 'eps'
]
TITLE_WORD_EXCEPTIONS = {'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'from', 'into', 'nor', 'of', 'on', 'or', 'out', 'over', 'the', 'up', 'with'}
ARTIST_PREFIX_CONNECTORS = {'and', 'feat', 'ft', 'featuring', 'x', 'vs'}


def _tag_value(tags: Any, *keys: str):
    for key in keys:
        value = tags.get(key) if tags and hasattr(tags, 'get') else None
        if value:
            return str(value[0] if isinstance(value, (list, tuple)) else value).strip()
    return None


def read_metadata(path: Path) -> dict[str, Any]:
    result = {'duration_seconds': None}
    try:
        from mutagen import File

        media = File(path, easy=True)
        tags = media.tags if media else None
        result.update({
            'duration_seconds': getattr(getattr(media, 'info', None), 'length', None),
            'title': _tag_value(tags, 'title'),
            'artist': _tag_value(tags, 'artist'),
            'album': _tag_value(tags, 'album'),
            'album_artist': _tag_value(tags, 'albumartist'),
            'genre': _tag_value(tags, 'genre'),
            'year': _tag_value(tags, 'date', 'year'),
        })
    except Exception:
        pass
    try:
        result['year'] = int(str(result.get('year'))[:4])
    except Exception:
        result['year'] = None
    return result


def generic(value):
    return not value or str(value).strip().lower() in {
        'unknown artist', 'unknown album', 'unknown year', 'cd1', 'cd2', 'track 01', 'various artists', 'unknown'
    }


def year_title(name):
    match = re.match(r'^(\d{4})\s*-\s*(.+)$', name or '')
    return (int(match.group(1)), match.group(2)) if match else (None, name)


def artist_slug(value: str | None) -> str:
    return re.sub(r'[^a-z0-9]+', '_', (value or '').lower()).strip('_')


def slug_to_display(value: str) -> str:
    text = value.replace('_', ' ').replace('.', ' ').strip()
    return title_case_release(text)


def normalize_compare(value: str | None) -> str:
    text = re.sub(r'[^a-z0-9]+', ' ', (value or '').lower()).strip()
    text = re.sub(r'\btha\b', 'the', text)
    return re.sub(r'\s+', ' ', text)


def title_case_token(word: str, word_index: int) -> str:
    match = re.match(r'^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9.]*)$', word)
    if not match:
        return word
    prefix, core, suffix = match.groups()
    lower = core.lower()
    stripped = lower.strip('.,!?;:')
    if not core:
        return word
    if re.fullmatch(r'(?:[a-z]\.){2,}', lower):
        return prefix + lower.upper() + suffix
    if re.fullmatch(r'[a-z]\.{2,}', lower):
        return prefix + lower.upper() + suffix
    if word_index > 0 and stripped in TITLE_WORD_EXCEPTIONS:
        return prefix + lower + suffix
    if stripped in {'feat', 'ft'}:
        return prefix + stripped.capitalize() + '.' + suffix
    base_match = re.match(r'^([\w\']+)(.*)$', core)
    if not base_match:
        return word
    base, inner_suffix = base_match.groups()
    return prefix + base[:1].upper() + base[1:].lower() + inner_suffix + suffix


def title_case_release(value: str, artist: str | None = None) -> str:
    words = re.split(r'(\s+)', value)
    output: list[str] = []
    word_index = 0
    for word in words:
        if word.isspace():
            output.append(word)
            continue
        output.append(title_case_token(word, word_index))
        word_index += 1
    text = ''.join(output)
    text = re.sub(r'\bFeat\b\.?', 'Feat.', text)
    text = re.sub(r'\bFt\b\.?', 'Ft.', text)
    return text


def strip_collection_descriptor(collection_name: str) -> str | None:
    cleaned = re.sub(r'\s+', ' ', collection_name or '').strip()
    lower = cleaned.lower()
    for suffix in sorted(COLLECTION_DESCRIPTOR_SUFFIXES, key=len, reverse=True):
        marker = ' ' + suffix
        if lower.endswith(marker) and len(cleaned) > len(suffix):
            return cleaned[: -len(marker)].strip()
    return None


def likely_artist_prefix(segment: str, canonical_artist: str | None = None) -> bool:
    value = artist_slug(segment)
    if not value:
        return False
    canonical = artist_slug(canonical_artist)
    if canonical and (value == canonical or canonical in value.split('_') or canonical in value):
        return True
    return False


def extract_prefix_artist(filename: str) -> str | None:
    stem = Path(filename).stem.lower()
    stem = re.sub(r'^\d{1,2}\s*-\s*', '', stem)
    stem = re.sub(r'^\(?\d{1,3}\)?[_\s.-]*', '', stem)
    match = re.match(r'^\[?([a-z0-9_]+(?:_(?:and|feat|ft|x)_[a-z0-9_]+)*)\]?(?:\s*[-_]\s*|-)', stem)
    if not match:
        return None
    prefix = match.group(1).strip('_')
    return slug_to_display(prefix) if likely_artist_prefix(prefix) else None


def resolve_discography_artist(collection_name: str, filenames: list[str] | None = None) -> dict[str, Any]:
    stripped = strip_collection_descriptor(collection_name)
    display_artist = stripped or collection_name
    was_collection_label = bool(stripped)

    counts: dict[str, int] = {}
    for name in filenames or []:
        prefix = extract_prefix_artist(name)
        if prefix:
            counts[prefix] = counts.get(prefix, 0) + 1
    if counts and filenames:
        prefix, count = max(counts.items(), key=lambda item: item[1])
        if count / max(len(filenames), 1) >= 0.60:
            if not stripped or artist_slug(display_artist) in artist_slug(prefix) or artist_slug(prefix) in artist_slug(display_artist):
                display_artist = stripped or prefix
                was_collection_label = was_collection_label or display_artist != collection_name

    return {
        'display_artist': display_artist,
        'collection_label': collection_name,
        'was_collection_label': was_collection_label,
    }


def is_dirty_release_title(value: str | None, artist: str | None = None) -> bool:
    if not value:
        return False
    raw = str(value).strip()
    lower = raw.lower()
    slug = artist_slug(artist)
    if '_' in raw and len(raw) > 8:
        return True
    if slug and (lower.startswith(slug + '-') or lower.startswith(slug + '_')):
        return True
    if re.search(r'-(?:' + '|'.join(sorted(RELEASE_SUFFIXES)) + r')$', lower):
        return True
    if re.match(r'^[a-z0-9_]+-[a-z0-9_()\.]+-[a-z0-9]+$', lower):
        return True
    if re.match(r'^[a-z0-9_]+-\d{1,2}-[a-z0-9_()\.]+$', lower):
        return True
    if re.match(r'^\d{1,2}\s*-\s*\(?\d{1,3}\)?[_\s.-]*[\[_]?[a-z0-9_]+', lower):
        return True
    if lower == raw and '_' in raw:
        return True
    return False


def clean_title(name):
    value = str(name or '').strip()
    stem = Path(value).stem if Path(value).suffix.lower() in MUSIC_EXTENSIONS else value
    cleaned = re.sub(r'^(?:\d+[-_.\s]+)?\d+\s*[-_.]+\s*', '', stem).strip()
    cleaned = re.sub(r'^\d+\s*[-_.]\s*', '', cleaned).strip()
    return cleaned or value


def remove_release_suffix(text: str, dirty: bool) -> str:
    if not dirty or '-' not in text:
        return text
    left, right = text.rsplit('-', 1)
    suffix = re.sub(r'[^a-z0-9]', '', right.lower())
    if 2 <= len(suffix) <= 12 and (suffix in RELEASE_SUFFIXES or re.fullmatch(r'[a-z0-9]{2,12}', suffix)):
        return left.strip()
    return text


def remove_artist_prefix(text: str, canonical_artist: str | None, collection_label: str | None = None) -> tuple[str, str | None]:
    value = text.strip()
    bracket = re.match(r'^\[([^\]]+)\][\s_-]*(.+)$', value)
    if bracket:
        prefix = bracket.group(1)
        if likely_artist_prefix(prefix, canonical_artist):
            return bracket.group(2).strip(), slug_to_display(prefix)
    if '-' not in value:
        return value, None
    left, right = value.split('-', 1)
    left_clean = left.strip(' []_')
    canonical = artist_slug(canonical_artist)
    collection = artist_slug(collection_label)
    left_slug = artist_slug(left_clean)
    if (
        likely_artist_prefix(left_clean, canonical_artist)
        or (canonical and canonical in left_slug)
        or (collection and collection in left_slug)
    ):
        return right.strip(), slug_to_display(left_clean)
    return value, None


def final_title_format(text: str, canonical_artist: str | None = None, album: str | None = None) -> str:
    value = text.replace('_-_', '-').replace('_', ' ')
    value = re.sub(r'\s*-\s*', ' - ', value)
    value = re.sub(r'\s+', ' ', value).strip()
    value = re.sub(r'\(\s+', '(', value)
    value = re.sub(r'\s+\)', ')', value)
    value = re.sub(r'\bfeat\.?\b', 'Feat.', value, flags=re.I)
    value = re.sub(r'\bft\.?\b', 'Ft.', value, flags=re.I)
    formatted = title_case_release(value, canonical_artist)
    if album and normalize_compare(formatted) == normalize_compare(album):
        return album
    return formatted


def clean_release_title(value: str, artist: str | None = None, collection_label: str | None = None, album: str | None = None) -> str:
    parsed = parse_scene_track_filename(value, artist, collection_label, album)
    return parsed['clean_title']


def parse_track_number_title(stem: str) -> tuple[int | None, int | None, str]:
    parsed = parse_scene_track_filename(stem, None)
    return parsed.get('disc'), parsed.get('track_number'), parsed.get('raw_title') or stem


def parse_scene_track_filename(stem: str, canonical_artist: str | None, collection_label: str | None = None, album: str | None = None) -> dict[str, Any]:
    value = str(stem)
    parsed_path = Path(value)
    original = parsed_path.stem if parsed_path.suffix.lower() in MUSIC_EXTENSIONS else value
    text = original.strip()
    dirty = is_dirty_release_title(text, canonical_artist) or '_' in text
    text = re.sub(r'_+\s*-\s*_+', '-', text)
    text = re.sub(r'\s*_+\s*', '_', text)
    text = re.sub(r'\s+', ' ', text)
    disc = None
    track_number = None

    patterns = [
        r'^(?P<disc>\d{1,2})\s*-\s*(?P<track>\d{1,3})\s*[-_.]\s*(?P<title>.+)$',
        r'^(?P<disc>\d{1,2})-(?P<track>\d{2})\s*-\s*(?P<title>.+)$',
        r'^(?P<track>\d{1,3})\s*-\s*\((?P<track2>\d{1,3})\)[_\s.-]*(?P<title>.+)$',
        r'^(?P<track>\d{1,3})\s*[-_.]\s*(?P<title>.+)$',
    ]
    for pattern in patterns:
        match = re.match(pattern, text)
        if match:
            groups = match.groupdict()
            disc = int(groups['disc']) if groups.get('disc') else disc
            track_number = int(groups.get('track2') or groups.get('track') or 0) or track_number
            text = groups['title'].strip()
            break

    text = re.sub(r'^[\s_-]+', '', text).strip()
    text = re.sub(r'^\(?\d{1,3}\)?[_\s.-]+', '', text).strip()
    text = re.sub(r'^(\d{1,3})\.(?=[A-Za-z])', '', text).strip()
    text = re.sub(r'^\[([^\]]+)\][\s_-]*', r'[\1] ', text).strip()
    text = re.sub(r'_+\s*-\s*_+', '-', text)
    text = re.sub(r'\s*_+\s*', '_', text)
    text = re.sub(r'\s+', ' ', text).strip()

    detected_prefix_artist = None
    for _ in range(2):
        text, detected = remove_artist_prefix(text, canonical_artist, collection_label)
        if detected and not detected_prefix_artist:
            detected_prefix_artist = detected
        text = re.sub(r'^[\s_-]+', '', text).strip()
        text = re.sub(r'^\d{1,3}\s*[-_.]\s*', '', text).strip()

    scene_dirty = dirty or bool(detected_prefix_artist) or '_' in original or re.search(r'-[A-Za-z0-9]{2,12}$', original)
    text = remove_release_suffix(text, scene_dirty)
    text = re.sub(r'^\(?\d{1,3}\)?[_\s.-]+', '', text).strip()
    clean = final_title_format(text, canonical_artist, album)
    return {
        'disc': disc,
        'track_number': track_number,
        'raw_title': text,
        'clean_title': clean,
        'detected_prefix_artist': detected_prefix_artist,
    }


def clean_album(name):
    if not name:
        return name
    _, title = year_title(str(name))
    return re.sub(r'^(cd|disc)\s*\d+$', '', title, flags=re.I).strip() or title


def discography_filenames(collection_dir: Path) -> list[str]:
    if not collection_dir.is_dir():
        return []
    try:
        return [p.name for p in collection_dir.rglob('*') if p.is_file() and p.suffix.lower() in MUSIC_EXTENSIONS][:500]
    except Exception:
        return []


def parse_discography_path(path: Path, music_root: Path) -> dict[str, Any] | None:
    try:
        parts = path.relative_to(music_root).parts
    except ValueError:
        return None
    if len(parts) < 4 or parts[0].lower() != 'discographies':
        return None
    collection_label = parts[1]
    collection_dir = music_root / 'Discographies' / collection_label
    artist_info = resolve_discography_artist(collection_label, discography_filenames(collection_dir))
    artist = artist_info['display_artist']
    album_folder = next((part for part in parts[2:-1] if re.match(r'^\d{4}\s*-', part)), path.parent.name)
    year, album_name = year_title(album_folder)
    album = clean_album(album_name)
    parsed = parse_scene_track_filename(path.stem, artist, collection_label, album)
    return {
        'artist': artist,
        'album_artist': artist,
        'collection_label': collection_label,
        'album': album,
        'year': year,
        'disc': parsed['disc'],
        'track_number': parsed['track_number'],
        'title': parsed['clean_title'],
        'library_area': 'Discographies',
    }


def sidecar(path, root):
    for folder in [path.parent, *path.parents]:
        if folder == root.parent:
            break
        for name in ('music-album.json', 'discography.json', 'album.json', 'metadata.json'):
            for file in (folder / 'metadata' / name, folder / name):
                if file.is_file():
                    try:
                        return json.loads(file.read_text(encoding='utf-8'))
                    except Exception:
                        return {}
    return {}


def flatten_sidecar(side: dict[str, Any]) -> dict[str, Any]:
    meta = side.get('suggested_metadata') if isinstance(side.get('suggested_metadata'), dict) else {}
    album = side.get('album') if isinstance(side.get('album'), dict) else {}
    out = {**album, **side, **meta}
    if isinstance(out.get('artist'), dict):
        out['artist'] = out['artist'].get('name')
    return out


def infer(path, root):
    discography = parse_discography_path(path, root)
    if discography:
        return discography
    parts = path.relative_to(root).parts
    for marker in ('MP3', 'FLAC'):
        if marker in parts:
            i = parts.index(marker)
            artist = parts[i + 1] if len(parts) > i + 1 else None
            folder = next((p for p in parts[i + 2:-1] if re.match(r'^\d{4}\s*-', p)), path.parent.name)
            year, album = year_title(folder)
            return {'artist': artist, 'album': clean_album(album), 'album_artist': artist, 'year': year, 'library_area': 'Library'}
    return {'library_area': 'Library'}


def pick(side, path_data, tags, key):
    s = side.get(key) or side.get({'album_artist': 'albumartist'}.get(key, ''))
    if s:
        return s
    p = path_data.get(key)
    if p:
        return p
    v = tags.get(key)
    return None if generic(v) else v


def find_cover(album_dir: Path, roots: list[Path]) -> str | None:
    dirs = [album_dir, album_dir / 'metadata', album_dir / 'Artwork', album_dir / 'artwork', album_dir / 'Covers', album_dir / 'covers']
    for directory in dirs:
        if not directory.is_dir() or not is_approved_path(directory, roots):
            continue
        files = [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
        for stem in COVER_STEMS:
            for p in files:
                if p.stem.lower() == stem and is_approved_path(p, roots):
                    return str(p)
            for p in files:
                if p.stem.lower().startswith(stem) and is_approved_path(p, roots):
                    return str(p)
    return None


def scan_music(db: Session):
    roots = [Path(settings.MUSIC_MP3_ROOT), Path(settings.MUSIC_FLAC_ROOT), Path(settings.MUSIC_DISCOGRAPHIES_ROOT)]
    existing = [r for r in roots if r.is_dir()]
    root = Path(settings.MUSIC_ROOT)
    result = {
        'status': 'ok',
        'tracks_scanned': 0,
        'tracks_added': 0,
        'tracks_updated': 0,
        'roots_scanned': [str(r) for r in existing],
        'skipped_roots': [str(r) for r in roots if not r.is_dir()],
        'errors': [],
    }
    for scan_root in existing:
        for path in safe_media_files(scan_root, MUSIC_EXTENSIONS, existing):
            try:
                tags = read_metadata(path)
                path_data = infer(path, root)
                side = flatten_sidecar(sidecar(path, root))
                is_discography = path_data.get('library_area') == 'Discographies'

                artist = path_data.get('artist') if is_discography else (pick(side, path_data, tags, 'artist') or path.parent.name)
                album_artist = path_data.get('album_artist') if is_discography else (pick(side, path_data, tags, 'album_artist') or artist)
                album = clean_album(path_data.get('album') if is_discography else (pick(side, path_data, tags, 'album') or path_data.get('album') or path.parent.name))
                year = path_data.get('year') if is_discography else pick(side, path_data, tags, 'year')

                raw_title = tags.get('title') or path.stem
                path_title = path_data.get('title') or clean_release_title(path.stem, artist, path_data.get('collection_label'), album)
                if is_discography or is_dirty_release_title(raw_title, artist):
                    title = path_title
                else:
                    title = clean_title(raw_title)

                cover = find_cover(path.parent, existing)
                data = {
                    'relative_path': str(path.relative_to(root)),
                    'title': title,
                    'artist': artist,
                    'album': album,
                    'album_artist': album_artist or artist,
                    'genre': pick(side, path_data, tags, 'genre'),
                    'year': year,
                    'duration_seconds': tags.get('duration_seconds'),
                    'file_ext': path.suffix.lower(),
                    'library_area': path_data.get('library_area', 'Library'),
                    'cover_path': cover,
                    'last_indexed_at': datetime.now(timezone.utc),
                }
                track = db.query(models.Track).filter_by(path=str(path)).one_or_none()
                if track:
                    for key, value in data.items():
                        setattr(track, key, value)
                    result['tracks_updated'] += 1
                else:
                    db.add(models.Track(path=str(path), **data))
                    result['tracks_added'] += 1
                result['tracks_scanned'] += 1
            except Exception as exc:
                result['errors'].append(f'{path}: {exc}')
    db.commit()
    return result
