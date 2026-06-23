from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum, Float, Text
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
    album_artist = Column(String)
    genre = Column(String, index=True)
    year = Column(Integer)
    duration_seconds = Column(Float)
    file_ext = Column(String)
    library_area = Column(String)  # Library, Discographies, etc.
    cover_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_indexed_at = Column(DateTime(timezone=True))

    thumbs = relationship("TrackThumb", back_populates="track")
    favorites = relationship("TrackFavorite", back_populates="track")

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
    status = Column(String, default="available") # available, in_progress, finished, etc.
    favorite = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_indexed_at = Column(DateTime(timezone=True))

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
    track_id = Column(Integer, ForeignKey("tracks.id"))
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=True)
    value = Column(Enum(ThumbValue))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    track = relationship("Track", back_populates="thumbs")

class TrackFavorite(Base):
    __tablename__ = "track_favorites"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    track = relationship("Track", back_populates="favorites")

class PlaybackEvent(Base):
    __tablename__ = "playback_events"

    id = Column(Integer, primary_key=True, index=True)
    track_id = Column(Integer, ForeignKey("tracks.id"), nullable=True)
    audiobook_id = Column(Integer, ForeignKey("audiobooks.id"), nullable=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=True)
    event_type = Column(String) # start, stop, skip, finish
    position_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AudiobookProgress(Base):
    __tablename__ = "audiobook_progress"

    id = Column(Integer, primary_key=True, index=True)
    audiobook_id = Column(Integer, ForeignKey("audiobooks.id"))
    chapter_id = Column(Integer, ForeignKey("audiobook_chapters.id"), nullable=True)
    position_seconds = Column(Float)
    progress_percent = Column(Float)
    status = Column(String) # in_progress, finished
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    audiobook = relationship("Audiobook", back_populates="progress")
