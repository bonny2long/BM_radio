# BM Radio Technical Runbook

Owner: Bonny Makaniankhondo  
Project: NAS System / BM Radio  
Updated: 2026-06-24  
Status: Early working local app. Scanner and playback exist. UI polish is ongoing.

## 1. Purpose

This runbook records the technical state and intended operating model for BM Radio.

BM Radio is a separate app that reads final Music and Audiobooks libraries from the NAS-style `nas-data` root. It provides private radio playback, direct music playback, and audiobook listening.

## 2. Current stack

Current scaffold stack:

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

Backend `.env.example` currently contains absolute local Windows paths.

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

Encoding note: the current inspected codebase has a UTF-8 BOM at the start of these files:

```text
backend/.env.example
frontend/.env.example
backend/app/routes/library.py
backend/app/routes/stations.py
```

This is not necessarily fatal, but the next cleanup pass should save these files as plain UTF-8 without BOM and search for replacement characters such as `�`.

## 5. Backend route map

Current backend routers are mounted in `backend/app/main.py`.

```text
GET  /api/health
GET  /api/library/summary
GET  /api/library/paths
GET  /api/library/tracks
GET  /api/library/artists
GET  /api/library/albums
GET  /api/library/search?q=
POST /api/library/scan/music
GET  /api/library/album-tracks?artist=&album=

GET  /api/stations/
POST /api/queue/station
POST /api/queue/album
POST /api/queue/artist
GET  /api/queue/current

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
Track
Audiobook
AudiobookChapter
Station
TrackThumb
TrackFavorite
PlaybackEvent
AudiobookProgress
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
Scans MUSIC_MP3_ROOT
Scans MUSIC_FLAC_ROOT
Scans MUSIC_DISCOGRAPHIES_ROOT
Reads supported audio files
Uses mutagen for available metadata
Stores title, artist, album, genre, year, duration, file extension, library area
Does not mutate tags
```

Music extensions currently supported:

```text
.mp3 .flac .m4a .aac .ogg .opus .wav
```

Audiobook scanner:

```text
Scans AUDIOBOOKS_ROOT
Groups files by top-level book folder
Reads chapter files
Stores book, author fallback, year, duration, chapters
Does not mutate files
```

Audiobook extensions currently supported:

```text
.mp3 .m4b .m4a .flac .aac .ogg .opus
```

## 8. Path safety rules

Current backend path safety is in:

```text
backend/app/scanner/path_safety.py
```

Blocked folder parts:

```text
_INGEST
_STAGING
_QUARANTINE
_REPORTS
_METADATA_RECOVERY
```

Approved streaming roots:

```text
Music Library
Music Discographies
Audiobooks Library
```

Streaming endpoints should only serve files from approved final library roots.

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

Supported audio MIME map:

```text
.mp3  -> audio/mpeg
.flac -> audio/flac
.m4a  -> audio/mp4
.m4b  -> audio/mp4
.aac  -> audio/aac
.ogg  -> audio/ogg
.opus -> audio/opus
.wav  -> audio/wav
```

Artwork lookup searches nearby cover image files with names such as:

```text
cover.jpg
folder.jpg
front.jpg
album.jpg
artwork.jpg
```

Also searched subfolders:

```text
Artwork
artwork
Covers
covers
metadata
```

## 10. Frontend structure

Current frontend pages:

```text
HomePage.tsx
RadioPage.tsx
LibraryPage.tsx
BookshelfPage.tsx
NowPlayingPage.tsx
```

Current frontend components:

```text
AppShell.tsx
BottomNav.tsx
MiniPlayer.tsx
Artwork.tsx
IconButton.tsx
PlayerIcons.tsx
ProgressBar.tsx
```

Current playback state:

```text
frontend/src/state/PlaybackContext.tsx
```

Playback context owns:

```text
browser Audio object
current queue
queue index
now playing item
play/pause state
current time
duration
next/previous/seek
basic audiobook progress save
```

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

Open:

```text
http://127.0.0.1:5174
```

API health:

```text
http://127.0.0.1:8094/api/health
```

Path check:

```text
http://127.0.0.1:8094/api/library/paths
```

## 12. Current verified development status

From current screenshots and uploaded code:

```text
BM Radio sees shared nas-data.
Music scan returns 486 tracks, 44 artists, 44 albums.
Audiobook scan returns 1 available book.
Stations generate from scanned music.
Music playback is producing sound.
Library album artwork appears.
Mini-player and Now Playing exist.
Bookshelf and audiobook chapter detail exist.
```

Backend Python compile check passed in this environment:

```text
python -m compileall backend/app
```

Frontend build was not rerun in this environment. Run locally after `npm install`.

## 13. Current known issues / polish targets

Next coding pass should focus on:

```text
Ensure album art appears consistently in Library, MiniPlayer, and Now Playing.
Improve Home so it feels like a premium radio app, not only a scanner dashboard.
Remove corrupted replacement characters and odd symbols.
Clean up audiobook metadata display: author, title, chapter labels.
Add proper Library tabs: Albums, Artists, Songs, Discographies, Search.
Add Radio sections: Featured stations, Genre stations, Artist stations, Favorites, Deep Cuts, Recently Added.
Add Bookshelf filters: All, In Progress, Finished, Favorites.
Wire thumbs/favorite buttons to backend endpoints from Now Playing.
Improve queue generation to avoid long same-album streaks.
Add clear empty/error/loading states.
```

## 14. Future TrueNAS mapping

Future NAS container mapping should prefer read-only mounts for media:

```text
/mnt/rust-pool/Music:/app/music:ro
/mnt/rust-pool/Audiobooks/Library:/app/audiobooks:ro
/mnt/rust-pool/Music/Playlists:/app/playlists:rw only when playlist writing is intentionally approved
/mnt/fast-pool/apps/personal-radio/database:/app/database
/mnt/fast-pool/apps/personal-radio/config:/app/config
/mnt/fast-pool/apps/personal-radio/cache:/app/cache
```

Future environment example:

```env
NAS_DATA_ROOT=/app/data
MUSIC_ROOT=/app/music
MUSIC_LIBRARY_ROOT=/app/music/Library
MUSIC_FLAC_ROOT=/app/music/Library/FLAC
MUSIC_MP3_ROOT=/app/music/Library/MP3
MUSIC_DISCOGRAPHIES_ROOT=/app/music/Discographies
AUDIOBOOKS_ROOT=/app/audiobooks
DATABASE_URL=postgresql+psycopg://bm_radio:CHANGE_ME@bm-radio-postgres:5432/bm_radio
PUBLIC_ACCESS=false
ALLOW_FILE_MUTATION=false
ALLOW_DELETE=false
ALLOW_TAG_WRITES=false
SCAN_INGEST_FOLDERS=false
```

## 15. Acceptance tests before next document update

Before updating these docs again, verify:

```text
1. Backend starts on 8094.
2. Frontend starts on 5174.
3. /api/health returns ok.
4. /api/library/paths confirms final library paths exist.
5. Music scan completes without scanning ingest folders.
6. Audiobook scan completes without scanning ingest folders.
7. Home shows real counts.
8. Radio stations generate.
9. Recently Added starts playback.
10. Album play starts playback.
11. Audiobook chapter starts playback.
12. Mini-player artwork displays or clean fallback displays.
13. Now Playing artwork displays or clean fallback displays.
14. No weird characters appear in the UI.
15. No media files are modified.
16. No delete behavior exists.
```
