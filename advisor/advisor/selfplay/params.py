# -*- coding: utf-8 -*-
"""Registry of hand-tuned scoring knobs that hillclimb may perturb (P6).

Prefer wiring existing advisor module constants over inventing game rules.
Impact-ruler constants stay out of scope unless explicitly promoted.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class ParamSpec:
    key: str
    module: str
    attr: str
    lo: float
    hi: float
    step: float
    note: str = ""
    # When set, ``getattr(mod, attr)`` is a dict and this selects the entry.
    dict_key: Optional[str] = None


# Expanded surface (P6): scoring weights, refresh EV, gap, margin/upgrade,
# compass, invest/sell tags, item EV. Baseline P5 only ever nudged ``effdps.full``.
PARAMS: List[ParamSpec] = [
    # --- economy investment tags (buy-side EV for refresh/gold/sell traits) ---
    ParamSpec("invest.free_refresh", "advisor.economy", "INVEST_WEIGHT", 10, 40, 2,
              "economy.INVEST_WEIGHT['free_refresh']", "free_refresh"),
    ParamSpec("invest.extra_gold", "advisor.economy", "INVEST_WEIGHT", 10, 40, 2,
              "economy.INVEST_WEIGHT['extra_gold']", "extra_gold"),
    ParamSpec("invest.special_buy_price", "advisor.economy", "INVEST_WEIGHT", 10, 40, 2,
              "economy.INVEST_WEIGHT['special_buy_price']", "special_buy_price"),
    ParamSpec("invest.special_sell_price", "advisor.economy", "INVEST_WEIGHT", 4, 24, 1,
              "economy.INVEST_WEIGHT['special_sell_price']", "special_sell_price"),
    ParamSpec("invest.free_recruit", "advisor.economy", "INVEST_WEIGHT", 10, 40, 2,
              "economy.INVEST_WEIGHT['free_recruit']", "free_recruit"),
    ParamSpec("invest.item_generation", "advisor.economy", "INVEST_WEIGHT", 4, 24, 1,
              "economy.INVEST_WEIGHT['item_generation']", "item_generation"),
    ParamSpec("invest.covenant_coin", "advisor.economy", "INVEST_WEIGHT", 6, 28, 1,
              "economy.INVEST_WEIGHT['covenant_coin']", "covenant_coin"),
    # --- team gap bonuses ---
    ParamSpec("gap.cap", "advisor.team_gaps", "GAP_BONUS_CAP", 15, 40, 1,
              "team_gaps.GAP_BONUS_CAP"),
    ParamSpec("gap.primary", "advisor.team_gaps", "GAP_BONUS_PRIMARY", 8, 25, 1,
              "team_gaps.GAP_BONUS_PRIMARY"),
    ParamSpec("gap.secondary", "advisor.team_gaps", "GAP_BONUS_SECONDARY", 3, 16, 1,
              "team_gaps.GAP_BONUS_SECONDARY"),
    # --- refresh EV bands + hunt/spare levers ---
    ParamSpec("refresh.soft_ceiling", "advisor.engine", "REFRESH_SOFT_CEILING", 40, 70, 2,
              "engine.REFRESH_SOFT_CEILING"),
    ParamSpec("refresh.critical_floor", "advisor.engine", "REFRESH_CRITICAL_FLOOR", 55, 90, 2,
              "engine.REFRESH_CRITICAL_FLOOR"),
    ParamSpec("refresh.hunt_per_tier", "advisor.engine", "REFRESH_HUNT_PER_TIER", 4, 14, 0.5,
              "engine.REFRESH_HUNT_PER_TIER (tier EV hunt scale)"),
    ParamSpec("refresh.spare_rich", "advisor.engine", "REFRESH_SPARE_RICH_BONUS", 4, 18, 1,
              "engine.REFRESH_SPARE_RICH_BONUS (spare>=8)"),
    ParamSpec("refresh.spare_ok", "advisor.engine", "REFRESH_SPARE_OK_BONUS", 2, 12, 1,
              "engine.REFRESH_SPARE_OK_BONUS (spare>=4)"),
    ParamSpec("refresh.spare_tight", "advisor.engine", "REFRESH_SPARE_TIGHT_PENALTY", 2, 16, 1,
              "engine.REFRESH_SPARE_TIGHT_PENALTY (spare<=1)"),
    # --- armor-fit / star micro ---
    ParamSpec("effdps.full", "advisor.engine", "EFFDPS_FULL", 8, 30, 1,
              "engine.EFFDPS_FULL"),
    ParamSpec("star.tier_weight", "advisor.engine", "STAR_TIER_WEIGHT", 0.0, 3.0, 0.25,
              "engine.STAR_TIER_WEIGHT"),
    # --- clear-margin bands + damage/upgrade steering ---
    ParamSpec("margin.critical_at", "advisor.clear_margin", "CRITICAL_AT", 0.3, 0.9, 0.05,
              "clear_margin.CRITICAL_AT"),
    ParamSpec("margin.comfortable_at", "advisor.clear_margin", "COMFORTABLE_AT", 1.1, 2.5, 0.1,
              "clear_margin.COMFORTABLE_AT"),
    ParamSpec("margin.dmg_critical", "advisor.clear_margin", "DAMAGE_BONUS", 6, 20, 1,
              "clear_margin.DAMAGE_BONUS['critical']", "critical"),
    ParamSpec("margin.dmg_tight", "advisor.clear_margin", "DAMAGE_BONUS", 2, 14, 1,
              "clear_margin.DAMAGE_BONUS['tight']", "tight"),
    ParamSpec("margin.upgrade_comfortable", "advisor.clear_margin", "UPGRADE_ADJUST", 0, 20, 1,
              "clear_margin.UPGRADE_ADJUST['comfortable']", "comfortable"),
    ParamSpec("margin.upgrade_critical", "advisor.clear_margin", "UPGRADE_ADJUST", -30, 0, 1,
              "clear_margin.UPGRADE_ADJUST['critical']", "critical"),
    # --- compass lineup direction ---
    ParamSpec("compass.carry", "advisor.compass", "CARRY_PTS", 15, 50, 1,
              "compass.CARRY_PTS"),
    ParamSpec("compass.member", "advisor.compass", "MEMBER_PTS", 10, 40, 1,
              "compass.MEMBER_PTS"),
    ParamSpec("compass.core_bond", "advisor.compass", "CORE_BOND_PTS", 6, 30, 1,
              "compass.CORE_BOND_PTS"),
    ParamSpec("compass.weak_weight", "advisor.compass", "WEAK_WEIGHT", 0.2, 1.0, 0.05,
              "compass.WEAK_WEIGHT"),
    # --- item economy EV (consumable valuation) ---
    ParamSpec("item.gold_per_point", "advisor.item_economy", "GOLD_PER_POINT", 4, 20, 1,
              "item_economy.GOLD_PER_POINT"),
    ParamSpec("item.delay_discount", "advisor.item_economy", "DELAY_DISCOUNT", 0.5, 1.0, 0.05,
              "item_economy.DELAY_DISCOUNT"),
]


def _import(path: str):
    import importlib
    return importlib.import_module(path)


def _get_value(spec: ParamSpec) -> float:
    mod = _import(spec.module)
    obj = getattr(mod, spec.attr)
    if spec.dict_key is not None:
        return float(obj[spec.dict_key])
    return float(obj)


def _set_value(spec: ParamSpec, value: float) -> None:
    mod = _import(spec.module)
    if spec.dict_key is not None:
        obj = getattr(mod, spec.attr)
        obj[spec.dict_key] = float(value)
        return
    setattr(mod, spec.attr, float(value))


def snapshot_params(keys: Iterable[str] | None = None) -> Dict[str, float]:
    want = set(keys) if keys is not None else None
    out = {}
    for spec in PARAMS:
        if want is not None and spec.key not in want:
            continue
        out[spec.key] = _get_value(spec)
    return out


def apply_params(values: Dict[str, float]) -> Dict[str, float]:
    """Apply overrides; return previous values for restore."""
    prev = {}
    by_key = {p.key: p for p in PARAMS}
    for key, val in values.items():
        spec = by_key[key]
        prev[key] = _get_value(spec)
        lo, hi = spec.lo, spec.hi
        clamped = max(lo, min(hi, float(val)))
        _set_value(spec, clamped)
    return prev


def restore_params(prev: Dict[str, float]) -> None:
    apply_params(prev)


def clamp_pair(values: Dict[str, float]) -> Dict[str, float]:
    """Keep paired thresholds ordered when both present."""
    out = dict(values)
    soft = out.get("refresh.soft_ceiling")
    crit = out.get("refresh.critical_floor")
    if soft is not None and crit is not None and soft >= crit:
        out["refresh.soft_ceiling"] = float(crit) - 2.0
    crit_at = out.get("margin.critical_at")
    comf_at = out.get("margin.comfortable_at")
    if crit_at is not None and comf_at is not None and crit_at >= comf_at:
        out["margin.critical_at"] = max(0.3, float(comf_at) - 0.2)
    dmg_c = out.get("margin.dmg_critical")
    dmg_t = out.get("margin.dmg_tight")
    if dmg_c is not None and dmg_t is not None and dmg_t > dmg_c:
        out["margin.dmg_tight"] = float(dmg_c)
    return out


def list_params() -> List[Tuple[str, str, float, float, float]]:
    return [(p.key, p.note or p.attr, p.lo, p.hi, p.step) for p in PARAMS]


def param_catalog() -> List[Dict[str, Any]]:
    """JSON-friendly catalog for docs / CLI."""
    return [
        {
            "key": p.key,
            "module": p.module,
            "attr": p.attr,
            "dict_key": p.dict_key,
            "lo": p.lo,
            "hi": p.hi,
            "step": p.step,
            "note": p.note or p.attr,
            "default": _get_value(p),
        }
        for p in PARAMS
    ]
