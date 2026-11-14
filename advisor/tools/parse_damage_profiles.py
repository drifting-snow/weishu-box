# -*- coding: utf-8 -*-
"""Stage-B integration: attach damage type + tier matrices to every operator.

Joins the two pure-logic modules (advisor/damage_type.py, advisor/damage_calc.py)
with the real unpacked tables and the stage-A fixed-level panels:

  * operator basic-attack type  : native_trait text + branch default
  * per-skill Rank7 type        : skill_table description keyword -> branch default
  * elemental secondary flag    : 神经/侵蚀/灼燃/凋亡/元素损伤
  * standard-tier damage matrix : physical sweeps DEF tiers, arts sweeps RES
  * break-armor / half-damage lines for the in-skill attack power

Healing skills (MEDIC / HEAL) produce no damage matrix. Skills already flagged
hard-review in stage A (no usable multiplier) carry the type label only, with no
matrix, so no number is fabricated.

Stdlib only. Output: data/operator_damage_profiles.json
"""
import io, json, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from advisor import damage_type as dt
from advisor import damage_calc as dc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAMEDATA = os.path.join(ROOT, "data/source/gamedata")
COMBAT = os.path.join(ROOT, "data/operator_combat_metrics.json")
OPERATORS = os.path.join(ROOT, "data/operators.json")
OVERRIDES = os.path.join(ROOT, "data/damage_type_overrides.json")
OUT_PATH = os.path.join(ROOT, "data/operator_damage_profiles.json")
RANK7_INDEX = 6


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def clean(text):
    return re.sub(r"<[^>]+>|</>", "", text or "")


def skill_description(skill_table, skill_id):
    sk = skill_table.get(skill_id)
    if not sk or len(sk.get("levels", [])) <= RANK7_INDEX:
        return ""
    return clean(sk["levels"][RANK7_INDEX].get("description"))


def build_state(state_metrics, char_rec, skill_table, native_trait, override_map):
    """Damage profile for one fixed-level state (initial or elite)."""
    prof = char_rec.get("profession")
    sub = char_rec.get("subProfessionId")
    atk = state_metrics["atk_with_trust"]

    baseline = dt.classify_operator_baseline(native_trait, prof, sub)
    skills_out = []
    for sm in state_metrics["skill_metrics"]:
        desc = skill_description(skill_table, sm["skill_id"])
        # Healing skills are a separate family identified by their HPS number,
        # not by damage-type keywords (a shield that *absorbs* arts damage must
        # not be mislabeled as an arts attack).
        if sm.get("heal_hps") is not None:
            verdict = {"damage_type": dt.HEAL, "source": "profession",
                       "has_elemental": False, "needs_review": []}
        else:
            verdict = dt.classify_skill(desc, prof, sub)
        # Targeted override adjudicates mixed-text skills (and >5% ArkDPS
        # validation gaps later) by skill_id; it clears the review flag.
        if sm["skill_id"] in override_map:
            verdict = {"damage_type": override_map[sm["skill_id"]],
                       "source": "override", "has_elemental": verdict["has_elemental"],
                       "needs_review": []}
        entry = {
            "skill_id": sm["skill_id"], "name": sm["name"],
            "damage_type": verdict["damage_type"], "type_source": verdict["source"],
            "has_elemental": verdict["has_elemental"],
            "type_review": verdict["needs_review"],
        }
        # Build a matrix ONLY for a real offensive number (single_dps). A bare
        # multiplier on a shield/functional skill (single_dps=None) must not
        # fabricate damage; mixed-text unresolved types are also excluded.
        if (verdict["damage_type"] in (dt.PHYSICAL, dt.ARTS, dt.TRUE)
                and sm.get("single_dps") is not None):
            skill_atk = atk * sm["multiplier"]
            entry["skill_attack_power"] = round(skill_atk, 2)
            entry["damage_matrix"] = dc.damage_matrix(
                skill_atk, verdict["damage_type"],
                hit_count=sm.get("hit_count", 1), targets=sm.get("targets", 1))
        skills_out.append(entry)

    return {
        "phase": state_metrics["phase"], "level": state_metrics["level"],
        "baseline_damage_type": baseline["damage_type"],
        "baseline_source": baseline["source"],
        "baseline_has_elemental": baseline["has_elemental"],
        "baseline_review": baseline["needs_review"],
        "skill_profiles": skills_out,
    }


def main():
    chars = load(os.path.join(GAMEDATA, "character_table.json"))
    skill_table = load(os.path.join(GAMEDATA, "skill_table.json"))
    combat = load(COMBAT)
    traits = {o["name"]: o.get("native_trait", "") for o in load(OPERATORS)}
    override_doc = load(OVERRIDES)
    override_map = {o["skill_id"]: o["damage_type"] for o in override_doc["overrides"]}

    records, missing = [], []
    src_counter = {"text": 0, "trait": 0, "default": 0, "profession": 0,
                   "none": 0, "mixed_text": 0, "override": 0}
    type_counter = {dt.PHYSICAL: 0, dt.ARTS: 0, dt.TRUE: 0, dt.HEAL: 0, "none": 0}
    elemental_skills = 0
    matrix_skills = 0
    review_skills = 0

    for r in combat["operators"]:
        char_rec = chars.get(r["char_id"])
        if not char_rec:
            missing.append(r["name"])
            continue
        native_trait = traits.get(r["name"], "")
        rec = {
            "name": r["name"], "char_id": r["char_id"], "star": r["star"],
            "shop_tier": r["shop_tier"], "profession": r["profession"],
            "sub_profession": r["sub_profession"],
            "initial": build_state(r["initial"], char_rec, skill_table,
                                   native_trait, override_map),
            "elite": build_state(r["elite"], char_rec, skill_table,
                                 native_trait, override_map),
        }
        for st in ("initial", "elite"):
            src_counter[rec[st]["baseline_source"]] += 1
            for s in rec[st]["skill_profiles"]:
                src_counter[s["type_source"]] = src_counter.get(s["type_source"], 0) + 1
                t = s["damage_type"] or "none"
                type_counter[t] = type_counter.get(t, 0) + 1
                if s["has_elemental"]:
                    elemental_skills += 1
                if "damage_matrix" in s:
                    matrix_skills += 1
                if s["type_review"]:
                    review_skills += 1
        records.append(rec)

    out = {
        "_meta": {
            "description": "阶段B伤害画像：技能级伤害类型(物/法/真/治疗)+元素副标签，标准档伤害矩阵与破甲/半伤线。",
            "sources": ["character_table.json", "skill_table.json",
                        "operator_combat_metrics.json", "operators.json",
                        "damage_type_overrides.json"],
            "override_note": "mixed_text 技能由 damage_type_overrides.json 按 skill_id 人工裁定，source=override",
            "tier_note": "ArkDPS为连续滑杆(0..1000)无离散档；本项目用覆盖全区间的离散标准档，每点可在其滑杆同值对拍",
            "def_tiers": list(dc.DEF_TIERS), "res_tiers": list(dc.RES_TIERS),
            "classifier_tiers": "技能文本关键词 > 特性文本 > 职业/分支默认；混合类型回退默认并标review",
            "formulas": {
                "physical_hit": "max(ATK-DEF, ATK*0.05)",
                "arts_hit": "ATK*(1-RES/100), RES capped 95",
                "true_hit": "ATK (ignores DEF/RES)",
                "break_armor_def": "0.95*ATK (5% floor binds); half-damage DEF=0.5*ATK",
                "arts_half_res": "50",
            },
            "source_distribution": src_counter,
            "type_distribution": type_counter,
            "elemental_skill_entries": elemental_skills,
            "matrix_skill_entries": matrix_skills,
            "review_skill_entries": review_skills,
            "operator_count": len(records), "missing": missing,
            "limitations": [
                "元素损伤仅作副标签，结算留待阶段C",
                "阶段A硬review(无倍率)技能只标类型，不生成矩阵",
                "矩阵为单次技能动作(含连击/对群)在各档位伤害，未含回转覆盖率(阶段C)",
            ],
        },
        "operators": records,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print("operators:", len(records), "| missing:", missing)
    print("source dist:", src_counter)
    print("type dist:", type_counter)
    print("elemental entries:", elemental_skills, "| matrices:", matrix_skills,
          "| review:", review_skills)
    by = {r["name"]: r for r in records}
    for nm in ("史尔特尔", "蓝毒", "夜莺", "温蒂", "卡达"):
        if nm not in by:
            continue
        e = by[nm]["elite"]
        print("\n%s 基线=%s(%s)" % (nm, e["baseline_damage_type"], e["baseline_source"]))
        for s in e["skill_profiles"]:
            mat = ""
            if "damage_matrix" in s:
                d = s["damage_matrix"]
                first = list(d["per_action_damage"].items())[:3]
                mat = " 矩阵样本%s" % first
            print("   %-12s %-8s[%s] elem=%s%s %s" %
                  (s["name"], s["damage_type"], s["type_source"],
                   s["has_elemental"], mat, s["type_review"]))


if __name__ == "__main__":
    main()
