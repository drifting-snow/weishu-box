# -*- coding: utf-8 -*-
"""Static weakness/counter matching.

Maps the nine tactical-training enemy types (data/enemy_traits.json) to the
counter capabilities an operator can provide. Capabilities have four sources:

  profession : anti-air inferred from branch/position (operator.anti_air)
  mechanic   : operator.mechanic_tags (talent + skill + trait keyword tags)
  bond       : bond milestone effects, manually curated below with the unlock
               threshold (e.g. 奥术 3 distinct operators -> anti_stealth)
  item       : equipment granting a counter (e.g. 奥术法阵 -> silence)

Bond-sourced counters are team-level and only active once the milestone count
is reached; counter_score reports how many operators are still missing so the
advisor can explain "one more 奥术 unlocks anti-stealth". No combat simulation.
"""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Manually curated bond-milestone -> counter tags, verified against
# bonds_structured.json milestone text. Keyed by bond name with the unlock
# condition. `need` is the distinct-operator threshold; base-level effects use
# need = activation count.
BOND_COUNTERS = {
    "奥术": [{"need": 3, "trigger": "distinct_operator", "tags": ["anti_stealth", "def_pierce"],
             "why": "3人里程碑：敌人隐匿失效且法术抗性降低"}],
    "乌萨斯": [{"need": 6, "trigger": "distinct_operator", "tags": ["bleed_dot", "dot"],
               "why": "6人里程碑：伤害转生命流失(流血)+阻挡法术伤害"}],
    "精准": [{"need": 3, "trigger": "distinct_operator", "tags": ["def_pierce"],
             "why": "3人里程碑：无视一定防御力和法术抗性"}],
    "萨尔贡": [{"need": 6, "trigger": "distinct_operator", "tags": ["cc"],
               "why": "6人里程碑：流沙束缚+迟钝"}],
    "谢拉格": [{"need": 6, "trigger": "distinct_operator", "tags": ["cc"],
               "why": "6人里程碑：雪山巨人，寒冷冻结体系"}],
    "叙拉古": [{"need": 6, "trigger": "distinct_operator", "tags": ["cc", "true_damage"],
               "why": "6人里程碑：异常状态+2种异常时真实伤害"}],
    "卡西米尔": [{"need": 6, "trigger": "distinct_operator", "tags": ["true_damage"],
                 "why": "6人里程碑：攻击附带65%真实伤害+击倒召唤"}],
    "伊比利亚": [{"need": 6, "trigger": "distinct_operator", "tags": ["dot"],
                 "why": "6人里程碑：持续法术伤害翻倍+减速"}],
    "炎": [{"need": 6, "trigger": "distinct_operator", "tags": ["dot"],
            "why": "6人里程碑：攻击附加随机元素损伤(大羁绊元素体系)"}],
    "坚守": [{"need": 3, "trigger": "distinct_operator", "tags": ["damage_soak"],
             "why": "3人里程碑：非坚守干员所受伤害40%由坚守干员承担"}],
    "聚合": [
        {"need": 2, "trigger": "activation", "tags": ["shield_heal"],
         "why": "激活：攻击范围内持续治疗与元素损伤回复"},
        {"need": 3, "trigger": "distinct_operator", "tags": ["shelter"],
         "why": "3人里程碑：范围内干员获得庇护"},
    ],
    "不屈": [{"need": 2, "trigger": "activation", "tags": ["revive"],
             "why": "激活：地面干员被击倒时概率立即重新部署"}],
    "阿戈尔": [{"need": 6, "trigger": "distinct_operator", "tags": ["revive"],
               "why": "6人里程碑：前3名阿戈尔干员首次被击倒立即复活"}],
}

# Item -> counter tag (equipment that grants a mechanic the base kit lacks).
ITEM_COUNTER_KEYWORDS = [
    ("silence", "失去特殊能力"),
]


def load_enemy_types():
    with open(os.path.join(DATA_DIR, "enemy_traits.json"), encoding="utf-8") as f:
        return json.load(f)["enemy_types"]


def operator_native_tags(operator) -> set:
    """Tags an operator brings on its own (profession + mechanics), no bonds."""
    tags = set(operator.get("mechanic_tags", []))
    if operator.get("anti_air"):
        tags.add("anti_air")
    return tags


def item_counter_tag(item) -> str:
    """Return the counter tag an equipment grants, or None."""
    text = (item.get("base", "") or "") + (item.get("advanced", "") or "")
    for tag, kw in ITEM_COUNTER_KEYWORDS:
        if kw in text:
            return tag
    return None


def bond_counter_plan(operator) -> list:
    """Bond-milestone counters this operator can help unlock, via its bonds."""
    plan = []
    for bond in operator.get("bonds", []):
        for spec in BOND_COUNTERS.get(bond, []):
            plan.append({"bond": bond, **spec})
    return plan


def counter_score(ds, operator, enemy_type_keys, bond_counts=None) -> dict:
    """Score one operator against a set of enemy type keys.

    enemy_type_keys: e.g. ["stealth", "flying"]. Empty/unknown -> neutral 0.
    bond_counts: current distinct-operator count per bond on the board, used to
    report unlock progress for bond-sourced counters.
    Returns {score, hits, locked, anti_synergy} with human-readable reasons.
    """
    enemy_types = load_enemy_types()
    bond_counts = bond_counts or {}
    wanted = {}   # tag -> aggregate weight across the given enemy types
    anti_flags = set()
    for key in enemy_type_keys:
        et = enemy_types.get(key)
        if not et:
            continue
        for tag, w in et["counter_tags"].items():
            wanted[tag] = max(wanted.get(tag, 0), w)
        anti_flags.update(et.get("anti_synergy", []))

    if not wanted:
        return {"score": 0.0, "hits": [], "locked": [], "anti_synergy": [],
                "neutral": True}

    score = 0.0
    hits, locked = [], []
    ready_tags = set()

    # 1) native tags (profession + talent/skill mechanics) always available
    native = operator_native_tags(operator)
    for tag in native:
        if tag in wanted:
            w = wanted[tag]
            score += 10.0 * w
            ready_tags.add(tag)
            hits.append({"tag": tag, "weight": w, "source": "native", "ready": True})

    # 2) bond-milestone tags this operator contributes toward
    for plan in bond_counter_plan(operator):
        for tag in plan["tags"]:
            if tag not in wanted:
                continue
            have = bond_counts.get(plan["bond"], 0)
            ready = have >= plan["need"]
            w = wanted[tag]
            if ready:
                score += 8.0 * w
                ready_tags.add(tag)
                hits.append({"tag": tag, "weight": w, "source": "bond",
                             "bond": plan["bond"], "ready": True, "why": plan["why"]})
            else:
                # partial credit: closer to unlock = more valuable, but flagged
                progress = min(1.0, have / plan["need"])
                score += 3.0 * w * progress
                locked.append({"tag": tag, "bond": plan["bond"],
                               "have": have, "need": plan["need"],
                               "missing": plan["need"] - have, "why": plan["why"]})

    # 3) anti-synergy penalties (soft, with a warning rather than a hard veto).
    # A counter already provided (native or an unlocked bond) suppresses the warn.
    anti = []
    if "ground_only" in anti_flags and "anti_air" not in ready_tags:
        score -= 6.0
        anti.append("无法对空，飞行敌人会漏掉")
    if "pure_arts_no_shred" in anti_flags and "def_pierce" not in ready_tags and \
            operator.get("prof") == "术师":
        score -= 4.0
        anti.append("纯法术遇折射被折减，且无削抗手段")
    if "no_anti_stealth" in anti_flags and "anti_stealth" not in ready_tags and \
            not any(l["tag"] == "anti_stealth" for l in locked):
        score -= 4.0
        anti.append("无反隐手段，难以命中隐匿敌人")

    return {"score": round(score, 1), "hits": hits, "locked": locked,
            "anti_synergy": anti, "neutral": False}
