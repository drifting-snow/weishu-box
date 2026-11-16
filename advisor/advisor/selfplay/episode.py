# -*- coding: utf-8 -*-
"""One self-play episode: roll shop → recommend → apply → battle clear check."""
from __future__ import annotations

import json
import os
import random
from copy import deepcopy
from typing import Any, Dict, List, Optional

from advisor.battle import adapter as battle_adapter
from advisor.clear_margin import apply_reservoir_pressure, clear_margin
from advisor.data import Dataset
from advisor.enemy_catalog import (
    load_enemy_catalog,
    load_enemy_name_index,
    resolve_enemies,
)
from advisor.engine import Advisor
from advisor.model import BoardUnit, GameState

from . import income as income_mod
from .shop_roll import odds_disclaimer, roll_shop

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "data")
WAVES_PATH = os.path.join(DATA_DIR, "act3_waves.json")


def _load_waves():
    with open(WAVES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _mode_key(regulation_level: int) -> str:
    return "mode_single_%d" % int(regulation_level)


def _level_for_round(waves: dict, mode: str, round_no: int) -> Optional[dict]:
    entries = (waves.get("round_to_level") or {}).get(mode, {}).get(str(round_no))
    if not entries:
        return None
    non_prep = [e for e in entries if not e.get("is_prepare")]
    chosen = (non_prep or entries)[0]
    stem = chosen["level"]
    level = (waves.get("level_stems") or {}).get(stem)
    if not level:
        return None
    return {"stem": stem, "level": level}


def _enemy_picture(level: dict, catalog, name_index) -> Dict[str, Any]:
    names = []
    for sp in level.get("spawns") or []:
        nm = sp.get("enemy_name")
        if nm:
            names.extend([nm] * int(sp.get("count") or 1))
    # Cap name list for resolve; unique order preserved for catalog.
    uniq = list(dict.fromkeys(names))
    resolved = resolve_enemies(uniq, catalog, name_index)
    return {
        "enemy_names": list(resolved.get("names") or uniq),
        "enemy_types": list(resolved.get("trait_keys") or []),
    }


def _board_add(board: List[BoardUnit], name: str, tier: int, bonds: List[str]) -> None:
    for u in board:
        if u.name == name:
            u.count = int(u.count) + 1
            if u.count >= 3 and not u.elite:
                u.count = 1
                u.elite = True
            return
    board.append(BoardUnit(name=name, count=1, tier=tier, bonds=list(bonds or []),
                           elite=False))


def _apply_top(ds: Dataset, st: GameState, rec: dict, rng: random.Random,
               season: str) -> str:
    """Apply one affordable recommendation; return verb or 'noop'."""
    picks = list(rec.get("recommendations") or [])
    if rec.get("top_pick"):
        picks = [rec["top_pick"]] + [p for p in picks if p is not rec.get("top_pick")]
    for action in picks:
        verb = str(action.get("verb") or "")
        cost = int(action.get("cost") or 0)
        if verb == "buy":
            if cost > st.gold:
                continue
            name = action.get("target")
            op = ds.operator(name)
            if not op:
                continue
            st.gold -= cost
            _board_add(st.board, name, int(op.get("shop_tier") or 1),
                       list(op.get("bonds") or []))
            # Remove purchased card from shop if present.
            st.shop = [c for c in st.shop if c.name != name]
            return "buy"
        if verb == "refresh":
            if cost > st.gold:
                continue
            st.gold -= cost
            st.shop = roll_shop(ds, st.dispatch_level, st.difficulty,
                                season=season, rng=rng)
            return "refresh"
        if verb == "upgrade":
            if cost > st.gold or st.dispatch_level >= 6:
                continue
            st.gold -= cost
            st.dispatch_level = int(st.dispatch_level) + 1
            return "upgrade"
        if verb == "merge":
            # Elite promotion already handled on buy when count hits 3.
            return "merge"
        if verb in ("freeze", "skip"):
            return verb
    return "noop"


def run_episode(
    *,
    ds: Optional[Dataset] = None,
    regulation_level: int = 1,
    max_rounds: int = 14,
    actions_per_round: int = 8,
    seed: int = 0,
    season: str = "guicheng",
    income_flat: Optional[int] = None,
    income_table=None,
    use_battle: bool = True,
) -> Dict[str, Any]:
    """Play until a wave fails or ``max_rounds`` cleared.

    Win condition per wave (v0): battle_sim cleared with leaked==0 when
    ``use_battle``; else clear_margin band != critical after reservoir wire.
    """
    ds = ds or Dataset()
    adv = Advisor(ds)
    rng = random.Random(seed)
    waves = _load_waves()
    mode = _mode_key(regulation_level)
    catalog = load_enemy_catalog()
    name_index = load_enemy_name_index()

    st = GameState(
        round=1,
        gold=0,
        dispatch_level=1,
        difficulty="standard",
        regulation_level=int(regulation_level),
        board=[],
        shop=[],
    )
    log: List[dict] = []
    cleared = 0

    for round_no in range(1, max_rounds + 1):
        meta = _level_for_round(waves, mode, round_no)
        if meta is None:
            break
        st.round = round_no
        # Rest start: REPLACE gold with round income (wiki: unspent clears at
        # rest end; no TFT-style interest). Do not add leftover from last wave.
        income = income_mod.gold_for_round(
            round_no, table=income_table, flat=income_flat)
        st.gold = income
        picture = _enemy_picture(meta["level"], catalog, name_index)
        st.enemy_names = picture["enemy_names"]
        st.enemy_types = picture["enemy_types"]
        st.shop = roll_shop(ds, st.dispatch_level, st.difficulty,
                            season=season, rng=rng)

        actions = []
        for _ in range(actions_per_round):
            if not st.board and st.gold <= 0 and not st.shop:
                break
            rec = adv.recommend(st)
            verb = _apply_top(ds, st, rec, rng, season)
            actions.append(verb)
            if verb in ("noop", "freeze", "skip"):
                break
            if st.gold <= 0 and verb != "merge":
                break

        if not st.board:
            log.append({
                "round": round_no,
                "ok": False,
                "reason": "empty_board",
                "actions": actions,
                "gold_granted": income,
                "gold_end": st.gold,
                "gold_unspent_cleared": True,
                "gold_interest": False,
                "gold_assumed": income_flat is None,
            })
            break

        wave_ok = False
        detail: Dict[str, Any] = {}
        if use_battle:
            try:
                sim = battle_adapter.simulate(st, ds)
            except Exception as exc:  # pragma: no cover
                sim = {"error": type(exc).__name__}
            detail["battle_sim"] = {
                "error": sim.get("error") if isinstance(sim, dict) else None,
                "result": (sim or {}).get("result") if isinstance(sim, dict) else None,
            }
            result = (sim or {}).get("result") if isinstance(sim, dict) else None
            if isinstance(result, dict):
                wave_ok = (
                    int(result.get("leaked") or 0) == 0
                    and str(result.get("reason") or "") == "cleared"
                )
                detail["leaked"] = result.get("leaked")
                detail["reason"] = result.get("reason")
        if not use_battle or detail.get("battle_sim", {}).get("error"):
            paper = clear_margin(st, ds=ds)
            paper = apply_reservoir_pressure(paper, detail.get("battle_sim"))
            detail["clear_margin"] = {
                "band": None if not paper else paper.get("band"),
                "margin": None if not paper else paper.get("margin"),
            }
            if not use_battle:
                wave_ok = bool(paper) and paper.get("band") != "critical"

        log.append({
            "round": round_no,
            "ok": wave_ok,
            "gold_granted": income,
            "gold_end": st.gold,
            "gold_unspent_cleared": True,
            "gold_interest": False,
            "gold_assumed": income_flat is None,
            "dispatch_level": st.dispatch_level,
            "board": [u.name for u in st.board],
            "actions": actions,
            "level_stem": meta["stem"],
            **detail,
        })
        # Rest end: any leftover is discarded next iteration when st.gold is
        # replaced; explicit zero here documents no carry / no interest.
        st.gold = 0
        if not wave_ok:
            break
        cleared = round_no

    return {
        "max_round_cleared": cleared,
        "regulation_level": regulation_level,
        "seed": seed,
        "season": season,
        "income_note": income_mod.ASSUMED_INCOME_NOTE,
        "income_disclaimer": income_mod.income_disclaimer(),
        "shop_odds": odds_disclaimer(),
        "log": log,
    }
