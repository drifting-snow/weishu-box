# -*- coding: utf-8 -*-
"""Fetch authoritative Arknights game data tables for per-level stats.

The PRTS wikitext ``{{属性}}`` template only stores four level anchors
(E0 Lv1, E0 max, E1 max, E2 max); it has no growth curve, so the fixed
Guard-Protocol levels (E1 Lv55/60, E2 Lv1/50/55/60) cannot be recovered from
the local wiki cache. The game's unpacked ``character_table.json`` stores
per-elite-phase ``attributesKeyFrames`` (Lv1 and max level), which lets us
linearly interpolate every fixed level exactly the way the client does.
``favor_table.json`` supplies the trust-bonus key frames.

Source repo: Kengxxiao/ArknightsGameData (community-maintained unpacked data).
Served through CDNs that are reachable without a VPN; raw.githubusercontent is
kept only as a last resort because it is often blocked/slow in CN networks.

Stdlib only. Files are cached under data/source/gamedata/ and are git-ignored
(rebuildable), matching the PRTS cache convention.

Usage:
  python tools/fetch_game_data.py --probe            # list targets + sizes
  python tools/fetch_game_data.py                    # download all targets
  python tools/fetch_game_data.py --only character_table
"""
import argparse, io, json, os, sys, time, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST = os.path.join(ROOT, "data", "source", "gamedata")
REPO = "Kengxxiao/ArknightsGameData"
BRANCH = "master"
# Ordered by reachability observed on CN networks (no VPN). fastly first.
CDN_BASES = [
    "https://fastly.jsdelivr.net/gh/%s@%s" % (REPO, BRANCH),
    "https://cdn.jsdelivr.net/gh/%s@%s" % (REPO, BRANCH),
    "https://raw.githubusercontent.com/%s/%s" % (REPO, BRANCH),
]
# repo-relative paths (zh_CN build so the `name` fields are Simplified Chinese).
# character_table already carries each character's favorKeyFrames, so no separate
# favor table is needed.
TARGETS = {
    "character_table": "zh_CN/gamedata/excel/character_table.json",
    # skill levels (blackboard multipliers, duration, sp, heal/damage scaling)
    "skill_table": "zh_CN/gamedata/excel/skill_table.json",
    # enemy raw stats/abilities. NOTE: unlike most excel tables, the enemy
    # database lives under levels/enemydata/ in current unpacked builds (the old
    # excel/enemy_database.json path now 404s).
    "enemy_database": "zh_CN/gamedata/levels/enemydata/enemy_database.json",
    # enemy Simplified-Chinese names + handbook descriptions (small, ~2 MB)
    "enemy_handbook_table": "zh_CN/gamedata/excel/enemy_handbook_table.json",
    # Guard Protocol (autochess) mode config lives inside activity_table:
    # autoChessData + activity.AUTOCHESS_SEASON.act2autochess; large (~15 MB).
    "activity_table": "zh_CN/gamedata/excel/activity_table.json",
}
UA = "weishu-advisor/0.1 (open-source data builder; stdlib only)"
CHUNK = 1024 * 256  # 256 KiB per Range request


def _request(url, headers=None, timeout=30):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    return urllib.request.Request(url, headers=h)


def remote_size(path):
    """Return the byte size via the GitHub contents API (api.github reachable)."""
    api = ("https://api.github.com/repos/%s/contents/%s?ref=%s"
           % (REPO, urllib.request.quote(path), BRANCH))
    with urllib.request.urlopen(_request(api), timeout=30) as r:
        meta = json.load(r)
    return int(meta["size"])


def cdn_urls(path):
    return ["%s/%s" % (base, path) for base in CDN_BASES]


def download(path, dest_path, expected_size=None):
    """Resumable chunked download across CDNs; returns bytes written."""
    have = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    if expected_size and have == expected_size:
        print("  skip (complete): %s (%d bytes)" % (os.path.basename(dest_path), have))
        return have

    last_err = None
    for url in cdn_urls(path):
        start = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
        try:
            headers = {"Range": "bytes=%d-" % start} if start else {}
            with urllib.request.urlopen(_request(url, headers), timeout=45) as r:
                total = r.headers.get("Content-Range")
                # 206 -> resuming; 200 -> server ignored Range, restart from 0
                if r.status == 200 and start:
                    start = 0
                    mode = "wb"
                else:
                    mode = "ab"
                with open(dest_path, mode) as f:
                    while True:
                        buf = r.read(CHUNK)
                        if not buf:
                            break
                        f.write(buf)
                if total:
                    full = int(total.split("/")[-1])
                    if os.path.getsize(dest_path) == full:
                        return os.path.getsize(dest_path)
            # no Content-Range: trust local size if an expected size was given
            if expected_size and os.path.getsize(dest_path) == expected_size:
                return os.path.getsize(dest_path)
            if not expected_size:
                return os.path.getsize(dest_path)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            print("  CDN failed (%s): %r; trying next..." % (url.split("/")[2], e))
            continue
    raise RuntimeError("all CDNs failed for %s: %r" % (path, last_err))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="only query and print remote file sizes")
    ap.add_argument("--only", choices=sorted(TARGETS),
                    help="download a single table by key")
    args = ap.parse_args()
    os.makedirs(DEST, exist_ok=True)

    keys = [args.only] if args.only else sorted(TARGETS)
    for key in keys:
        rel = TARGETS[key]
        name = os.path.basename(rel)
        dest = os.path.join(DEST, name)
        print("== %s (%s)" % (key, rel))
        try:
            size = remote_size(rel)
            print("  remote size: %d bytes (%.2f MiB)" % (size, size / 1048576))
        except Exception as e:
            print("  size probe failed (%r); downloading without pre-check" % e)
            size = None
        if args.probe:
            continue
        t0 = time.time()
        written = download(rel, dest, expected_size=size)
        # validate it parses as JSON
        with open(dest, "r", encoding="utf-8") as f:
            doc = json.load(f)
        print("  saved %s | %d bytes | %d top-level keys | %.1fs"
              % (dest, written, len(doc), time.time() - t0))


if __name__ == "__main__":
    main()
