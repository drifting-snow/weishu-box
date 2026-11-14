# -*- coding: utf-8 -*-
"""Fetch PRTS wikitext for every weishu operator and cache locally.

Uses the MediaWiki revisions API in batches (rvslots content). Each operator
is saved to data/source/prts/<name>.wiki so reruns skip already-fetched pages
and survive network timeouts. Stdlib only.

Usage:
  python tools/fetch_prts_wiki.py --limit 3   # smoke test
  python tools/fetch_prts_wiki.py             # full fetch (141)
"""
import argparse, io, json, os, re, sys, time, urllib.request, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "source", "prts")
os.makedirs(CACHE, exist_ok=True)
API = "https://prts.wiki/api.php"
UA = "weishu-advisor/0.1 (offline PDK helper; contact: local)"


def http_get(params, timeout=30, retries=4):
    url = API + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(min(2 * (attempt + 1), 8))
    raise RuntimeError("GET failed after %d retries: %r" % (retries, last))


def fetch_batch(titles):
    """Return {title: wikitext} for a batch via revisions API."""
    j = http_get({
        "action": "query", "format": "json",
        "titles": "|".join(titles),
        "prop": "revisions", "rvprop": "content", "rvslots": "main",
        "redirects": 1,
    })
    # normalize redirects back to requested titles
    norm = {}
    for r in j.get("query", {}).get("redirects", []):
        norm[r["to"]] = r["from"]
    out = {}
    for page in j.get("query", {}).get("pages", {}).values():
        title = page.get("title", "")
        name = norm.get(title, title)
        revs = page.get("revisions")
        if revs and "slots" in revs[0]:
            out[name] = revs[0]["slots"]["main"].get("*", "")
        elif revs:
            out[name] = revs[0].get("*", "")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch", type=int, default=10)
    args = ap.parse_args()
    ops = json.load(open(os.path.join(ROOT, "data", "operators.json"), encoding="utf-8"))
    names = [o["name"] for o in ops]
    if args.limit:
        names = names[:args.limit]

    todo = [n for n in names if not os.path.exists(os.path.join(CACHE, n + ".wiki"))]
    print("total %d, cached %d, to fetch %d" %
          (len(names), len(names) - len(todo), len(todo)), flush=True)

    for i in range(0, len(todo), args.batch):
        batch = todo[i:i + args.batch]
        try:
            got = fetch_batch(batch)
        except Exception as e:
            print("BATCH FAIL %s: %r" % (batch, e), flush=True)
            continue
        for name, wt in got.items():
            if wt:
                with open(os.path.join(CACHE, name + ".wiki"), "w", encoding="utf-8") as f:
                    f.write(wt)
        print("fetched %d/%d (batch %d): %s" %
              (min(i + args.batch, len(todo)), len(todo), len(got),
               "、".join(batch[:4]) + ("..." if len(batch) > 4 else "")), flush=True)
        time.sleep(0.5)

    have = [n for n in names if os.path.exists(os.path.join(CACHE, n + ".wiki"))]
    print("DONE cached %d/%d" % (len(have), len(names)), flush=True)


if __name__ == "__main__":
    main()
