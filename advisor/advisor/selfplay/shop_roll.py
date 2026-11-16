# -*- coding: utf-8 -*-
"""Roll a shop offer from ASSUMED shop_odds.tier_probs + Dataset operators/items.

Items: ASSUMED per-slot mix rate from ``shop_roll_odds.json`` ``item_mix``
(not official). Within items, uniform over ``Dataset.items``.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from advisor.data import Dataset
from advisor.economy import buy_price
from advisor.model import ShopCard
from advisor import shop_odds


# Fallback when JSON has no item_mix block.
ASSUMED_ITEM_SLOT_RATE = 0.25
ASSUMED_ITEM_MIX_NOTE = (
    "ASSUMED item_mix: per-slot item rate (default 0.25), uniform over items; "
    "not official Hypergryph odds"
)


def operators_by_tier(ds: Dataset) -> Dict[int, List[dict]]:
    buckets: Dict[int, List[dict]] = {}
    for op in ds.operators:
        tier = op.get("shop_tier")
        if tier is None:
            continue
        buckets.setdefault(int(tier), []).append(op)
    return buckets


def item_slot_rate(odds_doc=None) -> float:
    doc = odds_doc if odds_doc is not None else shop_odds.load_shop_roll_odds()
    mix = (doc or {}).get("item_mix") or {}
    if mix.get("per_slot_item_rate") is not None:
        return float(mix["per_slot_item_rate"])
    return float(ASSUMED_ITEM_SLOT_RATE)


def _roll_operator_card(
    ds: Dataset,
    buckets: Dict[int, List[dict]],
    tiers: List,
    weights: List[float],
    rng: random.Random,
) -> Optional[ShopCard]:
    tier_s = rng.choices(tiers, weights=weights, k=1)[0]
    tier = int(tier_s)
    pool = buckets.get(tier) or []
    while not pool and tier > 1:
        tier -= 1
        pool = buckets.get(tier) or []
    if not pool:
        return None
    op = rng.choice(pool)
    price = buy_price(ds, op)
    return ShopCard(
        kind="operator",
        name=op["name"],
        tier=int(op.get("shop_tier") or tier),
        price=int(price),
        bond=(op.get("bonds") or [None])[0],
    )


def _roll_item_card(ds: Dataset, rng: random.Random) -> Optional[ShopCard]:
    items = list(ds.items or [])
    if not items:
        return None
    it = rng.choice(items)
    price = it.get("price")
    try:
        price_i = int(price) if price is not None else 0
    except (TypeError, ValueError):
        price_i = 0
    tier = it.get("tier")
    try:
        tier_i = int(tier) if tier is not None else None
    except (TypeError, ValueError):
        tier_i = None
    return ShopCard(
        kind="item",
        name=it["name"],
        tier=tier_i,
        price=price_i,
        bond=it.get("bond"),
    )


def roll_shop(
    ds: Dataset,
    dispatch_level: int,
    difficulty: str = "standard",
    *,
    season: str = "guicheng",
    rng: Optional[random.Random] = None,
    odds_doc=None,
    n_slots: Optional[int] = None,
    include_items: bool = True,
) -> List[ShopCard]:
    """Sample shop cards using ASSUMED tier_probs (+ optional ASSUMED item mix).

    Within an operator tier, draws are uniform (full-pool, no depletion).
    """
    rng = rng or random.Random()
    odds_doc = odds_doc if odds_doc is not None else shop_odds.load_shop_roll_odds()
    n = int(n_slots if n_slots is not None
            else (ds.slots(dispatch_level, difficulty) or 3))
    probs = shop_odds.tier_probs(dispatch_level, season=season, doc=odds_doc)
    buckets = operators_by_tier(ds)
    tiers = sorted(probs.keys(), key=lambda t: int(t))
    weights = [float(probs[t]) for t in tiers]
    rate = item_slot_rate(odds_doc) if include_items else 0.0
    cards: List[ShopCard] = []
    for _ in range(n):
        card = None
        if include_items and rate > 0 and rng.random() < rate:
            card = _roll_item_card(ds, rng)
        if card is None:
            card = _roll_operator_card(ds, buckets, tiers, weights, rng)
        if card is not None:
            cards.append(card)
    return cards


def odds_disclaimer() -> str:
    doc = shop_odds.load_shop_roll_odds()
    mix = doc.get("item_mix") or {}
    return (
        "shop_odds ASSUMED=%s official=%s source=%s; "
        "item_mix ASSUMED=%s per_slot_rate=%s"
        % (
            doc.get("assumed"),
            doc.get("official"),
            doc.get("source"),
            mix.get("assumed", True),
            item_slot_rate(doc),
        )
    )
