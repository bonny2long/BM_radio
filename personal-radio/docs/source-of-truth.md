# BM Radio Source-of-Truth Addendum

Owner: Bonny Makaniankhondo  
Project: NAS System / BM Radio  
Updated: 2026-06-24  
Status: Fourth-app source-of-truth addendum after BM Radio reached scanner + playback working state.

## 1. Purpose

This file updates the NAS project source of truth with BM Radio as the fourth custom app.

The current custom NAS system is now:

```text
Intake Watcher
Archive Assistant
Cleaner
BM Radio
```

The first three apps are the media pipeline. BM Radio is the private listening app.

## 2. System model

```text
Intake Watcher
  Watches active uploads and promotes completed media to ready.

Archive Assistant
  Scans ready media, supports review/edit/approval, moves approved media to final libraries, and writes manifests/logs.

Cleaner
  Reads evidence after approved moves and reports safe cleanup candidates in dry-run mode.

BM Radio
  Reads final Music and Audiobooks libraries and streams privately to Bonny's phone/browser.
```

## 3. BM Radio role

BM Radio answers:

```text
How do I privately listen to my own organized music and audiobooks from the NAS?
```

BM Radio should feel like:

```text
Premium private music app
Pandora-style radio
Direct music player
Simple audiobook bookshelf
Phone-first NAS listening experience
```

BM Radio should not feel like:

```text
An admin dashboard
A file manager
A scanner tool
A cleanup tool
A Spotify clone
An Audible clone
```

## 4. Folder ownership

BM Radio reads final approved media only.

BM Radio may read:

```text
nas-data/Music/Library/MP3
nas-data/Music/Library/FLAC
nas-data/Music/Discographies
nas-data/Audiobooks/Library
```

BM Radio may write only to its own app database/config/cache.

BM Radio must not write to:

```text
nas-data/_INGEST
nas-data/_STAGING
nas-data/_QUARANTINE
nas-data/_REPORTS/archive-assistant
nas-data/_REPORTS/cleaner
nas-data/Music/Library
nas-data/Music/Discographies
nas-data/Audiobooks/Library
```

Future playlist writing may be approved later only under:

```text
nas-data/Music/Playlists/personal-radio
```

That is not a V1 requirement.

## 5. Local path contract

Current local NAS data root:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\nas-data
```

Current BM Radio project path:

```text
C:\Users\BonnyMakaniankhondo\Documents\GitHub\NAS\BM_radio-main\personal-radio
```

Current local ports:

```text
Backend: 8094
Frontend: 5174
```

## 6. TrueNAS path contract

Future host paths:

```text
/mnt/rust-pool/Music
/mnt/rust-pool/Audiobooks/Library
/mnt/fast-pool/apps/personal-radio
```

Future container mapping:

```text
/mnt/rust-pool/Music:/app/music:ro
/mnt/rust-pool/Audiobooks/Library:/app/audiobooks:ro
/mnt/fast-pool/apps/personal-radio/database:/app/database
/mnt/fast-pool/apps/personal-radio/config:/app/config
/mnt/fast-pool/apps/personal-radio/cache:/app/cache
```

The music/audiobook mounts should stay read-only unless a later runbook approves a very narrow write path for playlists.

## 7. Safety rules

BM Radio non-negotiable rules:

```text
No deletion.
No embedded tag mutation.
No moving media.
No ingest scanning.
No cleanup behavior.
No quarantine handling.
No Archive Assistant report writes.
No Cleaner report writes.
No public internet exposure for the local/admin phase.
Private LAN/Tailscale access only.
```

BM Radio can store app-owned state:

```text
Station definitions
Queue history
Thumbs up/down
Favorites
Playback events
Audiobook progress
Book status
UI preferences later
```

This app-owned state is not the source of truth for archive organization.

## 8. Current BM Radio status

Current working state from the latest local checkpoint:

```text
Shared nas-data connection works.
Music scanner sees final Music library.
Audiobook scanner sees final Audiobooks library.
Observed library count: 486 tracks, 44 artists, 44 albums.
Observed audiobook count: 1 available book.
Stations generate from library data.
Audio playback works.
Library album artwork appears.
Mini-player and Now Playing screens exist.
Bookshelf and chapter list exist.
```

Current polish needs:

```text
Artwork consistency in MiniPlayer and Now Playing.
Home screen premium redesign.
Miscellaneous character cleanup.
Audiobook metadata cleanup.
More complete Library tabs.
More complete Radio sections.
Bookshelf filtering and simple analytics.
```

## 9. Data flow

BM Radio data flow:

```text
Archive Assistant moves approved music/audiobooks
  -> final Music/Audiobooks libraries
  -> BM Radio scans final libraries read-only
  -> BM Radio builds app database/index
  -> BM Radio generates stations/library/bookshelf views
  -> Bonny plays media over LAN/Tailscale
  -> BM Radio saves thumbs, favorites, queue history, and audiobook progress
```

BM Radio does not send files back into the media pipeline.

## 10. Current app database purpose

BM Radio database stores app behavior only:

```text
Tracks index
Audiobook index
Audiobook chapters
Stations
Track thumbs
Track favorites
Playback events
Audiobook progress
```

It should not store destructive actions.

## 11. Acceptance test for full NAS source-of-truth

Before BM Radio is marked stable in the main source of truth, all must be true:

```text
BM Radio scans only final Music/Audiobooks libraries.
BM Radio plays music on phone-sized UI.
BM Radio plays audiobook chapter audio.
BM Radio saves audiobook progress.
BM Radio shows album/book artwork or clean fallback art.
BM Radio has no delete/tag-write/move endpoints.
BM Radio does not scan _INGEST or _QUARANTINE.
BM Radio is available privately only.
BM Radio can be backed up by saving its database/config.
```

## 12. Source-of-truth status line

Use this line in the main NAS source-of-truth document:

```text
BM Radio is the fourth separate NAS app. It reads the final Music and Audiobooks libraries created by Archive Assistant and provides private radio, music playback, and audiobook bookshelf features over LAN/Tailscale. It must not participate in ingest, cleanup, quarantine, deletion, tag mutation, or final library organization.
```
