# -*- coding: utf-8 -*-
"""Roll a shop offer from ASSUMED shop_odds.tier_probs + Dataset operators/items.

Items (P5): default model is ``dedicated_item_slots`` — wiki/client-confirmed
exactly ``item_slots_per_shop`` (1) item beside operator 栏位. Which item
(tier≤dispatch, uniform) remains ASSUMED. Legacy Bernoulli ``per_slot_item_rate``
still supported when ``item_mix.model`` is ``bernoulli`` / rate is set.
"""
from __future__ import annotations

import random
from typing import Dict, List, Optional

from advisor.data import Dataset
from advisor.economy import buy_price
from advisor.model import ShopCard
from advisor import shop_odds


# Fallback when JSON has no item_mix block (legacy Bernoulli).
ASSUMED_ITEM_SLOT_RATE = 0.25
ASSUMED_ITEM_MIX_NOTE = (
    "item_mix: dedicated 1 item slot (slot count confirmed); "
    "which-item uniform tier-gated ASSUMED; not official Hypergryph odds"
)

DEDICATED_MODEL = "dedicated_item_slots"
BERNOULLI_MODEL = "bernoulli"


def operators_by_tier(ds: Dataset) -> Dict[int, List[dict]]:
    buckets: Dict[int, List[dict]] = {}
    for op in ds.operators:
        tier = op.get("shop_tier")
        if tier is None:
            continue
        buckets.setdefault(int(tier), []).append(op)
    return buckets


def item_mix_block(odds_doc=None) -> dict:
    doc = odds_doc if odds_doc is not None else shop_odds.load_shop_roll_odds()
    return dict((doc or {}).get("item_mix") or {})


def item_mix_model(odds_doc=None) -> str:
    mix = item_mix_block(odds_doc)
    model = mix.get("model")
    if model:
        return str(model)
    # Legacy: rate present without model → bernoulli.
    if mix.get("per_slot_item_rate") is not None:
        return BERNOULLI_MODEL
    return DEDICATED_MODEL


def item_slots_per_shop(odds_doc=None) -> int:
    """Dedicated item slot count (wiki/client: 1)."""
    mix = item_mix_block(odds_doc)
    if mix.get("item_slots_per_shop") is not None:
        return max(0, int(mix["item_slots_per_shop"]))
    if item_mix_model(odds_doc) == DEDICATED_MODEL:
        return 1
    return 0


def item_slot_rate(odds_doc=None) -> float:
    """Legacy Bernoulli per-operator-slot item rate (0 under dedicated model)."""
    mix = item_mix_block(odds_doc)
    if item_mix_model(odds_doc) == DEDICATED_MODEL:
        if mix.get("per_slot_item_rate") is not None:
            return float(mix["per_slot_item_rate"])
        return 0.0
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


def _eligible_items(ds: Dataset, dispatch_level: int) -> List[dict]:
    """Items with tier ≤ dispatch (wiki: 阶级不会超过调度中心等级)."""
    out: List[dict] = []
    cap = max(1, int(dispatch_level))
    for it in ds.items or []:
        tier = it.get("tier")
        try:
            tier_i = int(tier) if tier is not None else 1
        except (TypeError, ValueError):
            tier_i = 1
        if tier_i <= cap:
            out.append(it)
    return out or list(ds.items or [])


def _item_to_card(it: dict) -> ShopCard:
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


def _roll_item_card(
    ds: Dataset,
    rng: random.Random,
    dispatch_level: int = 6,
) -> Optional[ShopCard]:
    pool = _eligible_items(ds, dispatch_level)
    if not pool:
        return None
    return _item_to_card(rng.choice(pool))


def roll_item_cards(
    ds: Dataset,
    dispatch_level: int,
    n: int,
    *,
    rng: Optional[random.Random] = None,
) -> List[ShopCard]:
    """Roll ``n`` dedicated item offers (ASSUMED which-item)."""
    rng = rng or random.Random()
    cards: List[ShopCard] = []
    for _ in range(max(0, int(n))):
        card = _roll_item_card(ds, rng, dispatch_level)
        if card is not None:
            cards.append(card)
    return cards


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
    """Sample shop cards: operator slots + dedicated item slot(s).

    Operator draws use ASSUMED tier_probs (uniform within tier).
    Items: dedicated slots by default; Bernoulli only if model says so.
    """
    rng = rng or random.Random()
    odds_doc = odds_doc if odds_doc is not None else shop_odds.load_shop_roll_odds()
    n = int(n_slots if n_slots is not None
            else (ds.slots(dispatch_level, difficulty) or 3))
    probs = shop_odds.tier_probs(dispatch_level, season=season, doc=odds_doc)
    buckets = operators_by_tier(ds)
    tiers = sorted(probs.keys(), key=lambda t: int(t))
    weights = [float(probs[t]) for t in tiers]
    model = item_mix_model(odds_doc) if include_items else None
    rate = item_slot_rate(odds_doc) if (
        include_items and model == BERNOULLI_MODEL) else 0.0

    cards: List[ShopCard] = []
    for _ in range(n):
        card = None
        if include_items and model == BERNOULLI_MODEL and rate > 0 and rng.random() < rate:
            card = _roll_item_card(ds, rng, dispatch_level)
        if card is None:
            card = _roll_operator_card(ds, buckets, tiers, weights, rng)
        if card is not None:
            cards.append(card)

    if include_items and model == DEDICATED_MODEL:
        n_items = item_slots_per_shop(odds_doc)
        cards.extend(roll_item_cards(ds, dispatch_level, n_items, rng=rng))
    return cards


def merge_reward_config(odds_doc=None) -> dict:
    doc = odds_doc if odds_doc is not None else shop_odds.load_shop_roll_odds()
    cfg = dict((doc or {}).get("merge_reward") or {})
    cfg.setdefault("assumed", True)
    cfg.setdefault("official", False)
    cfg.setdefault("structure_confirmed", False)
    cfg.setdefault("picks", 3)
    cfg.setdefault("tier_boost", 1)
    cfg.setdefault("free_buys", 1)
    cfg.setdefault("operators_only", True)
    return cfg


def roll_merge_reward(
    ds: Dataset,
    dispatch_level: int,
    *,
    season: str = "guicheng",
    rng: Optional[random.Random] = None,
    odds_doc=None,
) -> List[ShopCard]:
    """Elite-promotion reward: N operator picks at boosted tier.

    Structure (3 picks, +1 tier, 1 free) confirmed by PRTS/BWiki; which
    operators appear remains ASSUMED (uniform at preferred tier).
    """
    rng = rng or random.Random()
    odds_doc = odds_doc if odds_doc is not None else shop_odds.load_shop_roll_odds()
    cfg = merge_reward_config(odds_doc)
    n = max(1, int(cfg.get("picks") or 3))
    boost = max(0, int(cfg.get("tier_boost") or 1))
    target = min(6, max(1, int(dispatch_level) + boost))
    buckets = operators_by_tier(ds)
    # Prefer exact target tier; fall back downward then upward.
    order = [target] + list(range(target - 1, 0, -1)) + list(range(target + 1, 7))
    cards: List[ShopCard] = []
    for _ in range(n):
        card = None
        for tier in order:
            pool = buckets.get(tier) or []
            if not pool:
                continue
            op = rng.choice(pool)
            price = buy_price(ds, op)
            card = ShopCard(
                kind="operator",
                name=op["name"],
                tier=int(op.get("shop_tier") or tier),
                price=int(price),
                bond=(op.get("bonds") or [None])[0],
                raw={"merge_reward": True, "assumed": True},
            )
            break
        if card is not None:
            cards.append(card)
    return cards


def odds_disclaimer() -> str:
    doc = shop_odds.load_shop_roll_odds()
    mix = item_mix_block(doc)
    mr = merge_reward_config(doc)
    model = item_mix_model(doc)
    return (
        "shop_odds ASSUMED=%s official=%s source=%s; "
        "item_mix model=%s slot_assumed=%s within_item_assumed=%s "
        "item_slots=%s; "
        "merge_reward structure_confirmed=%s pick_assumed=%s picks=%s tier_boost=%s"
        % (
            doc.get("assumed"),
            doc.get("official"),
            doc.get("source"),
            model,
            mix.get("assumed", True),
            mix.get("within_item_assumed", True),
            item_slots_per_shop(doc) if model == DEDICATED_MODEL else item_slot_rate(doc),
            mr.get("structure_confirmed", False),
            mr.get("assumed", True),
            mr.get("picks"),
            mr.get("tier_boost"),
        )
    )
