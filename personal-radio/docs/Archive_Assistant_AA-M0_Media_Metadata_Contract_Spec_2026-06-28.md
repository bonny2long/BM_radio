# Archive Assistant AA-M0 — Media-Wide Metadata Contract Specification

Owner: Bonny Makaniankhondo  
Project: NAS System / Archive Assistant / BM Radio / Jellyfin-supporting media pipeline  
Date: 2026-06-28  
Status: Design/spec phase only. No implementation in this phase.

---

## 1. Purpose

AA-M0 defines the metadata contract that Archive Assistant should produce for final organized media.

This phase exists because BM Radio exposed a larger system problem: Archive Assistant organizes files safely, but the metadata it produces is not yet rich enough for downstream apps that need intelligent behavior.

BM Radio needs better music and audiobook metadata for radio, stations, genre browsing, smart playlists, and listening intelligence.

Jellyfin can benefit from better movie and TV metadata, cleaner folder context, collection/franchise data, edition data, language/subtitle data, and external IDs later.

Book/audiobook apps can benefit from cleaner author, narrator, series, edition, and progress-related metadata.

AA-M0 is not a coding phase. It is a contract/spec phase that defines the data shape before adding extraction, inheritance, local metadata databases, or local AI helpers.

---

## 2. System Boundary

Archive Assistant owns archive metadata truth.

BM Radio owns listening/playback truth.

Jellyfin owns playback/streaming behavior for movies and TV.

Cleaner owns safe leftover review and cleanup planning.

Intake Watcher owns upload/copy stability and promotion into ready.

Archive Assistant may:

```text
scan ready media
extract metadata read-only
infer metadata from paths/folders/files
suggest metadata
allow human review/edit/approval
move approved media to final libraries
write manifests, logs, and approved metadata sidecars
regenerate approved metadata manifests later
```

Archive Assistant must not, in this contract phase:

```text
delete media
silently overwrite metadata
mutate embedded tags
make cloud AI calls
make internet metadata calls during normal ingest
change BM Radio playback state
change Jellyfin database state
```

Future phases may add local metadata databases or local AI suggestion helpers, but they must remain suggestion layers until Bonny approves the metadata.

---

## 3. Design Goals

The metadata contract must be:

```text
media-wide
manifest-first
human-approvable
source-aware
confidence-aware
versioned
rescan-friendly
offline-first
safe for bulk ingestion
useful to BM Radio, Jellyfin, book/audiobook apps, and future services
```

The contract should reduce repetitive manual entry through inheritance:

```text
artist/show/series profile
  -> release/season/movie/book profile
  -> track/episode/file override
```

The contract should support later automation without giving automation final authority.

---

## 4. Metadata Philosophy

Archive Assistant should not ask Bonny to manually fill every field for every file.

The workflow should be:

```text
extract what already exists
infer what is obvious
suggest what is likely
show confidence and reasons
allow bulk approval
allow targeted overrides
write approved metadata manifests
let downstream apps rescan and improve
```

Metadata should have provenance. A field with no source is not trusted metadata.

Every important value should be able to answer:

```text
What is the value?
Where did it come from?
How confident is Archive Assistant?
Did Bonny approve it?
When was it last updated?
What downstream apps can use it?
```

---

## 5. Field Value Envelope

Important metadata fields should use a consistent field envelope internally and in manifests when practical.

Recommended shape:

```json
{
  "value": "Hip-Hop",
  "source": "manual_artist_profile",
  "confidence": 0.95,
  "reason": "Approved artist profile for Nipsey Hussle maps to Hip-Hop.",
  "approved": true,
  "approved_at": "2026-06-28T00:00:00-05:00",
  "approved_by": "bonny",
  "updated_at": "2026-06-28T00:00:00-05:00"
}
```

For compact manifests, simple scalar values may also be emitted, but the richer envelope should remain available in the database or detailed manifest.

Required field source values:

```text
embedded_tag
folder_inference
filename_inference
path_context
archive_assistant_rule
artist_profile
release_profile
series_profile
show_profile
movie_profile
manual
local_metadata_db
local_audio_analysis
local_ai_suggestion
unknown
```

Approval states:

```text
pending
approved
rejected
needs_review
inherited
stale
```

Confidence levels:

```text
0.90 - 1.00 = high confidence
0.70 - 0.89 = likely but reviewable
0.40 - 0.69 = weak suggestion
0.00 - 0.39 = low confidence / do not auto-approve
```

---

## 6. Universal Metadata Contract

These fields apply across all media types where meaningful.

### 6.1 Core Universal Fields

```text
metadata_contract_version
manifest_type
manifest_version
metadata_version
media_type
media_subtype
canonical_title
display_title
original_title
sort_title
year
release_date
original_release_date
language
country
source_path
final_path
relative_final_path
folder_name
file_count
total_size_bytes
created_at
updated_at
approved_at
approved_by
approval_state
metadata_quality
warnings
notices
```

### 6.2 Creator / People Fields

Universal people fields should support roles.

```text
creators
contributors
primary_creator
secondary_creators
people_roles
```

Example:

```json
{
  "people": [
    {"name": "Nipsey Hussle", "role": "artist"},
    {"name": "J. Stone", "role": "featured_artist"}
  ]
}
```

Role values should be media-aware:

```text
artist
album_artist
composer
producer
director
writer
actor
showrunner
author
narrator
editor
publisher
label
studio
network
```

### 6.3 File / Technical Fields

```text
files
file_path
relative_path
file_name
extension
container
codec
audio_codec
video_codec
duration_seconds
bitrate
sample_rate
bit_depth
channels
resolution
frame_rate
hdr_format
subtitle_tracks
audio_tracks
is_corrupt
is_playable
```

Not every field applies to every media type.

### 6.4 Identity Fields

```text
identity_key
normalized_title
normalized_primary_creator
normalized_year
external_ids
source_fingerprint
content_fingerprint
metadata_fingerprint
```

External ID fields should be optional and source-aware:

```text
musicbrainz_artist_id
musicbrainz_release_group_id
musicbrainz_release_id
musicbrainz_recording_id
acoustid_id
tmdb_id
imdb_id
tvdb_id
tvmaze_id
openlibrary_id
isbn_10
isbn_13
asin
```

No external service is required in AA-M0. These are reserved contract fields for future local/offline metadata sources.

---

## 7. Music Metadata Contract

Music metadata is the first pressure test because BM Radio depends on it for radio intelligence.

### 7.1 Artist / Discography Profile

One profile per canonical artist/discography.

Recommended manifest:

```text
metadata/artist-profile.json
```

Fields:

```text
artist_name
artist_sort_name
aliases
primary_genre
subgenres
moods
energy_default
era
region
scene
language
related_artists
influenced_by
similar_to
confidence
profile_source
profile_approved
profile_version
```

Example:

```json
{
  "artist_name": "Nipsey Hussle",
  "primary_genre": "Hip-Hop",
  "subgenres": ["West Coast Rap", "Street Rap", "Conscious Rap"],
  "moods": ["street", "reflective", "confident"],
  "energy_default": "medium-high",
  "era": "2010s",
  "region": "Los Angeles",
  "scene": "West Coast Hip-Hop",
  "related_artists": ["Kendrick Lamar", "YG", "Dom Kennedy", "Jay Rock", "The Game"],
  "profile_source": "manual",
  "profile_approved": true,
  "profile_version": 1
}
```

### 7.2 Release Profile

One profile per album, EP, single, mixtape, compilation, soundtrack, or release folder.

Recommended manifest:

```text
metadata/music-release.json
```

Fields:

```text
release_title
release_sort_title
artist
album_artist
year
release_date
original_year
release_type
secondary_types
primary_genre
subgenres
moods
energy
era
region
scene
label
catalog_number
barcode
is_compilation
is_mixtape
is_soundtrack
is_live
is_remix_release
is_demo_release
is_deluxe
is_explicit
cover_path
cover_source
release_identity_key
recording_group_keys
tracks
```

Recommended `release_type` values:

```text
album
single
ep
mixtape
compilation
soundtrack
live
remix
demo
unknown
```

Recommended `secondary_types` values:

```text
deluxe
anniversary
remastered
collector_edition
radio_edit
clean
explicit
instrumental
bootleg
promo
```

### 7.3 Track Profile

Fields:

```text
track_title
track_sort_title
artist
album_artist
featured_artists
composer
producer
track_number
disc_number
total_tracks
total_discs
year
release_date
duration_seconds
primary_genre
subgenres
moods
energy
tempo_bpm
tempo_bucket
language
explicit
is_live
is_remix
is_demo
is_instrumental
is_bonus_track
is_interlude
is_skit
is_intro
is_outro
recording_key
track_release_key
musicbrainz_recording_id
acoustid_id
file_path
```

Radio-specific fields:

```text
radio_primary_genre
radio_subgenres
radio_moods
radio_energy
radio_era
radio_region
radio_scene
radio_related_artists
radio_exclude_reason
radio_weight_hint
```

BM Radio should prefer approved `radio_*` fields from Archive Assistant manifests over hardcoded app fallbacks.

---

## 8. Audiobook Metadata Contract

Audiobooks need a separate contract from music.

Recommended manifest:

```text
metadata/audiobook.json
```

Fields:

```text
title
sort_title
author
author_sort
narrator
series
series_number
year
release_date
publisher
edition
isbn_10
isbn_13
language
abridgement
is_abridged
is_unabridged
runtime_seconds
chapters
part_number
total_parts
cover_path
work_key
edition_key
files
```

Radio/BM Radio relevant audiobook fields:

```text
listening_type
audiobook_progress_group_key
chapter_titles
chapter_start_times
narrator_profile
series_profile
```

Suggested `abridgement` values:

```text
unabridged
abridged
dramatized
unknown
```

---

## 9. Book / Ebook Metadata Contract

Recommended manifest:

```text
metadata/book.json
```

Fields:

```text
title
sort_title
author
author_sort
series
series_number
year
publication_date
publisher
edition
isbn_10
isbn_13
language
format
page_count
file_count
cover_path
work_key
edition_key
subjects
genres
description
```

Book formats:

```text
epub
pdf
mobi
azw3
cbz
cbr
unknown
```

Future book apps can use these manifests, but Archive Assistant remains the review/approval source.

---

## 10. Movie Metadata Contract

Movies are not consumed by BM Radio, but Jellyfin can benefit from stronger Archive Assistant metadata.

Recommended manifest:

```text
metadata/movie.json
```

Fields:

```text
title
sort_title
original_title
year
release_date
edition
cut
collection
franchise
part_number
director
writers
cast
genres
moods
runtime_seconds
language
country
studio
rating
content_rating
tmdb_id
imdb_id
resolution
source_quality
video_codec
audio_codec
subtitle_tracks
is_remux
is_uhd
is_hdr
is_directors_cut
is_extended_cut
is_theatrical_cut
is_criterion
files
```

Recommended `edition/cut` values:

```text
theatrical
directors_cut
extended
unrated
criterion
remastered
special_edition
unknown
```

Recommended source quality values:

```text
web-dl
web-rip
blu-ray
uhd-blu-ray
dvd
hdtv
remux
unknown
```

---

## 11. TV Metadata Contract

TV needs careful handling because Archive Assistant already supports normal TV and anime/specials/OAD/OVA/OAV cases.

Recommended show manifest:

```text
metadata/tv-show.json
```

Recommended episode/season data can live inside the show manifest or split later.

Show fields:

```text
show_title
sort_title
original_title
year
first_air_date
status
network
country
language
genres
moods
show_type
is_anime
is_miniseries
tmdb_id
tvdb_id
imdb_id
tvmaze_id
seasons
specials
```

Season fields:

```text
season_number
season_title
year
episode_count
special_count
folder_path
```

Episode fields:

```text
episode_title
season_number
episode_number
absolute_episode_number
production_number
air_date
runtime_seconds
is_special
is_ova
is_oad
is_oav
is_recap
is_finale
is_movie_length_special
file_path
```

Special handling flags:

```text
special
oad
ova
oav
recap
extra
final_chapter
half_episode
```

---

## 12. Metadata Inheritance Rules

Inheritance is required so bulk media does not become manual data entry.

### 12.1 Music Inheritance

```text
artist/discography profile
  -> release profile
  -> track profile
```

Example:

```text
Nipsey Hussle artist profile:
primary_genre = Hip-Hop
subgenres = West Coast Rap, Street Rap
moods = street, reflective, confident
region = Los Angeles

Crenshaw release:
inherits artist profile
release_type = mixtape
energy = medium-high

Track:
inherits release values unless track has better embedded metadata or manual override
```

### 12.2 TV Inheritance

```text
show profile
  -> season profile
  -> episode profile
```

### 12.3 Movie Inheritance

```text
collection/franchise profile
  -> movie profile
  -> file profile
```

### 12.4 Book/Audiobook Inheritance

```text
author/series profile
  -> work profile
  -> edition profile
  -> file/chapter profile
```

### 12.5 Override Rule

Manual approved values always outrank suggestions.

Suggested priority:

```text
manual override
approved profile
approved release/season/work profile
embedded tag
local metadata DB
folder/path inference
filename inference
local audio analysis
local AI suggestion
unknown
```

---

## 13. Manifest Strategy

Archive Assistant should write metadata manifests in final library folders after approval/move.

Recommended manifest locations:

```text
Music/Discographies/<Artist>/metadata/artist-profile.json
Music/Discographies/<Artist>/Albums/<Year - Album>/metadata/music-release.json
Music/Library/FLAC/<Artist>/<Year - Album>/metadata/music-release.json
Audiobooks/Library/<Author>/<Year - Title>/metadata/audiobook.json
Books/EPUB/<Author>/<Year - Title>/metadata/book.json
Movies/Library/<Year - Movie Title>/metadata/movie.json
TV/Library/<Show Title>/metadata/tv-show.json
```

Existing manifests should not be broken. If new fields are added, increment the manifest version.

Every manifest should include:

```text
manifest_type
manifest_version
metadata_contract_version
metadata_version
generated_by
generated_at
source_batch_id
approval_state
consumer_hints
```

Consumer hints:

```json
{
  "consumers": {
    "bm_radio": {"eligible": true, "preferred": true},
    "jellyfin": {"eligible": false},
    "audiobookshelf": {"eligible": true},
    "kavita": {"eligible": false}
  }
}
```

---

## 14. Metadata Versioning and Living System Flow

Metadata must be able to improve after initial ingest.

Flow:

```text
Archive Assistant profile updated
  -> affected releases marked metadata_stale
  -> manifests regenerated or patched
  -> metadata_version increments
  -> BM Radio rescan detects changed metadata_version or checksum
  -> BM Radio updates app index metadata
  -> radio/stations improve without media file changes
```

Required version fields:

```text
metadata_contract_version
manifest_version
metadata_version
profile_version
last_metadata_update_at
metadata_checksum
```

Downstream apps should compare:

```text
file path
file mtime/size
metadata_version
metadata_checksum
```

BM Radio should not need to rescan audio files if only AA metadata manifests changed.

---

## 15. Local Metadata Database Plan

AA-M0 only reserves the concept.

Future local metadata database goals:

```text
local/offline metadata lookup
artist profiles
release profiles
genre/tag vocabulary
aliases
external IDs
relationships
related artists
release group types
```

Potential later sources:

```text
MusicBrainz local database dump
curated local artist profile database
approved Archive Assistant profiles
local CSV/JSON imports
future local AI suggestion cache
```

The local metadata DB should produce suggestions, not final truth.

---

## 16. Local AI Helper Positioning

Local AI is not part of AA-M0 implementation.

Future local AI may suggest:

```text
subgenres
moods
energy
region/scene
release type
related artists
weak title cleanup
collection/franchise matching
```

Local AI must return:

```text
suggested value
confidence
reason
evidence used
fields affected
```

Local AI must not:

```text
auto-approve metadata
write embedded tags
move files
delete files
call cloud APIs
be required for basic ingest
```

---

## 17. Premium Review UI Principles

The future UI should not feel like a spreadsheet.

Use:

```text
profile cards
release cards
confidence chips
source badges
inheritance badges
quick filters
bulk approve tools
collapsible advanced fields
```

Suggested review modes:

```text
Ready to approve
Needs quick confirmation
Weak metadata
Conflicts found
Missing core metadata
Advanced radio fields
```

For discographies:

```text
artist profile card at top
release cards below
per-release override drawer
track-level override only when needed
```

For TV:

```text
show profile card
season groups
episode/special review cards
```

For movies:

```text
movie profile card
edition/cut card
collection/franchise card
```

---

## 18. Required Acceptance Criteria for AA-M0

AA-M0 is complete when this spec is reviewed and locked enough to guide coding.

Acceptance criteria:

```text
universal metadata fields defined
music metadata fields defined
audiobook/book metadata fields defined
movie metadata fields defined
TV metadata fields defined
source/confidence model defined
approval model defined
inheritance model defined
manifest strategy defined
metadata versioning strategy defined
BM Radio consumer contract defined
Jellyfin/media-service consumer direction defined
local metadata DB reserved for later phase
local AI reserved for later phase
no code changes required
```

---

## 19. Proposed Roadmap After AA-M0

### AA-M1 — Read-Only Metadata Extraction

Add/improve read-only extraction from embedded tags, filenames, folder paths, durations, formats, covers, and existing sidecars.

No tag writing.

### AA-M2 — Artist/Release/Series Inheritance

Implement metadata inheritance for music first, then extend the same pattern to audiobooks/books, movies, and TV.

### AA-M3 — Premium Bulk Metadata Review UI

Build card-based profile/release review UI with chips, source badges, confidence badges, and batch approval.

### AA-M4 — Radio-Ready and Consumer-Ready Manifests

Write richer approved manifests for final media folders.

BM Radio can consume music/audiobook manifests.

Jellyfin-facing metadata can be planned separately and conservatively.

### AA-M5 — Local Metadata Database

Add local/offline metadata DB support for artist/release/work lookup and suggestion generation.

### AA-M6 — Metadata Propagation / Living System

Allow updated AA metadata profiles to refresh manifests and notify or support BM Radio rescans.

### AA-M7 — Optional Local AI Suggestion Helper

Only after schema, inheritance, review, and manifests are stable.

---

## 20. Locked Decision

Archive Assistant is becoming the metadata staging and approval layer for the NAS.

BM Radio should not become the metadata editor.

Jellyfin should not become the ingest authority.

Archive Assistant should produce approved, versioned, source-aware metadata manifests that downstream apps can consume.

This preserves the system model:

```text
Intake Watcher = upload stability
Archive Assistant = metadata/review/archive truth
Cleaner = safe cleanup planning
BM Radio = listening intelligence
Jellyfin = movie/TV playback
```

