# -*- coding: utf-8 -*-
"""Build exact fixed-level stats for Guard-Protocol operators.

The wiki cache only carries four level anchors per operator, so the mode's
fixed levels (E1 Lv55/60, E2 Lv1/50/55/60) used to be approximated by the
nearest elite-max anchor and flagged as over-estimates. This module replaces
those estimates with exact values interpolated from the unpacked game table
``character_table.json`` (per-phase attributesKeyFrames), plus the 100% trust
bonus from each character's ``favorKeyFrames``.

Interpolation matches the client: stats grow linearly between the phase's Lv1
and max-level key frames, then round to nearest int. Trust is a flat additive
bonus (fully unlocked at 100% trust, which the mode always applies).

Inputs (git-ignored, rebuildable):
  data/source/gamedata/character_table.json  (fetch_game_data.py)
  data/mode_levels.json                       (user-verified fixity table)
  data/operators.json                         (local 141-operator roster)
Output:
  data/operator_mode_stats.json
"""
import io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAR_PATH = os.path.join(ROOT, "data/source/gamedata/character_table.json")
MODE_PATH = os.path.join(ROOT, "data/mode_levels.json")
ROSTER_PATH = os.path.join(ROOT, "data/operators.json")
OUT_PATH = os.path.join(ROOT, "data/operator_mode_stats.json")

# stat fields read straight from a key frame's `data` block
INT_FIELDS = ("atk", "maxHp", "def", "magicResistance", "cost", "blockCnt")
FLOAT_FIELDS = ("baseAttackTime", "attackSpeed", "respawnTime", "hpRecoveryPerSec")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_name_index(chars):
    """Chinese name -> real-operator char id (skip tokens/traps/summons)."""
    index = {}
    for cid, rec in chars.items():
        if not cid.startswith("char_"):
            continue
        nm = rec.get("name")
        if nm and nm not in index:  # first char_ id wins over any duplicate
            index[nm] = cid
    return index


def phase_frames(rec, phase):
    """Return the (lv1_frame, max_frame) of the requested elite phase."""
    frames = rec["phases"][phase]["attributesKeyFrames"]
    return frames[0], frames[-1]


def interpolate(rec, phase, level):
    """Linearly interpolate every stat at (phase, level), matching the client."""
    lo, hi = phase_frames(rec, phase)
    lo_lv, hi_lv = lo["level"], hi["level"]
    span = max(hi_lv - lo_lv, 1)
    ratio = (level - lo_lv) / span
    out = {"phase": phase, "level": level, "frame_lo": lo_lv, "frame_hi": hi_lv}
    for key in INT_FIELDS:
        a = lo["data"].get(key, 0)
        b = hi["data"].get(key, 0)
        out[key] = int(round(a + (b - a) * ratio))
    for key in FLOAT_FIELDS:
        a = lo["data"].get(key, 0.0)
        b = hi["data"].get(key, 0.0)
        out[key] = round(a + (b - a) * ratio, 4)
    return out


def trust_bonus(rec):
    """100% trust additive bonus (last favor key frame)."""
    frames = rec.get("favorKeyFrames") or []
    if not frames:
        return {"atk": 0, "maxHp": 0, "def": 0}
    d = frames[-1]["data"]
    return {"atk": d.get("atk", 0), "maxHp": d.get("maxHp", 0),
            "def": d.get("def", 0)}


def fixed_panel(rec, spec):
    """Exact panel for one mode state (initial or elite) plus trust."""
    panel = interpolate(rec, spec["phase"], spec["level"])
    bonus = trust_bonus(rec)
    panel["trust"] = bonus
    panel["atk_with_trust"] = panel["atk"] + bonus["atk"]
    panel["maxHp_with_trust"] = panel["maxHp"] + bonus["maxHp"]
    panel["def_with_trust"] = panel["def"] + bonus["def"]
    panel["skill_rank"] = spec["skill_rank"]
    panel["module"] = spec["module"]
    # naked physical DPS at this exact level (trust atk / attack interval)
    panel["base_dps"] = round(panel["atk_with_trust"] / panel["baseAttackTime"], 2)
    return panel


def main():
    chars = load_json(CHAR_PATH)
    mode = load_json(MODE_PATH)
    roster = load_json(ROSTER_PATH)
    tiers = mode["tiers"]
    name_idx = build_name_index(chars)

    records, missing = [], []
    for op in roster:
        nm = op["name"]
        cid = name_idx.get(nm)
        if not cid:
            missing.append(nm)
            continue
        rec = chars[cid]
        shop_tier = str(op.get("shop_tier") or op.get("tier"))
        spec = tiers[shop_tier]
        records.append({
            "name": nm,
            "char_id": cid,
            "star": str(op["star"]),
            "shop_tier": int(shop_tier),
            "profession": rec.get("profession"),
            "sub_profession": rec.get("subProfessionId"),
            "position": rec.get("position"),
            "initial": fixed_panel(rec, spec["initial"]),
            "elite": fixed_panel(rec, spec["elite"]),
        })

    out = {
        "_meta": {
            "description": "卫戍协议固定练度下的精确面板。由解包表 character_table.json 的 "
                           "attributesKeyFrames 在阶段内线性插值(与客户端成长一致，四舍五入)，"
                           "加 favorKeyFrames 的100%信赖加成。替代此前用精英满级锚点的高估近似。",
            "source": "Kengxxiao/ArknightsGameData zh_CN character_table.json + data/mode_levels.json",
            "interpolation": "stat(lv)=frame1+(frameMax-frame1)*(lv-frame1.level)/(frameMax.level-frame1.level)",
            "trust": "信赖恒100%，取 favorKeyFrames 末帧，作为 atk/maxHp/def 的固定加值",
            "skill_note": "模式技能无专精；skill_rank 初始4/精锐7，见 mode_levels.json",
            "operator_count": len(records),
            "missing": missing,
        },
        "operators": records,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("operators:", len(records), "| missing:", missing)
    # spot check vs. previously anchor-flagged operators
    by_name = {r["name"]: r for r in records}
    for nm in ("史尔特尔", "烈夏", "卡达"):
        r = by_name[nm]
        i, e = r["initial"], r["elite"]
        print("%s t%s: 初始 精%sLv%s 攻%s(含信赖%s) 血%s | 精锐 精%sLv%s 攻%s DPS=%.1f"
              % (nm, r["shop_tier"], i["phase"], i["level"], i["atk"],
                 i["atk_with_trust"], i["maxHp_with_trust"],
                 e["phase"], e["level"], e["atk_with_trust"], e["base_dps"]))


if __name__ == "__main__":
    main()
