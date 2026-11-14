# -*- coding: utf-8 -*-
"""Fetch act3 Guard-Protocol (autochess) level files from official unpacked data.

The act3 wave timing data (spawn count/interval/route) lives in the per-level
JSON under levels/activities/act3autochess, not in the excel tables. Stage-1
clear-margin needs those spawn definitions, so this mirrors fetch_game_data.py:
same community unpacked repo (Kengxxiao, NOT the GPL Stronghold reimplementation),
same CDN fallbacks, stdlib only.

Files are cached under data/source/gamedata/levels/activities/act3autochess/,
which is already covered by the data/source/gamedata/ gitignore rule, so nothing
proprietary is ever committed; the builder recomputes derived values from them.

Usage:
  python tools/fetch_act3_levels.py --probe   # list remote entries + sizes
  python tools/fetch_act3_levels.py           # download every .json
  python tools/fetch_act3_levels.py --only level_act3autochess_01.json
"""
import argparse, io, json, os, sys, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_REL = "zh_CN/gamedata/levels/activities/act3autochess"
DEST = os.path.join(ROOT, "data", "source", "gamedata",
                    "levels", "activities", "act3autochess")
REPO = "Kengxxiao/ArknightsGameData"
BRANCH = "master"
CDN_BASES = [
    "https://fastly.jsdelivr.net/gh/%s@%s" % (REPO, BRANCH),
    "https://cdn.jsdelivr.net/gh/%s@%s" % (REPO, BRANCH),
    "https://raw.githubusercontent.com/%s/%s" % (REPO, BRANCH),
]
UA = "weishu-advisor/0.1 (open-source data builder; stdlib only)"


def _request(url, headers=None, timeout=30):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    return urllib.request.Request(url, headers=h)


def list_entries():
    """Return [{name, size, download_url}] for every file in the remote dir."""
    api = ("https://api.github.com/repos/%s/contents/%s?ref=%s"
           % (REPO, urllib.request.quote(DIR_REL), BRANCH))
    with urllib.request.urlopen(_request(api), timeout=30) as r:
        meta = json.load(r)
    out = []
    for e in meta:
        if e.get("type") == "file" and e["name"].endswith(".json"):
            out.append({"name": e["name"], "size": int(e["size"]),
                        "download_url": e.get("download_url")})
    return sorted(out, key=lambda x: x["name"])


def cdn_urls(name):
    path = DIR_REL + "/" + name
    return ["%s/%s" % (base, path) for base in CDN_BASES]


def download_one(name, expected_size=None):
    dest = os.path.join(DEST, name)
    if os.path.exists(dest) and (expected_size is None
                                 or os.path.getsize(dest) == expected_size):
        return os.path.getsize(dest), "skip"
    last_err = None
    for url in cdn_urls(name):
        try:
            with urllib.request.urlopen(_request(url), timeout=60) as r:
                data = r.read()
            if expected_size and len(data) != expected_size:
                raise IOError("size mismatch: got %d, expected %d"
                              % (len(data), expected_size))
            with open(dest, "wb") as fh:
                fh.write(data)
            return len(data), "ok"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            print("  CDN failed (%s): %r; trying next..." %
                  (url.split("/")[2], e))
            continue
    raise RuntimeError("all CDNs failed for %s: %r" % (name, last_err))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--only", help="download a single file by name")
    args = ap.parse_args()

    entries = list_entries()
    total = sum(e["size"] for e in entries)
    print("remote dir %s" % DIR_REL)
    print("files: %d | total %.1f KB" % (len(entries), total / 1024))
    if args.probe:
        for e in entries:
            print("  %-34s %8d B" % (e["name"], e["size"]))
        return

    os.makedirs(DEST, exist_ok=True)
    targets = [e for e in entries if (not args.only or e["name"] == args.only)]
    if args.only and not targets:
        print("no remote file named %s" % args.only)
        sys.exit(1)
    ok = skipped = 0
    for e in targets:
        n, status = download_one(e["name"], e["size"])
        if status == "skip":
            skipped += 1
        else:
            ok += 1
        print("  [%s] %-34s %8d B" % (status, e["name"], n))
    print("done: downloaded %d, skipped(complete) %d, dest %s" %
          (ok, skipped, DEST))


if __name__ == "__main__":
    main()
