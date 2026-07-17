"""current schema baseline

Revision ID: 0001_current_schema_baseline
Revises:
Create Date: 2026-07-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = '0001_current_schema_baseline'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('album_radio_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('artist', sa.String(), nullable=False),
        sa.Column('album', sa.String(), nullable=False),
        sa.Column('primary_genre', sa.String()),
        sa.Column('subgenres_json', sa.Text()),
        sa.Column('moods_json', sa.Text()),
        sa.Column('energy', sa.String()),
        sa.Column('era', sa.String()),
        sa.Column('source', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('artist', 'album', name='uq_album_radio_profile_artist_album'),
    )

    op.create_table('artist_radio_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('artist', sa.String(), nullable=False),
        sa.Column('primary_genre', sa.String()),
        sa.Column('subgenres_json', sa.Text()),
        sa.Column('moods_json', sa.Text()),
        sa.Column('energy', sa.String()),
        sa.Column('era', sa.String()),
        sa.Column('related_artists_json', sa.Text()),
        sa.Column('source', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('audiobooks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String()),
        sa.Column('relative_path', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('author', sa.String()),
        sa.Column('narrator', sa.String()),
        sa.Column('series', sa.String()),
        sa.Column('year', sa.Integer()),
        sa.Column('duration_seconds', sa.Float()),
        sa.Column('metadata_source', sa.String()),
        sa.Column('source_manifest_path', sa.String()),
        sa.Column('source_manifest_version', sa.String()),
        sa.Column('source_metadata_version', sa.String()),
        sa.Column('status', sa.String()),
        sa.Column('favorite', sa.Boolean()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('last_indexed_at', sa.DateTime(timezone=True)),
        sa.Column('library_availability', sa.String(), server_default=sa.text("'available'")),
        sa.Column('last_seen_scan_id', sa.Integer()),
        sa.Column('unavailable_since', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('music_recordings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('identity_key', sa.String(), nullable=False),
        sa.Column('artist', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('normalized_artist', sa.String(), nullable=False, server_default=sa.text("''")),
        sa.Column('normalized_title', sa.String(), nullable=False, server_default=sa.text("''")),
        sa.Column('recording_type', sa.String(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('version_hint', sa.String()),
        sa.Column('duration_bucket', sa.String(), nullable=False, server_default=sa.text("''")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('music_releases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('identity_key', sa.String(), nullable=False),
        sa.Column('album_artist', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('normalized_album_artist', sa.String(), nullable=False, server_default=sa.text("''")),
        sa.Column('normalized_title', sa.String(), nullable=False, server_default=sa.text("''")),
        sa.Column('release_type', sa.String(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('playlists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String()),
        sa.Column('description', sa.String()),
        sa.Column('kind', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('scan_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('media_kind', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default=sa.text("'running'")),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('roots_json', sa.Text(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('items_discovered', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('items_added', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('items_updated', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('items_unavailable', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('error_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('error_summary', sa.String(1000)),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('stations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String()),
        sa.Column('type', sa.String()),
        sa.Column('seed_value', sa.String()),
        sa.Column('favorite', sa.Boolean()),
        sa.Column('description', sa.String()),
        sa.Column('tuning_discovery', sa.Integer()),
        sa.Column('tuning_energy', sa.Integer()),
        sa.Column('tuning_deep_cuts', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('last_played_at', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('tracks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('path', sa.String()),
        sa.Column('relative_path', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('artist', sa.String()),
        sa.Column('album', sa.String()),
        sa.Column('album_artist', sa.String()),
        sa.Column('genre', sa.String()),
        sa.Column('year', sa.Integer()),
        sa.Column('duration_seconds', sa.Float()),
        sa.Column('file_ext', sa.String()),
        sa.Column('library_area', sa.String()),
        sa.Column('cover_path', sa.String()),
        sa.Column('metadata_source', sa.String()),
        sa.Column('source_manifest_path', sa.String()),
        sa.Column('source_manifest_version', sa.String()),
        sa.Column('source_metadata_version', sa.String()),
        sa.Column('track_number', sa.Integer()),
        sa.Column('disc_number', sa.Integer()),
        sa.Column('primary_genre', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('last_indexed_at', sa.DateTime(timezone=True)),
        sa.Column('library_availability', sa.String(), server_default=sa.text("'available'")),
        sa.Column('last_seen_scan_id', sa.Integer()),
        sa.Column('unavailable_since', sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('audiobook_chapters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('audiobook_id', sa.Integer()),
        sa.Column('path', sa.String()),
        sa.Column('relative_path', sa.String()),
        sa.Column('title', sa.String()),
        sa.Column('chapter_number', sa.Integer()),
        sa.Column('duration_seconds', sa.Float()),
        sa.Column('sort_order', sa.Integer()),
        sa.Column('library_availability', sa.String(), server_default=sa.text("'available'")),
        sa.Column('last_seen_scan_id', sa.Integer()),
        sa.Column('unavailable_since', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['audiobook_id'], ['audiobooks.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('music_editions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('identity_key', sa.String(), nullable=False),
        sa.Column('release_id', sa.Integer(), nullable=False),
        sa.Column('display_title', sa.String()),
        sa.Column('year', sa.Integer()),
        sa.Column('edition_type', sa.String(), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('source_scope', sa.String(), nullable=False),
        sa.Column('source_format_family', sa.String(), nullable=False, server_default=sa.text("'UNKNOWN'")),
        sa.Column('source_manifest_path', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['release_id'], ['music_releases.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('music_recording_participation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recording_id', sa.Integer(), nullable=False),
        sa.Column('participation_state', sa.String(), nullable=False, server_default=sa.text("'included'")),
        sa.Column('state_source', sa.String(), nullable=False, server_default=sa.text("'user'")),
        sa.Column('reason_code', sa.String(100)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("state_source in ('user', 'system')", name='ck_music_recording_participation_source'),
        sa.CheckConstraint("participation_state in ('included', 'library_only', 'archived', 'blocked')", name='ck_music_recording_participation_state'),
        sa.ForeignKeyConstraint(['recording_id'], ['music_recordings.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('music_recording_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recording_id', sa.Integer(), nullable=False),
        sa.Column('auto_preferred_track_id', sa.Integer()),
        sa.Column('user_preferred_track_id', sa.Integer()),
        sa.Column('decision_state', sa.String(), nullable=False, server_default=sa.text("'no_eligible_source'")),
        sa.Column('confidence', sa.String(), nullable=False, server_default=sa.text("'none'")),
        sa.Column('reason_code', sa.String(100), nullable=False, server_default=sa.text("'no_available_source'")),
        sa.Column('policy_version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('candidate_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('eligible_candidate_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('evaluated_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['auto_preferred_track_id'], ['tracks.id']),
        sa.ForeignKeyConstraint(['recording_id'], ['music_recordings.id']),
        sa.ForeignKeyConstraint(['user_preferred_track_id'], ['tracks.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('music_technical_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('probe_status', sa.String(), nullable=False, server_default=sa.text("'partial'")),
        sa.Column('probe_source', sa.String(), nullable=False, server_default=sa.text("'mutagen'")),
        sa.Column('probe_version', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('codec', sa.String()),
        sa.Column('container', sa.String()),
        sa.Column('is_lossless', sa.Boolean()),
        sa.Column('sample_rate_hz', sa.Integer()),
        sa.Column('bit_depth_bits', sa.Integer()),
        sa.Column('bitrate_bps', sa.Integer()),
        sa.Column('channel_count', sa.Integer()),
        sa.Column('file_size_bytes', sa.Integer()),
        sa.Column('replaygain_track_gain_db', sa.Float()),
        sa.Column('replaygain_album_gain_db', sa.Float()),
        sa.Column('replaygain_track_peak', sa.Float()),
        sa.Column('replaygain_album_peak', sa.Float()),
        sa.Column('probe_error_code', sa.String(100)),
        sa.Column('probed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('playback_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer()),
        sa.Column('recording_id', sa.Integer()),
        sa.Column('audiobook_id', sa.Integer()),
        sa.Column('station_id', sa.Integer()),
        sa.Column('event_type', sa.String()),
        sa.Column('position_seconds', sa.Float()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.ForeignKeyConstraint(['audiobook_id'], ['audiobooks.id']),
        sa.ForeignKeyConstraint(['recording_id'], ['music_recordings.id']),
        sa.ForeignKeyConstraint(['station_id'], ['stations.id']),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('playlist_tracks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('playlist_id', sa.Integer()),
        sa.Column('track_id', sa.Integer()),
        sa.Column('position', sa.Integer()),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.ForeignKeyConstraint(['playlist_id'], ['playlists.id']),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('track_favorites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer()),
        sa.Column('recording_id', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.ForeignKeyConstraint(['recording_id'], ['music_recordings.id']),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('track_radio_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('primary_genre', sa.String()),
        sa.Column('subgenres_json', sa.Text()),
        sa.Column('moods_json', sa.Text()),
        sa.Column('energy', sa.String()),
        sa.Column('tempo_bucket', sa.String()),
        sa.Column('radio_tags_json', sa.Text()),
        sa.Column('source', sa.String()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('track_thumbs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer()),
        sa.Column('recording_id', sa.Integer()),
        sa.Column('station_id', sa.Integer()),
        sa.Column('value', sa.Enum('up', 'down', name='thumbvalue')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.ForeignKeyConstraint(['recording_id'], ['music_recordings.id']),
        sa.ForeignKeyConstraint(['station_id'], ['stations.id']),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('audiobook_progress',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('audiobook_id', sa.Integer()),
        sa.Column('chapter_id', sa.Integer()),
        sa.Column('position_seconds', sa.Float()),
        sa.Column('progress_percent', sa.Float()),
        sa.Column('status', sa.String()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.ForeignKeyConstraint(['audiobook_id'], ['audiobooks.id']),
        sa.ForeignKeyConstraint(['chapter_id'], ['audiobook_chapters.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table('music_track_identities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('edition_id', sa.Integer(), nullable=False),
        sa.Column('recording_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(['edition_id'], ['music_editions.id']),
        sa.ForeignKeyConstraint(['recording_id'], ['music_recordings.id']),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('ix_album_radio_profiles_album', 'album_radio_profiles', ['album'])
    op.create_index('ix_album_radio_profiles_artist', 'album_radio_profiles', ['artist'])
    op.create_index('ix_album_radio_profiles_id', 'album_radio_profiles', ['id'])
    op.create_index('ix_artist_radio_profiles_artist', 'artist_radio_profiles', ['artist'], unique=True)
    op.create_index('ix_artist_radio_profiles_id', 'artist_radio_profiles', ['id'])
    op.create_index('ix_audiobooks_author', 'audiobooks', ['author'])
    op.create_index('ix_audiobooks_created_at', 'audiobooks', ['created_at'])
    op.create_index('ix_audiobooks_id', 'audiobooks', ['id'])
    op.create_index('ix_audiobooks_last_indexed_at', 'audiobooks', ['last_indexed_at'])
    op.create_index('ix_audiobooks_last_seen_scan_id', 'audiobooks', ['last_seen_scan_id'])
    op.create_index('ix_audiobooks_library_availability', 'audiobooks', ['library_availability'])
    op.create_index('ix_audiobooks_path', 'audiobooks', ['path'], unique=True)
    op.create_index('ix_audiobooks_status', 'audiobooks', ['status'])
    op.create_index('ix_audiobooks_title', 'audiobooks', ['title'])
    op.create_index('ix_audiobooks_updated_at', 'audiobooks', ['updated_at'])
    op.create_index('ix_music_recordings_artist', 'music_recordings', ['artist'])
    op.create_index('ix_music_recordings_id', 'music_recordings', ['id'])
    op.create_index('ix_music_recordings_identity_key', 'music_recordings', ['identity_key'], unique=True)
    op.create_index('ix_music_recordings_recording_type', 'music_recordings', ['recording_type'])
    op.create_index('ix_music_recordings_title', 'music_recordings', ['title'])
    op.create_index('ix_music_releases_album_artist', 'music_releases', ['album_artist'])
    op.create_index('ix_music_releases_id', 'music_releases', ['id'])
    op.create_index('ix_music_releases_identity_key', 'music_releases', ['identity_key'], unique=True)
    op.create_index('ix_music_releases_title', 'music_releases', ['title'])
    op.create_index('ix_playlists_id', 'playlists', ['id'])
    op.create_index('ix_playlists_name', 'playlists', ['name'])
    op.create_index('ix_scan_runs_id', 'scan_runs', ['id'])
    op.create_index('ix_scan_runs_media_kind', 'scan_runs', ['media_kind'])
    op.create_index('ix_scan_runs_started_at', 'scan_runs', ['started_at'])
    op.create_index('ix_scan_runs_status', 'scan_runs', ['status'])
    op.create_index('ix_stations_id', 'stations', ['id'])
    op.create_index('ix_stations_name', 'stations', ['name'])
    op.create_index('ix_tracks_album', 'tracks', ['album'])
    op.create_index('ix_tracks_album_artist', 'tracks', ['album_artist'])
    op.create_index('ix_tracks_artist', 'tracks', ['artist'])
    op.create_index('ix_tracks_created_at', 'tracks', ['created_at'])
    op.create_index('ix_tracks_genre', 'tracks', ['genre'])
    op.create_index('ix_tracks_id', 'tracks', ['id'])
    op.create_index('ix_tracks_last_indexed_at', 'tracks', ['last_indexed_at'])
    op.create_index('ix_tracks_last_seen_scan_id', 'tracks', ['last_seen_scan_id'])
    op.create_index('ix_tracks_library_area', 'tracks', ['library_area'])
    op.create_index('ix_tracks_library_availability', 'tracks', ['library_availability'])
    op.create_index('ix_tracks_path', 'tracks', ['path'], unique=True)
    op.create_index('ix_tracks_title', 'tracks', ['title'])
    op.create_index('ix_audiobook_chapters_id', 'audiobook_chapters', ['id'])
    op.create_index('ix_audiobook_chapters_last_seen_scan_id', 'audiobook_chapters', ['last_seen_scan_id'])
    op.create_index('ix_audiobook_chapters_library_availability', 'audiobook_chapters', ['library_availability'])
    op.create_index('ix_music_editions_id', 'music_editions', ['id'])
    op.create_index('ix_music_editions_identity_key', 'music_editions', ['identity_key'], unique=True)
    op.create_index('ix_music_editions_release_id', 'music_editions', ['release_id'])
    op.create_index('ix_music_editions_source_scope', 'music_editions', ['source_scope'])
    op.create_index('ix_music_recording_participation_id', 'music_recording_participation', ['id'])
    op.create_index('ix_music_recording_participation_participation_state', 'music_recording_participation', ['participation_state'])
    op.create_index('ix_music_recording_participation_recording_id', 'music_recording_participation', ['recording_id'], unique=True)
    op.create_index('ix_music_recording_participation_state_source', 'music_recording_participation', ['state_source'])
    op.create_index('ix_music_recording_preferences_auto_preferred_track_id', 'music_recording_preferences', ['auto_preferred_track_id'])
    op.create_index('ix_music_recording_preferences_decision_state', 'music_recording_preferences', ['decision_state'])
    op.create_index('ix_music_recording_preferences_id', 'music_recording_preferences', ['id'])
    op.create_index('ix_music_recording_preferences_recording_id', 'music_recording_preferences', ['recording_id'], unique=True)
    op.create_index('ix_music_recording_preferences_user_preferred_track_id', 'music_recording_preferences', ['user_preferred_track_id'])
    op.create_index('ix_music_technical_profiles_codec', 'music_technical_profiles', ['codec'])
    op.create_index('ix_music_technical_profiles_id', 'music_technical_profiles', ['id'])
    op.create_index('ix_music_technical_profiles_is_lossless', 'music_technical_profiles', ['is_lossless'])
    op.create_index('ix_music_technical_profiles_probe_status', 'music_technical_profiles', ['probe_status'])
    op.create_index('ix_music_technical_profiles_track_id', 'music_technical_profiles', ['track_id'], unique=True)
    op.create_index('ix_playback_events_audiobook_id', 'playback_events', ['audiobook_id'])
    op.create_index('ix_playback_events_created_at', 'playback_events', ['created_at'])
    op.create_index('ix_playback_events_event_type', 'playback_events', ['event_type'])
    op.create_index('ix_playback_events_id', 'playback_events', ['id'])
    op.create_index('ix_playback_events_recording_id', 'playback_events', ['recording_id'])
    op.create_index('ix_playback_events_station_id', 'playback_events', ['station_id'])
    op.create_index('ix_playback_events_track_id', 'playback_events', ['track_id'])
    op.create_index('ix_playlist_tracks_id', 'playlist_tracks', ['id'])
    op.create_index('ix_playlist_tracks_playlist_id', 'playlist_tracks', ['playlist_id'])
    op.create_index('ix_playlist_tracks_track_id', 'playlist_tracks', ['track_id'])
    op.create_index('ix_track_favorites_created_at', 'track_favorites', ['created_at'])
    op.create_index('ix_track_favorites_id', 'track_favorites', ['id'])
    op.create_index('ix_track_favorites_recording_id', 'track_favorites', ['recording_id'])
    op.create_index('ix_track_favorites_track_id', 'track_favorites', ['track_id'])
    op.create_index('ix_track_radio_profiles_id', 'track_radio_profiles', ['id'])
    op.create_index('ix_track_radio_profiles_track_id', 'track_radio_profiles', ['track_id'], unique=True)
    op.create_index('ix_track_thumbs_created_at', 'track_thumbs', ['created_at'])
    op.create_index('ix_track_thumbs_id', 'track_thumbs', ['id'])
    op.create_index('ix_track_thumbs_recording_id', 'track_thumbs', ['recording_id'])
    op.create_index('ix_track_thumbs_station_id', 'track_thumbs', ['station_id'])
    op.create_index('ix_track_thumbs_track_id', 'track_thumbs', ['track_id'])
    op.create_index('ix_audiobook_progress_audiobook_id', 'audiobook_progress', ['audiobook_id'])
    op.create_index('ix_audiobook_progress_chapter_id', 'audiobook_progress', ['chapter_id'])
    op.create_index('ix_audiobook_progress_id', 'audiobook_progress', ['id'])
    op.create_index('ix_audiobook_progress_updated_at', 'audiobook_progress', ['updated_at'])
    op.create_index('ix_music_track_identities_edition_id', 'music_track_identities', ['edition_id'])
    op.create_index('ix_music_track_identities_id', 'music_track_identities', ['id'])
    op.create_index('ix_music_track_identities_recording_id', 'music_track_identities', ['recording_id'])
    op.create_index('ix_music_track_identities_track_id', 'music_track_identities', ['track_id'], unique=True)
    op.execute('CREATE INDEX IF NOT EXISTS ix_tracks_library_availability ON tracks (library_availability)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_tracks_last_seen_scan_id ON tracks (last_seen_scan_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audiobooks_library_availability ON audiobooks (library_availability)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audiobooks_last_seen_scan_id ON audiobooks (last_seen_scan_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audiobook_chapters_library_availability ON audiobook_chapters (library_availability)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audiobook_chapters_last_seen_scan_id ON audiobook_chapters (last_seen_scan_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_scan_runs_media_kind ON scan_runs (media_kind)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_scan_runs_status ON scan_runs (status)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_scan_runs_started_at ON scan_runs (started_at)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_playback_events_recording_id ON playback_events (recording_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_track_favorites_recording_id ON track_favorites (recording_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_track_thumbs_recording_id ON track_thumbs (recording_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_tracks_album_artist ON tracks (album_artist)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_tracks_library_area ON tracks (library_area)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_tracks_created_at ON tracks (created_at)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_tracks_last_indexed_at ON tracks (last_indexed_at)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_track_thumbs_track_id ON track_thumbs (track_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_track_thumbs_station_id ON track_thumbs (station_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_track_thumbs_created_at ON track_thumbs (created_at)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_track_favorites_track_id ON track_favorites (track_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_track_favorites_created_at ON track_favorites (created_at)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_playback_events_track_id ON playback_events (track_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_playback_events_audiobook_id ON playback_events (audiobook_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_playback_events_station_id ON playback_events (station_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_playback_events_event_type ON playback_events (event_type)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_playback_events_created_at ON playback_events (created_at)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audiobooks_status ON audiobooks (status)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audiobooks_updated_at ON audiobooks (updated_at)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audiobook_progress_audiobook_id ON audiobook_progress (audiobook_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audiobook_progress_chapter_id ON audiobook_progress (chapter_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_audiobook_progress_updated_at ON audiobook_progress (updated_at)')


def downgrade() -> None:
    op.drop_index('ix_music_track_identities_track_id', table_name='music_track_identities')
    op.drop_index('ix_music_track_identities_recording_id', table_name='music_track_identities')
    op.drop_index('ix_music_track_identities_id', table_name='music_track_identities')
    op.drop_index('ix_music_track_identities_edition_id', table_name='music_track_identities')
    op.drop_index('ix_audiobook_progress_updated_at', table_name='audiobook_progress')
    op.drop_index('ix_audiobook_progress_id', table_name='audiobook_progress')
    op.drop_index('ix_audiobook_progress_chapter_id', table_name='audiobook_progress')
    op.drop_index('ix_audiobook_progress_audiobook_id', table_name='audiobook_progress')
    op.drop_index('ix_track_thumbs_track_id', table_name='track_thumbs')
    op.drop_index('ix_track_thumbs_station_id', table_name='track_thumbs')
    op.drop_index('ix_track_thumbs_recording_id', table_name='track_thumbs')
    op.drop_index('ix_track_thumbs_id', table_name='track_thumbs')
    op.drop_index('ix_track_thumbs_created_at', table_name='track_thumbs')
    op.drop_index('ix_track_radio_profiles_track_id', table_name='track_radio_profiles')
    op.drop_index('ix_track_radio_profiles_id', table_name='track_radio_profiles')
    op.drop_index('ix_track_favorites_track_id', table_name='track_favorites')
    op.drop_index('ix_track_favorites_recording_id', table_name='track_favorites')
    op.drop_index('ix_track_favorites_id', table_name='track_favorites')
    op.drop_index('ix_track_favorites_created_at', table_name='track_favorites')
    op.drop_index('ix_playlist_tracks_track_id', table_name='playlist_tracks')
    op.drop_index('ix_playlist_tracks_playlist_id', table_name='playlist_tracks')
    op.drop_index('ix_playlist_tracks_id', table_name='playlist_tracks')
    op.drop_index('ix_playback_events_track_id', table_name='playback_events')
    op.drop_index('ix_playback_events_station_id', table_name='playback_events')
    op.drop_index('ix_playback_events_recording_id', table_name='playback_events')
    op.drop_index('ix_playback_events_id', table_name='playback_events')
    op.drop_index('ix_playback_events_event_type', table_name='playback_events')
    op.drop_index('ix_playback_events_created_at', table_name='playback_events')
    op.drop_index('ix_playback_events_audiobook_id', table_name='playback_events')
    op.drop_index('ix_music_technical_profiles_track_id', table_name='music_technical_profiles')
    op.drop_index('ix_music_technical_profiles_probe_status', table_name='music_technical_profiles')
    op.drop_index('ix_music_technical_profiles_is_lossless', table_name='music_technical_profiles')
    op.drop_index('ix_music_technical_profiles_id', table_name='music_technical_profiles')
    op.drop_index('ix_music_technical_profiles_codec', table_name='music_technical_profiles')
    op.drop_index('ix_music_recording_preferences_user_preferred_track_id', table_name='music_recording_preferences')
    op.drop_index('ix_music_recording_preferences_recording_id', table_name='music_recording_preferences')
    op.drop_index('ix_music_recording_preferences_id', table_name='music_recording_preferences')
    op.drop_index('ix_music_recording_preferences_decision_state', table_name='music_recording_preferences')
    op.drop_index('ix_music_recording_preferences_auto_preferred_track_id', table_name='music_recording_preferences')
    op.drop_index('ix_music_recording_participation_state_source', table_name='music_recording_participation')
    op.drop_index('ix_music_recording_participation_recording_id', table_name='music_recording_participation')
    op.drop_index('ix_music_recording_participation_participation_state', table_name='music_recording_participation')
    op.drop_index('ix_music_recording_participation_id', table_name='music_recording_participation')
    op.drop_index('ix_music_editions_source_scope', table_name='music_editions')
    op.drop_index('ix_music_editions_release_id', table_name='music_editions')
    op.drop_index('ix_music_editions_identity_key', table_name='music_editions')
    op.drop_index('ix_music_editions_id', table_name='music_editions')
    op.drop_index('ix_audiobook_chapters_library_availability', table_name='audiobook_chapters')
    op.drop_index('ix_audiobook_chapters_last_seen_scan_id', table_name='audiobook_chapters')
    op.drop_index('ix_audiobook_chapters_id', table_name='audiobook_chapters')
    op.drop_index('ix_tracks_title', table_name='tracks')
    op.drop_index('ix_tracks_path', table_name='tracks')
    op.drop_index('ix_tracks_library_availability', table_name='tracks')
    op.drop_index('ix_tracks_library_area', table_name='tracks')
    op.drop_index('ix_tracks_last_seen_scan_id', table_name='tracks')
    op.drop_index('ix_tracks_last_indexed_at', table_name='tracks')
    op.drop_index('ix_tracks_id', table_name='tracks')
    op.drop_index('ix_tracks_genre', table_name='tracks')
    op.drop_index('ix_tracks_created_at', table_name='tracks')
    op.drop_index('ix_tracks_artist', table_name='tracks')
    op.drop_index('ix_tracks_album_artist', table_name='tracks')
    op.drop_index('ix_tracks_album', table_name='tracks')
    op.drop_index('ix_stations_name', table_name='stations')
    op.drop_index('ix_stations_id', table_name='stations')
    op.drop_index('ix_scan_runs_status', table_name='scan_runs')
    op.drop_index('ix_scan_runs_started_at', table_name='scan_runs')
    op.drop_index('ix_scan_runs_media_kind', table_name='scan_runs')
    op.drop_index('ix_scan_runs_id', table_name='scan_runs')
    op.drop_index('ix_playlists_name', table_name='playlists')
    op.drop_index('ix_playlists_id', table_name='playlists')
    op.drop_index('ix_music_releases_title', table_name='music_releases')
    op.drop_index('ix_music_releases_identity_key', table_name='music_releases')
    op.drop_index('ix_music_releases_id', table_name='music_releases')
    op.drop_index('ix_music_releases_album_artist', table_name='music_releases')
    op.drop_index('ix_music_recordings_title', table_name='music_recordings')
    op.drop_index('ix_music_recordings_recording_type', table_name='music_recordings')
    op.drop_index('ix_music_recordings_identity_key', table_name='music_recordings')
    op.drop_index('ix_music_recordings_id', table_name='music_recordings')
    op.drop_index('ix_music_recordings_artist', table_name='music_recordings')
    op.drop_index('ix_audiobooks_updated_at', table_name='audiobooks')
    op.drop_index('ix_audiobooks_title', table_name='audiobooks')
    op.drop_index('ix_audiobooks_status', table_name='audiobooks')
    op.drop_index('ix_audiobooks_path', table_name='audiobooks')
    op.drop_index('ix_audiobooks_library_availability', table_name='audiobooks')
    op.drop_index('ix_audiobooks_last_seen_scan_id', table_name='audiobooks')
    op.drop_index('ix_audiobooks_last_indexed_at', table_name='audiobooks')
    op.drop_index('ix_audiobooks_id', table_name='audiobooks')
    op.drop_index('ix_audiobooks_created_at', table_name='audiobooks')
    op.drop_index('ix_audiobooks_author', table_name='audiobooks')
    op.drop_index('ix_artist_radio_profiles_id', table_name='artist_radio_profiles')
    op.drop_index('ix_artist_radio_profiles_artist', table_name='artist_radio_profiles')
    op.drop_index('ix_album_radio_profiles_id', table_name='album_radio_profiles')
    op.drop_index('ix_album_radio_profiles_artist', table_name='album_radio_profiles')
    op.drop_index('ix_album_radio_profiles_album', table_name='album_radio_profiles')
    op.drop_table('music_track_identities')
    op.drop_table('audiobook_progress')
    op.drop_table('track_thumbs')
    op.drop_table('track_radio_profiles')
    op.drop_table('track_favorites')
    op.drop_table('playlist_tracks')
    op.drop_table('playback_events')
    op.drop_table('music_technical_profiles')
    op.drop_table('music_recording_preferences')
    op.drop_table('music_recording_participation')
    op.drop_table('music_editions')
    op.drop_table('audiobook_chapters')
    op.drop_table('tracks')
    op.drop_table('stations')
    op.drop_table('scan_runs')
    op.drop_table('playlists')
    op.drop_table('music_releases')
    op.drop_table('music_recordings')
    op.drop_table('audiobooks')
    op.drop_table('artist_radio_profiles')
    op.drop_table('album_radio_profiles')
