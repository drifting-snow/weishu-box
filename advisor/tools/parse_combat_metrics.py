# -*- coding: utf-8 -*-
"""Stage-A combat metrics from exact fixed-level panels + Rank7 skill table.

Replaces star-rating proxies with physically meaningful combat numbers, all
derived from the two validated unpacked tables (character_table, skill_table)
and the fixed-level panels in operator_mode_stats.json. Only unambiguous,
well-defined quantities are computed; mechanic-specific skills are flagged
under needs_review instead of guessed.

Blackboard multiplier semantics (verified against in-game skill text):
  * key ``atk`` is an ADDITIVE buff  -> effective multiplier = 1 + atk
      e.g. 攻击力强化β atk=0.5 at Rank7 => 150%; atk=0.8 at M3 => +80%.
      黄昏 atk=2.4 => 3.4x; medic 治疗强化γ atk=0.7 => 1.7x healing.
  * key ``atk_scale`` / ``heal_scale`` / ``attack@atk_scale`` is a TOTAL
    multiplier used as-is (蓝毒二重射击 atk_scale=1.55 => 155% at Rank7).
  * ``times`` / ``attack@times`` is extra hit count; only applied when the
    skill is a clean multi-hit, otherwise flagged for the combat layer.

Metrics per operator, for BOTH the mode initial and elite fixed level:
  effective_hp.physical / .arts  (physical vs arts damage soak)
  base_dps                        normal-attack intrinsic DPS (no enemy DEF/RES)
  skill_metrics[]                 Rank7-only per-skill single/aoe DPS or HPS,
                                  with parsed multiplier and review flags.

Stdlib only.
"""
import io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMEDATA = os.path.join(ROOT, "data/source/gamedata")
MODE_STATS = os.path.join(ROOT, "data/operator_mode_stats.json")
OUT_PATH = os.path.join(ROOT, "data/operator_combat_metrics.json")

RANK7_INDEX = 6  # levels[0..6]=Rank1..7; index 7+ are mastery (disabled in mode)

# additive buff keys (effective multiplier = 1 + value)
ADDITIVE_KEYS = ("atk", "attack@atk")
# total-multiplier keys (used as-is)
TOTAL_KEYS = ("atk_scale", "heal_scale", "attack@atk_scale", "attack@heal_scale",
              "attack@atk_scale_ex", "attack@atk_scale_s2", "attack@atk_scale_s3",
              "attack@atk_scale_twice", "attack@atk_scale_base")
HIT_COUNT_KEYS = ("times", "attack@times")
TARGET_KEYS = ("attack@max_target", "max_target")
# Structural mechanics that make a single clean DPS number unreliable; these
# suppress aoe/multi-hit expansion and force a review note.
STRUCTURAL_HINTS = ("trait_scale", "talent_scale", "aura.", "chain.", "shield",
                    "projectile", "summon", "token", "ep_", "_ep",
                    "damage_per_second", "dynamic_")
# Side-effect keys do NOT change the main-attack multiplier, so they only add a
# soft note and must not suppress DPS/aoe (e.g. Surtr's self-damage hp_ratio).
SIDE_EFFECT_HINTS = ("hp_ratio", "prob", "stun", "force", "sluggish", "ct",
                     "max_hp", "magic_resistance", "attack_speed", "sp",
                     "taunt", "status_resistance")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def effective_hp(panel):
    """Physical and arts effective HP from the fixed-level panel."""
    hp = panel["maxHp_with_trust"]
    dfn = panel["def_with_trust"]
    res = min(max(panel["magicResistance"], 0.0), 95.0)
    phys_mit = dfn / (dfn + 100.0)          # physical mitigation curve
    arts_mit = res / 100.0                  # 1 RES = 1% arts reduction
    return {
        "physical": round(hp / max(1.0 - phys_mit, 0.05), 1),
        "arts": round(hp / max(1.0 - arts_mit, 0.05), 1),
        "raw_hp": hp, "def": dfn, "res": res,
    }


def _blackboard(level):
    return {b["key"]: b.get("value") for b in level.get("blackboard", [])}


def _find(bb, keys):
    """First exact then prefix match; return (key, value)."""
    for k in keys:
        if k in bb and bb[k] is not None:
            return k, bb[k]
    for k, v in bb.items():
        if v is None:
            continue
        for base in keys:
            if k.startswith(base):
                return k, v
    return None, None


def _effective_multiplier(bb):
    """Resolve the offensive/healing multiplier and its source semantics."""
    tk, tv = _find(bb, TOTAL_KEYS)
    if tv is not None:
        return tv, "total", tk
    ak, av = _find(bb, ADDITIVE_KEYS)
    if av is not None:
        return 1.0 + av, "additive", ak
    return None, None, None


def analyze_skill(skill_rec, skill_table, profession):
    """Parse one skill at Rank7. Conservative; flag ambiguous mechanics."""
    sid = skill_rec["skillId"]
    sk = skill_table.get(sid)
    review = []
    if not sk or len(sk.get("levels", [])) <= RANK7_INDEX:
        return {"skill_id": sid, "name": None,
                "needs_review": ["技能表缺失或等级不足"]}
    lv = sk["levels"][RANK7_INDEX]
    bb = _blackboard(lv)
    is_medic = profession == "MEDIC"
    notes = []  # informational; never invalidates the computed number
    entry = {
        "skill_id": sid, "name": lv.get("name"), "skill_type": lv.get("skillType"),
        "duration": lv.get("duration"), "multiplier": None, "mult_source": None,
        "hit_count": 1, "targets": 1,
        "single_dps": None, "aoe_dps": None, "heal_hps": None,
        "needs_review": review, "notes": notes,
    }

    # hit count / targets (recorded; structural complexity gets flagged)
    _, hits = _find(bb, HIT_COUNT_KEYS)
    if hits is not None and float(hits).is_integer():
        entry["hit_count"] = int(hits)
    _, targets = _find(bb, TARGET_KEYS)
    if targets is not None and float(targets).is_integer():
        entry["targets"] = int(targets)

    structural = sorted({h for h in STRUCTURAL_HINTS if any(h in k for k in bb)}
                        | {k for k in bb if "[" in k})  # character-specific [..] keys
    sidefx = sorted({h for h in SIDE_EFFECT_HINTS if any(h in k for k in bb)})
    mult, sem, mkey = _effective_multiplier(bb)
    if mult is None:
        review.append("无攻击/治疗倍率键(功能型/召唤/解放/条件机制)，不硬算")
        if structural:
            notes.append("结构机制: %s" % ",".join(structural[:4]))
        return entry
    entry["multiplier"] = round(mult, 4)
    entry["mult_source"] = sem
    # Structural mechanics suppress aoe/multi-hit expansion but the base
    # multiplier is still valid -> a note, not a hard review.
    if structural:
        notes.append("含结构机制键(%s)，仅取基础倍率，对群/连击未展开，待战斗层"
                     % ",".join(structural[:4]))
    if sidefx:
        notes.append("附带副作用/控制(%s)，不影响主攻击倍率" % ",".join(sidefx[:4]))

    # Medic path: multiplier scales healing per attack action.
    if is_medic:
        # instant/burst heals keyed by hp_ratio/ct are not a steady HPS.
        if "hp_ratio" in bb or "ct" in bb:
            review.append("瞬抬/按生命上限治疗(hp_ratio/ct)，非持续HPS口径")
            return entry
        entry["heal_hps"] = "PENDING"  # caller injects atk/interval
        return entry

    # Offensive path. The resolved multiplier always gives a base single-target
    # DPS. A clean multi-hit needs explicit times>=2 with no structural
    # complexity; times==1 is usually an extra projectile and is noted rather
    # than blindly multiplied. Aoe expansion is suppressed only by structural
    # mechanics, not by side effects like self-damage.
    if hits is not None and not structural:
        if float(hits).is_integer() and hits >= 2:
            entry["hit_count"] = int(hits)
        else:
            entry["hit_count"] = 1
            if float(hits) == 1:
                notes.append("times=1 多为额外攻击/投射物，总连击按主攻击保守计")
    else:
        entry["hit_count"] = 1
    entry["single_dps"] = "PENDING"  # caller injects atk/interval
    if entry["targets"] > 1 and not structural:
        entry["aoe_dps"] = "PENDING"
    return entry


def build_panel_metrics(panel, char_rec, skill_table):
    interval = panel["baseAttackTime"]
    atk = panel["atk_with_trust"]
    prof = char_rec.get("profession")
    metrics = {
        "phase": panel["phase"], "level": panel["level"],
        "skill_rank": panel["skill_rank"], "module": panel["module"],
        "atk_with_trust": atk, "attack_interval": interval,
        "base_dps": panel["base_dps"],
        "effective_hp": effective_hp(panel),
        "skill_metrics": [],
    }
    for srec in char_rec.get("skills", []):
        sm = analyze_skill(srec, skill_table, prof)
        if sm.get("single_dps") == "PENDING":
            per = atk * sm["multiplier"] * sm["hit_count"] / interval
            sm["single_dps"] = round(per, 2)
            if sm.get("aoe_dps") == "PENDING":
                sm["aoe_dps"] = round(per * sm["targets"], 2)
        if sm.get("heal_hps") == "PENDING":
            sm["heal_hps"] = round(atk * sm["multiplier"] / interval, 2)
        metrics["skill_metrics"].append(sm)
    return metrics


def main():
    chars = load(os.path.join(GAMEDATA, "character_table.json"))
    skill_table = load(os.path.join(GAMEDATA, "skill_table.json"))
    mode = load(MODE_STATS)

    records, missing = [], []
    for r in mode["operators"]:
        char_rec = chars.get(r["char_id"])
        if not char_rec:
            missing.append(r["name"])
            continue
        records.append({
            "name": r["name"], "char_id": r["char_id"], "star": r["star"],
            "shop_tier": r["shop_tier"], "profession": r["profession"],
            "sub_profession": r["sub_profession"], "position": r["position"],
            "initial": build_panel_metrics(r["initial"], char_rec, skill_table),
            "elite": build_panel_metrics(r["elite"], char_rec, skill_table),
        })

    def flat(st):
        return (s for r in records for s in r[st]["skill_metrics"])
    n_hard_review = sum(1 for st in ("initial", "elite") for s in flat(st)
                        if s["needs_review"] and s["single_dps"] is None
                        and s["heal_hps"] is None)
    n_notes = sum(1 for st in ("initial", "elite") for s in flat(st) if s["notes"])
    out = {
        "_meta": {
            "description": "阶段A战斗指标：固定练度精确面板推导的有效血量(物/法)、裸DPS、Rank7技能DPS(对单/对群)与医疗HPS。",
            "sources": ["character_table.json", "skill_table.json", "operator_mode_stats.json"],
            "rank_note": "技能固定Rank7(levels[6])，模式无专精，不读index7+专精行",
            "multiplier_semantics": {
                "atk": "增量加成，有效倍率=1+atk（已用游戏技能文本验证）",
                "atk_scale/heal_scale": "总倍率，直接取值",
            },
            "formulas": {
                "physical_ehp": "hp / (1 - def/(def+100))",
                "arts_ehp": "hp / (1 - res/100), res capped at 95",
                "base_dps": "atk_with_trust / baseAttackTime",
                "skill_single_dps": "atk * multiplier * hit_count / baseAttackTime (in-skill, no uptime cycle)",
                "aoe_dps": "single_dps * targets",
                "medic_hps": "atk * heal_multiplier / baseAttackTime (steady skills only)",
            },
            "limitations": [
                "技能DPS为技能开启期内理论值，未建模回转/覆盖率",
                "伤害类型(物/法/真/元素)无干净字段，分类总伤属阶段B/C",
                "含额外投射物/瞬抬/召唤/解放等机制的技能进needs_review，不硬算",
            ],
            "operator_count": len(records), "missing": missing,
            "hard_review_entries": n_hard_review,
            "note_entries": n_notes,
            "review_semantics": "needs_review=无数值/语义存疑；notes=有数值仅附带机制/副作用说明",
        },
        "operators": records,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("operators:", len(records), "| missing:", missing,
          "| hard review:", n_hard_review, "| notes:", n_notes)
    by = {r["name"]: r for r in records}
    for nm in ("史尔特尔", "能天使", "夜莺", "蓝毒", "卡达"):
        if nm not in by:
            continue
        e = by[nm]["elite"]
        print("\n%s 精%sLv%s 裸DPS=%.1f | 物EHP=%.0f 法EHP=%.0f" %
              (nm, e["phase"], e["level"], e["base_dps"],
               e["effective_hp"]["physical"], e["effective_hp"]["arts"]))
        for s in e["skill_metrics"]:
            tag = ""
            if s["needs_review"]:
                tag = "RV:" + ";".join(s["needs_review"])
            elif s["notes"]:
                tag = "note:" + ";".join(s["notes"][:2])
            print("   %-12s x%.2f(%s) 单DPS=%s 群DPS=%s HPS=%s %s" %
                  (s["name"], s["multiplier"] or 0, s["mult_source"] or "-",
                   s["single_dps"], s["aoe_dps"], s["heal_hps"], tag))


if __name__ == "__main__":
    main()
