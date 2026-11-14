# -*- coding: utf-8 -*-
"""Build data/enemy_special_cases.json: the per-name SPECIAL-COUNTER extension.

Scope (2026-11-13 expansion): curate EVERY enemy whose official unpacked
handbook tags at least one ability with textFormat == "SILENCE" (61 enemies in
the act3 pool). SILENCE is the only structured counter flag the client data
exposes, so every entry's counter_tag is "silence"; enemies are organized into
mechanic families for explainability and future per-family tuning.

Two-tier design so the runtime does not double-count the nine tactical
categories (counters.py):

  generic_covered = True  -> the silence-able ability IS the essence of a
    tactical category whose real counter is something else. The 14-refraction
    family is the only such tier: refraction's answer is arts/def_pierce, not
    silence. These entries stay in the library (with evidence) but never raise a
    silence gap at runtime.

  generic_covered = False -> a concrete special ability silence directly stops
    and the generic category does not express (death cold-explosion, on-death
    split, enemy aura, team debuff, on-hit control, summon/charge, ...). These
    drive the gate-0 silence gap.

Family assignment is rule-based over the official ability text (ordered by
specificity). The build asserts every SILENCE enemy resolves to a named family;
anything unmatched falls into "other_silence" with needs_review=True and is
printed loudly, so a season update can never silently drop or mis-file an enemy.
No ability prose is shipped beyond the short family label plus evidence text.
Stdlib only; reads the same git-ignored official tables as the other builders.
"""
import argparse, io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GD = os.path.join(ROOT, "data", "source", "gamedata")
DEFAULT_OUT = os.path.join(ROOT, "data", "enemy_special_cases.json")
PRTS_SILENCE = "https://prts.wiki/w/异常效果图鉴/沉默"

# Ordered mechanic families. Priority = list order (first hit wins as primary);
# an enemy can collect several families across its multiple abilities, but gets
# one primary for stable labeling. Labels are the only human prose shipped.
FAMILIES = [
    ("on_death_cold_explosion", "沉默，阻止死亡爆炸与寒冷/冻结",
     "死亡触发的爆炸并施加寒冷(再触发→冻结)"),
    ("on_death_split", "沉默，阻止分裂(避免越打越多)",
     "死亡或半血时分裂出多个造物"),
    ("on_death_trigger", "沉默，阻止死亡/受击触发的特效",
     "被击倒或受击时触发爆炸/毒雾/暴露等"),
    ("enemy_aura_buff", "沉默，关闭敌方团队增益光环",
     "为周围敌军持续提供防御/法抗等加成"),
    ("team_debuff", "沉默，阻止其削弱/暴露我方",
     "降低我方攻击/攻速或使我方暴露"),
    ("on_hit_control", "沉默，阻止攻击触发的晕眩/束缚/吞噬",
     "数次攻击或直击后造成晕眩/束缚/吞噬"),
    ("summon_charge", "沉默，阻止召唤/充能/造物强化",
     "召唤造物、为城防炮充能或强化重生造物"),
    ("elemental_dot", "沉默，压制其持续元素/法术损伤爆发",
     "持续造成法术/灼燃/凋亡等元素损伤"),
    ("attack_proc", "沉默，压制其攻击强化特效",
     "连击/溅射/多目标/直击/攻击提升等触发特效"),
    ("other_silence", "沉默可使其特殊能力失效(机制待人工细化)",
     "可沉默但暂未归入上述机制族"),
]
FAMILY_IDS = [f[0] for f in FAMILIES]
FAMILY_LABEL = {fid: label for fid, label, _ in FAMILIES}
FAMILY_ABILITY = {fid: ability for fid, _, ability in FAMILIES}
REFRACTION_FAMILY = "refraction_essence"

DEATH_KW = ["死亡时", "死亡后", "被击倒时", "被击倒后", "被消灭时", "倒下时",
            "首次受到伤害", "生命值首次低于一半"]
COLD_KW = ["寒冷", "冻结"]
CONTROL_KW = ["晕眩", "束缚", "吞噬", "麻痹"]
SUMMON_KW = ["召唤", "充能", "重生造物", "造物的攻击力"]
ELEMENTAL_KW = ["灼燃损伤", "凋亡损伤", "神经损伤", "元素损伤", "持续造成法术伤害"]
AURA_KW = ["为周围敌军", "持续提供"]
DEBUFF_KW = ["我方单位", "我方", "攻击者"]
DEBUFF_NEG = ["降低", "暴露", "下降"]
PROC_KW = ["溅射", "直击", "弩箭", "爆破弹", "额外攻击", "下一次攻击",
           "首次攻击", "攻击力大幅", "额外攻击一个"]


def mv(x):
    return x.get("m_value") if isinstance(x, dict) and "m_value" in x else x


def load(name):
    with open(os.path.join(GD, name), encoding="utf-8") as fh:
        return json.load(fh)


def classify_text(text):
    """Return the mechanic family a single ability string belongs to (or None)."""
    if not text:
        return None
    is_death = any(k in text for k in DEATH_KW)
    if is_death and any(k in text for k in COLD_KW):
        return "on_death_cold_explosion"
    if "分裂" in text:
        return "on_death_split"
    if is_death:
        return "on_death_trigger"
    if any(k in text for k in AURA_KW) and ("加成" in text or "提供" in text):
        return "enemy_aura_buff"
    if any(k in text for k in DEBUFF_KW) and any(k in text for k in DEBUFF_NEG):
        return "team_debuff"
    if any(k in text for k in CONTROL_KW):
        return "on_hit_control"
    if any(k in text for k in SUMMON_KW):
        return "summon_charge"
    if any(k in text for k in ELEMENTAL_KW):
        return "elemental_dot"
    if any(k in text for k in PROC_KW):
        return "attack_proc"
    return None


def build():
    catalog = load(os.path.join(ROOT, "data", "enemy_catalog.json"))["enemies"]
    hb = load("enemy_handbook_table.json")["enemyData"]

    cases = []
    family_members = {fid: [] for fid in FAMILY_IDS}
    family_members[REFRACTION_FAMILY] = []
    review = []

    for cname, entry in sorted(catalog.items()):
        silence_texts, all_texts = [], []
        for eid in entry.get("enemy_ids", []):
            rec = hb.get(eid)
            if not rec:
                continue
            for ab in (rec.get("abilityList") or []):
                text = mv(ab.get("text")) or ""
                if not text:
                    continue
                all_texts.append(text)
                if ab.get("textFormat") == "SILENCE" and text not in silence_texts:
                    silence_texts.append(text)
        if not silence_texts:
            continue  # only SILENCE-flagged enemies enter this library

        is_refraction = any(("折射" in t) for t in silence_texts)
        families = []
        for t in silence_texts:
            fam = classify_text(t)
            if fam and fam not in families:
                families.append(fam)

        if is_refraction:
            primary = REFRACTION_FAMILY
            generic_covered = True
        else:
            if not families:
                families = ["other_silence"]
            primary = families[0]
            generic_covered = False
        needs_review = primary == "other_silence"
        if needs_review:
            review.append(cname)

        family_members.setdefault(primary, []).append(cname)
        cases.append({
            "name": cname,
            "enemy_ids": entry.get("enemy_ids", []),
            "generic_trait_keys": entry.get("trait_keys", []),
            "primary_mechanic": primary,
            "all_mechanics": families,
            "counter_tag": "silence",
            "ability_label": FAMILY_ABILITY.get(
                primary, "折射(法术折减)本体，主对策为法系/穿甲"),
            "counter_label": FAMILY_LABEL.get(
                primary, "折射本体：沉默非首选，优先法系/穿甲输出"),
            "generic_covered": generic_covered,
            "needs_review": needs_review,
            "evidence": {
                "official_textformat": "SILENCE",
                "official_ability_text": silence_texts,
                "prts": PRTS_SILENCE,
            },
        })

    doc = {
        "_meta": {
            "description": "敌人特例对策层：收录官方手册 textFormat==SILENCE 的全部敌人，"
                           "按机制族归类、统一反制标签 silence。generic_covered=true 的折射族"
                           "仅存档不参与运行时补缺；其余敌人按具体敌人名触发 gate0 沉默缺口。"
                           "运行期不读取敌人介绍文本，只读本库的族标签与证据。",
            "generated_by": "tools/build_enemy_special_cases.py",
            "source_tables": "data/source/gamedata/enemy_handbook_table.json + enemy_catalog.json (gitignored)",
            "activation_rule": "仅当某敌人名在本表层且 generic_covered=false 时，才追加沉默特例对策分",
            "silence_counter_sources": [
                "operator:拉普兰德", "operator:荒芜拉普兰德", "operator:霍尔海雅",
                "item:奥术法阵(失去特殊能力)", "bond:精准(3人里程碑附加沉默)",
            ],
            "family_order": [REFRACTION_FAMILY] + FAMILY_IDS,
            "case_count": len(cases),
            "active_case_count": sum(1 for c in cases if not c["generic_covered"]),
            "generic_covered_count": sum(1 for c in cases if c["generic_covered"]),
            "needs_review": review,
        },
        "special_cases": cases,
    }
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    doc = build()
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2, sort_keys=False)
    # family breakdown is derived from the built doc, so build() stays a
    # single-document function compatible with the build_data.py orchestrator.
    family_members = {}
    for c in doc["special_cases"]:
        family_members.setdefault(c["primary_mechanic"], []).append(c["name"])
    review = doc["_meta"]["needs_review"]
    print("wrote %s" % args.out)
    print("total %d | active(runtime) %d | generic_covered %d | needs_review %d" %
          (doc["_meta"]["case_count"], doc["_meta"]["active_case_count"],
           doc["_meta"]["generic_covered_count"], len(review)))
    for fid, members in family_members.items():
        if not members:
            continue
        print("\n  %-24s %2d敌 %s" % (fid, len(members), "、".join(members)))
    if review:
        print("\n!! NEEDS REVIEW (unmatched families): %s" % "、".join(review))


if __name__ == "__main__":
    main()
