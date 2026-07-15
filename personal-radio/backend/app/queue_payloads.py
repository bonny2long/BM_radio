from .availability import is_track_available
from .routes.serializers import track_item


def _station_identity_fields(track):
    fields = {}
    recording_id = getattr(track, "_station_recording_id", None)
    if recording_id is not None:
        fields.update({
            "recording_id": recording_id,
            "effective_track_id": getattr(track, "_station_effective_track_id", track.id),
            "profile_track_id": getattr(track, "_station_profile_track_id", track.id),
            "participation_state": getattr(track, "_station_participation_state", None),
            "recording_type": getattr(track, "_station_recording_type", None),
            "version_hint": getattr(track, "_station_version_hint", None),
            "source_resolution": getattr(track, "_station_source_resolution", None),
            "source_confidence": getattr(track, "_station_source_confidence", None),
            "source_reason_code": getattr(track, "_station_source_reason_code", None),
        })
    elif hasattr(track, "_station_candidate"):
        fields.update({
            "recording_id": None,
            "effective_track_id": track.id,
            "profile_track_id": track.id,
            "participation_state": getattr(track, "_station_participation_state", None),
            "source_resolution": getattr(track, "_station_source_resolution", None),
            "source_confidence": getattr(track, "_station_source_confidence", None),
            "source_reason_code": getattr(track, "_station_source_reason_code", None),
        })
    return fields


def payload(tracks, **meta):
    queue = []
    for track in tracks:
        if not is_track_available(track):
            continue
        item = track_item(track)
        item['track_id'] = track.id
        item.update(_station_identity_fields(track))
        queue.append(item)
    data = {'queue': queue}
    data.update(meta)
    return data