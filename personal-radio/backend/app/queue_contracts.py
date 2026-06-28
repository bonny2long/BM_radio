from pydantic import BaseModel


class StationQueueRequest(BaseModel):
    type: str
    seed_value: str | None = None
    seed_track_id: int | None = None
    limit: int = 50
    shuffle: bool = True
    exclude_track_ids: list[int] = []


class AlbumQueueRequest(BaseModel):
    artist: str
    album: str
    limit: int = 500
    shuffle: bool = False


class ArtistQueueRequest(BaseModel):
    artist: str
    limit: int = 50
    shuffle: bool = False


class PlaylistQueueRequest(BaseModel):
    playlist_id: int
    shuffle: bool = False


class SmartPlaylistQueueRequest(BaseModel):
    key: str
    shuffle: bool = False
    limit: int = 1000
