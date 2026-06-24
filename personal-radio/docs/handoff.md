# BM Radio Current Status Handoff

Owner: Bonny Makaniankhondo  
Project: NAS System / BM Radio  
Updated: 2026-06-24  
Status: Local BM Radio app has working data flow and playback. UI/product polish continues next.

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
    health.py
    library.py
    stations.py
    queue.py
    playback.py
    media.py
    audiobooks.py
    serializers.py
  scanner/
    music_scanner.py
    audiobook_scanner.py
    path_safety.py

frontend/src/
  App.tsx
  api.ts
  components/
    AppShell.tsx
    Artwork.tsx
    BottomNav.tsx
    IconButton.tsx
    MiniPlayer.tsx
    PlayerIcons.tsx
    ProgressBar.tsx
  pages/
    HomePage.tsx
    RadioPage.tsx
    LibraryPage.tsx
    BookshelfPage.tsx
    NowPlayingPage.tsx
  state/
    PlaybackContext.tsx
  styles/
    tokens.css
    base.css
  utils/
    mediaMappers.ts
```

## 3. What works now

Confirmed by current screenshots/user testing and code inspection:

```text
BM Radio connects to the shared nas-data folder.
Music files are discovered from the final Music library.
Audiobooks are discovered from the final Audiobooks library.
Home shows real library counts.
Radio stations generate from scanned tracks.
Library shows albums.
Library shows album artwork.
Audio playback produces sound.
Mini-player exists.
Now Playing screen exists.
Bookshelf screen exists.
Book detail/chapter list exists.
Audiobook chapter playback route exists.
Audiobook progress endpoint exists.
Path safety blocks ingest/staging/quarantine/report folders.
```

Observed counts from latest UI screenshots:

```text
486 tracks
44 artists
44 albums
1 book available
0 books in progress
```

Backend compile check passed:

```text
python -m compileall backend/app
```

## 4. Current product state

BM Radio is no longer just a scaffold. It is an early playable MVP.

Current screens:

```text
Home
Radio
Library
Bookshelf
Now Playing
```

Current interaction model:

```text
Scan/rescan library
Play Recently Added
Play station queues
Play album queues
Open MiniPlayer
Open Now Playing
Open Bookshelf book detail
Play audiobook chapters
```

## 5. Known issues

Do not treat the app as finished. The next stage is polish and product completion.

Known issues / unfinished areas:

```text
Home still needs a stronger premium radio layout.
MiniPlayer and Now Playing artwork must be verified across all album/track cases.
Some text/metadata still appears raw or weak.
Some files include UTF-8 BOM markers and should be saved as normal UTF-8.
Audiobook author/title/chapter naming needs cleanup.
Library only has an album list; Artists, Songs, Discographies, and Search still need real UI.
Radio page needs better grouping: Featured, Genres, Artists, Favorites, Recently Added, Deep Cuts.
Thumbs up/down buttons exist visually but need stronger UI wiring/feedback.
Favorites need UI feedback and saved state display.
Queue generation is functional but basic.
There is no station tuning UI yet.
Bookshelf needs filters and simple analytics.
Playback error states need to be more visible.
```

Files with UTF-8 BOM detected during inspection:

```text
backend/.env.example
frontend/.env.example
backend/app/routes/library.py
backend/app/routes/stations.py
```

Next cleanup pass should save those as UTF-8 without BOM and search for replacement characters such as `�`.

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
```

Required safety rule for all future prompts:

```text
Do not add delete, move, cleanup, tag-write, ingest-watch, quarantine-write, or Archive Assistant report-write behavior to BM Radio.
```

## 7. Next recommended coding phases

### Phase 1 — UI cleanup checkpoint

Goal: make the current app feel clean and premium before adding more features.

Tasks:

```text
Fix any remaining weird characters.
Remove BOM from source/env files.
Verify artwork loads in Library, MiniPlayer, and Now Playing.
Improve Home layout.
Improve MiniPlayer spacing and tap behavior.
Improve Now Playing typography and queue preview.
Add empty/loading/error states.
```

Done when:

```text
The app looks clean on phone width.
Music still plays.
Audiobooks still play.
Artwork/fallback art is consistent.
No corrupted UI characters remain.
```

### Phase 2 — Library completion

Goal: make Library useful beyond albums.

Tasks:

```text
Add Library tabs: Albums, Artists, Songs, Discographies, Search.
Add artist pages or artist list.
Add song list with search/filter.
Add discography grouping.
Improve album sorting by year/artist.
Add play buttons for artist, album, song.
```

### Phase 3 — Radio completion

Goal: make Radio feel like the main app identity.

Tasks:

```text
Group stations into Featured, Genres, Artists, Favorites, Recently Added, Deep Cuts.
Improve station cards with artwork/fallback gradients.
Wire thumbs up/down to backend.
Wire track favorites to backend.
Improve queue generation so it avoids repetitive same-album runs.
Add station favorite toggle.
Add basic station tuning later.
```

### Phase 4 — Bookshelf completion

Goal: make audiobooks feel like a simple private bookshelf.

Tasks:

```text
Add filters: All, Not Started, In Progress, Finished, Favorites.
Add continue-listening section.
Improve book detail page.
Clean chapter names.
Add mark finished / favorite UI state.
Add simple stats cards.
Add playback speed later.
Add sleep timer later.
```

### Phase 5 — deployment hardening later

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
We are continuing BM Radio after the first playable MVP. The app already scans shared nas-data, finds music/audiobooks, generates stations, and plays audio. Do not rewrite the architecture.

Focus only on cleanup and polish:
1. Remove UTF-8 BOM and any corrupted replacement characters from source/env files.
2. Verify artwork URLs are normalized through mediaUrl() and appear in Library, MiniPlayer, and Now Playing.
3. Improve Home so it feels like a premium private radio app with Start BM Radio, Favorite/Featured stations, Continue Listening, Recently Added, and small library stats.
4. Keep MiniPlayer always available above bottom nav, with artwork/fallback, title, subtitle, progress, play/pause, and next.
5. Keep Now Playing clean with large artwork, progress, play controls, thumbs/favorite buttons, and Up Next.
6. Do not add deletion, tag mutation, ingest scanning, cleanup behavior, or public exposure.
7. Preserve existing playback and scanner behavior.

Stop after the app looks clean, plays music, plays audiobook chapters, and shows no weird characters.
```

## 9. Chat-start prompt for future BM Radio work

Use this when opening a new chat:

```text
We are continuing BM Radio, the fourth app in my NAS system. It is separate from Intake Watcher, Archive Assistant, and Cleaner. BM Radio reads the final Music and Audiobooks libraries only. It must not scan ingest, move media, delete files, mutate tags, clean leftovers, touch quarantine, or write Archive Assistant/Cleaner reports.

Current local app: FastAPI backend on 8094, React/Vite frontend on 5174, shared nas-data connection works, 486 tracks / 44 artists / 44 albums / 1 audiobook are detected, stations generate, audio playback works, Library shows album art, MiniPlayer and Now Playing exist. Current focus is premium UI polish, artwork consistency, character cleanup, Library tabs, Radio sections, and Bookshelf filters/stats.
```

## 10. Done criteria for the next stable checkpoint

The next stable checkpoint should be created when:

```text
Backend starts cleanly.
Frontend builds cleanly.
Music scan works.
Audiobook scan works.
Station play works.
Album play works.
Audiobook chapter play works.
MiniPlayer looks correct.
Now Playing looks correct.
Library artwork appears.
Home feels like BM Radio, not a scanner page.
No corrupted characters appear.
No unsafe media write/delete behavior exists.
```
