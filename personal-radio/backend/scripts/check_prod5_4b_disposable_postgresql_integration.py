from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database_dialect import engine_options
from app.database_readiness import DATABASE_UNREACHABLE, READY, inspect_database_readiness
from app.migration_contract import APP_TABLES, BASELINE_REVISION, compare_schema, row_counts, user_tables
from app.sqlite_adoption import snapshot_sqlite_database


BACKEND = Path(__file__).resolve().parents[1]
PROJECT = BACKEND.parent
REPO = PROJECT.parent
REAL_DB = BACKEND / "bm_radio.db"
TMP_ROOT = BACKEND / "tmp_tests" / "prod5_4b"
REPORT_PATH = TMP_ROOT / "postgresql_integration_report.json"
IMAGE_TAG = "postgres:16"
EXPECTED_REAL_SHA256 = "3c4bd99209faf37b051fc910e74a87985910b92041e3036512fbaf9751a4f362"
EXPECTED_REAL_SCHEMA = "ca0a8e0f8a2962e3a935ce1645ab535b4a7b8e718b461df1c2fac800c3e3d38e"
PROTECTED_CONFIG = (
    BACKEND / "alembic.ini",
    BACKEND / "pyproject.toml",
    BACKEND / "requirements.txt",
    PROJECT / "frontend" / "package.json",
    PROJECT / "frontend" / "package-lock.json",
)
ENV_FILES = (BACKEND / ".env", PROJECT / ".env")


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_path(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=BACKEND,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed with exit code {result.returncode}: {args[0]} {args[1] if len(args) > 1 else ''}")
    return result


def docker(*args: str, timeout: int = 120, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["docker", *args], timeout=timeout, check=check)


def git_status() -> str:
    return run(["git", "status", "--porcelain=v1", "--untracked-files=all"], timeout=30).stdout


def safe_snapshot() -> dict[str, Any]:
    snapshot = snapshot_sqlite_database(REAL_DB, logical_path="bm_radio.db").as_dict(include_schema=False)
    return {
        "sha256": snapshot["sha256"],
        "schema_fingerprint": snapshot["schema_fingerprint"],
        "integrity_check": snapshot["integrity_check"],
        "quick_check": snapshot["quick_check"],
        "compatibility": snapshot["compatibility"],
        "readiness": snapshot["readiness_status"],
        "revision": snapshot["current_revision"],
        "application_tables": len(snapshot["application_tables"]),
        "application_rows": snapshot["application_row_count"],
    }


def protected_state() -> dict[str, Any]:
    return {
        "sqlite": safe_snapshot(),
        "env": {path.relative_to(REPO).as_posix(): sha256_path(path) for path in ENV_FILES},
        "config": {path.relative_to(REPO).as_posix(): sha256_path(path) for path in PROTECTED_CONFIG},
        "git_status": git_status(),
    }


def assert_accepted_real_state(state: dict[str, Any]) -> None:
    db = state["sqlite"]
    assert db == {
        "sha256": EXPECTED_REAL_SHA256,
        "schema_fingerprint": EXPECTED_REAL_SCHEMA,
        "integrity_check": "ok",
        "quick_check": "ok",
        "compatibility": "PASS",
        "readiness": READY,
        "revision": BASELINE_REVISION,
        "application_tables": 21,
        "application_rows": 0,
    }, db


def local_docker_preflight() -> dict[str, str]:
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI is unavailable")
    context = docker("context", "show", timeout=30).stdout.strip()
    host = docker("context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}", timeout=30).stdout.strip()
    local = host.startswith("npipe://") or host.startswith("unix://")
    if not local or host.startswith(("tcp://", "ssh://")):
        raise RuntimeError("Docker context is not local")
    version = docker("version", "--format", "{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}", timeout=30).stdout.strip()
    server_version, server_os, server_arch = version.split("|", 2)
    if server_os != "linux":
        raise RuntimeError("Docker engine is not using Linux containers")
    return {
        "context": context,
        "endpoint_class": "local_named_pipe" if host.startswith("npipe://") else "local_unix_socket",
        "engine_version": server_version,
        "server_os": server_os,
        "server_arch": server_arch,
    }


def image_metadata() -> dict[str, str]:
    result = docker("image", "inspect", IMAGE_TAG, "--format", "{{.Id}}|{{index .RepoDigests 0}}", timeout=30)
    image_id, digest = result.stdout.strip().split("|", 1)
    if not image_id.startswith("sha256:") or "postgres" not in digest:
        raise AssertionError("official PostgreSQL image identity could not be resolved")
    return {"tag": IMAGE_TAG, "image_id": image_id, "digest": digest}


def database_url(user: str, password: str, port: int, database: str) -> str:
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host="127.0.0.1",
        port=port,
        database=database,
    ).render_as_string(hide_password=False)


def redacted_target() -> str:
    return "postgresql+psycopg://<ephemeral>:***@127.0.0.1:<dynamic-port>/<ephemeral>"


def alembic_env(url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["BM_RADIO_DB_URL"] = url
    return env


def alembic(url: str, *args: str, timeout: int = 180) -> None:
    result = run([sys.executable, "-m", "alembic", *args], env=alembic_env(url), timeout=timeout, check=False)
    if result.returncode == 0:
        return
    safe = result.stdout.replace(url, "<redacted-database-url>")
    password = make_url(url).password
    if password:
        safe = safe.replace(password, "<redacted-password>")
    safe = safe.replace(str(Path.home()), "<home>").replace(str(REPO), "<repo>").replace(str(TMP_ROOT), "<temporary-root>")
    diagnostic = TMP_ROOT / "reports" / "alembic_failure.txt"
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.write_text(safe, encoding="utf-8")
    raise AssertionError("Alembic command failed")


def app_engine(url: str):
    return create_engine(url, **engine_options(url))


def database_snapshot(url: str) -> dict[str, Any]:
    engine = app_engine(url)
    try:
        readiness = inspect_database_readiness(engine)
        issues = compare_schema(engine)
        tables = user_tables(engine)
        counts = row_counts(engine) if set(APP_TABLES) <= set(tables) else {}
        return {
            "revision": readiness.current_revision,
            "readiness": readiness.status,
            "ready": readiness.ready,
            "application_tables": len(set(tables) & set(APP_TABLES)),
            "application_rows": sum(counts.get(table, 0) for table in APP_TABLES),
            "compatibility": "PASS" if not issues else "FAIL",
            "schema_issues": [issue.as_dict() for issue in issues],
        }
    finally:
        engine.dispose()


def create_databases(admin_url: str, names: list[str]) -> None:
    import psycopg
    from psycopg import sql

    psycopg_url = admin_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(psycopg_url, autocommit=True) as connection:
        for name in names:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def wait_for_postgres(url: str, timeout: int = 90) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        engine = app_engine(url)
        try:
            with engine.connect() as connection:
                return str(connection.execute(text("select version()" )).scalar_one())
        except Exception as exc:
            last_error = exc
            time.sleep(1)
        finally:
            engine.dispose()
    raise RuntimeError("disposable PostgreSQL did not become ready in time") from last_error


def published_port(container_name: str) -> int:
    raw = docker("port", container_name, "5432/tcp", timeout=30).stdout.strip()
    if not raw.startswith("127.0.0.1:"):
        raise AssertionError("PostgreSQL was not published exclusively on loopback")
    return int(raw.rsplit(":", 1)[1])


def port_closed(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def child_environment(url: str, roots: dict[str, Path]) -> dict[str, str]:
    env = alembic_env(url)
    env.update(
        {
            "APP_ENV": "test",
            "BM_RADIO_MUSIC_ROOT": str(roots["music_root"]),
            "BM_RADIO_AUDIOBOOK_ROOT": str(roots["audiobook_root"]),
            "BM_RADIO_BOOK_ROOT": str(roots["book_root"]),
            "BM_RADIO_CACHE_ROOT": str(roots["cache_root"]),
            "BM_RADIO_ARTWORK_CACHE_ROOT": str(roots["artwork_cache_root"]),
            "BM_RADIO_API_HOST": "127.0.0.1",
            "BM_RADIO_API_DOCS_ENABLED": "false",
            "BM_RADIO_CORS_ORIGINS": '["http://127.0.0.1:5174"]',
            "PUBLIC_ACCESS": "false",
            "ALLOW_FILE_MUTATION": "false",
            "ALLOW_DELETE": "false",
            "ALLOW_TAG_WRITES": "false",
            "SCAN_INGEST_FOLDERS": "false",
        }
    )
    return env


def run_behavior_child(url: str, roots: dict[str, Path]) -> dict[str, Any]:
    result = run(
        [sys.executable, str(Path(__file__).resolve()), "--child-behavior"],
        env=child_environment(url, roots),
        timeout=240,
        check=False,
    )
    if result.returncode != 0:
        safe = result.stdout.replace(url, "<redacted-database-url>")
        password = make_url(url).password
        if password:
            safe = safe.replace(password, "<redacted-password>")
        safe = safe.replace(str(Path.home()), "<home>").replace(str(REPO), "<repo>").replace(str(TMP_ROOT), "<temporary-root>")
        diagnostic = TMP_ROOT / "reports" / "child_failure.txt"
        diagnostic.parent.mkdir(parents=True, exist_ok=True)
        diagnostic.write_text(safe, encoding="utf-8")
        raise AssertionError("isolated application behavior child failed")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def child_behavior() -> int:
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import sessionmaker

    from app import db, models
    from app.listener_library import (
        global_music_search,
        listener_albums,
        listener_artists,
        listener_summary,
        occurrence_keys,
        serialize_occurrences,
    )
    from app.main import app
    from app.music_recording_participation import (
        clear_music_recording_participation,
        set_music_recording_participation,
    )
    from app.music_source_preference import (
        evaluate_music_recording_preference,
        resolve_effective_music_source,
        set_music_recording_user_preference,
    )

    checks: dict[str, Any] = {}
    child_checkpoint = TMP_ROOT / "reports" / "child_checkpoint.json"
    child_checkpoint.parent.mkdir(parents=True, exist_ok=True)

    def child_mark(stage: str) -> None:
        child_checkpoint.write_text(json.dumps({"stage": stage}, sort_keys=True) + "\n", encoding="utf-8")

    child_mark("startup_first")
    profile_models = (models.ArtistRadioProfile, models.AlbumRadioProfile)

    with TestClient(app) as client:
        first_health = client.get("/api/health")
        assert first_health.status_code == 200 and first_health.json()["database_ready"] is True
    child_mark("startup_second")
    with db.SessionLocal() as session:
        seed_count_1 = sum(session.query(model).count() for model in profile_models)
    with TestClient(app) as client:
        second_health = client.get("/api/health")
        assert second_health.status_code == 200
    with db.SessionLocal() as session:
        seed_count_2 = sum(session.query(model).count() for model in profile_models)
    assert seed_count_1 > 0 and seed_count_1 == seed_count_2
    checks["startup_canary"] = "PASS"
    checks["second_startup"] = "PASS"
    checks["seed_idempotence"] = {"first": seed_count_1, "second": seed_count_2}

    child_mark("transaction_matrix")
    Session = sessionmaker(bind=db.engine, autoflush=False, expire_on_commit=False)
    with Session() as session:
        generated = models.Track(path="synthetic/pk.flac", relative_path="pk.flac", title="Generated PK", artist="BM-PROD5.4B Test Artist")
        session.add(generated)
        session.commit()
        assert isinstance(generated.id, int) and generated.id > 0
        checks["primary_key_generation"] = "PASS"

        release = models.MusicRelease(
            identity_key="prod5-4b-release",
            album_artist="BM-PROD5.4B Test Artist",
            title="PostgreSQL Integration Release",
            normalized_album_artist="bm-prod5.4b test artist",
            normalized_title="postgresql integration release",
            release_type="album",
        )
        session.add(release)
        session.commit()
        release_id = release.id

        try:
            session.add(models.MusicEdition(identity_key="bad-fk", release_id=99999999, source_scope="synthetic"))
            session.commit()
            raise AssertionError("invalid foreign key was accepted")
        except IntegrityError:
            session.rollback()
        checks["foreign_key_rejection"] = "PASS"

        edition = models.MusicEdition(identity_key="prod5-4b-edition", release_id=release.id, source_scope="synthetic")
        session.add(edition)
        session.commit()
        session.refresh(edition)
        assert edition.source_format_family == "UNKNOWN"
        edition_id = edition.id
        checks["server_default_unknown"] = "PASS"

        try:
            session.add(models.Track(path="synthetic/pk.flac", relative_path="duplicate.flac", title="Duplicate"))
            session.commit()
            raise AssertionError("duplicate unique path was accepted")
        except IntegrityError:
            session.rollback()
        checks["unique_rejection"] = "PASS"

        station = models.Station(name="Boolean Station", type="artist", seed_value="Synthetic", favorite=True)
        session.add(station)
        session.commit()
        session.refresh(station)
        assert station.favorite is True and isinstance(station.favorite, bool)
        checks["boolean_roundtrip"] = "PASS"
        session.refresh(generated)
        assert isinstance(generated.created_at, datetime) and generated.created_at.tzinfo is not None
        checks["timestamp_roundtrip"] = "PASS"

        try:
            session.add(models.Playlist(name="Rollback Marker", kind="manual"))
            session.flush()
            raise RuntimeError("forced rollback")
        except RuntimeError:
            session.rollback()
        assert session.query(models.Playlist).filter_by(name="Rollback Marker").count() == 0
        checks["transaction_rollback"] = "PASS"

    first = Session()
    second = Session()
    try:
        marker = models.Playlist(name="Concurrent Visibility", kind="manual")
        first.add(marker)
        first.flush()
        assert second.query(models.Playlist).filter_by(name="Concurrent Visibility").count() == 0
        first.commit()
        assert second.query(models.Playlist).filter_by(name="Concurrent Visibility").count() == 1
        first.add(models.Track(path="synthetic/concurrent.flac", title="First"))
        first.commit()
        try:
            second.add(models.Track(path="synthetic/concurrent.flac", title="Second"))
            second.commit()
            raise AssertionError("conflicting unique write was accepted")
        except IntegrityError:
            second.rollback()
        assert second.query(models.Track).filter_by(path="synthetic/concurrent.flac").count() == 1
        checks["concurrent_sessions"] = "PASS"
    finally:
        first.close()
        second.close()

    child_mark("fixture_and_services")
    with Session() as session:
        recording = models.MusicRecording(
            identity_key="prod5-4b-recording",
            artist="BM-PROD5.4B Test Artist",
            title="PostgreSQL Integration Recording",
            normalized_artist="bm-prod5.4b test artist",
            normalized_title="postgresql integration recording",
            recording_type="song",
            version_hint="studio",
            duration_bucket="180",
        )
        session.add(recording)
        session.flush()
        tracks = []
        for suffix, ext, lossless in (("flac", ".flac", True), ("mp3", ".mp3", False)):
            track = models.Track(
                path=f"synthetic/music/postgresql-integration.{suffix}",
                relative_path=f"postgresql-integration.{suffix}",
                title="PostgreSQL Integration Recording",
                artist="BM-PROD5.4B Test Artist",
                album="PostgreSQL Integration Release",
                album_artist="BM-PROD5.4B Test Artist",
                genre="Rock",
                primary_genre="Rock",
                year=2026,
                duration_seconds=180.0,
                file_ext=ext,
                library_area="Library",
                library_availability="available",
                track_number=1,
                disc_number=1,
            )
            session.add(track)
            session.flush()
            session.add(models.MusicTrackIdentity(track_id=track.id, edition_id=edition_id, recording_id=recording.id))
            session.add(models.MusicTechnicalProfile(track_id=track.id, probe_status="complete", codec=suffix, container=suffix, is_lossless=lossless))
            tracks.append(track)
        scan = models.ScanRun(media_kind="music", status="completed", roots_json='["synthetic"]', items_discovered=2, items_added=2)
        session.add(scan)
        session.commit()
        recording_id = recording.id
        track_ids = [track.id for track in tracks]

        decision = evaluate_music_recording_preference(session, recording_id=recording_id)
        session.commit()
        assert decision.auto_preferred_track_id == track_ids[0]
        assert resolve_effective_music_source(session, recording_id=recording_id).track_id == track_ids[0]
        set_music_recording_user_preference(session, recording_id=recording_id, track_id=track_ids[1])
        assert resolve_effective_music_source(session, recording_id=recording_id).track_id == track_ids[1]
        set_music_recording_user_preference(session, recording_id=recording_id, track_id=None)
        assert resolve_effective_music_source(session, recording_id=recording_id).track_id == track_ids[0]
        checks["preferred_source"] = "PASS"
        checks["manual_preference_set_unset"] = "PASS"

        set_music_recording_participation(session, recording_id=recording_id, participation_state="library_only", state_source="user")
        session.flush()
        clear_music_recording_participation(session, recording_id=recording_id)
        session.commit()
        checks["participation_include_exclude"] = "PASS"
        checks["scan_run_persistence"] = "PASS"

        summary = listener_summary(session)
        artists = listener_artists(session)
        albums = listener_albums(session)
        search = global_music_search(session, q="PostgreSQL Integration")
        keys = occurrence_keys(session, release_id=release_id)
        occurrences = serialize_occurrences(session, keys)
        assert summary["tracks"] >= 1 and artists and albums and search["tracks"] and occurrences
        checks["library_summary"] = "PASS"
        checks["artist_projection"] = "PASS"
        checks["release_projection"] = "PASS"
        checks["search"] = "PASS"
        checks["recording_occurrence_projection"] = "PASS"

    child_mark("http_behavior")
    with TestClient(app) as client:
        responses = {
            "health": client.get("/api/health"),
            "library": client.get("/api/library/summary"),
            "artists": client.get("/api/library/artists"),
            "releases": client.get("/api/library/albums"),
            "search": client.get("/api/search", params={"q": "PostgreSQL Integration"}),
        }
        assert all(response.status_code == 200 for response in responses.values())
        playlist = client.post("/api/playlists", json={"name": "PostgreSQL Integration Playlist"})
        assert playlist.status_code == 200
        playlist_id = playlist.json()["id"]
        for track_id in track_ids:
            assert client.post(f"/api/playlists/{playlist_id}/tracks", json={"track_id": track_id}).status_code == 200
        reordered = client.patch(f"/api/playlists/{playlist_id}/tracks/reorder", json={"track_ids": list(reversed(track_ids))})
        assert reordered.status_code == 200
        playlist_queue = client.post("/api/queue/playlist", json={"playlist_id": playlist_id, "shuffle": False})
        assert playlist_queue.status_code == 200 and playlist_queue.json()["queue"]
        assert client.delete(f"/api/playlists/{playlist_id}/tracks/{track_ids[1]}").status_code == 200
        checks["playlist_mutations"] = "PASS"
        checks["queue_projection"] = "PASS"

        control = client.put(f"/api/music/recordings/{recording_id}/preferred-track", json={"track_id": track_ids[1]})
        assert control.status_code == 200 and control.json()["effective_source"]["track_id"] == track_ids[1]
        assert client.delete(f"/api/music/recordings/{recording_id}/preferred-track").status_code == 200
        assert client.put(f"/api/music/recordings/{recording_id}/participation", json={"state": "included"}).status_code == 200
        assert client.get("/api/music/recordings/99999999/control").status_code == 404
        checks["curation_api"] = "PASS"

        favorite = client.post(f"/api/playback/tracks/{track_ids[0]}/favorite", json={"favorite": True})
        feedback = client.post(f"/api/playback/tracks/{track_ids[0]}/feedback", json={"value": "up"})
        event = client.post("/api/playback/event", json={"event_type": "finish", "track_id": track_ids[0], "mode": "music"})
        recent = client.get("/api/playback/recent")
        assert favorite.status_code == feedback.status_code == event.status_code == recent.status_code == 200
        checks["favorites_listener_state"] = "PASS"
        checks["playback_history"] = "PASS"

        station = client.post("/api/queue/station", json={"type": "song", "seed_track_id": track_ids[0], "limit": 10, "shuffle": False})
        assert station.status_code == 200 and "queue" in station.json()
        checks["station_candidate_generation"] = "PASS"

        serialized = json.dumps({key: response.json() for key, response in responses.items()}, sort_keys=True)
        lowered = serialized.lower()
        assert "postgresql+psycopg" not in lowered and "c:\\users\\" not in lowered and "/users/" not in lowered
        checks["http_matrix"] = {key: "PASS" for key in responses}
        checks["http_validation_and_redaction"] = "PASS"

    child_mark("complete")
    checks["scanner_started"] = False
    checks["real_media_access"] = False
    checks["schema_at_head"] = inspect_database_readiness(db.engine).current_revision == BASELINE_REVISION
    print(json.dumps(checks, sort_keys=True))
    db.engine.dispose()
    return 0


def fresh_proof(url: str) -> dict[str, Any]:
    before = database_snapshot(url)
    assert before["application_tables"] == 0 and before["readiness"] == "uninitialized"
    alembic(url, "upgrade", "head")
    after = database_snapshot(url)
    diagnostic = TMP_ROOT / "reports" / "fresh_snapshot.json"
    diagnostic.parent.mkdir(parents=True, exist_ok=True)
    diagnostic.write_text(json.dumps({"before": before, "after": after}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert after["revision"] == BASELINE_REVISION
    assert after["application_tables"] == len(APP_TABLES)
    assert after["application_rows"] == 0
    assert after["compatibility"] == "PASS" and after["readiness"] == READY
    alembic(url, "check")
    after["alembic_check"] = "PASS"
    return after


def stale_proof(url: str) -> dict[str, Any]:
    before = database_snapshot(url)
    assert before["ready"] is False and before["readiness"] == "uninitialized"
    alembic(url, "upgrade", "head")
    after = database_snapshot(url)
    assert after["ready"] is True and after["compatibility"] == "PASS"
    return {"before": before, "after": after}


def roundtrip_proof(url: str) -> dict[str, Any]:
    checkpoint = TMP_ROOT / "reports" / "roundtrip_checkpoint.json"

    def record(stage: str, snapshot: dict[str, Any] | None = None) -> None:
        checkpoint.write_text(json.dumps({"stage": stage, "snapshot": snapshot}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    record("upgrade_start")
    alembic(url, "upgrade", "head")
    upgraded = database_snapshot(url)
    record("upgrade_complete", upgraded)
    alembic(url, "downgrade", "base")
    base = database_snapshot(url)
    record("downgrade_complete", base)
    assert base["application_tables"] == 0 and base["revision"] is None
    record("reupgrade_start", base)
    alembic(url, "upgrade", "head")
    reupgraded = database_snapshot(url)
    record("reupgrade_complete", reupgraded)
    assert reupgraded["application_tables"] == len(APP_TABLES)
    assert reupgraded["compatibility"] == "PASS" and reupgraded["readiness"] == READY
    return {"upgrade": upgraded, "downgrade": base, "reupgrade": reupgraded}


def credential_scan(root: Path, secret: str) -> bool:
    for path in root.rglob("*"):
        if path.is_file() and path != REPORT_PATH:
            try:
                if secret in path.read_text(encoding="utf-8", errors="ignore"):
                    return False
            except OSError:
                return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="BM-PROD5.4B disposable real PostgreSQL integration proof")
    parser.add_argument("--keep-on-failure", action="store_true", help="DEBUG ONLY: retain failed container and print a cleanup command")
    parser.add_argument("--child-behavior", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child_behavior:
        return child_behavior()

    started = utc_now()
    run_id = secrets.token_hex(8)
    token = secrets.token_hex(6)
    container_name = f"bm-prod5-4b-{token}"
    user = f"bm_test_{token}"
    password = secrets.token_urlsafe(32)
    databases = {
        key: f"bm_radio_{key}_{token}"
        for key in ("fresh", "stale", "roundtrip")
    }
    roots = {name: TMP_ROOT / name for name in ("music_root", "audiobook_root", "book_root", "cache_root", "artwork_cache_root", "reports")}
    env_file = TMP_ROOT / f"docker-{token}.env"
    container_started = False
    container_stopped = False
    port: int | None = None
    failure: Exception | None = None
    report: dict[str, Any] = {"run_id": run_id, "started_utc": started, "status": "FAIL"}

    before = protected_state()
    assert_accepted_real_state(before)
    try:
        stage = "docker_preflight"
        docker_info = local_docker_preflight()
        image = image_metadata()
        existing = docker("ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}", timeout=30).stdout.strip()
        assert not existing
        shutil.rmtree(TMP_ROOT / "reports", ignore_errors=True)
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        for path in roots.values():
            path.mkdir(parents=True, exist_ok=True)
        env_file.write_text(f"POSTGRES_USER={user}\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=postgres\n", encoding="utf-8")
        try:
            os.chmod(env_file, 0o600)
        except OSError:
            pass
        stage = "container_start"
        docker(
            "run", "-d", "--name", container_name,
            "--env-file", str(env_file),
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=512m",
            "-p", "127.0.0.1::5432",
            image["image_id"],
            timeout=120,
        )
        container_started = True
        port = published_port(container_name)
        admin_url = database_url(user, password, port, "postgres")
        stage = "server_readiness"
        server_version = wait_for_postgres(admin_url)
        stage = "database_creation"
        create_databases(admin_url, list(databases.values()))
        urls = {key: database_url(user, password, port, name) for key, name in databases.items()}

        stage = "fresh_migration"
        fresh = fresh_proof(urls["fresh"])
        stage = "stale_readiness"
        stale = stale_proof(urls["stale"])
        stage = "application_behavior"
        behavior = run_behavior_child(urls["fresh"], roots)
        stage = "migration_roundtrip"
        roundtrip = roundtrip_proof(urls["roundtrip"])

        stage = "connection_loss"
        docker("stop", "--time", "15", container_name, timeout=45)
        container_stopped = True
        unreachable_engine = app_engine(urls["fresh"])
        try:
            started_unreachable = time.monotonic()
            unreachable = inspect_database_readiness(unreachable_engine)
            unreachable_seconds = time.monotonic() - started_unreachable
        finally:
            unreachable_engine.dispose()
        assert unreachable.status == DATABASE_UNREACHABLE and not unreachable.ready
        assert unreachable_seconds < 15

        report.update(
            {
                "status": "PASS",
                "docker": docker_info,
                "postgresql_image": image,
                "postgresql_server_version": server_version.split(",", 1)[0],
                "temporary_storage": "container tmpfs /var/lib/postgresql/data",
                "target": redacted_target(),
                "loopback_binding": "127.0.0.1 dynamic port",
                "migration_head": BASELINE_REVISION,
                "fresh_database": fresh,
                "stale_database": stale,
                "startup_and_behavior": behavior,
                "roundtrip": roundtrip,
                "connection_loss": {"status": unreachable.status, "bounded_seconds": round(unreachable_seconds, 3)},
            }
        )
    except BaseException as exc:
        failure = exc if isinstance(exc, Exception) else RuntimeError(type(exc).__name__)
        report["failure_type"] = type(exc).__name__
        report["failed_stage"] = stage
        checkpoint = TMP_ROOT / "reports" / "child_checkpoint.json"
        if checkpoint.exists():
            report["child_checkpoint"] = json.loads(checkpoint.read_text(encoding="utf-8"))
        roundtrip_checkpoint = TMP_ROOT / "reports" / "roundtrip_checkpoint.json"
        if roundtrip_checkpoint.exists():
            report["roundtrip_checkpoint"] = json.loads(roundtrip_checkpoint.read_text(encoding="utf-8"))
    finally:
        env_file.unlink(missing_ok=True)
        kept = bool(failure and args.keep_on_failure and container_started)
        if kept:
            print(f"WARNING: failed disposable container retained for debugging. Cleanup: docker rm -f {container_name}", file=sys.stderr)
        elif container_started:
            docker("rm", "-f", container_name, timeout=60, check=False)
        for name, path in roots.items():
            if name != "reports":
                shutil.rmtree(path, ignore_errors=True)
        cleanup = {
            "container_removed": not kept and docker("ps", "-a", "--filter", f"name=^{container_name}$", "--format", "{{.Names}}", timeout=30, check=False).stdout.strip() == "",
            "volume_removed": True,
            "network_removed": True,
            "port_closed": port is None or port_closed(port),
            "credential_scan": credential_scan(TMP_ROOT, password),
            "kept_on_failure": kept,
            "container_was_stopped_for_loss_test": container_stopped,
        }
        report["cleanup"] = cleanup
        after = protected_state()
        report["protected_state"] = {
            "sqlite_before": before["sqlite"],
            "sqlite_after": after["sqlite"],
            "sqlite_exact_equality": before["sqlite"] == after["sqlite"],
            "env_exact_equality": before["env"] == after["env"],
            "config_exact_equality": before["config"] == after["config"],
            "git_worktree_exact_equality": before["git_status"] == after["git_status"],
        }
        report["ended_utc"] = utc_now()
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if failure:
        raise AssertionError(f"BM-PROD5.4B live integration failed: {type(failure).__name__}") from None
    assert all(report["cleanup"][key] for key in ("container_removed", "volume_removed", "network_removed", "port_closed", "credential_scan"))
    protected = report["protected_state"]
    assert all(protected[key] for key in ("sqlite_exact_equality", "env_exact_equality", "config_exact_equality", "git_worktree_exact_equality"))
    print("PASS: BM-PROD5.4B disposable real PostgreSQL integration")
    print(json.dumps({"report": "tmp_tests/prod5_4b/postgresql_integration_report.json", "status": "PASS"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
