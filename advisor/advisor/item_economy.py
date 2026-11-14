# -*- coding: utf-8 -*-
"""Round-aware valuation of consumable economy items.

Many economy items do NOT pay off immediately:
  - immediate   : takes effect the same rest phase (盟约之币, 驮兽储蓄罐)
  - next_round  : pays off only next round (见钱眼开玩偶, 博士投影 base)
  - recurring   : produces gold every later round (精打细算玩偶, 定期存折)

Whether a delayed item is worth buying depends on how many rounds remain
(the payback window). A recurring gold item bought on the final rest phase can
never return its cost; the same item bought early is the strongest investment.

A full run is ~14-15 rounds (short challenge stages are 4/9). The engine passes
the current round and an expected total; default total comes from economy.json.

Classification is rule-based over the item text so no hand-maintained table of
16 items is needed. Stdlib only, deterministic.
"""
import re

DEFAULT_TOTAL_ROUNDS = 15

# timing
IMMEDIATE = "immediate"
NEXT_ROUND = "next_round"
RECURRING = "recurring"

# benefit categories
GOLD = "gold"
BOND_STACK = "bond_stack"
ELITE = "elite"
REFRESH = "refresh"
RECRUIT = "recruit"
ITEM = "item"
DEPLOY_CAP = "deploy_cap"
COMMAND = "command"
OTHER = "other"

# Heuristic utility per non-gold benefit (centralized tuning knobs).
BENEFIT_UTILITY = {
    RECRUIT: 18.0,     # free operator (otherwise 2-4 gold)
    ELITE: 30.0,       # instant elite promotion skips a 3-copy merge
    REFRESH: 14.0,
    BOND_STACK: 12.0,
    DEPLOY_CAP: 20.0,
    ITEM: 12.0,
    COMMAND: 8.0,
    OTHER: 4.0,
}
GOLD_PER_POINT = 10.0   # 1 expected gold maps to this many score points
DELAY_DISCOUNT = 0.9    # next-round payoff is slightly worse than immediate


def is_consumable(item) -> bool:
    return "销毁" in (item.get("base", "") or "")


def classify(item):
    """Return (timing, benefit) for a consumable item from its base text."""
    text = item.get("base", "") or ""
    if "每回合" in text:
        timing = RECURRING
    elif ("下回合" in text) or ("下个回合" in text):
        timing = NEXT_ROUND
    else:
        timing = IMMEDIATE

    benefit = OTHER
    if "资金" in text:
        benefit = GOLD
    elif "盟约层数" in text:
        benefit = BOND_STACK
    elif "晋升为精锐" in text:
        benefit = ELITE
    elif "刷新" in text:
        benefit = REFRESH
    elif re.search(r"干员", text) and re.search(r"获得|获取|出现", text):
        benefit = RECRUIT
    elif re.search(r"免费获取.*装备|出现\d+件装备", text):
        benefit = ITEM
    elif "最大可部署人数" in text:
        benefit = DEPLOY_CAP
    elif "指令" in text:
        benefit = COMMAND
    return timing, benefit


def effective_rounds_left(current_round: int, total_rounds: int) -> int:
    """Rounds in which a recurring/next-round effect can still pay off.

    A recurring item triggers at the START of later rounds, so the round it is
    bought in does not count. Window = total - current (clamped at 0).
    """
    return max(0, total_rounds - current_round)


def _expected_gold(item, timing, window):
    """Expected gold yield of a gold-type item over the remaining window."""
    name = item.get("name", "")
    text = item.get("base", "") or ""
    if name == "盟约之币":
        return 1.0                      # immediate +1
    if name == "驮兽储蓄罐":
        return (1 + 6) / 2.0            # uniform 1..6 -> 3.5
    if name == "见钱眼开玩偶":
        return 2.0 if window >= 1 else 0.0   # next-round +2
    if timing == RECURRING:
        # 精打细算玩偶 / 定期存折: +1 per later round
        return float(window)
    # fallback: pull an explicit number if present
    m = re.search(r"获得\s*(\d+)\s*资金", text)
    return float(m.group(1)) if m else 0.0


def value_item(item, current_round: int, total_rounds: int = DEFAULT_TOTAL_ROUNDS):
    """Round-aware score for a shop item.

    Returns dict: {score, timing, benefit, consumable, window, rationale,
    time_sensitive}. `time_sensitive` flags delayed items whose window is
    closing so the engine can explain/warn.
    """
    price = int(item["price"]) if str(item.get("price", "")).isdigit() else 0
    if not is_consumable(item):
        return None  # non-consumables are handled by the normal bond/power logic

    timing, benefit = classify(item)
    window = effective_rounds_left(current_round, total_rounds)
    time_sensitive = timing in (NEXT_ROUND, RECURRING)

    # delayed item with no round left to trigger: it cannot pay off
    if time_sensitive and window <= 0:
        return {
            "score": -50.0, "timing": timing, "benefit": benefit,
            "consumable": True, "window": window, "time_sensitive": True,
            "rationale": "延时生效但已无剩余回合，来不及回本，不建议拿",
        }

    if benefit == GOLD:
        gross = _expected_gold(item, timing, window)
        net_gold = gross - price
        score = net_gold * GOLD_PER_POINT
        if timing == RECURRING:
            rationale = "持续产金：每回合+1，剩余%d回合预期%.0f金，买价%d，净%.0f金" % (
                window, gross, price, net_gold)
            if window <= 2:
                score -= 8  # barely breaks even; warn
        elif timing == NEXT_ROUND:
            score *= DELAY_DISCOUNT
            rationale = "下回合+%.0f金，买价%d，净%.0f金（需还有下回合）" % (
                gross, price, net_gold)
        else:
            rationale = "即时+%.0f金，买价%d，净%.0f金" % (gross, price, net_gold)
    else:
        util = BENEFIT_UTILITY.get(benefit, BENEFIT_UTILITY[OTHER])
        score = util - price * GOLD_PER_POINT * 0.5  # gold cost still matters
        if timing == NEXT_ROUND:
            score *= DELAY_DISCOUNT
        if timing == RECURRING:
            score = max(score, score * min(1.0, window / 4.0))
        label = {
            BOND_STACK: "盟约层数", ELITE: "晋升精锐", REFRESH: "特殊刷新",
            RECRUIT: "免费招募", ITEM: "免费装备", DEPLOY_CAP: "部署位+",
            COMMAND: "替换指令", OTHER: "特殊效果",
        }.get(benefit, benefit)
        rationale = "%s型（%s），买价%d" % (
            {"immediate": "即时", "next_round": "下回合", "recurring": "持续"}[timing],
            label, price)
        if time_sensitive and window <= 2:
            rationale += "；剩余回合少，回本窗口紧张"
            score -= 6

    return {
        "score": round(score, 1), "timing": timing, "benefit": benefit,
        "consumable": True, "window": window,
        "time_sensitive": time_sensitive, "rationale": rationale,
    }
