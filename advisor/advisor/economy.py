# -*- coding: utf-8 -*-
"""Economy derivation: actual buy/sell price and investment tagging.

Special prices are NOT a separate marker field. They live in an operator's
整备能力 entries (e.g. 真理/至简 "购买价格为1", 温蒂 "售出价格为3",
海沫 "自身售出价格+1"). This module scans those entries and applies them on
top of the default tiered economy table.

It also classifies preparation/stack abilities that affect the economy
(refresh, gold, free recruit, item generation, special price) into structured
"investment" tags, because such cards are a form of investment and must feed
the buy recommendation, not only combat power.

Stdlib only. Deterministic.
"""
import re

# ---- entry text patterns (Chinese, from the BWiki dataset) ----
_BUY_FIXED = re.compile(r"购买价格为\s*(\d+)")
_SELL_FIXED = re.compile(r"售出价格为\s*(\d+)")
_SELL_BONUS = re.compile(r"自身售出价格\s*\+\s*(\d+)")
_FREE_REFRESH = re.compile(r"(\d+)\s*次免费刷新|获得一次免费刷新|获得两次免费刷新|特殊刷新")
_EXTRA_GOLD = re.compile(r"额外获得\s*(\d+)\s*资金")
_FREE_RECRUIT = re.compile(r"免费特殊招募|免费刷新")
_GIVE_ITEM = re.compile(r"获得一[件枚个]|获得一个|获得一件|获得一枚")
_COVENANT_COIN = re.compile(r"盟约之币")

# Investment tag -> human label and a default scoring weight (used by engine).
# Weights are heuristic knobs, centralized here so tuning is one place.
# 2026-11-13: raised so economy/refresh EV can beat non-critical 1-copy merges
# when the shop has no 2→3 / bond-threshold hit (prefs: raise 经济/刷新 EV).
INVEST_WEIGHT = {
    "free_refresh": 20.0,    # saves 1 gold per refresh and cycles the shop
    "extra_gold": 22.0,      # directly produces gold next round
    "special_buy_price": 24.0,   # cheap entry (often 1 gold) -> high ROI
    "special_sell_price": 10.0,  # can be sold at a premium / sell-based stacking
    "free_recruit": 20.0,    # free operator recruit
    "item_generation": 11.0, # free equipment
    "covenant_coin": 14.0,   # 盟约之币 economy resource
}


def _entries(operator):
    return operator.get("entries", []) if operator else []


def base_buy_price(ds, shop_tier):
    """Default buy price from the tiered table, flat value as fallback."""
    table = ds.economy.get("buy_price_by_shop_tier")
    if table:
        v = table.get(str(shop_tier))
        if v is not None:
            return int(v)
    return int(ds.economy.get("buy_operator_cost", 3))


def buy_price(ds, operator):
    """Actual buy price: special 整备能力 override wins over the tier table."""
    for e in _entries(operator):
        m = _BUY_FIXED.search(e.get("trait", ""))
        if m:
            return int(m.group(1))
    return base_buy_price(ds, operator.get("shop_tier")) if operator else \
        int(ds.economy.get("buy_operator_cost", 3))


def sell_price(ds, operator, advanced=False):
    """Actual sell price.

    Default 1. Fixed "售出价格为N" sets an absolute value; "自身售出价格+N"
    adds a bonus. `advanced` selects the 进阶 form when both exist (the
    dataset stores 基础 and 进阶 as separate entries); by default we report
    the 基础 form, which is what an unpromoted card gives.
    """
    price = int(ds.economy.get("default_sell_price", 1))
    fixed = None
    bonus = 0
    for e in _entries(operator):
        if advanced and e.get("form") != "进阶":
            continue
        if not advanced and e.get("form") not in (None, "基础"):
            continue
        trait = e.get("trait", "")
        m = _SELL_FIXED.search(trait)
        if m:
            fixed = int(m.group(1))
        m = _SELL_BONUS.search(trait)
        if m:
            bonus = max(bonus, int(m.group(1)))
    if fixed is not None:
        return fixed
    return price + bonus


def investment_tags(operator):
    """Return a list of structured investment tags from an operator's entries.

    Each tag: {"tag", "weight", "trait", "kind", "form"}. Deduplicated by
    (tag, trait) so 基础/进阶 duplicates do not double-count.
    """
    tags = []
    seen = set()

    def add(tag, trait, kind, form):
        key = (tag, trait)
        if key in seen:
            return
        seen.add(key)
        tags.append({
            "tag": tag,
            "weight": INVEST_WEIGHT.get(tag, 0.0),
            "trait": trait,
            "kind": kind,
            "form": form,
        })

    for e in _entries(operator):
        trait = e.get("trait", "")
        kind = e.get("kind", "")
        form = e.get("form", "")
        if _BUY_FIXED.search(trait):
            add("special_buy_price", trait, kind, form)
        if _SELL_FIXED.search(trait) or _SELL_BONUS.search(trait):
            add("special_sell_price", trait, kind, form)
        if _FREE_REFRESH.search(trait):
            add("free_refresh", trait, kind, form)
        if _EXTRA_GOLD.search(trait):
            add("extra_gold", trait, kind, form)
        if _FREE_RECRUIT.search(trait) and "招募" in trait:
            add("free_recruit", trait, kind, form)
        if _COVENANT_COIN.search(trait):
            add("covenant_coin", trait, kind, form)
        elif _GIVE_ITEM.search(trait) and kind == "整备能力":
            add("item_generation", trait, kind, form)
    return tags


def investment_score(operator):
    """Total investment weight for an operator (0 if it has no economy ability)."""
    return round(sum(t["weight"] for t in investment_tags(operator)), 1)


def has_investment(operator):
    return bool(investment_tags(operator))
