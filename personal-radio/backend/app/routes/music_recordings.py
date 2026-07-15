from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, constr
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..music_recording_participation import (
    clear_music_recording_participation,
    get_music_recording_participation,
    set_music_recording_participation,
)
from ..music_source_preference import resolve_effective_music_source, set_music_recording_user_preference

router = APIRouter()

ParticipationState = Literal["included", "library_only", "archived", "blocked"]


class PreferredTrackPayload(BaseModel):
    track_id: int


class ParticipationPayload(BaseModel):
    state: ParticipationState
    reason_code: constr(strip_whitespace=True, max_length=100) | None = None


def iso(value):
    return value.isoformat() if value else None


def get_recording_or_404(db: Session, recording_id: int) -> models.MusicRecording:
    recording = db.get(models.MusicRecording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


def participation_payload(db: Session, recording_id: int) -> dict:
    state = get_music_recording_participation(db, recording_id=recording_id)
    return {
        "recording_id": state.recording_id,
        "participation_state": state.participation_state,
        "state": state.participation_state,
        "state_source": state.state_source,
        "reason_code": state.reason_code,
        "explicit": state.explicit,
        "row_id": state.row_id,
    }


def preference_payload(row: models.MusicRecordingPreference | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "recording_id": row.recording_id,
        "auto_preferred_track_id": row.auto_preferred_track_id,
        "user_preferred_track_id": row.user_preferred_track_id,
        "decision_state": row.decision_state,
        "confidence": row.confidence,
        "reason_code": row.reason_code,
        "policy_version": row.policy_version,
        "candidate_count": row.candidate_count,
        "eligible_candidate_count": row.eligible_candidate_count,
        "evaluated_at": iso(row.evaluated_at),
    }


def effective_source_payload(resolution) -> dict:
    return {
        "recording_id": resolution.recording_id,
        "track_id": resolution.track_id,
        "source": resolution.source,
        "decision_state": resolution.decision_state,
        "confidence": resolution.confidence,
        "reason_code": resolution.reason_code,
        "user_override_track_id": resolution.user_override_track_id,
        "auto_preferred_track_id": resolution.auto_preferred_track_id,
    }


def _candidate_rows(db: Session, recording_id: int):
    return (
        db.query(
            models.MusicTrackIdentity,
            models.Track,
            models.MusicEdition,
            models.MusicRelease,
            models.MusicTechnicalProfile,
        )
        .join(models.Track, models.Track.id == models.MusicTrackIdentity.track_id)
        .join(models.MusicEdition, models.MusicEdition.id == models.MusicTrackIdentity.edition_id)
        .join(models.MusicRelease, models.MusicRelease.id == models.MusicEdition.release_id)
        .outerjoin(models.MusicTechnicalProfile, models.MusicTechnicalProfile.track_id == models.Track.id)
        .filter(models.MusicTrackIdentity.recording_id == recording_id)
        .all()
    )


def candidate_payload(identity, track, edition, release, technical, preference, effective_track_id: int | None) -> dict:
    return {
        "track_id": track.id,
        "track": {
            "title": track.title,
            "artist": track.artist,
            "album": track.album,
            "album_artist": track.album_artist,
            "year": track.year,
            "track_number": track.track_number,
            "disc_number": track.disc_number,
            "file_ext": track.file_ext,
            "library_availability": track.library_availability,
            "relative_path": track.relative_path,
        },
        "identity": {
            "recording_id": identity.recording_id,
            "edition_id": identity.edition_id,
            "release_id": edition.release_id,
        },
        "release": {
            "title": release.title,
            "album_artist": release.album_artist,
            "release_type": release.release_type,
        },
        "edition": {
            "display_title": edition.display_title,
            "year": edition.year,
            "edition_type": edition.edition_type,
            "source_scope": edition.source_scope,
            "source_format_family": edition.source_format_family,
        },
        "technical": None if technical is None else {
            "probe_status": technical.probe_status,
            "codec": technical.codec,
            "container": technical.container,
            "is_lossless": technical.is_lossless,
            "sample_rate_hz": technical.sample_rate_hz,
            "bit_depth_bits": technical.bit_depth_bits,
            "bitrate_bps": technical.bitrate_bps,
            "channel_count": technical.channel_count,
            "file_size_bytes": technical.file_size_bytes,
            "replaygain_track_gain_db": technical.replaygain_track_gain_db,
            "replaygain_album_gain_db": technical.replaygain_album_gain_db,
            "replaygain_track_peak": technical.replaygain_track_peak,
            "replaygain_album_peak": technical.replaygain_album_peak,
        },
        "preference_flags": {
            "is_auto_preferred": bool(preference and preference.auto_preferred_track_id == track.id),
            "is_user_preferred": bool(preference and preference.user_preferred_track_id == track.id),
            "is_effective_source": effective_track_id == track.id,
        },
    }


def candidate_order_key(item: dict) -> tuple[int, int, int, int, int]:
    flags = item["preference_flags"]
    availability = item["track"].get("library_availability")
    return (
        0 if flags["is_effective_source"] else 1,
        0 if flags["is_user_preferred"] else 1,
        0 if flags["is_auto_preferred"] else 1,
        0 if availability == "available" else 1,
        int(item["track_id"]),
    )


def control_detail(db: Session, recording_id: int) -> dict:
    recording = get_recording_or_404(db, recording_id)
    resolution = resolve_effective_music_source(db, recording_id=recording_id)
    preference = db.query(models.MusicRecordingPreference).filter_by(recording_id=recording_id).one_or_none()
    candidates = [
        candidate_payload(identity, track, edition, release, technical, preference, resolution.track_id)
        for identity, track, edition, release, technical in _candidate_rows(db, recording_id)
    ]
    candidates.sort(key=candidate_order_key)
    return {
        "recording": {
            "id": recording.id,
            "identity_key": recording.identity_key,
            "artist": recording.artist,
            "title": recording.title,
            "recording_type": recording.recording_type,
            "version_hint": recording.version_hint,
            "duration_bucket": recording.duration_bucket,
        },
        "participation": participation_payload(db, recording_id),
        "preference": preference_payload(preference),
        "effective_source": effective_source_payload(resolution),
        "candidates": candidates,
    }


@router.get("/{recording_id}/control")
def get_recording_control(recording_id: int, db: Session = Depends(get_db)):
    return control_detail(db, recording_id)


@router.put("/{recording_id}/preferred-track")
def put_preferred_track(recording_id: int, payload: PreferredTrackPayload, db: Session = Depends(get_db)):
    get_recording_or_404(db, recording_id)
    if db.get(models.Track, payload.track_id) is None:
        raise HTTPException(status_code=404, detail="Track not found")
    try:
        set_music_recording_user_preference(db, recording_id=recording_id, track_id=payload.track_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return control_detail(db, recording_id)


@router.delete("/{recording_id}/preferred-track")
def delete_preferred_track(recording_id: int, db: Session = Depends(get_db)):
    get_recording_or_404(db, recording_id)
    set_music_recording_user_preference(db, recording_id=recording_id, track_id=None)
    db.commit()
    return control_detail(db, recording_id)


@router.put("/{recording_id}/participation")
def put_participation(recording_id: int, payload: ParticipationPayload, db: Session = Depends(get_db)):
    get_recording_or_404(db, recording_id)
    try:
        set_music_recording_participation(
            db,
            recording_id=recording_id,
            participation_state=payload.state,
            reason_code=payload.reason_code,
            state_source="user",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return control_detail(db, recording_id)


@router.delete("/{recording_id}/participation")
def delete_participation(recording_id: int, db: Session = Depends(get_db)):
    get_recording_or_404(db, recording_id)
    clear_music_recording_participation(db, recording_id=recording_id)
    db.commit()
    return control_detail(db, recording_id)
