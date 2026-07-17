from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .migration_contract import BASELINE_REVISION
from .sqlite_adoption import restore_sqlite_backup, snapshot_sqlite_database

SIDECAR_SUFFIXES = ('-wal', '-shm', '-journal')


@dataclass(frozen=True)
class ReplacementResult:
    archived_database: Path
    archived_sidecars: tuple[Path, ...]
    current_snapshot: dict[str, Any]
    rollback_snapshot: dict[str, Any]


def sqlite_url(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    return f'sqlite:///{path.resolve().as_posix()}'


def sidecar_paths(path: Path) -> tuple[Path, ...]:
    return tuple(path.with_name(path.name + suffix) for suffix in SIDECAR_SUFFIXES)


def existing_sidecars(path: Path) -> tuple[Path, ...]:
    return tuple(sidecar for sidecar in sidecar_paths(path) if sidecar.exists())


def build_fresh_sqlite_database(path: Path, *, backend: Path, timeout: int = 180) -> str:
    if path.exists():
        path.unlink()
    for sidecar in sidecar_paths(path):
        if sidecar.exists():
            sidecar.unlink()
    url = sqlite_url(path)
    result = subprocess.run(
        [sys.executable, '-m', 'alembic', '-x', f'db_url={url}', 'upgrade', 'head'],
        cwd=backend,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AssertionError(f'alembic upgrade head failed for fresh DB:\n{result.stdout}')
    snapshot = snapshot_sqlite_database(path, logical_path=path.name)
    if snapshot.current_revision != BASELINE_REVISION or snapshot.compatibility != 'PASS' or snapshot.readiness_status != 'ready':
        raise AssertionError(snapshot.as_dict(include_schema=False))
    if sum(snapshot.application_row_counts.values()) != 0:
        raise AssertionError(snapshot.as_dict(include_schema=False))
    return url


def copy_sqlite_database(source: Path, destination: Path) -> None:
    restore_sqlite_backup(source, destination)


def archive_database_with_sidecars(current: Path, archive_dir: Path, *, archive_stem: str) -> tuple[Path, tuple[Path, ...]]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_db = archive_dir / f'{archive_stem}.db'
    if archived_db.exists():
        raise FileExistsError(archived_db)
    shutil.move(str(current), str(archived_db))
    archived_sidecars = []
    for sidecar in existing_sidecars(current):
        archived_sidecar = archive_dir / f'{archive_stem}{sidecar.name[len(current.name):]}'
        if archived_sidecar.exists():
            raise FileExistsError(archived_sidecar)
        shutil.move(str(sidecar), str(archived_sidecar))
        archived_sidecars.append(archived_sidecar)
    return archived_db, tuple(archived_sidecars)


def replace_current_with_candidate(current: Path, candidate: Path, archive_dir: Path, *, archive_stem: str) -> tuple[Path, tuple[Path, ...]]:
    if not current.exists():
        raise FileNotFoundError(current)
    if not candidate.exists():
        raise FileNotFoundError(candidate)
    archived_db, archived_sidecars = archive_database_with_sidecars(current, archive_dir, archive_stem=archive_stem)
    os.replace(candidate, current)
    return archived_db, archived_sidecars


def rehearse_replacement_and_rollback(legacy_backup: Path, fresh_candidate: Path, base: Path) -> ReplacementResult:
    work = base / 'replacement_rehearsal'
    archive = work / 'archive'
    work.mkdir(parents=True, exist_ok=True)
    current = work / 'current.db'
    candidate = work / 'current.db.new'
    restore_sqlite_backup(legacy_backup, current)
    restore_sqlite_backup(fresh_candidate, candidate)
    old_snapshot = snapshot_sqlite_database(current, logical_path='current.db')
    fresh_snapshot = snapshot_sqlite_database(candidate, logical_path='current.db.new')
    if fresh_snapshot.compatibility != 'PASS' or fresh_snapshot.readiness_status != 'ready':
        raise AssertionError(fresh_snapshot.as_dict(include_schema=False))
    archived_db, archived_sidecars = replace_current_with_candidate(current, candidate, archive, archive_stem='current.pre_rebuild')
    current_snapshot = snapshot_sqlite_database(current, logical_path='current.db').as_dict(include_schema=False)
    if current_snapshot['compatibility'] != 'PASS' or current_snapshot['readiness_status'] != 'ready':
        raise AssertionError(current_snapshot)
    new_archive = archive / 'current.fresh_rebuild.db'
    shutil.move(str(current), str(new_archive))
    shutil.move(str(archived_db), str(current))
    rollback = snapshot_sqlite_database(current, logical_path='current.db')
    if rollback.schema_fingerprint != old_snapshot.schema_fingerprint or rollback.sha256 != old_snapshot.sha256:
        raise AssertionError({'old': old_snapshot.as_dict(include_schema=False), 'rollback': rollback.as_dict(include_schema=False)})
    return ReplacementResult(
        archived_database=new_archive,
        archived_sidecars=archived_sidecars,
        current_snapshot=current_snapshot,
        rollback_snapshot=rollback.as_dict(include_schema=False),
    )
