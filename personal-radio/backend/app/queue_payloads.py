from .routes.serializers import track_item


def payload(tracks, **meta):
    data = {'queue': [track_item(t) for t in tracks]}
    data.update(meta)
    return data
