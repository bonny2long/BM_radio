from __future__ import annotations

import shutil
from pathlib import Path
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.scanner.path_safety import is_approved_path, safe_media_files


def main() -> None:
    base = Path(tempfile.mkdtemp(prefix="bm-safe-roots-"))
    if base.exists():
        shutil.rmtree(base)
    root = base / "Music" / "Library" / "MP3"
    good = root / "Artist" / "Album" / "01 Song.mp3"
    bad_ingest = base / "_INGEST" / "incoming" / "01 Song.mp3"
    bad_quarantine = base / "Music" / "_QUARANTINE" / "01 Song.mp3"
    good.parent.mkdir(parents=True)
    bad_ingest.parent.mkdir(parents=True)
    bad_quarantine.parent.mkdir(parents=True)
    good.write_bytes(b"x")
    bad_ingest.write_bytes(b"x")
    bad_quarantine.write_bytes(b"x")
    roots = [root]
    assert is_approved_path(good, roots)
    assert not is_approved_path(bad_ingest, roots)
    assert not is_approved_path(bad_quarantine, roots)
    found = list(safe_media_files(root, {".mp3"}, roots))
    assert found == [good], found
    shutil.rmtree(base, ignore_errors=True)
    print("ok: BM Radio safe roots")


if __name__ == "__main__":
    main()
