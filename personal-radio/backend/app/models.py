from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, Float, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from .db import Base

class ThumbValue(enum.Enum):
    up = "up"
    down = "down"

class Track(Base):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, unique=True, index=True)
    relative_path = Column(String)
    title = Column(String, index=True)
    artist = Column(String, index=True)
    album = Column(String, index=True)
    album_artist = Column(String, index=True)
    genre = Column(String, index=True)
    year = Column(Integer)
    duration_seconds = Column(Float)
    file_ext = Column(String)
    library_area = Column(String, index=True)  # Library, Discographies, etc.
    cover_path = Column(String, nullable=True)
    metadata_source = Column(String, nullable=True)
    source_manifest_path = Column(String, nullable=True)
    source_manifest_version = Column(String, nullable=True)
    source_metadata_version = Column(String, nullable=True)
    track_number = Column(Integer, nullable=True)
    disc_number = Column(Integer, nullable=True)
    primary_genre = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_indexed_at = Column(DateTime(timezone=True), index=True)
    library_availability = Column(String, default="available", server_default="available", index=True)
    last_seen_scan_id = Column(Integer, nullable=True, index=True)
    unavailable_since = Column(DateTime(timezone=True), nullable=True)

    thumbs = relationship("TrackThumb", back_populates="track")
    favorites = relationship("TrackFavorite", back_populates="track")
    music_identity = relationship("MusicTrackIdentity", back_populates="track", uselist=False)
    technical_profile = relationship("MusicTechnicalProfile", back_populates="track", uselist=False)


class MusicRelease(Base):
    __tablename__ = "music_releases"

    id = Column(Integer, primary_key=True, index=True)
    identity_key = Column(String, unique=True, index=True, nullable=False)
    album_artist = Column(String, index=True, nullable=True)
    title = Column(String, index=True, nullable=True)
    normalized_album_artist = Column(String, nullable=False, default="", server_default="")
    normalized_title = Column(String, nullable=False, default="", server_default="")
    release_type = Column(String, nullable=False, default="unknown", server_default="unknown")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    editions = relationship("MusicEdition", back_populates="release")


class MusicEdition(Base):
    __tablename__ = "music_editions"

    id = Column(Integer, primary_key=True, index=True)
    identity_key = Column(String, unique=True, index=True, nullable=False)
    release_id = Column(Integer, ForeignKey("music_releases.id"), index=True, nullable=False)
    display_title = Column(String, nullable=True)
    year = Column(Integer, nullable=True)
    edition_type = Column(String, nullable=False, default="unknown", server_default="unknown")
    source_scope = Column(String, index=True, nullable=False)
    source_format_family = Column(String, nullable=False, default="UNKNOWN", server_default="UNKNOWN")
    source_manifest_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    release = relationship("MusicRelease", back_populates="editions")
    track_links = relationship("MusicTrackIdentity", back_populates="edition")


class MusicRecording(Base):
    __tablename__ = "music_recordings"

    id = Column(Integer, primary_key=True, index=True)
    identity_key = Column(String, unique=True, index=True, nullable=False)
    artist = Column(String, index=True, nullable=True)
    title = Column(String, index=True, nullable=True)
    normalized_artist = Column(String, nullable=False, default="", server_default="")
    normalized_title = Column(String, nullable=False, default="", server_default="")
    recording_type = Column(String, index=True, nullable=False, default="unknown", server_default="unknown")
    version_hint = Column(String, nullable=True)
    duration_bucket = Column(String, nullable=False, default="", server_default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    track_links = relationship("MusicTrackIdentity", back_populates="recording")
    preference = relationship("MusicRecordingPreference", back_populates="recording", uselist=False)
    participation = relationship("MusicRecordingParticipation", back_populates="recording", uselist=False)


class MusicTrackIdentity(Base):
    __tablename__ = "music_track_identities"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), unique=True, index=True, nullable=False)
    edition_id = Column(Integer, ForeignKey("music_editions.id"), index=True, nullable=False)
    recording_id = Column(Integer, ForeignKey("music_recordings.id"), index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    track = relationship("Track", back_populates="music_identity")
    edition = relationship("MusicEdition", back_populates="track_links")
    recording = relationship("MusicRecording", back_populates="track_links")


class MusicTechnicalProfile(Base):
    __tablename__ = "music_technical_profiles"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), unique=True, index=True, nullable=False)
    probe_status = Column(String, nullable=False, default="partial", server_default="partial", index=True)
    probe_source = Column(String, nullable=False, default="mutagen", server_default="mutagen")
    probe_version = Column(Integer, nullable=False, default=1, server_default="1")
    codec = Column(String, nullable=True, index=True)
    container = Column(String, nullable=True)
    is_lossless = Column(Boolean, nullable=True, index=True)
    sample_rate_hz = Column(Integer, nullable=True)
    bit_depth_bits = Column(Integer, nullable=True)
    bitrate_bps = Column(Integer, nullable=True)
    channel_count = Column(Integer, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    replaygain_track_gain_db = Column(Float, nullable=True)
    replaygain_album_gain_db = Column(Float, nullable=True)
    replaygain_track_peak = Column(Float, nullable=True)
    replaygain_album_peak = Column(Float, nullable=True)
    probe_error_code = Column(String(100), nullable=True)
    probed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    track = relationship("Track", back_populates="technical_profile")


class MusicRecordingPreference(Base):
    __tablename__ = "music_recording_preferences"

    id = Column(Integer, primary_key=True, index=True)
    recording_id = Column(Integer, ForeignKey("music_recordings.id"), unique=True, index=True, nullable=False)
    auto_preferred_track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True, index=True)
    user_preferred_track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True, index=True)
    decision_state = Column(String, nullable=False, default="no_eligible_source", server_default="no_eligible_source", index=True)
    confidence = Column(String, nullable=False, default="none", server_default="none")
    reason_code = Column(String(100), nullable=False, default="no_available_source", server_default="no_available_source")
    policy_version = Column(Integer, nullable=False, default=1, server_default="1")
    candidate_count = Column(Integer, nullable=False, default=0, server_default="0")
    eligible_candidate_count = Column(Integer, nullable=False, default=0, server_default="0")
    evaluated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    recording = relationship("MusicRecording", back_populates="preference")
    auto_preferred_track = relationship("Track", foreign_keys=[auto_preferred_track_id])
    user_preferred_track = relationship("Track", foreign_keys=[user_preferred_track_id])



class MusicRecordingParticipation(Base):
    __tablename__ = "music_recording_participation"
    __table_args__ = (
        CheckConstraint("participation_state in ('included', 'library_only', 'archived', 'blocked')", name="ck_music_recording_participation_state"),
        CheckConstraint("state_source in ('user', 'system')", name="ck_music_recording_participation_source"),
    )

    id = Column(Integer, primary_key=True, index=True)
    recording_id = Column(Integer, ForeignKey("music_recordings.id"), unique=True, index=True, nullable=False)
    participation_state = Column(String, nullable=False, default="included", server_default="included", index=True)
    state_source = Column(String, nullable=False, default="user", server_default="user", index=True)
    reason_code = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    recording = relationship("MusicRecording", back_populates="participation")

class ArtistRadioProfile(Base):
    __tablename__ = "artist_radio_profiles"

    id = Column(Integer, primary_key=True, index=True)
    artist = Column(String, unique=True, index=True, nullable=False)
    primary_genre = Column(String, nullable=True)
    subgenres_json = Column(Text, nullable=True)
    moods_json = Column(Text, nullable=True)
    energy = Column(String, nullable=True)
    era = Column(String, nullable=True)
    related_artists_json = Column(Text, nullable=True)
    source = Column(String, default="seed")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class AlbumRadioProfile(Base):
    __tablename__ = "album_radio_profiles"
    __table_args__ = (UniqueConstraint("artist", "album", name="uq_album_radio_profile_artist_album"),)

    id = Column(Integer, primary_key=True, index=True)
    artist = Column(String, index=True, nullable=False)
    album = Column(String, index=True, nullable=False)
    primary_genre = Column(String, nullable=True)
    subgenres_json = Column(Text, nullable=True)
    moods_json = Column(Text, nullable=True)
    energy = Column(String, nullable=True)
    era = Column(String, nullable=True)
    source = Column(String, default="seed")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class TrackRadioProfile(Base):
    __tablename__ = "track_radio_profiles"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), unique=True, index=True, nullable=False)
    primary_genre = Column(String, nullable=True)
    subgenres_json = Column(Text, nullable=True)
    moods_json = Column(Text, nullable=True)
    energy = Column(String, nullable=True)
    tempo_bucket = Column(String, nullable=True)
    radio_tags_json = Column(Text, nullable=True)
    source = Column(String, default="manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, index=True)
    media_kind = Column(String, nullable=False, index=True)
    status = Column(String, default="running", server_default="running", nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    roots_json = Column(Text, default="[]", server_default="[]", nullable=False)
    items_discovered = Column(Integer, default=0, server_default="0", nullable=False)
    items_added = Column(Integer, default=0, server_default="0", nullable=False)
    items_updated = Column(Integer, default=0, server_default="0", nullable=False)
    items_unavailable = Column(Integer, default=0, server_default="0", nullable=False)
    error_count = Column(Integer, default=0, server_default="0", nullable=False)
    error_summary = Column(String(1000), nullable=True)


class Audiobook(Base):
    __tablename__ = "audiobooks"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String, unique=True, index=True)
    relative_path = Column(String)
    title = Column(String, index=True)
    author = Column(String, index=True)
    narrator = Column(String, nullable=True)
    series = Column(String, nullable=True)
    year = Column(Integer, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    metadata_source = Column(String, nullable=True)
    source_manifest_path = Column(String, nullable=True)
    source_manifest_version = Column(String, nullable=True)
    source_metadata_version = Column(String, nullable=True)
    status = Column(String, default="available", index=True) # available, in_progress, finished, etc.
    favorite = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), index=True)
    last_indexed_at = Column(DateTime(timezone=True), index=True)
    library_availability = Column(String, default="available", server_default="available", index=True)
    last_seen_scan_id = Column(Integer, nullable=True, index=True)
    unavailable_since = Column(DateTime(timezone=True), nullable=True)

    chapters = relationship("AudiobookChapter", back_populates="audiobook")
    progress = relationship("AudiobookProgress", back_populates="audiobook")

class AudiobookChapter(Base):
    __tablename__ = "audiobook_chapters"

    id = Column(Integer, primary_key=True, index=True)
    audiobook_id = Column(Integer, ForeignKey("audiobooks.id"))
    path = Column(String)
    relative_path = Column(String)
    title = Column(String)
    chapter_number = Column(Integer, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    sort_order = Column(Integer)
    library_availability = Column(String, default="available", server_default="available", index=True)
    last_seen_scan_id = Column(Integer, nullable=True, index=True)
    unavailable_since = Column(DateTime(timezone=True), nullable=True)

    audiobook = relationship("Audiobook", back_populates="chapters")

class Station(Base):
    __tablename__ = "stations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    type = Column(String) # artist, genre, favorites, recently_added, deep_cuts
    seed_value = Column(String) # artist name, genre name, etc.
    favorite = Column(Boolean, default=False)
    description = Column(String, nullable=True)
    tuning_discovery = Column(Integer, default=50)
    tuning_energy = Column(Integer, default=50)
    tuning_deep_cuts = Column(Integer, default=50)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_played_at = Column(DateTime(timezone=True), nullable=True)

class TrackThumb(Base):
    __tablename__ = "track_thumbs"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), index=True)
    recording_id = Column(Integer, ForeignKey("music_recordings.id"), nullable=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=True, index=True)
    value = Column(Enum(ThumbValue))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    track = relationship("Track", back_populates="thumbs")

class TrackFavorite(Base):
    __tablename__ = "track_favorites"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), index=True)
    recording_id = Column(Integer, ForeignKey("music_recordings.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    track = relationship("Track", back_populates="favorites")

class PlaybackEvent(Base):
    __tablename__ = "playback_events"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True, index=True)
    recording_id = Column(Integer, ForeignKey("music_recordings.id"), nullable=True, index=True)
    audiobook_id = Column(Integer, ForeignKey("audiobooks.id"), nullable=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=True, index=True)
    event_type = Column(String, index=True) # start, stop, skip, finish
    position_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

class AudiobookProgress(Base):
    __tablename__ = "audiobook_progress"

    id = Column(Integer, primary_key=True, index=True)
    audiobook_id = Column(Integer, ForeignKey("audiobooks.id"), index=True)
    chapter_id = Column(Integer, ForeignKey("audiobook_chapters.id"), nullable=True, index=True)
    position_seconds = Column(Float)
    progress_percent = Column(Float)
    status = Column(String) # in_progress, finished
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)

    audiobook = relationship("Audiobook", back_populates="progress")
class Playlist(Base):
    __tablename__ = "playlists"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String, nullable=True)
    kind = Column(String, default="manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tracks = relationship("PlaylistTrack", back_populates="playlist", cascade="all, delete-orphan")

class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"

    id = Column(Integer, primary_key=True, index=True)
    playlist_id = Column(Integer, ForeignKey("playlists.id"), index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), index=True)
    position = Column(Integer)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    playlist = relationship("Playlist", back_populates="tracks")
    track = relationship("Track")
