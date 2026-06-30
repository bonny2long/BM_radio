from .. import models

def track_item(track: models.Track) -> dict:
    return {
        'id': track.id,
        'title': track.title,
        'artist': track.artist,
        'album': track.album,
        'genre': track.genre,
        'primary_genre': getattr(track, 'primary_genre', None),
        'year': track.year,
        'duration_seconds': track.duration_seconds,
        'file_ext': track.file_ext,
        'library_area': track.library_area,
        'metadata_source': getattr(track, 'metadata_source', None),
        'source_manifest_path': getattr(track, 'source_manifest_path', None),
        'source_manifest_version': getattr(track, 'source_manifest_version', None),
        'source_metadata_version': getattr(track, 'source_metadata_version', None),
        'track_number': getattr(track, 'track_number', None),
        'disc_number': getattr(track, 'disc_number', None),
        'stream_url': f'/api/media/tracks/{track.id}/stream',
        'cover_url': f'/api/media/tracks/{track.id}/cover',
    }

def chapter_item(chapter: models.AudiobookChapter) -> dict:
    return {
        'id': chapter.id,
        'title': chapter.title,
        'sort_order': chapter.sort_order,
        'duration_seconds': chapter.duration_seconds,
        'stream_url': f'/api/media/audiobooks/{chapter.audiobook_id}/chapters/{chapter.id}/stream',
    }

def audiobook_item(book: models.Audiobook) -> dict:
    return {
        'id': book.id,
        'title': book.title,
        'author': book.author,
        'narrator': book.narrator,
        'status': book.status,
        'favorite': book.favorite,
        'duration_seconds': book.duration_seconds,
        'metadata_source': getattr(book, 'metadata_source', None),
        'source_manifest_path': getattr(book, 'source_manifest_path', None),
        'source_manifest_version': getattr(book, 'source_manifest_version', None),
        'source_metadata_version': getattr(book, 'source_metadata_version', None),
        'cover_url': f'/api/media/audiobooks/{book.id}/cover',
    }