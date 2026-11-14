# -*- coding: utf-8 -*-
"""Bond stack-growth feasibility (叠层可行性) for ALL bonds.

A bond's milestones only pay off if its layers can actually be grown, and
different bonds are very different to stack: 远见's named stackers only appear
at tier 4+, while 投资人 gets a free passive injection from 锡人 at tier 2.
This turns the universal stack_sources registry into a comparable 0..1
feasibility factor per bond, so bond-level scoring (economy engines today,
大羁绊 milestone planning later) can discount paper value by how hard it is to
realize.

Four explainable sub-scores, each in 0..1, combined with fixed weights:
  timing   : earliest shop tier that offers a direct stacker (early = easy)
  breadth  : count of distinct direct stacker operators (not single-card dependent)
  means    : how easy the trigger is (hold-passive > operations > aura > combat)
  rate     : average fixed layer amount per trigger (dynamic amounts -> neutral)
Generic ('*') auras/passives held by a bond's own members add a small bonus;
cap boosters never count (they raise caps, they do not produce layers).

Stdlib only, deterministic. No live stack tracking (that is the bond_stacks
layer); this is a static "how growable is this bond" profile.
"""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Trigger means -> ease weight in 0..1 (higher = easier to grow layers).
MEANS_EASE = {
    "passive_or_other": 1.00,   # held operator auto-stacks the active bond
    "end_of_rest": 0.95,        # automatic rest-end growth, no gold/combat
    "start_of_rest": 0.90,      # automatic rest-start growth
    "on_acquire": 0.90,         # fires when the operator is acquired (passive)
    "op_acquire": 0.85,         # rest-phase operation: buy an operator
    "op_refresh": 0.80,         # rest-phase operation: refresh the shop
    "on_sell": 0.70,            # rest-phase operation: sell an operator
    "battle_start": 0.65,       # automatic at battle start
    "battle_end": 0.65,         # automatic at battle end
    "convert_transient": 0.55,  # transient -> fixed conversion mechanic
    "aura_adjacent": 0.55,      # needs adjacency positioning
    "aura_front": 0.50,         # needs front-cell positioning
    "on_deploy": 0.50,          # combat: on deployment
    "on_skill": 0.40,           # combat: requires skill activation
    "on_kill": 0.35,            # combat: requires kills in range
    "on_affliction": 0.30,      # combat: requires applying an affliction
}

# blend weights for the four continuous-growth sub-scores (sum to 1.0).
# Rate now dominates: per user, combat/battle-growth engines with a high
# per-round layer capacity grow faster and better than cheap buy-triggered
# passives, so operational ease (means) is down-weighted relative to raw rate.
W_TIMING, W_BREADTH, W_MEANS, W_RATE = 0.25, 0.20, 0.15, 0.40
BREADTH_FULL_AT = 5.0      # 5 distinct stackers -> breadth saturates
AMOUNT_FULL_AT = 6.0       # avg 6 layers/trigger -> per-trigger amount saturates
CAP_FULL_AT = 20.0         # 20 layers/round capacity -> throughput saturates
# inside rate, per-round throughput outweighs a single big trigger
W_CAP, W_AMOUNT = 0.65, 0.35
GENERIC_BONUS_CAP = 0.10   # generic stackers add at most +10%
# Final factor = continuous-growth core (the engine that grows a large stack)
# blended with startup (one-shot injection that seeds layers early).
W_CONTINUOUS, W_STARTUP = 0.85, 0.15
INJECTION_FULL_AT = 3.0    # 3 distinct injection operators -> startup saturates


def _load(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _timing_score(earliest_tier):
    if not earliest_tier:
        return 0.0
    # tier 1 -> 1.0, tier 6 -> ~0.17
    return round(max(0.0, (7.0 - earliest_tier) / 6.0), 3)


# Positioning difficulty (the `scope` field) discounts trigger ease: an
# end-of-rest aura that must sit in the front cell is less effortless than a
# self-targeted one. Multiplicative, so it never changes the trigger ranking.
SCOPE_PENALTY = {
    "self_or_named": 1.00,
    "reserve": 0.95,        # reserve-zone-wide, low positioning demand
    "same_row": 0.90,
    "front_cell": 0.85,     # must occupy the cell directly ahead
    "adjacent": 0.85,       # needs an 8/4-cell neighbour
}


def _means_ease(records):
    if not records:
        return 0.0
    weights = [
        MEANS_EASE.get(r["means"], 0.3) * SCOPE_PENALTY.get(r.get("scope"), 1.0)
        for r in records
    ]
    # best available trigger dominates, average avoids one fluke source
    return round(0.6 * max(weights) + 0.4 * (sum(weights) / len(weights)), 3)


def _rate_score(records):
    """Growth throughput 0..1 from two factors:
      cap    : best per-round layer capacity (how fast a stack can ramp),
      amount : average fixed layers per trigger (how big each tick is).
    Sources without an explicit per-round cap fall back to their fixed amount
    as the throughput proxy; all-dynamic sources stay neutral, never guessed.
    """
    base = [r for r in records if r.get("shape") != "cap_booster"]
    caps = [r["cap"] for r in base
            if r.get("cap_scope") == "per_round" and r.get("cap")]
    fixed = [r["amount"] for r in base if r.get("amount") is not None]

    if not caps and not fixed:
        return 0.5  # all dynamic: neutral, do not punish or reward blind

    if caps:
        cap_part = min(1.0, max(caps) / CAP_FULL_AT)
    elif fixed:
        # uncapped passive: assume its per-tick amount is the rough throughput
        cap_part = min(1.0, (sum(fixed) / len(fixed)) / AMOUNT_FULL_AT)
    else:
        cap_part = 0.5

    amount_part = (min(1.0, (sum(fixed) / len(fixed)) / AMOUNT_FULL_AT)
                   if fixed else 0.5)
    return round(W_CAP * cap_part + W_AMOUNT * amount_part, 3)


def _startup_score(injection_recs):
    """0..1 ability to seed layers early via one-shot injections."""
    if not injection_recs:
        return 0.0
    base_form = [r for r in injection_recs if r.get("form") != "进阶"] or injection_recs
    injectors = {r["operator"] for r in base_form}
    breadth = min(1.0, len(injectors) / INJECTION_FULL_AT)
    earliest = min((r["shop_tier"] for r in base_form if r.get("shop_tier")), default=None)
    timing = _timing_score(earliest)
    return round(0.6 * timing + 0.4 * breadth, 3)


def feasibility_report(registry=None, operators=None):
    """Return {bond: {factor, grade, sub-scores..., details}} for every bond
    that has at least one named (direct) stack source."""
    registry = registry or _load("stack_sources.json")
    operators = operators or _load("operators.json")
    sources = registry["sources"]
    members = {o["name"]: o.get("bonds", []) for o in operators}

    # direct (named-bond) sources, excluding cap boosters, split by growth mode.
    # continuous = post-activation re-triggering engine (grows large stacks);
    # injection = one-shot startup lump granted without an active requirement.
    direct, injections = {}, {}
    for r in sources:
        if r["target_bond"] == "*" or r["shape"] == "cap_booster":
            continue
        if r.get("growth_mode") == "injection":
            injections.setdefault(r["target_bond"], []).append(r)
        else:
            direct.setdefault(r["target_bond"], []).append(r)

    # generic sources index by the bonds their owning operator belongs to
    generic_by_bond = {}
    for r in sources:
        if r["target_bond"] != "*" or r["shape"] == "cap_booster":
            continue
        for b in members.get(r["operator"], []):
            generic_by_bond.setdefault(b, set()).add(r["operator"])

    report = {}
    all_bonds = set(direct) | set(injections)
    for bond in sorted(all_bonds):
        recs = direct.get(bond, [])
        inj_recs = injections.get(bond, [])
        base_form = [r for r in recs if r.get("form") != "进阶"] or recs
        inject_form = [r for r in inj_recs if r.get("form") != "进阶"] or inj_recs
        stackers = {r["operator"] for r in base_form}
        injectors = {r["operator"] for r in inject_form}
        earliest = min((r["shop_tier"] for r in base_form if r.get("shop_tier")),
                       default=None)
        timing = _timing_score(earliest)
        breadth = round(min(1.0, len(stackers) / BREADTH_FULL_AT), 3)
        means = _means_ease(base_form)
        rate = _rate_score(base_form)

        core = (W_TIMING * timing + W_BREADTH * breadth +
                W_MEANS * means + W_RATE * rate)
        generic_helpers = sorted(generic_by_bond.get(bond, set()))
        generic_bonus = min(GENERIC_BONUS_CAP, 0.03 * len(generic_helpers))
        continuous_factor = round(min(1.0, core + generic_bonus), 3)
        startup = _startup_score(inj_recs)
        factor = round(W_CONTINUOUS * continuous_factor + W_STARTUP * startup, 3)

        grade = "高" if factor >= 0.75 else ("中" if factor >= 0.55 else "低")
        report[bond] = {
            "factor": factor,
            "grade": grade,
            "continuous_factor": continuous_factor,
            "startup_score": startup,
            "earliest_tier": earliest,
            "continuous_stacker_count": len(stackers),
            "injector_count": len(injectors),
            "stackers": sorted(stackers),
            "injectors": sorted(injectors),
            "sub_scores": {
                "timing": timing, "breadth": breadth,
                "means_ease": means, "rate": rate,
            },
            "generic_helpers": generic_helpers,
            "means_used": sorted({r["means"] for r in base_form}),
            "dynamic_sources": sum(1 for r in base_form if r.get("amount_dynamic")),
        }
    return report


def feasibility_factor(bond, report=None):
    """0..1 growability factor for one bond; unknown bond -> neutral 0.5."""
    report = report or feasibility_report()
    return report.get(bond, {}).get("factor", 0.5)


def write_report(path=None):
    path = path or os.path.join(DATA_DIR, "stack_feasibility.json")
    report = feasibility_report()
    ordered = dict(sorted(report.items(), key=lambda kv: kv[1]["factor"], reverse=True))
    out = {
        "_meta": {
            "description": "全羁绊叠层可行性因子(0~1，越高越容易养大层数)。持续叠加(激活后反复触发)"
                           "占%.0f%%，按时机%.2f/广度%.2f/手段%.2f/速率%.2f 四维加权，通用叠层手至多+%.2f；"
                           "单次注入(获得即给层的启动能力)占%.0f%%。静态画像，不含实时层数。" %
                           (W_CONTINUOUS * 100, W_TIMING, W_BREADTH, W_MEANS, W_RATE,
                            GENERIC_BONUS_CAP, W_STARTUP * 100),
            "grade_rule": "高>=0.75, 中>=0.55, 低<0.55",
            "means_ease": MEANS_EASE,
        },
        "bonds": ordered,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return path, ordered


if __name__ == "__main__":
    import sys
    io = sys.stdout
    path, report = write_report()
    for bond, r in report.items():
        s = r["sub_scores"]
        print("%-6s 可行性%.2f[%s] 持续%.2f 启动%.2f | 最早%s本 持续手%d 注入手%d | 时机%.2f 广度%.2f 手段%.2f 速率%.2f" %
              (bond, r["factor"], r["grade"], r["continuous_factor"], r["startup_score"],
               r["earliest_tier"], r["continuous_stacker_count"], r["injector_count"],
               s["timing"], s["breadth"], s["means_ease"], s["rate"]))
    print("written", path)
