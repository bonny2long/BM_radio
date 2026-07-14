from .availability import is_track_available
from .routes.serializers import track_item


def payload(tracks, **meta):
    data = {'queue': [track_item(t) for t in tracks if is_track_available(t)]}
    data.update(meta)
    return data