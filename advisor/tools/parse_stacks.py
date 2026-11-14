# -*- coding: utf-8 -*-
"""Parse ALL bond-stack sources from operators.json into stack_sources.json.

A bond's power lives in its layer (层数) milestones, and layers do not grow by
themselves: specific operators add them through specific means. This builds a
general registry across EVERY bond (core + attached, not just the economy
bonds) so later "how to grow large stacks" logic and a bond_stacks layer have
structured data instead of re-parsing free text.

One operator entry can add layers to several bonds at once (e.g. 黍 gives
炎+8 and 远见+4), so we emit one source record PER target bond.

Entry sentence shapes handled (see tools probe):
  named_plus_n     【X】层数+N
  recurring_capped ...（每回合至多叠加K层）
  battle_capped    ...（每场战斗至多叠加K层）
  dynamic_var      uses {showtag_value_1} template (amount runtime-dependent)
  generic_aura     "已激活的盟约层数+N" (no named bond -> applies to active bonds)
  dynamic_amount   amount tied to dispatch level / sell price
  convert_transient 临时层数 -> 固定层数
  cap_booster      raises stacking cap (not a direct layer source)
  other/强化       special, flagged for review

Stdlib only. Deterministic. Run: python tools/parse_stacks.py
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

BOND_RE = re.compile(r"【([^】]+)】")
PLUS_N_RE = re.compile(r"层数\s*\+\s*(\d+)")
ROUND_CAP_RE = re.compile(r"每回合至多叠加\s*(\d+)\s*层")
BATTLE_CAP_RE = re.compile(r"每场战斗至多叠加\s*(\d+)\s*层")
PERCENT_CAP_RE = re.compile(r"叠层上限\s*\+\s*(\d+)\s*%")
FLAT_CAP_RE = re.compile(r"叠层上限\s*\+\s*(\d+)(?!\s*%)")
CONVERT_RE = re.compile(r"转化\s*(\d+)\s*层【([^】]+)】临时层数")


# Raw trigger-timing tags (from parse_timing.py, since clean() deletes the
# angle brackets) mapped onto the means vocabulary used by the feasibility
# layer. Data-driven; replaces the old hand-written single-name override.
TIMING_TAG_MEANS = {
    "休整期结束时": "end_of_rest",      # automatic per rest-end growth
    "进入休整期时": "start_of_rest",
    "休整期开始时": "start_of_rest",
    "获得时": "on_acquire",            # fires once when the operator is acquired
    "售出时": "on_sell",
    "刷新时": "op_refresh",
    "开启技能时": "on_skill",
    "战斗开始时": "battle_start",
    "战斗结束时": "battle_end",
}
_TIMING_CACHE = None


def _timing_index():
    """Lazy-load {operator: {form: [tags]}} from operator_timing.json."""
    global _TIMING_CACHE
    if _TIMING_CACHE is None:
        path = os.path.join(DATA, "operator_timing.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _TIMING_CACHE = json.load(f).get("by_operator", {})
        else:
            _TIMING_CACHE = {}
    return _TIMING_CACHE


def timing_means_for(operator_name, form=None):
    """Resolve a means class from extracted trigger-timing tags, or None."""
    forms = _timing_index().get(operator_name)
    if not forms:
        return None
    tags = forms.get(form) if form else next(iter(forms.values()), [])
    for tag in tags or []:
        if tag in TIMING_TAG_MEANS:
            return TIMING_TAG_MEANS[tag]
    return None


def trigger_means(trait, operator_name=None, form=None):
    """Classify HOW the layers are produced (drives stacking difficulty).

    Prefer the explicit trigger-timing tag recovered from the raw wikitext;
    fall back to trait-text heuristics for entries without a timing tag.
    """
    tagged = timing_means_for(operator_name, form) if operator_name else None
    if tagged:
        return tagged
    if "每进行过1次刷新" in trait or "首次主动刷新" in trait or ("刷新" in trait and "层数" in trait):
        return "op_refresh"          # 休整期运营：刷新
    if "每获得过一名干员" in trait or "获得过一名干员" in trait:
        return "op_acquire"          # 休整期运营：获得干员
    if "部署时" in trait:
        return "on_deploy"           # 战斗：部署触发
    if "开启技能" in trait or "开技能" in trait:
        return "on_skill"            # 战斗：开技能
    if "敌人被击倒" in trait or "击倒" in trait:
        return "on_kill"             # 战斗：击杀
    if "陷入" in trait or "异常状态" in trait:
        return "on_affliction"       # 战斗：异常状态
    if "身前一格" in trait:
        return "aura_front"          # 光环：身前格站位
    if "周围八格" in trait or "周围四格" in trait:
        return "aura_adjacent"       # 光环：周围格
    if "转化" in trait:
        return "convert_transient"   # 临时转固定
    return "passive_or_other"


def effect_scope(trait):
    """WHO receives the layers (distinct from WHEN it triggers).
    Timing lives in `means`; positioning difficulty lives here so the front-cell
    / adjacency requirement is not lost once means becomes trigger-timing."""
    if "身前一格" in trait or "身后一格" in trait:
        return "front_cell"
    if "周围八格" in trait or "周围四格" in trait or "周围" in trait:
        return "adjacent"
    if "整备区每名" in trait or "整备区每有一名" in trait:
        return "reserve"
    if "同一行" in trait:
        return "same_row"
    return "self_or_named"


def growth_mode(kind, trait):
    """Distinguish one-shot layer injection from post-activation continuous growth.

    injection  : '【X】层数+N' with no active requirement (kind=单次叠加) -> a
                 startup lump granted once on acquire/deploy, helps reach a
                 milestone early but cannot keep feeding layers.
    continuous: '使已激活的【X】层数+N' (kind=持续叠加) -> only works once the bond
                 is active and re-triggers (kill/skill/each round); this is the
                 engine that actually grows a large stack.
    Cap boosters/conversions are neither direct layer source; tagged separately.
    """
    if "叠层上限" in trait:
        return "cap_booster"
    if kind == "单次叠加" and "已激活" not in trait:
        return "injection"
    return "continuous"


def parse_cap(trait):
    m = ROUND_CAP_RE.search(trait)
    if m:
        return {"cap_scope": "per_round", "cap": int(m.group(1))}
    m = BATTLE_CAP_RE.search(trait)
    if m:
        return {"cap_scope": "per_battle", "cap": int(m.group(1))}
    return {"cap_scope": None, "cap": None}


def parse_entry(operator, entry):
    """Return a list of stack-source records for one operator entry."""
    trait = entry.get("trait", "")
    kind = entry.get("kind", "")
    form = entry.get("form", "")
    if "叠加" not in kind:
        return []

    base = {
        "operator": operator["name"],
        "shop_tier": operator.get("shop_tier"),
        "star": operator.get("star"),
        "form": form,
        "kind": kind,
        "growth_mode": growth_mode(kind, trait),
        "means": trigger_means(trait, operator["name"], form),
        "scope": effect_scope(trait),
        "trait": trait,
    }
    base.update(parse_cap(trait))
    named_bonds = BOND_RE.findall(trait)
    records = []

    # ---- cap booster: raises a stacking cap, does not directly add layers ----
    if "叠层上限" in trait and (PERCENT_CAP_RE.search(trait) or FLAT_CAP_RE.search(trait)):
        pm, fm = PERCENT_CAP_RE.search(trait), FLAT_CAP_RE.search(trait)
        for b in named_bonds or ["*"]:
            rec = {**base, "target_bond": b, "shape": "cap_booster",
                   "amount": None, "amount_dynamic": True}
            if pm:
                rec["cap_bonus_pct"] = int(pm.group(1))
            if fm:
                rec["cap_bonus_flat"] = int(fm.group(1))
            records.append(rec)
        return records

    # ---- transient -> fixed conversion ----
    if "转化" in trait and "临时层数" in trait:
        for m in CONVERT_RE.finditer(trait):
            records.append({**base, "target_bond": m.group(2),
                            "shape": "convert_transient",
                            "amount": int(m.group(1)), "amount_dynamic": False})
        if not records:  # conversion with an unparsed amount
            for b in named_bonds or ["*"]:
                records.append({**base, "target_bond": b,
                                "shape": "convert_transient",
                                "amount": None, "amount_dynamic": True})
        return records

    # ---- generic aura / generic active-bond stacking (no named bond) ----
    generic = ("盟约层数" in trait) and not named_bonds
    if generic:
        amount_m = PLUS_N_RE.search(trait)
        records.append({**base, "target_bond": "*", "shape": "generic_active_bond",
                        "amount": int(amount_m.group(1)) if amount_m else None,
                        "amount_dynamic": amount_m is None})
        return records

    # ---- dynamic amount tied to level / sell price ----
    if "等同于" in trait and "层数" in trait:
        for b in named_bonds or ["*"]:
            records.append({**base, "target_bond": b, "shape": "dynamic_amount",
                            "amount": None, "amount_dynamic": True})
        return records

    # ---- named bond(s): split per bond, read each 【X】...层数+N ----
    if named_bonds:
        # find every "(bonds...) 层数+N" clause; simplest robust approach: for
        # each named bond, find the nearest +N after its bracket.
        dynamic = "{showtag_value" in trait
        for b in named_bonds:
            # locate this bond's bracket and search the following short window
            idx = trait.find("【%s】" % b)
            window = trait[idx: idx + 40] if idx >= 0 else trait
            m = PLUS_N_RE.search(window) or PLUS_N_RE.search(trait)
            shape = "named_plus_n"
            if base["cap_scope"] == "per_round":
                shape = "recurring_capped"
            elif base["cap_scope"] == "per_battle":
                shape = "battle_capped"
            elif dynamic:
                shape = "dynamic_var"
            records.append({**base, "target_bond": b, "shape": shape,
                            "amount": int(m.group(1)) if (m and not dynamic) else None,
                            "amount_dynamic": dynamic or m is None})
        return records

    # ---- fallback: stacking entry we could not map ----
    records.append({**base, "target_bond": "*", "shape": "other",
                    "amount": None, "amount_dynamic": True, "needs_review": True})
    return records


def main():
    ops = json.load(open(os.path.join(DATA, "operators.json"), encoding="utf-8"))
    sources, review = [], []
    seen = set()
    for o in ops:
        for e in o.get("entries", []):
            for rec in parse_entry(o, e):
                key = (rec["operator"], rec["form"], rec["target_bond"],
                       rec["shape"], rec["trait"])
                if key in seen:
                    continue
                seen.add(key)
                sources.append(rec)
                if rec.get("needs_review"):
                    review.append(rec)

    # summary per bond
    by_bond = {}
    for r in sources:
        by_bond.setdefault(r["target_bond"], []).append(r)

    out = {
        "_meta": {
            "description": "全羁绊叠层来源注册表：每个干员条目如何给目标羁绊增加层数。"
                           "target_bond='*' 表示对任意已激活盟约通用。amount_dynamic=True "
                           "表示层数运行时决定（模板变量/调度等级/售价），静态只记录手段。",
            "means_glossary": {
                "op_refresh": "运营-刷新触发", "op_acquire": "运营-获得干员触发",
                "on_deploy": "战斗-部署触发", "on_skill": "战斗-开技能触发",
                "on_kill": "战斗-击杀触发", "on_affliction": "战斗-异常状态触发",
                "aura_front": "光环-身前格", "aura_adjacent": "光环-周围格",
                "convert_transient": "临时层数转固定", "passive_or_other": "被动/其他",
            },
            "shape_glossary": {
                "named_plus_n": "点名羁绊固定+N", "recurring_capped": "每回合计数带上限",
                "battle_capped": "每场战斗计数带上限", "dynamic_var": "模板变量动态层数",
                "dynamic_amount": "层数挂钩等级/售价", "generic_active_bond": "通用已激活盟约",
                "convert_transient": "临时转固定", "cap_booster": "提升叠层上限",
                "other": "待人工复核",
            },
            "total_sources": len(sources),
            "needs_review": len(review),
        },
        "sources": sources,
    }
    path = os.path.join(DATA, "stack_sources.json")
    json.dump(out, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # console summary
    print("stack sources:", len(sources), "| needs_review:", len(review))
    for bond in sorted(by_bond):
        rows = by_bond[bond]
        direct = [r for r in rows if r["shape"] not in ("cap_booster",)]
        earliest = min((r["shop_tier"] for r in direct if r["shop_tier"]), default=None)
        means = sorted({r["means"] for r in direct})
        print("  %-6s 来源%2d 最早%s本 手段=%s" %
              (bond, len(rows), earliest, ",".join(means)))
    if review:
        print("REVIEW:")
        for r in review:
            print("  ", r["operator"], r["trait"][:60])
    print("written", path)


if __name__ == "__main__":
    main()
