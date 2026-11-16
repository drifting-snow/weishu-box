# -*- coding: utf-8 -*-
"""Roll a shop offer from ASSUMED shop_odds.tier_probs + Dataset operators."""
from __future__ import annotations

import random
from typing import Dict, List, Optional, Sequence

from advisor.data import Dataset
from advisor.economy import buy_price
from advisor.model import ShopCard
from advisor import shop_odds


def operators_by_tier(ds: Dataset) -> Dict[int, List[dict]]:
    buckets: Dict[int, List[dict]] = {}
    for op in ds.operators:
        tier = op.get("shop_tier")
        if tier is None:
            continue
        buckets.setdefault(int(tier), []).append(op)
    return buckets


def roll_shop(
    ds: Dataset,
    dispatch_level: int,
    difficulty: str = "standard",
    *,
    season: str = "guicheng",
    rng: Optional[random.Random] = None,
    odds_doc=None,
) -> List[ShopCard]:
    """Sample ``slots`` shop operators using ASSUMED tier_probs.

    Within a tier, operators are drawn uniformly (full-pool, no depletion).
    Items are omitted in v0. Odds: ``shop_odds.tier_probs`` / shop_roll_odds.json.
    """
    rng = rng or random.Random()
    n = int(ds.slots(dispatch_level, difficulty) or 3)
    probs = shop_odds.tier_probs(dispatch_level, season=season, doc=odds_doc)
    buckets = operators_by_tier(ds)
    tiers = sorted(probs.keys(), key=lambda t: int(t))
    weights = [float(probs[t]) for t in tiers]
    cards: List[ShopCard] = []
    for _ in range(n):
        tier_s = rng.choices(tiers, weights=weights, k=1)[0]
        tier = int(tier_s)
        pool = buckets.get(tier) or []
        # If a tier is empty (data hole), fall back to nearest lower non-empty.
        while not pool and tier > 1:
            tier -= 1
            pool = buckets.get(tier) or []
        if not pool:
            continue
        op = rng.choice(pool)
        price = buy_price(ds, op)
        cards.append(ShopCard(
            kind="operator",
            name=op["name"],
            tier=int(op.get("shop_tier") or tier),
            price=int(price),
            bond=(op.get("bonds") or [None])[0],
        ))
    return cards


def odds_disclaimer() -> str:
    doc = shop_odds.load_shop_roll_odds()
    return (
        "shop_odds ASSUMED=%s official=%s source=%s"
        % (doc.get("assumed"), doc.get("official"), doc.get("source"))
    )
