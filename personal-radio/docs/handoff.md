# BM Radio Current Status Handoff

Owner: Bonny Makaniankhondo  
Project: NAS System / BM Radio  
Updated: 2026-07-27  
Status: Local BM Radio app has working data flow, playback, playlists, radio profiles, library integrity diagnostics, and queue management.

## 1. Purpose

Use this handoff when starting the next BM Radio coding chat or when returning to the project after a break.

This file summarizes the current codebase, what is already working, what still needs cleanup, and the next recommended coding phases.

## 2. Current codebase inspected

Uploaded code ZIP:

```text
BM_radio-main.zip
```

Project root inside ZIP:

```text
BM_radio-main/personal-radio
```

Primary app structure:

```text
backend/app/
  config.py
  db.py
  main.py
  models.py
  routes/
    audiobooks.py
    health.py
    library.py
    library_integrity.py
    media.py
    music_recordings.py
    playback.py
    playlists.py
    queue.py
    radio_profiles.py
    search.py
    serializers.py
    stations.py
  scanner/
    music_scanner.py
    audiobook_scanner.py
    path_safety.py

frontend/src/
  App.tsx
  api.ts
  components/
  pages/
    AlbumDetailPage.tsx
    ArtistDetailPage.tsx
    BookshelfPage.tsx
    HomePage.tsx
    LibraryIntegrityPage.tsx
    LibraryPage.tsx
    NowPlayingPage.tsx
    PlaylistDetailPage.tsx
    QueuePage.tsx
    RadioPage.tsx
  state/
    PlaybackContext.tsx
  styles/
    tokens.css
    base.css
  utils/
    mediaMappers.ts
```

## 3. What works now

Confirmed by current user testing and code inspection:

```text
BM Radio connects to the shared nas-data folder.
Music files are discovered from the final Music library.
Audiobooks are discovered from the final Audiobooks library.
Home shows real library counts and access to quick features.
Radio stations generate from scanned tracks.
Library integrity page flags missing covers, missing genres, and duplicate candidates.
Manual and Smart Playlists are supported.
Queue can be manipulated and saved as a manual playlist.
Artist and Track Radio Profiles allow manual tagging of genre, mood, and energy.
Music Recordings feature allows managing track deduplication and source preference.
Audio playback produces sound.
Mini-player exists.
Now Playing screen exists.
Audiobook chapter playback works with progress saving.
Path safety blocks ingest/staging/quarantine/report folders.
```

## 4. Current product state

BM Radio has evolved from a scaffold into a full-featured premium listening app.

Current screens:

```text
Home
Radio
Library (with Artists, Albums, Search)
Bookshelf
Now Playing
Queue
Playlists (Manual & Smart)
Library Integrity
```

Current interaction model:

```text
Play stations, playlists, and albums
Queue management (Shuffle Up Next, Save Queue)
Library integrity diagnostics (view duplicates, missing covers, stale scans)
Radio profiling (manual tagging for tracks/artists)
Deduplication / Participation state for music recordings
Audiobook chapter playback and progress tracking
```

## 5. Known issues

Do not treat the app as finished. The next stage is polish and product completion.

Known issues / unfinished areas:

```text
MiniPlayer and Now Playing artwork must be verified across all album/track cases.
Some text/metadata still appears raw or weak.
Audiobook author/title/chapter naming needs further cleanup.
Radio page needs better grouping: Featured, Genres, Artists, Favorites, Recently Added, Deep Cuts.
Station tuning UI is not fully implemented yet.
Bookshelf needs filters and simple analytics.
Playback error states need to be more visible.
```

## 6. Safety status

Current safety posture is good and must be preserved.

Safety behavior present:

```text
Path safety helper checks approved roots.
Blocked folders include _INGEST, _STAGING, _QUARANTINE, _REPORTS, and _METADATA_RECOVERY.
Streaming routes serve only approved media/image file types.
Config includes ALLOW_FILE_MUTATION=false.
Config includes ALLOW_DELETE=false.
Config includes ALLOW_TAG_WRITES=false.
Config includes SCAN_INGEST_FOLDERS=false.
Integrity page provides read-only diagnostics without exposing mutations.
```

Required safety rule for all future prompts:

```text
Do not add delete, move, cleanup, tag-write, ingest-watch, quarantine-write, or Archive Assistant report-write behavior to BM Radio.
```

## 7. Next recommended coding phases

### Phase 1 — UI polish and metadata presentation

Goal: make the current app feel clean and premium before adding more features.

Tasks:

```text
Verify artwork loads in Library, MiniPlayer, Now Playing, and Queue.
Improve MiniPlayer spacing and tap behavior.
Improve Now Playing typography and queue preview.
Add empty/loading/error states.
Clean up audiobook metadata display.
```

### Phase 2 — Radio and Bookshelf completion

Goal: make Radio feel like the main app identity and Bookshelf a simple private shelf.

Tasks:

```text
Group stations into Featured, Genres, Artists, Favorites, Recently Added, Deep Cuts.
Improve station cards with artwork/fallback gradients.
Add station favorite toggle.
Add Bookshelf filters: All, Not Started, In Progress, Finished, Favorites.
Add continue-listening section for books.
Add mark finished / favorite UI state for books.
Add simple stats cards for books.
```

### Phase 3 — deployment hardening later

Goal: prepare for NAS/Tailscale use.

Tasks:

```text
Docker Compose for BM Radio.
PostgreSQL option.
Read-only media mounts.
Config/database/cache on fast-pool.
Private-only host binding.
Backup/restore procedure.
```

Do not start this until local app UX is stable.

## 8. Recommended next IDE prompt

Use this prompt for the next coding pass:

```text
We are continuing BM Radio. The app already scans shared nas-data, finds music/audiobooks, generates stations, manages playlists and queues, offers library integrity diagnostics, and plays audio. Do not rewrite the architecture.

Focus only on cleanup and polish:
1. Verify artwork URLs are normalized through mediaUrl() and appear in Library, MiniPlayer, Queue, and Now Playing.
2. Keep MiniPlayer always available above bottom nav, with artwork/fallback, title, subtitle, progress, play/pause, and next.
3. Keep Now Playing clean with large artwork, progress, play controls, thumbs/favorite buttons, and Up Next.
4. Improve Bookshelf with filters and a continue-listening section.
5. Do not add deletion, tag mutation, ingest scanning, cleanup behavior, or public exposure.
6. Preserve existing playback, scanner, and integrity diagnostic behavior.

Stop after the app looks clean, plays music, plays audiobook chapters, and behaves smoothly.
```

## 9. Chat-start prompt for future BM Radio work

Use this when opening a new chat:

```text
We are continuing BM Radio, the fourth app in my NAS system. It is separate from Intake Watcher, Archive Assistant, and Cleaner. BM Radio reads the final Music and Audiobooks libraries only. It must not scan ingest, move media, delete files, mutate tags, clean leftovers, touch quarantine, or write Archive Assistant/Cleaner reports.

Current local app: FastAPI backend on 8094, React/Vite frontend on 5174, shared nas-data connection works. Stations, playlists, queues, radio profiles, music recordings deduplication, and library integrity all function. Current focus is premium UI polish, artwork consistency, Radio sections, and Bookshelf filters/stats.
```

## 10. Done criteria for the next stable checkpoint

The next stable checkpoint should be created when:

```text
Backend starts cleanly.
Frontend builds cleanly.
Music/Audiobook scan works.
Playlists, Queue, and Integrity pages load cleanly.
Station/Playlist play works.
Album play works.
Audiobook chapter play works.
MiniPlayer looks correct.
Now Playing looks correct.
No unsafe media write/delete behavior exists.
```
