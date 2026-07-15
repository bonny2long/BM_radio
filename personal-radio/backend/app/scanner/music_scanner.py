from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import os
import json
import re

from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..media_identity import duration_bucket, music_recording_key, music_track_release_key
from ..music_identity_graph import materialize_music_identity_graph
from ..scan_runs import MEDIA_KIND_MUSIC, complete_scan_run, fail_scan_run, mark_track_seen, reconcile_unseen_tracks, start_scan_run
from .archive_assistant_manifest import extract_music_manifest_metadata, load_aa_manifest_context
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

def _dedupe_root_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def configured_music_scan_roots() -> list[Path]:
    roots = [Path(settings.MUSIC_FLAC_ROOT), Path(settings.MUSIC_MP3_ROOT)]
    if settings.BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN:
        roots.append(Path(settings.MUSIC_DISCOGRAPHIES_ROOT))

    seen: set[str] = set()
    unique_roots: list[Path] = []
    for root in roots:
        key = _dedupe_root_key(root)
        if key in seen:
            continue
        seen.add(key)
        unique_roots.append(root)
    return unique_roots


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
    if artist and normalize_compare(strip_known_leading_segments(raw, artist=artist)) != normalize_compare(raw):
        return True
    if lower == raw and '_' in raw:
        return True
    return False


def clean_title(name):
    value = str(name or '').strip()
    stem = Path(value).stem if Path(value).suffix.lower() in MUSIC_EXTENSIONS else value
    cleaned = strip_duplicate_track_prefix(stem, None)
    return cleaned or value


def strip_duplicate_track_prefix(text: str, track_number: int | None) -> str:
    value = str(text or '').strip()
    if not value:
        return value

    if track_number is not None:
        value = re.sub(r'^\(?\d{1,2}\)?\s*[-_.]\s*', '', value).strip()
        value = re.sub(r'^\(?\d{1,2}\)?\s+(?=[A-Za-z])', '', value).strip()
        return value

    value = re.sub(r'^\(?\d{1,2}\)?\s*[-_.]\s*', '', value).strip()
    value = re.sub(r'^\(\d{1,3}\)\s+', '', value).strip()
    return value


def strip_vinyl_side_prefix(text: str) -> str:
    return re.sub(r'^[A-H]\d{1,2}\s*[-_.]?\s+(?=[A-Za-z0-9])', '', str(text or '').strip())


def segment_is_track_marker(segment: str, track_number: int | None = None) -> bool:
    value = str(segment or '').strip().strip('.').strip()
    if not value:
        return False
    if re.fullmatch(r'\(?\d{1,2}\)?', value):
        if track_number is None:
            return True
        return int(value.strip('()')) == int(track_number)
    if re.fullmatch(r'\d{1,2}-\d{1,2}', value):
        return True
    return False


def segment_is_year_marker(segment: str, year: int | str | None) -> bool:
    value = str(segment or '').strip()
    if not re.fullmatch(r'\d{4}', value):
        return False
    try:
        return year is not None and int(value) == int(str(year)[:4])
    except Exception:
        return False


def segment_is_artist_marker(segment: str, artist: str | None, album_artist: str | None = None) -> bool:
    value = normalize_compare(segment)
    return bool(value and (value == normalize_compare(artist) or value == normalize_compare(album_artist)))


def strip_known_leading_segments(
    text: str,
    artist: str | None = None,
    album_artist: str | None = None,
    album: str | None = None,
    year: int | str | None = None,
    track_number: int | None = None,
) -> str:
    value = str(text or '').strip()
    if not value:
        return value
    value = re.sub(r'_+', ' ', value)
    value = re.sub(r'\s*[-??]+\s*', ' - ', value)
    value = strip_duplicate_track_prefix(value, track_number)
    value = strip_vinyl_side_prefix(value)
    parts = [part.strip() for part in value.split(' - ') if part.strip()]
    dropped_metadata = track_number is not None
    while len(parts) > 1:
        first = parts[0]
        if segment_is_track_marker(first, track_number):
            parts.pop(0)
            dropped_metadata = True
            continue
        if segment_is_artist_marker(first, artist, album_artist):
            parts.pop(0)
            dropped_metadata = True
            continue
        if segment_is_year_marker(first, year) or (dropped_metadata and re.fullmatch(r'(?:19|20)\d{2}', first)):
            parts.pop(0)
            dropped_metadata = True
            continue
        if album and normalize_compare(first) == normalize_compare(album):
            parts.pop(0)
            dropped_metadata = True
            continue
        break
    cleaned = ' - '.join(parts) if parts else value
    cleaned = strip_duplicate_track_prefix(cleaned, track_number)
    cleaned = strip_vinyl_side_prefix(cleaned)
    return final_title_format(cleaned, artist, album)


def is_weak_embedded_title(
    embedded_title: str | None,
    path_title: str | None,
    artist: str | None,
    album: str | None,
    year: int | None,
) -> bool:
    embedded = str(embedded_title or '').strip()
    path_value = str(path_title or '').strip()
    if not embedded:
        return True
    if generic(embedded):
        return True

    embedded_norm = normalize_compare(embedded)
    path_norm = normalize_compare(path_value)
    if not embedded_norm:
        return True
    if year and embedded_norm == str(year):
        return True
    if artist and embedded_norm == normalize_compare(artist):
        return True
    if album and embedded_norm == normalize_compare(album):
        return True
    cleaned_embedded = strip_known_leading_segments(embedded, artist=artist, album=album, year=year)
    cleaned_norm = normalize_compare(cleaned_embedded)
    if path_norm and cleaned_norm == path_norm and cleaned_norm != embedded_norm:
        return True
    if path_norm and embedded_norm != path_norm and embedded_norm in path_norm:
        embedded_has_number = bool(re.search(r'\d', embedded))
        path_has_number = bool(re.search(r'\d', path_value))
        if path_has_number and not embedded_has_number:
            return True
    return False


def remove_release_suffix(text: str, dirty: bool) -> str:
    if not dirty or '-' not in text:
        return text
    left, right = text.rsplit('-', 1)
    suffix = re.sub(r'[^a-z0-9]', '', right.lower())
    if 2 <= len(suffix) <= 12 and suffix in RELEASE_SUFFIXES:
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
    text = strip_duplicate_track_prefix(text, track_number)
    if track_number is not None:
        text = strip_vinyl_side_prefix(text)
    text = re.sub(r'^(\d{1,2})\.(?=[A-Za-z])', '', text).strip()
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
        text = strip_duplicate_track_prefix(text, track_number)
        if track_number is not None:
            text = strip_vinyl_side_prefix(text)

    scene_dirty = dirty or bool(detected_prefix_artist) or '_' in original or re.search(r'-[A-Za-z0-9]{2,12}$', original)
    text = remove_release_suffix(text, scene_dirty)
    text = strip_duplicate_track_prefix(text, track_number)
    if track_number is not None:
        text = strip_vinyl_side_prefix(text)
    album_year, _ = year_title(album or '')
    clean = strip_known_leading_segments(text, artist=canonical_artist, album_artist=canonical_artist, album=album, year=album_year, track_number=track_number)
    return {
        'disc': disc,
        'track_number': track_number,
        'raw_title': text,
        'clean_title': clean,
        'detected_prefix_artist': detected_prefix_artist,
    }


def _title_parser_regression_cases() -> list[tuple[str, str, str | None, str]]:
    return [
        ("01 - 01. 100 Grandkids", "Mac Miller", "100 Grandkids", "100 Grandkids"),
        ("01 - 01. Break the Law", "Mac Miller", "Break the Law", "Break the Law"),
        ("01 - 05. 100 Grandkids", "Mac Miller", "GOOD AM", "100 Grandkids"),
        ("01 - 10. Break the Law", "Mac Miller", "GOOD AM", "Break the Law"),
        ("01 - A1 Bixby Canyon Bridge", "Death Cab for Cutie", "Narrow Stairs", "Bixby Canyon Bridge"),
        ("01 - A2 I Will Possess Your Heart", "Death Cab for Cutie", "Narrow Stairs", "I Will Possess Your Heart"),
        ("01 - A3 No Sunlight", "Death Cab for Cutie", "Narrow Stairs", "No Sunlight"),
        ("01 - A4 Cath...", "Death Cab for Cutie", "Narrow Stairs", "Cath..."),
        ("01 - 01 - Death Cab For Cutie - Photobooth", "Death Cab for Cutie", "Forbidden Love EP", "Photobooth"),
        ("01 - 05 - Death Cab For Cutie - Company Calls Epilogue (Alternate)", "Death Cab for Cutie", "Forbidden Love EP", "Company Calls Epilogue (Alternate)"),
        ("1-01 - 01-Bend_To_Squares", "Death Cab for Cutie", "Something About Airplanes", "Bend To Squares"),
        ("01 - 04 - S.D.S.", "Mac Miller", "Watching Movies with the Sound Off", "S.D.S."),
        ("01 - Bastille - 2013 - Pompeii", "Bastille", "Bad Blood", "Pompeii"),
        ("02 - Bastille - 2013 - Things We Lost In The Fire", "Bastille", "Bad Blood", "Things We Lost In the Fire"),
        ("03 - Bastille - 2013 - Bad Blood", "Bastille", "Bad Blood", "Bad Blood"),
        ("01 - 01 - Bastille - 2013 - Pompeii", "Bastille", "Bad Blood", "Pompeii"),
        ("01 - 12. 2009", "Mac Miller", "Swimming", "2009"),
        ("01 - 15. 55", "Mac Miller", "Faces", "55"),
        ("01 - 18. 72", "Mac Miller", "I Love Life, Thank You", "72"),
    ]


def run_title_parser_regression() -> list[str]:
    failures = []
    for stem, artist, album, expected in _title_parser_regression_cases():
        actual = parse_scene_track_filename(stem, artist, None, album)['clean_title']
        if actual != expected:
            failures.append(f"{stem}: expected {expected!r}, got {actual!r}")
    return failures


def strip_release_junk_suffix(title: str) -> str:
    value = str(title or '').strip()
    value = re.sub(r'\s+HDtracks(?:\s*\(\d{4}\))?$', '', value, flags=re.I).strip()
    value = re.sub(r'\s+\[?\d{2,3}(?:bit|kHz|khz|hz|flac|mp3)[^\]]*\]?$', '', value, flags=re.I).strip()
    return value


def strip_leading_album_year_from_title(title: str, year: int | None) -> str:
    value = str(title or '').strip()
    if year:
        value = re.sub(rf'^{int(year)}\s*[-_.]\s*', '', value).strip()
    return value


def clean_album(name):
    if not name:
        return name
    _, title = year_title(str(name))
    title = strip_release_junk_suffix(title)
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



def _pending_artist_profile(db: Session, artist: str | None):
    target = normalize_compare(artist)
    if not target:
        return None
    for item in db.new:
        if isinstance(item, models.ArtistRadioProfile) and normalize_compare(item.artist) == target:
            return item
    return None


def _pending_album_profile(db: Session, artist: str | None, album: str | None):
    target = (normalize_compare(artist), normalize_compare(album))
    if not target[0] or not target[1]:
        return None
    for item in db.new:
        if isinstance(item, models.AlbumRadioProfile) and (normalize_compare(item.artist), normalize_compare(item.album)) == target:
            return item
    return None


def _pending_track_profile(db: Session, track_id: int | None):
    if not track_id:
        return None
    for item in db.new:
        if isinstance(item, models.TrackRadioProfile) and item.track_id == track_id:
            return item
    return None


def seed_aa_radio_profiles(db: Session, track: models.Track, manifest_meta: dict[str, Any]) -> None:
    if manifest_meta.get('metadata_source') != 'archive_assistant_manifest':
        return
    primary_genre = manifest_meta.get('primary_genre') or manifest_meta.get('genre')
    if not primary_genre:
        return

    artist = manifest_meta.get('artist') or getattr(track, 'artist', None)
    album_artist = manifest_meta.get('album_artist') or getattr(track, 'album_artist', None) or artist
    album = manifest_meta.get('album') or getattr(track, 'album', None)

    seen_artist_keys: set[str] = set()
    for artist_name in [artist, album_artist]:
        artist_name = str(artist_name or '').strip()
        artist_key = normalize_compare(artist_name)
        if not artist_name or not artist_key or artist_key in seen_artist_keys:
            continue
        seen_artist_keys.add(artist_key)
        row = _pending_artist_profile(db, artist_name)
        if not row:
            with db.no_autoflush:
                row = db.query(models.ArtistRadioProfile).filter_by(artist=artist_name).one_or_none()
        if row and row.source == 'manual':
            continue
        if not row:
            row = models.ArtistRadioProfile(artist=artist_name, source='archive_assistant_manifest')
            db.add(row)
        if not row.primary_genre or row.source != 'manual':
            row.primary_genre = primary_genre
            row.source = 'archive_assistant_manifest'

    if album_artist and album:
        row = _pending_album_profile(db, album_artist, album)
        if not row:
            with db.no_autoflush:
                row = db.query(models.AlbumRadioProfile).filter_by(artist=album_artist, album=album).one_or_none()
        if not (row and row.source == 'manual'):
            if not row:
                row = models.AlbumRadioProfile(artist=album_artist, album=album, source='archive_assistant_manifest')
                db.add(row)
            if not row.primary_genre or row.source != 'manual':
                row.primary_genre = primary_genre
                row.source = 'archive_assistant_manifest'

    row = _pending_track_profile(db, getattr(track, 'id', None))
    if not row:
        with db.no_autoflush:
            row = db.query(models.TrackRadioProfile).filter_by(track_id=track.id).one_or_none()
    if row and row.source == 'manual':
        return
    if not row:
        row = models.TrackRadioProfile(track_id=track.id, source='archive_assistant_manifest')
        db.add(row)
    if not row.primary_genre or row.source != 'manual':
        row.primary_genre = primary_genre
        row.source = 'archive_assistant_manifest'

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


def _existing_track_identity(track: models.Track) -> tuple[str, str, int | None]:
    try:
        _, track_number, _ = parse_track_number_title(Path(track.relative_path or track.path or '').stem)
    except Exception:
        track_number = None
    release_key = music_track_release_key(track.album_artist or track.artist, track.album, track.title, track.year, track_number)
    recording_key = music_recording_key(track.artist, track.title, track.duration_seconds)
    duration = duration_bucket(track.duration_seconds, tolerance=5)
    return release_key, recording_key, duration


def _set_scan_failed(db: Session, scan_run: models.ScanRun, result: dict[str, Any], error_summary: str, error_count: int) -> None:
    scan_run.items_discovered = result['tracks_scanned']
    scan_run.items_added = result['tracks_added']
    scan_run.items_updated = result['tracks_updated']
    scan_run.items_unavailable = 0
    fail_scan_run(db, scan_run, error_summary=error_summary, error_count=error_count)
    result['status'] = 'failed'
    result['scan_run_status'] = 'failed'
    result['tracks_unavailable'] = 0


def scan_music(db: Session):
    roots = configured_music_scan_roots()
    existing = [r for r in roots if r.is_dir()]
    root = Path(settings.MUSIC_ROOT)
    result = {
        'status': 'running',
        'scan_run_id': None,
        'scan_run_status': 'running',
        'tracks_scanned': 0,
        'tracks_added': 0,
        'tracks_updated': 0,
        'tracks_unavailable': 0,
        'roots_scanned': [str(r) for r in existing],
        'skipped_roots': [str(r) for r in roots if not r.is_dir()],
        'legacy_discography_scan_enabled': settings.BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN,
        'errors': [],
        'weak_titles_detected': 0,
        'titles_corrected': 0,
        'title_parser_failures': run_title_parser_regression(),
        'metadata_heavy_titles_cleaned': 0,
        'duplicates_skipped': 0,
        'duplicates_suspected': 0,
        'variants_detected': 0,
        'duplicate_warnings': [],
        'identity_tracks_materialized': 0,
        'physical_sources_preserved': 0,
    }

    scan_run = start_scan_run(db, media_kind=MEDIA_KIND_MUSIC, roots=[str(r) for r in existing])
    db.commit()
    scan_run_id = scan_run.id
    result['scan_run_id'] = scan_run_id

    if not existing:
        result['errors'].append('No configured music scan roots exist on disk; failing closed without reconciliation.')
        _set_scan_failed(db, scan_run, result, result['errors'][0], 1)
        db.commit()
        return result

    try:
        existing_tracks = db.query(models.Track).all()
        exact_path_tracks = {track.path: track for track in existing_tracks if track.path}
        release_seen: dict[str, dict[str, Any]] = {}
        recording_seen: dict[str, dict[str, Any]] = {}
        identity_track_ids: set[int] = set()
        for existing_track in existing_tracks:
            if existing_track.library_availability == 'unavailable':
                continue
            release_key, recording_key, duration = _existing_track_identity(existing_track)
            release_seen.setdefault(release_key, {'id': existing_track.id, 'path': existing_track.path, 'duration_bucket': duration, 'title': existing_track.title})
            recording_seen.setdefault(recording_key, {'id': existing_track.id, 'path': existing_track.path, 'release_key': release_key, 'title': existing_track.title})

        manifest_cache: dict[str, Any] = {}
        for scan_root in existing:
            for path in safe_media_files(scan_root, MUSIC_EXTENSIONS, existing):
                result['tracks_scanned'] += 1
                try:
                    path_text = str(path)
                    tags = read_metadata(path)
                    path_data = infer(path, root)
                    side = flatten_sidecar(sidecar(path, root))
                    aa_context = load_aa_manifest_context(path, existing, manifest_cache)
                    aa_meta = extract_music_manifest_metadata(aa_context, path)
                    is_discography = path_data.get('library_area') == 'Discographies'

                    fallback_artist = path_data.get('artist') if is_discography else (pick(side, path_data, tags, 'artist') or path.parent.name)
                    artist = aa_meta.get('artist') or fallback_artist
                    fallback_album_artist = path_data.get('album_artist') if is_discography else (pick(side, path_data, tags, 'album_artist') or artist)
                    album_artist = aa_meta.get('album_artist') or fallback_album_artist or artist
                    fallback_album = path_data.get('album') if is_discography else (pick(side, path_data, tags, 'album') or path_data.get('album') or path.parent.name)
                    album = clean_album(aa_meta.get('album') or fallback_album)
                    year = aa_meta.get('year') or (path_data.get('year') if is_discography else pick(side, path_data, tags, 'year'))

                    embedded_title = tags.get('title')
                    raw_title = embedded_title or path.stem
                    path_title = path_data.get('title') or clean_release_title(path.stem, artist, path_data.get('collection_label'), album)
                    path_title = strip_leading_album_year_from_title(path_title, year)
                    cleaned_embedded_title = strip_known_leading_segments(embedded_title or '', artist=artist, album_artist=album_artist, album=album, year=year)
                    weak_title = is_weak_embedded_title(embedded_title, path_title, artist, album, year)
                    metadata_heavy = bool(embedded_title and cleaned_embedded_title and normalize_compare(cleaned_embedded_title) != normalize_compare(embedded_title))
                    if aa_meta.get('title'):
                        title = str(aa_meta.get('title')).strip()
                    elif is_discography:
                        title = path_title
                        if weak_title:
                            result['weak_titles_detected'] += 1
                            result['titles_corrected'] += 1
                    elif weak_title:
                        title = path_title
                        result['weak_titles_detected'] += 1
                        result['titles_corrected'] += 1
                    elif metadata_heavy:
                        title = cleaned_embedded_title
                        result['metadata_heavy_titles_cleaned'] += 1
                        result['titles_corrected'] += 1
                    elif is_dirty_release_title(raw_title, artist):
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
                        'genre': aa_meta.get('genre') or pick(side, path_data, tags, 'genre'),
                        'year': year,
                        'duration_seconds': tags.get('duration_seconds'),
                        'file_ext': path.suffix.lower(),
                        'library_area': path_data.get('library_area', 'Library'),
                        'cover_path': cover,
                        'metadata_source': aa_meta.get('metadata_source') or ('embedded_tag' if any(tags.get(k) for k in ('title', 'artist', 'album', 'genre', 'year')) else 'path_inference'),
                        'source_manifest_path': aa_meta.get('source_manifest_path'),
                        'source_manifest_version': aa_meta.get('source_manifest_version'),
                        'source_metadata_version': aa_meta.get('source_metadata_version'),
                        'track_number': aa_meta.get('track_number') or path_data.get('track_number'),
                        'disc_number': aa_meta.get('disc_number') or path_data.get('disc'),
                        'primary_genre': aa_meta.get('primary_genre') or aa_meta.get('genre') or pick(side, path_data, tags, 'genre'),
                        'last_indexed_at': datetime.now(timezone.utc),
                    }
                    track_number = data.get('track_number')
                    release_key = music_track_release_key(data['album_artist'], data['album'], data['title'], data['year'], track_number)
                    recording_key = music_recording_key(data['artist'], data['title'], data['duration_seconds'])
                    file_duration_bucket = duration_bucket(data['duration_seconds'], tolerance=5)

                    track = exact_path_tracks.get(path_text)
                    if track:
                        for key, value in data.items():
                            setattr(track, key, value)
                        mark_track_seen(track, scan_run_id=scan_run_id)
                        result['tracks_updated'] += 1
                    else:
                        seen_release = release_seen.get(release_key)
                        if seen_release and seen_release.get('path') != path_text and seen_release.get('duration_bucket') == file_duration_bucket:
                            result['physical_sources_preserved'] += 1
                            result['duplicate_warnings'].append({
                                'type': 'physical_source_preserved',
                                'media_kind': 'music',
                                'title': data['title'],
                                'existing_id': seen_release.get('id'),
                                'candidate_path': path_text,
                                'reason': 'similar release identity and duration; distinct physical path retained for identity/preference resolution',
                            })
                        seen_recording = recording_seen.get(recording_key)
                        if seen_recording and seen_recording.get('path') != path_text and seen_recording.get('release_key') != release_key:
                            result['duplicates_suspected'] += 1
                            result['duplicate_warnings'].append({
                                'type': 'recording_duplicate_detected',
                                'media_kind': 'music',
                                'title': data['title'],
                                'existing_id': seen_recording.get('id'),
                                'candidate_path': path_text,
                                'reason': 'same recording key across different releases; kept as possible variant',
                            })

                        track = models.Track(path=path_text, **data)
                        db.add(track)
                        db.flush()
                        exact_path_tracks[path_text] = track
                        mark_track_seen(track, scan_run_id=scan_run_id)
                        result['tracks_added'] += 1

                    if getattr(track, 'id', None) is not None:
                        identity_track_ids.add(track.id)
                    release_seen[release_key] = {'id': getattr(track, 'id', None), 'path': path_text, 'duration_bucket': file_duration_bucket, 'title': data['title']}
                    recording_seen.setdefault(recording_key, {'id': getattr(track, 'id', None), 'path': path_text, 'release_key': release_key, 'title': data['title']})
                    seed_aa_radio_profiles(db, track, aa_meta)
                except Exception as exc:
                    result['errors'].append(f'{path}: {exc}')

        db.flush()
        if result['errors']:
            _set_scan_failed(db, scan_run, result, '\n'.join(result['errors']), len(result['errors']))
            db.commit()
            return result

        try:
            identity_result = materialize_music_identity_graph(db, track_ids=sorted(identity_track_ids))
            result['identity_tracks_materialized'] = identity_result['tracks_seen']
        except Exception as exc:
            db.rollback()
            scan_run = db.get(models.ScanRun, scan_run_id)
            result['errors'].append(f'identity materialization failed: {exc}')
            _set_scan_failed(db, scan_run, result, str(exc), max(1, len(result['errors'])))
            db.commit()
            return result

        unavailable = reconcile_unseen_tracks(db, scan_run_id=scan_run_id, scanned_roots=existing)
        result['tracks_unavailable'] = unavailable
        complete_scan_run(
            db,
            scan_run,
            items_discovered=result['tracks_scanned'],
            items_added=result['tracks_added'],
            items_updated=result['tracks_updated'],
            items_unavailable=unavailable,
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
            scan_run = start_scan_run(db, media_kind=MEDIA_KIND_MUSIC, roots=[str(r) for r in existing])
            result['scan_run_id'] = scan_run.id
        result['errors'].append(str(exc))
        _set_scan_failed(db, scan_run, result, str(exc), max(1, len(result['errors'])))
        db.commit()
        return result
