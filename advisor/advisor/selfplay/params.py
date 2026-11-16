# -*- coding: utf-8 -*-
"""Registry of hand-tuned scoring knobs that hillclimb may perturb."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class ParamSpec:
    key: str
    module: str
    attr: str
    lo: float
    hi: float
    step: float
    note: str = ""


# Keys intentionally limited to legacy-score + clear_margin levers that already
# steer buy/refresh/upgrade. Impact-ruler constants are out of scope for v0.
PARAMS: List[ParamSpec] = [
    ParamSpec("invest.free_refresh", "advisor.economy", "INVEST_WEIGHT", 10, 40, 2,
              "economy.INVEST_WEIGHT['free_refresh']"),
    ParamSpec("invest.extra_gold", "advisor.economy", "INVEST_WEIGHT", 10, 40, 2,
              "economy.INVEST_WEIGHT['extra_gold']"),
    ParamSpec("gap.cap", "advisor.team_gaps", "GAP_BONUS_CAP", 15, 40, 1),
    ParamSpec("gap.primary", "advisor.team_gaps", "GAP_BONUS_PRIMARY", 8, 25, 1),
    ParamSpec("refresh.soft_ceiling", "advisor.engine", "REFRESH_SOFT_CEILING", 40, 70, 2),
    ParamSpec("refresh.critical_floor", "advisor.engine", "REFRESH_CRITICAL_FLOOR", 55, 90, 2),
    ParamSpec("effdps.full", "advisor.engine", "EFFDPS_FULL", 8, 30, 1),
    ParamSpec("margin.critical_at", "advisor.clear_margin", "CRITICAL_AT", 0.3, 0.9, 0.05),
    ParamSpec("margin.comfortable_at", "advisor.clear_margin", "COMFORTABLE_AT", 1.1, 2.5, 0.1),
    ParamSpec("margin.dmg_critical", "advisor.clear_margin", "DAMAGE_BONUS", 6, 20, 1,
              "DAMAGE_BONUS['critical']"),
    ParamSpec("compass.carry", "advisor.compass", "CARRY_PTS", 15, 50, 1),
]


def _import(path: str):
    import importlib
    return importlib.import_module(path)


def _get_value(spec: ParamSpec) -> float:
    mod = _import(spec.module)
    obj = getattr(mod, spec.attr)
    if spec.key.startswith("invest."):
        sub = spec.key.split(".", 1)[1]
        return float(obj[sub])
    if spec.key == "margin.dmg_critical":
        return float(obj["critical"])
    return float(obj)


def _set_value(spec: ParamSpec, value: float) -> None:
    mod = _import(spec.module)
    obj = getattr(mod, spec.attr)
    if spec.key.startswith("invest."):
        sub = spec.key.split(".", 1)[1]
        obj[sub] = float(value)
        return
    if spec.key == "margin.dmg_critical":
        obj["critical"] = float(value)
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
    """Keep refresh soft ceiling below critical floor when both present."""
    out = dict(values)
    soft = out.get("refresh.soft_ceiling")
    crit = out.get("refresh.critical_floor")
    if soft is not None and crit is not None and soft >= crit:
        out["refresh.soft_ceiling"] = float(crit) - 2.0
    return out


def list_params() -> List[Tuple[str, str, float, float, float]]:
    return [(p.key, p.note or p.attr, p.lo, p.hi, p.step) for p in PARAMS]
