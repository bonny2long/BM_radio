from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import bindparam, inspect, text
from sqlalchemy.orm import Session

from .station_candidate_intent import INTENT_ARTIST, INTENT_GENRE, INTENT_SONG, StationCandidateIntent


def _has_table(db: Session, table_name: str) -> bool:
    return inspect(db.get_bind()).has_table(table_name)


def _sql_token_variants(values: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value or '').strip().lower().replace('_', ' ')
        for variant in (token, token.replace('-', ' '), token.replace(' ', '-')):
            variant = variant.strip()
            if variant and variant not in seen:
                seen.add(variant)
                out.append(variant)
    return tuple(out)


def _norm_sql(expression: str) -> str:
    return f"lower(replace(replace(trim(coalesce({expression}, '')), '_', ' '), '-', ' '))"


def _exists_track_profile(tokens_name: str) -> str:
    return f"exists (select 1 from track_radio_profiles trp where trp.track_id = t.id and {_norm_sql('trp.primary_genre')} in :{tokens_name})"


def _exists_artist_profile(tokens_name: str) -> str:
    track_artist = _norm_sql('t.artist')
    track_album_artist = _norm_sql('t.album_artist')
    return (
        "exists (select 1 from artist_radio_profiles arp "
        f"where {_norm_sql('arp.primary_genre')} in :{tokens_name} "
        f"and ({_norm_sql('arp.artist')} = {track_artist} or {_norm_sql('arp.artist')} = {track_album_artist}))"
    )


def _exists_album_profile(tokens_name: str) -> str:
    track_artist = _norm_sql('t.artist')
    track_album_artist = _norm_sql('t.album_artist')
    return (
        "exists (select 1 from album_radio_profiles alp "
        f"where {_norm_sql('alp.primary_genre')} in :{tokens_name} "
        f"and {_norm_sql('alp.album')} = {_norm_sql('t.album')} "
        f"and ({_norm_sql('alp.artist')} = {track_artist} or {_norm_sql('alp.artist')} = {track_album_artist}))"
    )


def _genre_match_sql(db: Session, tokens_name: str) -> str:
    clauses = [
        f"{_norm_sql('t.genre')} in :{tokens_name}",
        f"{_norm_sql('t.primary_genre')} in :{tokens_name}",
    ]
    if _has_table(db, 'track_radio_profiles'):
        clauses.append(_exists_track_profile(tokens_name))
    if _has_table(db, 'artist_radio_profiles'):
        clauses.append(_exists_artist_profile(tokens_name))
    if _has_table(db, 'album_radio_profiles'):
        clauses.append(_exists_album_profile(tokens_name))
    return '(' + ' or '.join(clauses) + ')'


def select_unified_intent_station_recording_ids(
    db: Session,
    *,
    limit: int,
    excluded_recording_ids: set[int] | None,
    intent: StationCandidateIntent,
) -> tuple[list[int], dict[str, Any]]:
    bounded = max(1, int(limit))
    excluded = tuple(sorted({int(value) for value in (excluded_recording_ids or set()) if value is not None})) or (-1,)
    seed_tokens = _sql_token_variants(intent.seed_artist_tokens)
    related_tokens = _sql_token_variants(intent.related_artist_tokens)
    exact_tokens = _sql_token_variants(intent.exact_genre_tokens)
    family_tokens = _sql_token_variants(intent.family_genre_tokens)

    if intent.mode not in {INTENT_SONG, INTENT_ARTIST, INTENT_GENRE}:
        return [], intent.debug_summary(total=0)

    seed_limit = int(intent.bucket_limits.get('seed_artist', 0) or 0)
    related_limit = int(intent.bucket_limits.get('related_artists', 0) or 0)
    exact_limit = int(intent.bucket_limits.get('exact_genre', bounded) or bounded)
    family_limit = int(intent.bucket_limits.get('genre_family', bounded) or bounded)
    global_limit = int(intent.bucket_limits.get('global_fallback', bounded) or bounded)

    artist_seed_match = f"({_norm_sql('t.artist')} in :seed_tokens or {_norm_sql('t.album_artist')} in :seed_tokens)"
    artist_related_match = f"({_norm_sql('t.artist')} in :related_tokens or {_norm_sql('t.album_artist')} in :related_tokens)"
    exact_match = _genre_match_sql(db, 'exact_tokens')
    family_match = _genre_match_sql(db, 'family_tokens')

    seed_bucket_condition = 'seed_artist_match = 1' if seed_tokens else '1 = 1'
    related_bucket_condition = 'related_artist_match = 1' if related_tokens else '1 = 1'
    exact_bucket_condition = 'exact_genre_match = 1' if exact_tokens else '1 = 1'
    family_bucket_condition = 'family_genre_match = 1' if family_tokens else '1 = 1'
    seed_order = ('seed_first_seen', 'seed_stable_track_id') if seed_tokens else ('first_seen', 'stable_track_id')
    related_order = ('related_first_seen', 'related_stable_track_id') if related_tokens else ('first_seen', 'stable_track_id')
    exact_order = ('exact_first_seen', 'exact_stable_track_id') if exact_tokens else ('first_seen', 'stable_track_id')
    family_order = ('family_first_seen', 'family_stable_track_id') if family_tokens else ('first_seen', 'stable_track_id')

    if intent.mode in {INTENT_SONG, INTENT_ARTIST}:
        bucket_selects = [
            f"select recording_id, 1 as tier, row_number() over (order by {seed_order[0]} desc, {seed_order[1]} asc) as bucket_row_number from candidate_facts where {seed_bucket_condition}",
            f"select recording_id, 2 as tier, row_number() over (order by {related_order[0]} desc, {related_order[1]} asc) as bucket_row_number from candidate_facts where {related_bucket_condition}",
            f"select recording_id, 3 as tier, row_number() over (order by {exact_order[0]} desc, {exact_order[1]} asc) as bucket_row_number from candidate_facts where {exact_bucket_condition}",
            f"select recording_id, 4 as tier, row_number() over (order by {family_order[0]} desc, {family_order[1]} asc) as bucket_row_number from candidate_facts where {family_bucket_condition}",
            "select recording_id, 5 as tier, row_number() over (order by first_seen desc, stable_track_id asc) as bucket_row_number from candidate_facts",
        ]
        bucket_names = {1: 'seed_artist', 2: 'related_artists', 3: 'exact_genre', 4: 'genre_family', 5: 'global_fallback'}
        bucket_raw_limits = {1: seed_limit, 2: related_limit, 3: exact_limit, 4: family_limit, 5: global_limit}
    else:
        bucket_selects = [
            f"select recording_id, 1 as tier, row_number() over (order by {exact_order[0]} desc, {exact_order[1]} asc) as bucket_row_number from candidate_facts where {exact_bucket_condition}",
            f"select recording_id, 2 as tier, row_number() over (order by {family_order[0]} desc, {family_order[1]} asc) as bucket_row_number from candidate_facts where {family_bucket_condition}",
            "select recording_id, 3 as tier, row_number() over (order by first_seen desc, stable_track_id asc) as bucket_row_number from candidate_facts",
        ]
        bucket_names = {1: 'exact_genre', 2: 'genre_family', 3: 'global_fallback'}
        bucket_raw_limits = {1: exact_limit, 2: family_limit, 3: global_limit}

    bucket_sql = '\nunion all\n'.join(bucket_selects)
    sql = f"""
with candidate_facts as (
    select
        mti.recording_id as recording_id,
        min(t.created_at) as first_seen,
        min(t.id) as stable_track_id,
        min(case when :has_seed_tokens = 1 and {artist_seed_match} then t.created_at end) as seed_first_seen,
        min(case when :has_seed_tokens = 1 and {artist_seed_match} then t.id end) as seed_stable_track_id,
        min(case when :has_related_tokens = 1 and {artist_related_match} then t.created_at end) as related_first_seen,
        min(case when :has_related_tokens = 1 and {artist_related_match} then t.id end) as related_stable_track_id,
        min(case when :has_exact_tokens = 1 and {exact_match} then t.created_at end) as exact_first_seen,
        min(case when :has_exact_tokens = 1 and {exact_match} then t.id end) as exact_stable_track_id,
        min(case when :has_family_tokens = 1 and {family_match} then t.created_at end) as family_first_seen,
        min(case when :has_family_tokens = 1 and {family_match} then t.id end) as family_stable_track_id,
        max(case when :has_seed_tokens = 1 and {artist_seed_match} then 1 else 0 end) as seed_artist_match,
        max(case when :has_related_tokens = 1 and {artist_related_match} then 1 else 0 end) as related_artist_match,
        max(case when :has_exact_tokens = 1 and {exact_match} then 1 else 0 end) as exact_genre_match,
        max(case when :has_family_tokens = 1 and {family_match} then 1 else 0 end) as family_genre_match
    from music_track_identities mti
    join tracks t on t.id = mti.track_id
    left join music_recording_participation mrp on mrp.recording_id = mti.recording_id
    where t.library_availability = 'available'
      and (mrp.id is null or mrp.participation_state = 'included')
      and mti.recording_id not in :excluded_recording_ids
    group by mti.recording_id
), bucketed as (
    {bucket_sql}
), reserved as (
    select recording_id, tier, bucket_row_number
    from bucketed
    where bucket_row_number <= :bounded
)
select recording_id, tier
from reserved
order by tier asc, bucket_row_number asc
"""
    stmt = text(sql).bindparams(
        bindparam('excluded_recording_ids', expanding=True),
        bindparam('seed_tokens', expanding=True),
        bindparam('related_tokens', expanding=True),
        bindparam('exact_tokens', expanding=True),
        bindparam('family_tokens', expanding=True),
    )
    params = {
        'bounded': bounded,
        'excluded_recording_ids': excluded,
        'seed_tokens': seed_tokens or ('__bm_no_seed__',),
        'related_tokens': related_tokens or ('__bm_no_related__',),
        'exact_tokens': exact_tokens or ('__bm_no_exact__',),
        'family_tokens': family_tokens or ('__bm_no_family__',),
        'has_seed_tokens': 1 if seed_tokens else 0,
        'has_related_tokens': 1 if related_tokens else 0,
        'has_exact_tokens': 1 if exact_tokens else 0,
        'has_family_tokens': 1 if family_tokens else 0,
        'seed_limit': max(0, min(seed_limit, bounded)),
        'related_limit': max(0, min(related_limit, bounded)),
        'exact_limit': max(0, min(exact_limit, bounded)),
        'family_limit': max(0, min(family_limit, bounded)),
        'global_limit': max(0, min(global_limit, bounded)),
    }
    rows = db.execute(stmt, params).mappings().all()
    recording_ids: list[int] = []
    selected: set[int] = set()
    bucket_counts: dict[str, int] = {}
    duplicates_removed = 0
    current_tier: int | None = None
    current_tier_quota = 0
    current_tier_added = 0
    for row in rows:
        tier = int(row['tier'])
        if tier != current_tier:
            current_tier = tier
            current_tier_added = 0
            current_tier_quota = max(0, min(int(bucket_raw_limits.get(tier, bounded) or bounded), bounded - len(recording_ids)))
            if current_tier_quota <= 0:
                bucket_counts.setdefault(bucket_names.get(tier, 'global_fallback'), 0)
        if current_tier_added >= current_tier_quota:
            continue
        recording_id = int(row['recording_id'])
        if recording_id in selected:
            duplicates_removed += 1
            continue
        selected.add(recording_id)
        recording_ids.append(recording_id)
        current_tier_added += 1
        name = bucket_names.get(tier, 'global_fallback')
        bucket_counts[name] = bucket_counts.get(name, 0) + 1
        if len(recording_ids) >= bounded:
            break
    metrics = intent.debug_summary(bucket_counts=bucket_counts, duplicates_removed=duplicates_removed, total=len(recording_ids))
    metrics['bucket_query_count'] = 1
    metrics['projection_query_count'] = 1
    metrics['selector_policy'] = 'unified_experimental'
    metrics['unified_projection'] = True
    return recording_ids, metrics
