# -*- coding: utf-8 -*-
"""Fixed-seed eval cards + param evaluation harness (self-play P3)."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

from advisor.data import Dataset

from .episode import run_episode
from .objective import aggregate_scores, score_episode
from .params import apply_params, clamp_pair, restore_params

DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
EVAL_CARDS_PATH = os.path.join(DATA_DIR, "selfplay_eval_cards.json")

_cache: Optional[dict] = None


def load_eval_doc(path: str = EVAL_CARDS_PATH) -> dict:
    global _cache
    if path == EVAL_CARDS_PATH and _cache is not None:
        return _cache
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if path == EVAL_CARDS_PATH:
        _cache = doc
    return doc


def clear_eval_cache() -> None:
    global _cache
    _cache = None


def list_cards(
    doc: Optional[Mapping] = None,
    *,
    suite: Optional[str] = None,
    ids: Optional[Sequence[str]] = None,
) -> List[dict]:
    doc = doc or load_eval_doc()
    cards = list(doc.get("cards") or [])
    by_id = {c["id"]: c for c in cards if c.get("id")}
    if ids is not None:
        return [by_id[i] for i in ids if i in by_id]
    if suite:
        suite_block = (doc.get("suites") or {}).get(suite) or {}
        want = suite_block.get("card_ids") or []
        return [by_id[i] for i in want if i in by_id]
    default = doc.get("default_suite") or "smoke"
    return list_cards(doc, suite=default)


def run_card(
    card: Mapping[str, Any],
    *,
    ds: Optional[Dataset] = None,
) -> Dict[str, Any]:
    """Run one eval card → episode + scored components."""
    ds = ds or Dataset()
    try:
        hp_scale = float(card.get("enemy_hp_scale", 1.0))
    except (TypeError, ValueError):
        hp_scale = 1.0
    ep = run_episode(
        ds=ds,
        seed=int(card.get("seed") or 0),
        regulation_level=int(card.get("regulation_level") or 1),
        max_rounds=int(card.get("max_rounds") or 3),
        actions_per_round=int(card.get("actions_per_round") or 6),
        season=str(card.get("season") or "guicheng"),
        use_battle=bool(card.get("use_battle", True)),
        income_flat=card.get("income_flat"),
        enemy_hp_scale=hp_scale,
    )
    scored = score_episode(ep)
    return {
        "card_id": card.get("id"),
        "seed": card.get("seed"),
        "max_rounds_cap": card.get("max_rounds"),
        "episode": {
            "max_round_cleared": ep.get("max_round_cleared"),
            "income_note": ep.get("income_note"),
            "shop_odds": ep.get("shop_odds"),
            "log": ep.get("log"),
        },
        **scored,
    }


def evaluate_on_cards(
    values: Optional[Mapping[str, float]] = None,
    *,
    suite: str = "smoke",
    cards: Optional[Sequence[Mapping[str, Any]]] = None,
    ds: Optional[Dataset] = None,
    variance_weight: Optional[float] = None,
) -> Dict[str, Any]:
    """Apply optional params, run fixed cards, return aggregate fitness."""
    from . import objective as objective_mod

    ds = ds or Dataset()
    doc = load_eval_doc()
    card_list = list(cards) if cards is not None else list_cards(doc, suite=suite)
    vw = (
        float(variance_weight)
        if variance_weight is not None
        else float(objective_mod.VARIANCE_WEIGHT)
    )

    prev = None
    if values is not None:
        prev = apply_params(clamp_pair(dict(values)))
    try:
        per_card = [run_card(c, ds=ds) for c in card_list]
        # Strip heavy episode logs from aggregate payload but keep summary.
        slim = []
        for row in per_card:
            slim.append({
                "card_id": row.get("card_id"),
                "seed": row.get("seed"),
                "fitness": row.get("fitness"),
                "max_round_cleared": row.get("max_round_cleared"),
                "total_leaked": row.get("total_leaked"),
                "fail_leaked": row.get("fail_leaked"),
                "gold_waste": row.get("gold_waste"),
                "overflow_s": row.get("overflow_s"),
                "clear_miss": row.get("clear_miss"),
                "clear_frac_sum": row.get("clear_frac_sum"),
                "margin_proxy": row.get("margin_proxy"),
                "rounds_ok": row.get("rounds_ok"),
                "rounds_played": row.get("rounds_played"),
            })
        agg = aggregate_scores(slim, variance_weight=vw)
        return {
            "suite": suite if cards is None else "custom",
            "assumed_env": bool(doc.get("assumed_env")),
            "params": dict(values) if values is not None else None,
            "cards": slim,
            "detail": per_card,
            **agg,
            "note": (
                "P3/P6/P7 eval harness: fixed seeds; fitness = mean(episode) "
                "- variance_weight * std; episode rewards clear_frac/margin "
                "proxies and penalizes leak/gold_waste/overflow/clear_miss; "
                "ASSUMED shop/income/item_mix"
            ),
        }
    finally:
        if prev is not None:
            restore_params(prev)
