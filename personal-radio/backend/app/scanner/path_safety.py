from pathlib import Path

BLOCKED_PARTS = {"_INGEST", "_STAGING", "_QUARANTINE", "_REPORTS", "_METADATA_RECOVERY"}


def is_approved_path(path: Path, roots: list[Path]) -> bool:
    """Return true only for files within an approved final-library root."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if any(part.upper() in BLOCKED_PARTS for part in resolved.parts):
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def safe_media_files(root: Path, extensions: set[str], approved_roots: list[Path]):
    if not root.is_dir() or not is_approved_path(root, approved_roots):
        return
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions and is_approved_path(path, approved_roots):
            yield path
