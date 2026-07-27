# BM Radio Technical Runbook

Owner: Bonny Makaniankhondo  
Project: NAS System / BM Radio  
Updated: 2026-07-27  
Status: Local app is actively working with scanner, playback, playlists, radio profiles, music deduplication, and library integrity. UI polish is ongoing.

## 1. Purpose

This runbook records the technical state and intended operating model for BM Radio.

BM Radio is a separate app that reads final Music and Audiobooks libraries from the NAS-style `nas-data` root. It provides private radio playback, direct music playback, playlist management, queue tracking, and audiobook listening.

## 2. Current stack

Current stack:

```text
Backend: FastAPI + SQLAlchemy + SQLite
Frontend: React + TypeScript + Vite
Playback: browser Audio object managed by React playback context
Metadata reading: mutagen in backend scanner
Default backend port: 8094
Default frontend port: 5174
```

Current project root inside ZIP:

```text
BM_radio-main/personal-radio
```

Primary folders:

```text
personal-radio/
  backend/
    app/
      config.py
      db.py
      main.py
      models.py
      routes/
      scanner/
  frontend/
    src/
      components/
      pages/
      state/
      styles/
      utils/
  docs/
```

## 3. Local NAS data contract

Local development should connect to the shared NAS-style folder used by Intake Watcher, Archive Assistant, and Cleaner:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data
```

BM Radio should read:

```text
nas-data/Music/Library/MP3
nas-data/Music/Library/FLAC
nas-data/Music/Discographies
nas-data/Audiobooks/Library
```

BM Radio should not scan:

```text
nas-data/_INGEST
nas-data/_STAGING
nas-data/_QUARANTINE
nas-data/_REPORTS
nas-data/_METADATA_RECOVERY
```

## 4. Current environment variables

Recommended local backend env:

```env
APP_NAME=BM Radio
APP_ENV=development
TZ=America/Chicago

NAS_DATA_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data
MUSIC_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music
MUSIC_LIBRARY_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Library
MUSIC_FLAC_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Library\FLAC
MUSIC_MP3_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Library\MP3
MUSIC_DISCOGRAPHIES_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Discographies
MUSIC_PLAYLISTS_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Playlists
MUSIC_METADATA_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Music\Metadata
AUDIOBOOKS_ROOT=C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data\Audiobooks\Library

DATABASE_URL=sqlite:///./bm_radio.db
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8094
FRONTEND_PORT=5174
PUBLIC_ACCESS=false
ALLOW_FILE_MUTATION=false
ALLOW_DELETE=false
ALLOW_TAG_WRITES=false
SCAN_INGEST_FOLDERS=false
```

Recommended frontend env:

```env
VITE_API_BASE_URL=http://127.0.0.1:8094/api
```

## 5. Backend route map

Current backend routers are mounted in `backend/app/main.py`.

```text
GET  /api/health

GET  /api/library/summary
GET  /api/library/paths
GET  /api/library/tracks
GET  /api/library/artists
GET  /api/library/albums
GET  /api/library/album-tracks?artist=&album=
POST /api/library/scan/music

GET  /api/integrity
GET  /api/integrity/scan-runs

GET  /api/playlists
GET  /api/playlists/smart
POST /api/playlists
POST /api/playlists/from-track-list
GET  /api/playlists/{playlist_id}
PATCH /api/playlists/{playlist_id}
DELETE /api/playlists/{playlist_id}
POST /api/playlists/{playlist_id}/tracks
DELETE /api/playlists/{playlist_id}/tracks/{track_id}
PATCH /api/playlists/{playlist_id}/tracks/reorder

GET  /api/stations/
POST /api/queue/station
POST /api/queue/album
POST /api/queue/artist
GET  /api/queue/current

GET  /api/radio-profiles/artists
GET  /api/radio-profiles/artists/{artist}
PATCH /api/radio-profiles/artists/{artist}
GET  /api/radio-profiles/tracks/{track_id}
PATCH /api/radio-profiles/tracks/{track_id}

GET  /api/recordings/{recording_id}/control
PUT  /api/recordings/{recording_id}/preferred-track
DELETE /api/recordings/{recording_id}/preferred-track
PUT  /api/recordings/{recording_id}/participation
DELETE /api/recordings/{recording_id}/participation

GET  /api/audiobooks/
GET  /api/audiobooks/summary
GET  /api/audiobooks/{audiobook_id}
POST /api/audiobooks/scan
POST /api/audiobooks/{audiobook_id}/progress
POST /api/audiobooks/{audiobook_id}/favorite
POST /api/audiobooks/{audiobook_id}/finished
POST /api/audiobooks/{audiobook_id}/not-started

GET  /api/media/tracks/{track_id}/stream
GET  /api/media/tracks/{track_id}/cover
GET  /api/media/albums/cover?artist=&album=
GET  /api/media/audiobooks/{audiobook_id}/chapters/{chapter_id}/stream
GET  /api/media/audiobooks/{audiobook_id}/cover

POST /api/playback/event
POST /api/playback/tracks/{track_id}/thumb
POST /api/playback/tracks/{track_id}/favorite
```

## 6. Database models

Current SQLAlchemy models:

```text
Core:
- Track
- Audiobook
- AudiobookChapter
- ScanRun

Library Organization / Feedback:
- Station
- Playlist
- PlaylistTrack
- TrackThumb
- TrackFavorite
- PlaybackEvent
- AudiobookProgress

Deduplication / Identity:
- MusicRelease
- MusicEdition
- MusicRecording
- MusicTrackIdentity
- MusicTechnicalProfile
- MusicRecordingPreference
- MusicRecordingParticipation

Radio Profiling:
- ArtistRadioProfile
- AlbumRadioProfile
- TrackRadioProfile
```

SQLite default database:

```text
backend/bm_radio.db
```

Future NAS target:

```text
PostgreSQL on fast-pool
```

Do not migrate to PostgreSQL until the local playback and UI are stable.

## 7. Scanner behavior

Music scanner:

```text
Scans MUSIC_MP3_ROOT, MUSIC_FLAC_ROOT, MUSIC_DISCOGRAPHIES_ROOT
Reads supported audio files, uses mutagen for available metadata
Stores title, artist, album, genre, year, duration, file extension, library area
Supports music track identity and recordings deduction
Does not mutate tags
```

Audiobook scanner:

```text
Scans AUDIOBOOKS_ROOT
Groups files by top-level book folder
Reads chapter files
Stores book, author fallback, year, duration, chapters
Does not mutate files
```

## 8. Path safety rules

Current backend path safety is in: `backend/app/scanner/path_safety.py`

Blocked folder parts:

```text
_INGEST, _STAGING, _QUARANTINE, _REPORTS, _METADATA_RECOVERY
```

Approved streaming roots:

```text
Music Library, Music Discographies, Audiobooks Library
```

Non-negotiable safety rules:

```text
No delete endpoints for media
No tag-writing endpoints
No ingest scanning
No final-library organization behavior
No cleanup behavior
No public exposure during local development
```

## 9. Media streaming behavior

Backend streaming uses `FileResponse` for approved audio files.
Supported audio MIME map covers standard formats (.mp3, .flac, .m4a, .m4b, .aac, .ogg, .opus, .wav).
Artwork lookup searches nearby cover image files (cover.jpg, folder.jpg, etc.) in the file's directory or subfolders.

## 10. Frontend structure

Current frontend pages:

```text
HomePage.tsx
RadioPage.tsx
LibraryPage.tsx
LibraryIntegrityPage.tsx
QueuePage.tsx
BookshelfPage.tsx
NowPlayingPage.tsx
AlbumDetailPage.tsx
ArtistDetailPage.tsx
PlaylistDetailPage.tsx
```

Current frontend components:

```text
AppShell.tsx, BottomNav.tsx, BottomSheet.tsx, TrackActionSheet.tsx, 
MiniPlayer.tsx, Artwork.tsx, IconButton.tsx, PlayerIcons.tsx, ProgressBar.tsx
```

Current playback state: `frontend/src/state/PlaybackContext.tsx`
Playback context owns the browser Audio object, current queue, queue index, play/pause state, current time, duration, and audiobook progress.

## 11. Local startup

Backend:

```powershell
cd C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\BM_radio-main\personal-radio\backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8094
```

Frontend:

```powershell
cd C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\BM_radio-main\personal-radio\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5174
```

## 12. Current verified development status

From current local state:

```text
BM Radio sees shared nas-data and library scans succeed.
Stations generate from scanned music.
Manual and smart playlists work.
Queue management and playback context function correctly.
Library Integrity endpoints show missing covers, unavailable tracks, etc.
Music Deduplication (Recordings/Participation) manages source preferences.
Audio playback is producing sound.
```

## 13. Current known issues / polish targets

Next coding pass should focus on:

```text
Ensure album art appears consistently across all views (Queue, MiniPlayer, Library).
Improve Home so it feels like a premium radio app.
Clean up audiobook metadata display: author, title, chapter labels.
Add complete Bookshelf filters: All, In Progress, Finished, Favorites.
Improve queue generation to avoid long same-album streaks.
Add clear empty/error/loading states.
```

## 14. Future TrueNAS mapping

Future NAS container mapping should prefer read-only mounts for media:

```text
/mnt/rust-pool/Music:/app/music:ro
/mnt/rust-pool/Audiobooks/Library:/app/audiobooks:ro
/mnt/rust-pool/Music/Playlists:/app/playlists:rw (only when playlist writing is intentionally approved)
/mnt/fast-pool/apps/personal-radio/database:/app/database
/mnt/fast-pool/apps/personal-radio/config:/app/config
/mnt/fast-pool/apps/personal-radio/cache:/app/cache
```

## 15. Acceptance tests before next document update

Before updating these docs again, verify:

```text
1. Backend starts on 8094 and Frontend starts on 5174.
2. /api/health returns ok.
3. Integrity page loads without errors.
4. Playlists load, can add/remove tracks.
5. Playback starts and progress tracks.
6. No weird characters appear in the UI.
7. No media files are modified or deleted.
```
