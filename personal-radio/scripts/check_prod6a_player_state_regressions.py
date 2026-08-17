from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile


PROJECT = Path(__file__).resolve().parents[1]
FRONTEND = PROJECT / "frontend"
SOURCE = FRONTEND / "src" / "state" / "playbackInvariants.ts"


def require_tool(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required frontend test tool is unavailable: {name}")
    return resolved


def main() -> int:
    node = require_tool("node")
    tsc = FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"
    if not tsc.is_file():
        raise RuntimeError("frontend dependencies are required; run npm ci first")

    with tempfile.TemporaryDirectory(prefix="bm-prod6a-player-") as raw_temp:
        temp = Path(raw_temp)
        compile_result = subprocess.run(
            [
                node, str(tsc),
                str(SOURCE),
                "--target", "ES2022",
                "--module", "CommonJS",
                "--outDir", str(temp),
                "--skipLibCheck",
                "--ignoreConfig",
            ],
            cwd=str(FRONTEND),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
        )
        assert compile_result.returncode == 0, compile_result.stdout
        compiled = temp / "playbackInvariants.js"
        assertions = r"""
const p = require(process.argv[1]);
const assert = (value, label) => { if (!value) throw new Error(label); };
assert(p.nextQueueIndex(0, 3) === 1, 'next advances exactly once');
assert(p.nextQueueIndex(2, 3) === -1, 'queue end is controlled');
assert(p.previousQueueIndex(2, 3) === 1, 'previous uses prior queue item');
assert(p.previousQueueIndex(0, 3) === -1, 'previous at queue start is safe');
assert(p.nextQueueIndex(-1, 0) === -1, 'empty queue is safe');
const identity = p.playbackIdentity('music', 7);
assert(p.playEventForIdentity(identity, null) === 'start', 'first real play is a start');
assert(p.playEventForIdentity(identity, identity) === 'resume', 'pause/resume is not a duplicate start');
assert(p.shouldAdvanceForEnded(identity, null) === true, 'first ended event advances');
assert(p.shouldAdvanceForEnded(identity, identity) === false, 'duplicate ended event cannot advance twice');
const queue = Object.freeze(['a', 'b', 'c']);
assert(JSON.stringify(p.removeQueueEntry(queue, 1)) === JSON.stringify(['a', 'c']), 'remove works');
assert(JSON.stringify(p.moveQueueEntry(queue, 2, 1)) === JSON.stringify(['a', 'c', 'b']), 'reorder works');
assert(JSON.stringify(queue) === JSON.stringify(['a', 'b', 'c']), 'queue helpers do not mutate input');
assert(p.clampVolume(-1) === 0 && p.clampVolume(2) === 1 && p.clampVolume(.4) === .4, 'volume is bounded');
console.log(JSON.stringify({checks: 13, result: 'PASS'}));
"""
        result = subprocess.run(
            [node, "-e", assertions, str(compiled)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        assert result.returncode == 0, result.stdout
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload == {"checks": 13, "result": "PASS"}, payload

    print("PASS: BM-PROD6A deterministic player-state regressions (13 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
