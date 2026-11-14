# -*- coding: utf-8 -*-
"""Structure equipment effect text into three-axis scoring material.

items.json only carries raw base/advanced text. The unified impact ruler needs
machine-readable effects, so this parser turns the CLEAN, regex-extractable
parts into typed fields and honestly flags everything it cannot statically
score:

  stat_mods   : numeric combat modifiers (atk/hp/def %, aspd, sp, block, res),
                including negative values (a drawback that is itself numeric).
  drawbacks   : qualitative penalties (cannot be healed, HP drain, taunt...).
  stack_gain  : covenant-layer grants (future/growth axis).
  combo_of    : two-component merge target (state tracking deferred).
  mechanics   : keyword tags (silence/revive/cc/true_damage...) for later
                counter matching; not yet scored on the power axis.
  needs_review: True when a conditional / probabilistic / combo / dynamic effect
                is present. The numeric stat_mods are still extracted, but the
                conditional part is NOT scored until a combat/state layer exists.

Consumables (装备时销毁) are economy material and are parsed lightly; the
round-aware item_economy.py already owns their valuation.

Stdlib only, deterministic. Output: data/items_structured.json
Run   : python tools/parse_items.py
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "items.json")
OUT = os.path.join(ROOT, "data", "items_structured.json")

# ---- numeric stat patterns (group 1 = signed number) ----
# aspd has two units: flat points ("攻击速度+30") and percent ("攻击速度-25%").
_PAT = {
    "atk_pct":       re.compile(r"攻击力\s*([+\-]\d+)%"),
    "hp_pct":        re.compile(r"生命上限\s*([+\-]\d+)%"),
    "def_pct":       re.compile(r"防御力\s*([+\-]\d+)%"),
    "aspd_pct":      re.compile(r"攻击速度\s*([+\-]\d+)%"),
    # negative lookahead must also reject a digit, else "-25%" backtracks to
    # "-2" (next char '5') and gets double-counted alongside aspd_pct.
    "aspd_flat":     re.compile(r"攻击速度\s*([+\-]\d+)(?![\d%])"),
    "sp_cost_pct":   re.compile(r"(?:技能开启所需)?技力[^\d]{0,6}?([+\-]\d+)%"),
    "sp_regen":      re.compile(r"技力自然回复速度\s*([+\-][\d.]+)\s*/\s*秒"),
    "block":         re.compile(r"阻挡数\s*([+\-]\d+)"),
    "res":           re.compile(r"法术抗性\s*([+\-]\d+)"),
    "redeploy_pct":  re.compile(r"再部署时间\s*([+\-]\d+)%"),
}
# qualitative drawbacks (not a simple numeric stat)
_DRAWBACK = [
    ("unhealable",   re.compile(r"无法被治疗")),
    ("hp_drain_flat", re.compile(r"每秒流失\s*(\d+)\s*点生命值")),
    ("hp_drain_pct", re.compile(r"每秒流失\s*(\d+)\s*%最大生命值")),
    ("taunt_up",     re.compile(r"更容易受到攻击")),
]
# positive non-numeric utility (informational)
_UTILITY = [
    ("taunt_down",   re.compile(r"更不容易受到攻击")),
    ("regen_flat",   re.compile(r"每秒回复\s*(\d+)\s*点生命值")),
    ("regen_pct",    re.compile(r"每秒恢复\s*(\d+)\s*%最大生命值")),
]
# mechanic keyword -> tag (mirrors operator mechanic_tags vocabulary)
_MECHANIC = [
    ("silence",      re.compile(r"失去特殊能力")),
    ("revive",       re.compile(r"复活|重新部署|再部署时间")),
    ("cc",           re.compile(r"晕眩|冻结|寒冷|战栗|麻痹|束缚|停顿|恐惧")),
    ("true_damage",  re.compile(r"真实伤害|弱点伤害")),
    ("def_pierce",   re.compile(r"无视其?\d*%?防御|无视.*?法术抗性|法术抗性降低")),
    ("dot",          re.compile(r"灼燃|侵蚀|流血|生命流失")),
    ("shield_heal",  re.compile(r"护盾|治疗其|立刻治疗")),
    ("anti_stealth", re.compile(r"隐匿")),
    ("immunity",     re.compile(r"免疫")),
]
# covenant-layer grants
_STACK = re.compile(r"盟约(?:临时)?层数\s*([+\-]\d+)")
# two-component merge
_COMBO = re.compile(r"组合为“(.+?)”")
# conditional / state-dependent wording -> needs_review (non-consumables only)
# Concrete trigger/state wording. A bare "时" is intentionally excluded (too
# broad); specific triggers like 部署时/战斗时 are listed explicitly.
_CONDITIONAL = [
    "概率", "每次", "首次", "若", "组合为", "同时持有", "隐匿", "衰减",
    "叠加", "距离", "范围内", "元素爆发", "异常状态", "转化", "额外盟约",
    "场上所有", "击倒", "部署后", "部署时", "身前一格", "左右两侧",
    "造成伤害时", "造成法术伤害时", "攻击时", "被击倒时", "受到伤害时",
    "开启一次技能", "再部署时",
]


def _signed_int(m):
    return int(m.group(1))


def parse_item(it):
    text = (it.get("base", "") or ""
            if it.get("base") not in (None, "—") else "")
    consumable = "销毁" in text
    rec = {
        "name": it["name"],
        "tier": int(it["tier"]) if str(it.get("tier")).isdigit() else None,
        "price": int(it["price"]) if str(it.get("price")).isdigit() else None,
        "bond": it.get("bond") or None,
        "consumable": consumable,
        "stat_mods": {},
        "drawbacks": [],
        "utility": [],
        "mechanics": [],
        "stack_gain": None,
        "combo_of": None,
        "needs_review": False,
        "review_reasons": [],
    }

    # consumables are economy material; only capture stack grants / deploy cap.
    if consumable:
        m = _STACK.search(text)
        if m:
            rec["stack_gain"] = {"amount": int(m.group(1)), "transient": False,
                                 "requires_active": "已激活" in text}
        return rec

    # ---- numeric stats (last match wins; texts state each stat once) ----
    for key, rx in _PAT.items():
        m = rx.search(text)
        if m:
            val = float(m.group(1))
            rec["stat_mods"][key] = int(val) if val == int(val) else val

    # ---- qualitative drawbacks ----
    for kind, rx in _DRAWBACK:
        m = rx.search(text)
        if m:
            rec["drawbacks"].append(
                {"kind": kind, "value": int(m.group(1)) if m.groups() else None})

    # ---- positive utility ----
    for kind, rx in _UTILITY:
        m = rx.search(text)
        if m:
            rec["utility"].append(
                {"kind": kind, "value": int(m.group(1)) if m.groups() else None})

    # ---- mechanic tags ----
    for tag, rx in _MECHANIC:
        if rx.search(text):
            rec["mechanics"].append(tag)

    # ---- covenant-layer grant (non-consumable, e.g. 卫戍推荐信/多功能补剂) ----
    m = _STACK.search(text)
    if m:
        rec["stack_gain"] = {
            "amount": int(m.group(1)),
            "transient": "临时层数" in text,
            "requires_active": "已激活" in text,
        }

    # ---- combo target ----
    m = _COMBO.search(text)
    if m:
        rec["combo_of"] = m.group(1)

    # ---- needs_review: any conditional/state-dependent wording ----
    hits = [kw for kw in _CONDITIONAL if kw in text]
    # "时" is broad; only treat as conditional alongside a real trigger context.
    # Drop bare generic hits that are already fully captured as numeric stats.
    if hits:
        rec["needs_review"] = True
        rec["review_reasons"] = sorted(set(hits))
    return rec


def main():
    items = json.load(open(SRC, encoding="utf-8"))
    parsed = [parse_item(it) for it in items]

    clean = [p for p in parsed if not p["needs_review"] and not p["consumable"]]
    review = [p for p in parsed if p["needs_review"]]
    consum = [p for p in parsed if p["consumable"]]
    with_mods = [p for p in parsed if p["stat_mods"]]

    out = {
        "_meta": {
            "description": "装备效果结构化(三轴评分原料)。stat_mods 为可正则化的数值属性(含负值)，"
                           "drawbacks 为定性负面，stack_gain 为盟约加层，combo_of 为两件合成成品(状态跟踪后置)，"
                           "mechanics 为机制标签(暂不计战力分)。needs_review=True 表示含条件/概率/组合/动态效果，"
                           "其数值部分仍提取，但条件部分在战斗/状态层建立前不计分。消耗品走 item_economy。",
            "total": len(parsed),
            "clean_combat": len(clean),
            "needs_review": len(review),
            "consumables": len(consum),
            "with_numeric_mods": len(with_mods),
            "stat_keys": list(_PAT.keys()),
        },
        "items": parsed,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("items:", len(parsed),
          "| clean combat:", len(clean),
          "| needs_review:", len(review),
          "| consumables:", len(consum),
          "| with numeric mods:", len(with_mods))
    print("\n-- clean combat items (fully scorable now) --")
    for p in clean:
        print("  %-12s %s drawbacks=%s" % (p["name"], p["stat_mods"],
              [d["kind"] for d in p["drawbacks"]]))
    print("\n-- needs_review (numeric part kept, conditional part deferred) --")
    for p in review:
        print("  %-12s mods=%s reasons=%s" % (p["name"], p["stat_mods"],
              p["review_reasons"]))
    print("\nwritten", OUT)


if __name__ == "__main__":
    main()
