# -*- coding: utf-8 -*-
"""Shell-side advice sanity filters (do not rewrite kernel).

- gold==0: primary advice = 位置调节并开战 (not buy/refresh)
- Affordability: never promote buy/upgrade/refresh whose cost exceeds gold
- Upgrade: also respect resources.upgrade_cost when OCR'd (engine table can lag)
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional


def _action_cost(action: Optional[dict]) -> Optional[int]:
    if not action:
        return None
    c = action.get("cost")
    if c is None and isinstance(action.get("impact"), dict):
        c = action["impact"].get("cost")
    try:
        return int(c) if c is not None else None
    except (TypeError, ValueError):
        return None


def _is_buy(action: Optional[dict]) -> bool:
    if not action:
        return False
    return str(action.get("verb") or "").lower() in ("buy", "购买")


def _is_upgrade(action: Optional[dict]) -> bool:
    if not action:
        return False
    return str(action.get("verb") or "").lower() in (
        "upgrade", "升本", "升级", "level"
    )


def _is_refresh(action: Optional[dict]) -> bool:
    if not action:
        return False
    return str(action.get("verb") or "").lower() in ("refresh", "刷新")


def _is_shop_spend(action: Optional[dict]) -> bool:
    return _is_buy(action) or _is_upgrade(action) or _is_refresh(action)


def _effective_cost(action: Optional[dict], resources: Optional[dict] = None) -> Optional[int]:
    """Cost used for affordability. Upgrade prefers OCR upgrade_cost when higher."""
    base = _action_cost(action)
    if not _is_upgrade(action):
        return base
    res = resources or {}
    uc = res.get("upgrade_cost")
    try:
        uc_i = int(uc) if uc is not None else None
    except (TypeError, ValueError):
        uc_i = None
    if uc_i is None:
        return base
    if base is None:
        return uc_i
    return max(base, uc_i)


def _affordable(action: Optional[dict], gold: int, resources: Optional[dict] = None) -> bool:
    if not action:
        return False
    verb = str(action.get("verb") or "").lower()
    if verb in (
        "freeze", "冻结", "merge", "ready", "battle", "开战", "准备", "准备就绪",
        "reposition", "adjust", "位置",
    ):
        return True
    cost = _effective_cost(action, resources)
    if cost is None:
        # unknown cost — allow non-spend; block buy/upgrade
        if _is_buy(action) or _is_upgrade(action):
            return False
        return True
    return cost <= gold


def _battle_ready_pick() -> dict:
    return {
        "verb": "ready",
        "target": "准备就绪",
        "score": 100,
        "reason": "金币为 0：请调节干员站位，确认后点「准备就绪」开战",
        "cost": 0,
        "shell_override": "gold_zero_battle",
        "affordable": True,
        "label": "位置调节并开战",
    }


def _pick_affordable_fallback(affordable: list[dict], gold_i: int) -> dict:
    if affordable:
        pick = dict(affordable[0])
        pick["shell_override"] = "unaffordable_spend"
        return pick
    if gold_i >= 1:
        return {
            "verb": "refresh",
            "target": "调度中心",
            "score": 0,
            "reason": f"金币不足升级/购买（金 {gold_i}）；可刷新或等待",
            "cost": 1,
            "shell_override": "unaffordable_spend_fallback",
            "affordable": True,
        }
    return _battle_ready_pick()


def filter_advice(result: dict, gold: Optional[int] = None) -> dict:
    """Return a shallow-copied result with shell overrides applied."""
    if not isinstance(result, dict):
        return result
    out = deepcopy(result)
    st = out.get("state") if isinstance(out.get("state"), dict) else {}
    res = out.get("resources") if isinstance(out.get("resources"), dict) else {}
    gold_status = str(res.get("gold_status") or "").lower()
    # Prefer explicit OCR gold; never invent 0 from missing OCR.
    if gold is None:
        if res.get("gold") is not None:
            gold = res.get("gold")
        elif st.get("gold") is not None and gold_status in ("ocr", "last_good", ""):
            gold = st.get("gold")
    try:
        gold_i = int(gold) if gold is not None else None
    except (TypeError, ValueError):
        gold_i = None

    # Sync upgrade action cost from OCR when present (engine table may be stale).
    uc = res.get("upgrade_cost")
    try:
        uc_i = int(uc) if uc is not None else None
    except (TypeError, ValueError):
        uc_i = None
    if uc_i is not None:
        for key in ("top_pick",):
            tp0 = out.get(key)
            if _is_upgrade(tp0):
                tp0 = dict(tp0)
                tp0["cost"] = max(int(tp0.get("cost") or 0), uc_i)
                out[key] = tp0
        new_recs = []
        for r in list(out.get("recommendations") or []):
            rr = dict(r)
            if _is_upgrade(rr):
                rr["cost"] = max(int(rr.get("cost") or 0), uc_i)
            new_recs.append(rr)
        out["recommendations"] = new_recs

    # Unknown gold: never treat as 0 → 准备就绪.
    if gold_i is None or gold_status in ("unknown", "ambiguous"):
        notes = list(out.get("notes") or [])
        notes.insert(0, "[壳层] 金币未确认：不触发「开战」；建议手填或重识")
        out["notes"] = notes
        out["shell_filter"] = {
            "gold": gold_i,
            "gold_status": gold_status or "unknown",
            "overridden": False,
            "demoted_buys": 0,
            "mode": "gold_unknown",
        }
        # Soft affordability with a conservative stand-in only for demote checks
        # (do not rewrite top_pick to ready).
        stand_in = gold_i if gold_i is not None else 10**9
        recs = []
        for r in list(out.get("recommendations") or []):
            rr = dict(r)
            if _is_shop_spend(rr) and gold_i is not None and not _affordable(rr, gold_i, res):
                rr["affordable"] = False
                rr["shell_demoted"] = True
            else:
                rr["affordable"] = True if gold_i is None else _affordable(rr, stand_in, res)
            recs.append(rr)
        out["recommendations"] = recs
        return out

    # --- gold == 0 (never from unknown/ambiguous): force battle-prep ---
    if gold_i == 0 and gold_status not in ("unknown", "ambiguous"):
        out["top_pick"] = _battle_ready_pick()
        recs = []
        for r in list(out.get("recommendations") or []):
            rr = dict(r)
            if _is_shop_spend(rr):
                rr["affordable"] = False
                rr["shell_demoted"] = True
                rr["shell_reason"] = "gold_zero"
            else:
                rr["affordable"] = True
            recs.append(rr)
        out["recommendations"] = [dict(out["top_pick"])] + recs
        notes = list(out.get("notes") or [])
        notes.insert(0, "[壳层] 金币为 0：主建议改为「位置调节并开战」，不提示购买/刷新")
        out["notes"] = notes
        out["shell_filter"] = {
            "gold": gold_i,
            "gold_status": gold_status or "ocr",
            "overridden": True,
            "demoted_buys": sum(1 for r in recs if r.get("shell_demoted")),
            "mode": "gold_zero_battle",
        }
        return out

    recs = list(out.get("recommendations") or [])
    affordable: list[dict] = []
    demoted: list[dict] = []
    for r in recs:
        rr = dict(r)
        if _is_shop_spend(rr) and not _affordable(rr, gold_i, res):
            rr["affordable"] = False
            rr["shell_demoted"] = True
            if _is_upgrade(rr):
                rr["shell_reason"] = "upgrade_cost_exceeds_gold"
            demoted.append(rr)
        else:
            rr["affordable"] = True
            affordable.append(rr)

    out["recommendations"] = affordable + demoted

    tp = out.get("top_pick")
    overridden = False
    if _is_shop_spend(tp) and not _affordable(tp, gold_i, res):
        overridden = True
        out["top_pick"] = _pick_affordable_fallback(affordable, gold_i)
        # Keep demoted upgrade cost visible in notes
        eff = _effective_cost(tp, res)
        notes = list(out.get("notes") or [])
        kind = "升级" if _is_upgrade(tp) else ("刷新" if _is_refresh(tp) else "购买")
        notes.insert(
            0,
            f"[壳层] {kind}花费 {eff} > 金币 {gold_i}，已改推可执行动作",
        )
        out["notes"] = notes

    out["shell_filter"] = {
        "gold": gold_i,
        "upgrade_cost": uc_i,
        "overridden": overridden,
        "demoted_buys": len(demoted),
        "mode": "upgrade_blocked" if overridden and _is_upgrade(tp) else (
            "spend_filtered" if overridden else "ok"
        ),
    }
    return out
