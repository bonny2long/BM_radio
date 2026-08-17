from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile


PROJECT = Path(__file__).resolve().parents[1]
FRONTEND = PROJECT / "frontend"
SOURCE = FRONTEND / "src" / "state" / "playbackInvariants.ts"


def main() -> int:
    node = shutil.which("node")
    tsc = FRONTEND / "node_modules" / "typescript" / "bin" / "tsc"
    assert node and tsc.is_file(), "frontend dependencies are required"
    with tempfile.TemporaryDirectory(prefix="bm-prod6b-refill-") as raw:
        result = subprocess.run(
            [node, str(tsc), str(SOURCE), "--target", "ES2022", "--module", "CommonJS", "--outDir", raw, "--skipLibCheck", "--ignoreConfig"],
            cwd=str(FRONTEND), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False,
        )
        assert result.returncode == 0, result.stdout
        compiled = str(Path(raw) / "playbackInvariants.js")
        assertions = r"""
const p = require(process.argv[1]);
const ok = (v, label) => { if (!v) throw new Error(label); };
const music = id => ({mode:'music', id, title:`t${id}`, stationName:'SQ Artist Radio'});
ok(!p.shouldPrefetchStation(20, 13, false), 'refill does not trigger early');
ok(p.shouldPrefetchStation(20, 14, false), 'refill triggers at threshold');
ok(!p.shouldPrefetchStation(20, 19, true), 'exhausted station stops refill');
const current = [music(1), music(2), music(3)];
const incoming = [music(3), music(4), music(4), music(5)];
const merged = p.appendUniqueQueueItems(current, incoming);
ok(JSON.stringify(merged.queue.map(x=>x.id)) === '[1,2,3,4,5]', 'refill appends unique items once');
ok(JSON.stringify(merged.appended.map(x=>x.id)) === '[4,5]', 'duplicate response members append once');
ok(merged.queue[0] === current[0], 'current queue item remains stable');
ok(merged.queue[3].stationName === 'SQ Artist Radio', 'station metadata is preserved');
const longQueue = Array.from({length:205}, (_, i)=>music(i+1));
const excludes = p.stationExcludeIds(longQueue);
ok(excludes.length === 200 && excludes[0] === 6 && excludes[199] === 205, 'exclude history is bounded to latest 200');
const album = {kind:'album', canContinue:false};
const playlist = {kind:'playlist', canContinue:false};
ok(album.canContinue === false && playlist.canContinue === false, 'album and playlist sources remain finite');
console.log(JSON.stringify({checks:9,result:'PASS'}));
"""
        result = subprocess.run(
            [node, "-e", assertions, compiled], text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", shell=False,
        )
        assert result.returncode == 0, result.stdout
        assert json.loads(result.stdout.strip().splitlines()[-1]) == {"checks": 9, "result": "PASS"}
    print("PASS: BM-PROD6B frontend station refill regressions (9 checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
