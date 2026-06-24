# BM Radio Product Blueprint

Owner: Bonny Makaniankhondo  
Project: NAS System / BM Radio  
Updated: 2026-06-24  
Status: Product direction locked; MVP is in early working state.

## 1. Product identity

BM Radio is a private premium radio, music player, and audiobook bookshelf built from Bonny's NAS media library.

Core promise:

```text
Private radio from your own NAS library.
```

BM Radio is not a fourth admin dashboard. Intake Watcher, Archive Assistant, and Cleaner are operational tools. BM Radio is the enjoyable consumer-facing listening app.

It should feel like a real personal media app: phone-first, premium, fast, smooth, simple, and comfortable to use.

## 2. Product boundaries

BM Radio reads the final approved media libraries after Archive Assistant has organized them.

BM Radio may:

```text
Read Music/Library/MP3
Read Music/Library/FLAC
Read Music/Discographies
Read Audiobooks/Library
Build its own app database/index
Create radio queues
Store thumbs up/down
Store favorites
Store station preferences
Store audiobook progress
Stream privately over LAN/Tailscale
```

BM Radio must not:

```text
Watch _INGEST
Classify new ingest media
Move files into final libraries
Edit embedded tags
Delete files
Clean leftovers
Write Archive Assistant reports
Write Cleaner reports
Own archive metadata truth
Expose itself publicly before a separate security review
```

## 3. Product model

BM Radio has three main areas:

```text
Radio
  Pandora-style stations from Bonny's own music.

Library
  Direct music browsing when Bonny wants a specific album, artist, song, or discography.

Bookshelf
  Audiobooks with all available books, continue listening, progress, finished status, favorites, and simple stats.
```

The app should default to radio, not folders.

## 4. Design direction

The design should be original, not copied from any example screenshot. The target feel is:

```text
Premium
Phone-first
Dark glass / soft gradient
Large artwork
Simple controls
Smooth cards
Minimal technical language
No admin-dashboard feeling
No file-manager feeling
```

Recommended visual style:

```text
Dark background
Violet / indigo / magenta accent system
Large rounded station cards
Big album art on Now Playing
Bottom mini-player always available
Bottom navigation for Home, Radio, Library, Books
Clean fallback art when no cover exists
```

Avoid:

```text
System paths on the main UI
Technical labels like DATA_ROOT or scanner state in normal pages
Crowded tables
NAS admin styling
Raw file names as primary product copy when better metadata exists
Broken placeholder characters
```

## 5. Main navigation

Primary bottom navigation:

```text
Home
Radio
Library
Books
```

Optional future navigation or secondary tabs:

```text
Search
Now Playing
Queue
Station Tune
```

## 6. Home screen target

Home should feel like the front door to BM Radio.

Required Home modules:

```text
Start BM Radio
Favorite stations
Continue listening
Recently added
Audiobooks progress
Library at a glance
Mini-player always visible
```

Home should not feel like only a scanner dashboard. Scan/rescan can exist, but it should be secondary.

Recommended Home hierarchy:

```text
1. BM Radio hero card
2. Primary action: Start BM Radio / Play Recently Added
3. Favorite or recommended stations
4. Continue Listening
5. Recently Added
6. Bookshelf progress card
7. Small library stats
```

## 7. Radio mode

Radio is the main identity of the app.

Station types for V1:

```text
Recently Added
Deep Cuts
Favorites Radio
Genre Radio
Artist Radio
```

Station types for V2:

```text
Mood stations
Energy stations
Late Night
Workout
Mixtape Radio
Decade/Era stations
Album Artist stations
Discovery station
```

Station behavior should feel like Pandora, not Spotify. The user should pick a station and let it play.

V1 queue logic can stay simple:

```text
Artist station:
  artist tracks + album artist matches

Genre station:
  tracks with matching genre metadata

Recently Added:
  newest indexed tracks

Deep Cuts:
  tracks with low/no playback history

Favorites:
  tracks marked favorite
```

Later similarity logic can score tracks by artist, genre, album artist, year range, thumbs, skips, and completion history.

## 8. Now Playing target

Now Playing should be the most polished screen in the app.

Required Now Playing elements:

```text
Large album/book artwork
Track or chapter title
Artist / album or book / author subtitle
Play / pause
Previous / next
Progress bar
Thumbs down
Thumbs up
Favorite
Queue preview
Station name when listening from station
```

Future Now Playing elements:

```text
Station tuning
Lyrics/metadata panel
More like this
Add to playlist
AirPlay/Cast-style target later if technically appropriate
```

## 9. Mini-player target

The mini-player should always be visible above the bottom nav except on the full Now Playing screen.

Required mini-player elements:

```text
Artwork or clean fallback art
Title
Subtitle
Progress strip
Play/pause
Next
Tap to open Now Playing
```

It must never show corrupted characters, raw icons, or placeholder symbols.

## 10. Library mode

Library mode is for direct music selection.

V1 tabs/sections:

```text
Albums
Artists
Songs
Discographies
Search
```

Current app already shows albums with artwork. The next product step is to add clean filters/tabs so Library does not become one long album list.

Recommended Library behavior:

```text
Tap album -> album detail or play album
Tap artist -> artist page with albums/tracks
Tap search -> find songs, artists, albums
Tap discography -> grouped artist releases
```

## 11. Bookshelf mode

Bookshelf is more than audiobook playback. It is a simple personal audiobook shelf.

Required Bookshelf sections:

```text
All Books
Continue Listening
Not Started
In Progress
Finished
Favorites
Simple stats
```

Book statuses:

```text
available
in_progress
finished
favorite
paused later
relisten_later later
```

Simple stats:

```text
Books Available
Books Started
Books Finished
Favorites
Books In Progress
Total Listening Time
This Month later
This Year later
```

Audiobook player requirements:

```text
Continue button
Chapter/file list
Progress percentage
Playback speed
15-second rewind later
30-second forward later
Sleep timer later
Mark finished
Favorite
```

Do not overbuild this into an Audible clone. Keep it smooth and personal.

## 12. V1 feature map

V1 must prove the app feels good and works with real NAS media.

V1 required:

```text
Read-only music scan
Read-only audiobook scan
Real music playback
Real audiobook chapter playback
Mini-player
Now Playing screen
Album artwork where available
Fallback artwork where missing
Recently Added station
Deep Cuts station
Genre stations
Artist stations
Library album browsing
Bookshelf all-books view
Audiobook chapter list
Audiobook progress saving
Favorite book toggle
Safe backend streaming endpoints
No file mutation
No deletion
No ingest scanning
```

## 13. V2 feature map

V2 should make BM Radio feel smarter.

V2 candidates:

```text
Station tuning
Better artist pages
Better genre cleanup
Search across tracks/albums/artists/books
Thumbs up/down affecting queue generation
Favorite stations
Book status filters
Sleep timer
Playback speed persistence
Series grouping for audiobooks
Book analytics cards
Recently played history
```

## 14. Later feature map

Later features after the core app is stable:

```text
Sounds-like engine
AI station names
Mood classifier
Lyrics/metadata extras
Multi-user profiles
Playlist writes to Music/Playlists/personal-radio
Tailscale deployment polish
TrueNAS app/container deployment
Offline/cache mode for phone later if needed
```

## 15. Product acceptance criteria

BM Radio V1 is acceptable when:

```text
The app opens cleanly on a phone-sized screen.
Music and audiobook data come from the shared nas-data final libraries.
Pressing a station starts music.
Pressing an album starts music.
Pressing an audiobook chapter starts audio.
Mini-player works and looks polished.
Now Playing works and shows artwork/fallback art.
Library shows albums with artwork.
Bookshelf shows all available audiobooks and chapter list.
Audiobook progress saves.
No weird characters appear in the UI.
No media file is modified, moved, or deleted.
No ingest folders are scanned.
No public exposure is required.
```
