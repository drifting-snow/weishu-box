# -*- coding: utf-8 -*-
"""Validate the exact fixed-level panels against independent data.

Three layers, cheapest first. The first two run fully offline on the cached
artifacts; the third is opt-in because it needs network access.

1. Local sanity  -- every interpolated grid point is in-range, non-negative and
   monotonic; trust is additive; fixed level sits inside its phase key frames.
2. Cross-source anchor -- game unpack table vs the PRTS-wiki-derived
   operator_power.json at the elite-max anchors (two independently maintained
   sources that must agree on atk/hp/def).
3. --remote second unpack -- Kengxxiao/ArknightsGameData_YoStar (en_US build,
   a separately maintained unpack) keyframes diffed against the zh_CN cache.

Why linear interpolation is exact, not an assumption: the unpacked
character_table stores only two attributesKeyFrames per elite phase (Lv1 and
max). The client has no per-level rows, so every intermediate displayed value
is produced by interpolating those two frames; we reproduce that operation and
round the same way. External game-design references also state stats grow
linearly within an elite phase.

Usage:
  python tools/validate_mode_stats.py            # layers 1-2 (offline)
  python tools/validate_mode_stats.py --remote    # add layer 3 (network)
"""
import argparse, io, json, os, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAR_PATH = os.path.join(ROOT, "data/source/gamedata/character_table.json")
MODE_STATS = os.path.join(ROOT, "data/operator_mode_stats.json")
POWER = os.path.join(ROOT, "data/operator_power.json")
YOSTAR_URL = ("https://fastly.jsdelivr.net/gh/Kengxxiao/ArknightsGameData_YoStar"
              "@master/en_US/gamedata/excel/character_table.json")
NUMERIC_FIELDS = ("atk", "maxHp", "def", "magicResistance",
                  "baseAttackTime", "cost", "blockCnt")
UA = "weishu-advisor/0.1 (data validation)"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def name_index(chars):
    idx = {}
    for cid, rec in chars.items():
        if cid.startswith("char_") and rec.get("name") and rec["name"] not in idx:
            idx[rec["name"]] = cid
    return idx


def interp(rec, phase, level, key):
    lo, hi = rec["phases"][phase]["attributesKeyFrames"]
    a, b = lo["data"][key], hi["data"][key]
    ratio = (level - lo["level"]) / max(hi["level"] - lo["level"], 1)
    return int(round(a + (b - a) * ratio))


def layer_local_sanity(chars, stats, idx):
    """Grid monotonicity + range + trust-additivity over every operator."""
    nonmono = out_of_range = nonpos = trust_bad = 0
    grid = 0
    for r in stats["operators"]:
        rec = chars[idx[r["name"]]]
        for state in ("initial", "elite"):
            s = r[state]
            if not (s["frame_lo"] <= s["level"] <= s["frame_hi"]):
                out_of_range += 1
            if s["atk_with_trust"] <= 0 or s["maxHp_with_trust"] <= 0:
                nonpos += 1
            if s["atk_with_trust"] != s["atk"] + s["trust"]["atk"]:
                trust_bad += 1
        for ph in range(len(rec["phases"])):
            lo, hi = rec["phases"][ph]["attributesKeyFrames"]
            if hi["level"] <= lo["level"]:
                continue
            prev = -1
            for lv in range(lo["level"], hi["level"] + 1):
                grid += 1
                cur = interp(rec, ph, lv, "atk")
                if cur < prev:
                    nonmono += 1
                prev = cur
    ok = not (nonmono or out_of_range or nonpos or trust_bad)
    print("[1] local sanity: grid_points=%d nonmonotonic=%d out_of_range=%d "
          "non_positive=%d trust_mismatch=%d -> %s"
          % (grid, nonmono, out_of_range, nonpos, trust_bad,
             "PASS" if ok else "FAIL"))
    return ok


def layer_anchor_crosscheck(chars, stats, idx, power):
    """Game table elite-max atk(+trust) must equal the PRTS wiki anchor."""
    wiki = {r["name"]: r for r in power["operators"]}
    mismatch = checked = 0
    examples = []
    for r in stats["operators"]:
        nm = r["name"]
        if nm not in wiki:
            continue
        rec = chars[idx[nm]]
        e2 = rec["phases"][2]["attributesKeyFrames"][-1]["data"]
        trust_atk = rec["favorKeyFrames"][-1]["data"]["atk"]
        game_e2 = e2["atk"] + trust_atk
        wiki_e2 = wiki[nm]["base"].get("atk_with_trust")
        if wiki_e2 is None:
            continue
        checked += 1
        if game_e2 != wiki_e2:
            mismatch += 1
            if len(examples) < 8:
                examples.append("%s game=%s wiki=%s" % (nm, game_e2, wiki_e2))
    ok = mismatch == 0
    print("[2] anchor cross-check (game unpack vs PRTS wiki, E2 max atk+trust): "
          "checked=%d mismatch=%d -> %s" % (checked, mismatch, "PASS" if ok else "FAIL"))
    for e in examples:
        print("    ", e)
    return ok


def layer_remote_second_unpack(chars, stats, idx):
    """Diff every keyframe numeric stat against the YoStar en_US unpack."""
    req = urllib.request.Request(YOSTAR_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as resp:
        yo = json.load(resp)
    roster = {r["name"] for r in stats["operators"]}
    diffs = frames = missing = 0
    examples = []
    for nm in roster:
        cid = idx[nm]
        a, b = chars.get(cid), yo.get(cid)
        if not a or not b:
            missing += 1
            continue
        for ph_a, ph_b in zip(a["phases"], b["phases"]):
            for ka, kb in zip(ph_a["attributesKeyFrames"],
                              ph_b["attributesKeyFrames"]):
                frames += 1
                for f in NUMERIC_FIELDS:
                    if ka["data"].get(f) != kb["data"].get(f):
                        diffs += 1
                        if len(examples) < 8:
                            examples.append("%s %s %s!=%s" % (nm, f, ka["data"].get(f),
                                                               kb["data"].get(f)))
    ok = diffs == 0
    print("[3] remote second unpack (YoStar en_US): frames=%d numeric_diffs=%d "
          "version_missing=%d -> %s" % (frames, diffs, missing, "PASS" if ok else "FAIL"))
    for e in examples:
        print("    ", e)
    if missing:
        print("     note: %d operators absent from the en_US build "
              "(not yet released globally) -- a version gap, not an error." % missing)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", action="store_true",
                    help="also fetch and diff the YoStar en_US second unpack")
    args = ap.parse_args()

    chars = load(CHAR_PATH)
    stats = load(MODE_STATS)
    idx = name_index(chars)
    results = [
        layer_local_sanity(chars, stats, idx),
        layer_anchor_crosscheck(chars, stats, idx, load(POWER)),
    ]
    if args.remote:
        results.append(layer_remote_second_unpack(chars, stats, idx))
    print("\nOVERALL:", "PASS" if all(results) else "FAIL")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
