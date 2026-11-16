# -*- coding: utf-8 -*-
"""One self-play episode: roll shop → recommend → apply → battle clear check."""
from __future__ import annotations

import json
import os
import random
from typing import Any, Dict, List, Optional

from advisor.battle import adapter as battle_adapter
from advisor.clear_margin import apply_reservoir_pressure, clear_margin
from advisor.data import Dataset
from advisor import economy as econ
from advisor.enemy_catalog import (
    load_enemy_catalog,
    load_enemy_name_index,
    resolve_enemies,
)
from advisor.engine import Advisor
from advisor.model import BoardUnit, GameState

from . import income as income_mod
from .shop_roll import (
    merge_reward_config,
    odds_disclaimer,
    roll_merge_reward,
    roll_shop,
)

# Default ε for action sampling among top recommendations (P4).
DEFAULT_ACTION_EPSILON = 0.15
DEFAULT_ACTION_TOP_K = 4

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
    uniq = list(dict.fromkeys(names))
    resolved = resolve_enemies(uniq, catalog, name_index)
    return {
        "enemy_names": list(resolved.get("names") or uniq),
        "enemy_types": list(resolved.get("trait_keys") or []),
    }


def _board_add(board: List[BoardUnit], name: str, tier: int, bonds: List[str]) -> bool:
    """Add a copy; return True if this call promoted the unit to elite."""
    for u in board:
        if u.name == name:
            u.count = int(u.count) + 1
            if u.count >= 3 and not u.elite:
                u.count = 1
                u.elite = True
                return True
            return False
    board.append(BoardUnit(name=name, count=1, tier=tier, bonds=list(bonds or []),
                           elite=False))
    return False


def _promote_elite(board: List[BoardUnit], name: str) -> bool:
    """Force elite promotion for merge-ready units; return True if promoted."""
    for u in board:
        if u.name == name and (not u.elite) and int(u.count) >= 3:
            u.count = 1
            u.elite = True
            return True
    return False


def _ordered_picks(
    rec: dict,
    rng: random.Random,
    *,
    epsilon: float = DEFAULT_ACTION_EPSILON,
    top_k: int = DEFAULT_ACTION_TOP_K,
) -> List[dict]:
    """ε-greedy reorder: with prob ε, sample one of top-k by score to try first."""
    picks = list(rec.get("recommendations") or [])
    if rec.get("top_pick"):
        picks = [rec["top_pick"]] + [p for p in picks if p is not rec.get("top_pick")]
    # Dedup by (verb, target) while preserving order.
    seen = set()
    uniq = []
    for p in picks:
        key = (p.get("verb"), p.get("target"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    picks = uniq
    if len(picks) <= 1 or float(epsilon) <= 0 or rng.random() >= float(epsilon):
        return picks
    k = max(1, min(int(top_k), len(picks)))
    head = picks[:k]
    weights = []
    for p in head:
        try:
            w = float(p.get("score") or 0.0)
        except (TypeError, ValueError):
            w = 0.0
        weights.append(max(w, 0.05))
    chosen = rng.choices(head, weights=weights, k=1)[0]
    return [chosen] + [p for p in picks if p is not chosen]


def _remove_shop_card(st: GameState, name: str, kind: Optional[str] = None) -> None:
    out = []
    removed = False
    for c in st.shop:
        if (not removed and c.name == name
                and (kind is None or c.kind == kind)):
            removed = True
            continue
        out.append(c)
    st.shop = out


def _equip_item(ds: Dataset, st: GameState, item_name: str) -> bool:
    """Attach item to first board carrier with a free equipment slot."""
    if not st.board:
        return False
    if st.equipment is None:
        st.equipment = {}
    cap = int((ds.economy or {}).get("items_per_operator") or 2)
    for u in st.board:
        bag = list(st.equipment.get(u.name) or [])
        if len(bag) < cap:
            bag.append(item_name)
            st.equipment[u.name] = bag
            return True
    first = st.board[0].name
    bag = list(st.equipment.get(first) or [])
    bag.append(item_name)
    st.equipment[first] = bag
    return True


def _sell_operator(ds: Dataset, st: GameState, name: str) -> bool:
    for i, u in enumerate(st.board):
        if u.name != name:
            continue
        op = ds.operator(name)
        gain = econ.sell_price(ds, op, advanced=bool(u.elite)) if op else \
            int((ds.economy or {}).get("default_sell_price") or 1)
        st.gold += int(gain)
        if (not u.elite) and int(u.count) > 1:
            u.count = int(u.count) - 1
        else:
            st.board.pop(i)
            if name not in {x.name for x in st.board}:
                (st.equipment or {}).pop(name, None)
        return True
    return False


def _max_hand(ds: Dataset) -> int:
    return int((ds.economy or {}).get("max_hand") or 10)


def _rest_start_shop(
    ds: Dataset,
    st: GameState,
    *,
    season: str,
    rng: random.Random,
) -> Dict[str, Any]:
    """Build rest-start shop; honor freeze carry (wiki: only empty/unfrozen refill).

    Freeze locks current remaining cards into the next rest, then clears
    (one-round lock). Operator 栏位 and the dedicated item slot refill
    independently. Manual refresh re-rolls everything separately.
    """
    from .shop_roll import item_mix_model, item_slots_per_shop, roll_item_cards

    n_ops = int(ds.slots(st.dispatch_level, st.difficulty) or 3)
    n_items = item_slots_per_shop() if item_mix_model() == "dedicated_item_slots" else 0
    meta = {"shop_carry_frozen": False, "frozen_kept": 0, "frozen_filled": 0}
    if st.frozen and st.shop:
        prev = list(st.shop)
        kept_ops = [c for c in prev if getattr(c, "kind", None) != "item"][:n_ops]
        kept_items = [c for c in prev if getattr(c, "kind", None) == "item"][:n_items]
        need_ops = max(0, n_ops - len(kept_ops))
        need_items = max(0, n_items - len(kept_items))
        filler_ops = roll_shop(
            ds, st.dispatch_level, st.difficulty,
            season=season, rng=rng, n_slots=need_ops,
            include_items=False) if need_ops else []
        filler_items = roll_item_cards(
            ds, st.dispatch_level, need_items, rng=rng) if need_items else []
        st.shop = kept_ops + filler_ops + kept_items + filler_items
        meta.update({
            "shop_carry_frozen": True,
            "frozen_kept": len(kept_ops) + len(kept_items),
            "frozen_filled": len(filler_ops) + len(filler_items),
        })
        # Lock delivered for this rest start.
        st.frozen = False
    else:
        st.shop = roll_shop(
            ds, st.dispatch_level, st.difficulty, season=season, rng=rng)
        st.frozen = False
    return meta


def _grant_merge_reward(
    ds: Dataset,
    st: GameState,
    rng: random.Random,
    season: str,
    ctx: Dict[str, Any],
) -> None:
    """ASSUMED: replace shop with 晋级 3-pick-1 and grant free buys."""
    cfg = merge_reward_config()
    st.shop = roll_merge_reward(
        ds, st.dispatch_level, season=season, rng=rng)
    ctx["free_buys"] = int(cfg.get("free_buys") or 1)
    ctx["merge_rewards"] = int(ctx.get("merge_rewards") or 0) + 1
    ctx["merge_reward_active"] = True


def _apply_top(
    ds: Dataset,
    st: GameState,
    rec: dict,
    rng: random.Random,
    season: str,
    *,
    ctx: Optional[Dict[str, Any]] = None,
    epsilon: float = DEFAULT_ACTION_EPSILON,
    top_k: int = DEFAULT_ACTION_TOP_K,
) -> str:
    """Apply one sampled/affordable recommendation; return verb or 'noop'."""
    ctx = ctx if ctx is not None else {}
    ctx.setdefault("free_buys", 0)
    picks = _ordered_picks(rec, rng, epsilon=epsilon, top_k=top_k)
    for action in picks:
        verb = str(action.get("verb") or "")
        cost = int(action.get("cost") or 0)
        if verb == "buy":
            name = action.get("target")
            card = next((c for c in st.shop if c.name == name), None)
            kind = (card.kind if card else None) or "operator"
            free = int(ctx.get("free_buys") or 0) > 0

            if kind == "item" or (card is None and ds.item(name) and not ds.operator(name)):
                it = ds.item(name)
                if not it:
                    continue
                try:
                    price = int(card.price) if card and card.price is not None \
                        else int(it.get("price") or cost or 0)
                except (TypeError, ValueError):
                    price = int(cost or 0)
                if free:
                    price = 0
                if price > st.gold:
                    continue
                if not st.board:
                    continue
                st.gold -= price
                if not _equip_item(ds, st, name):
                    st.gold += price
                    continue
                if free:
                    ctx["free_buys"] = int(ctx["free_buys"]) - 1
                _remove_shop_card(st, name, kind="item")
                return "buy_item"

            op = ds.operator(name)
            if not op:
                continue
            pay = 0 if free else cost
            if pay > st.gold:
                continue
            if (name not in {u.name for u in st.board}
                    and len(st.board) >= _max_hand(ds)):
                victim = st.board[-1].name
                if victim == name or not _sell_operator(ds, st, victim):
                    continue
            st.gold -= pay
            if free:
                ctx["free_buys"] = int(ctx["free_buys"]) - 1
            promoted = _board_add(
                st.board, name, int(op.get("shop_tier") or 1),
                list(op.get("bonds") or []))
            _remove_shop_card(st, name, kind="operator")
            if promoted:
                _grant_merge_reward(ds, st, rng, season, ctx)
                return "buy_merge_reward"
            return "buy"

        if verb == "sell":
            name = action.get("target")
            if name and _sell_operator(ds, st, name):
                return "sell"
            continue

        if verb == "refresh":
            if cost > st.gold:
                continue
            st.gold -= cost
            st.shop = roll_shop(ds, st.dispatch_level, st.difficulty,
                                season=season, rng=rng)
            st.frozen = False
            ctx["free_buys"] = 0
            ctx["merge_reward_active"] = False
            return "refresh"

        if verb == "upgrade":
            if cost > st.gold or st.dispatch_level >= 6:
                continue
            st.gold -= cost
            st.dispatch_level = int(st.dispatch_level) + 1
            return "upgrade"

        if verb == "merge":
            name = action.get("target")
            if name and _promote_elite(st.board, name):
                _grant_merge_reward(ds, st, rng, season, ctx)
                return "merge_reward"
            return "merge"

        if verb == "freeze":
            st.frozen = True
            return "freeze"

        if verb == "skip":
            return "skip"
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
    action_epsilon: float = DEFAULT_ACTION_EPSILON,
    action_top_k: int = DEFAULT_ACTION_TOP_K,
    enemy_hp_scale: float = 1.0,
) -> Dict[str, Any]:
    """Play until a wave fails or ``max_rounds`` cleared.

    Win condition per wave (v0): battle_sim cleared with leaked==0 when
    ``use_battle``; else clear_margin band != critical after reservoir wire.

    ``enemy_hp_scale`` softens stub enemy HP for smoke/self-play gradient
    reach (e.g. 0.8 ≈ quick-sim); default 1.0 leaves regulation HP alone.
    """
    ds = ds or Dataset()
    adv = Advisor(ds)
    rng = random.Random(seed)
    waves = _load_waves()
    mode = _mode_key(regulation_level)
    catalog = load_enemy_catalog()
    name_index = load_enemy_name_index()
    try:
        hp_scale = float(enemy_hp_scale)
    except (TypeError, ValueError):
        hp_scale = 1.0
    if hp_scale <= 0:
        hp_scale = 1.0

    st = GameState(
        round=1,
        gold=0,
        dispatch_level=1,
        difficulty="standard",
        regulation_level=int(regulation_level),
        board=[],
        shop=[],
        frozen=False,
        equipment={},
    )
    log: List[dict] = []
    cleared = 0
    act_ctx: Dict[str, Any] = {
        "free_buys": 0,
        "merge_rewards": 0,
        "merge_reward_active": False,
    }

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
        shop_meta = _rest_start_shop(ds, st, season=season, rng=rng)
        act_ctx["free_buys"] = 0
        act_ctx["merge_reward_active"] = False

        actions = []
        for _ in range(actions_per_round):
            if not st.board and st.gold <= 0 and not st.shop:
                break
            rec = adv.recommend(st)
            verb = _apply_top(
                ds, st, rec, rng, season, ctx=act_ctx,
                epsilon=action_epsilon, top_k=action_top_k)
            actions.append(verb)
            if verb in ("noop", "freeze", "skip"):
                break
            if (st.gold <= 0 and int(act_ctx.get("free_buys") or 0) <= 0
                    and verb not in ("merge", "merge_reward", "sell",
                                     "buy_merge_reward")):
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
                "frozen": st.frozen,
                **shop_meta,
            })
            break

        wave_ok = False
        detail: Dict[str, Any] = {"enemy_hp_scale": hp_scale}
        if use_battle:
            try:
                sim = battle_adapter.simulate(
                    st, ds, enemy_hp_scale=hp_scale)
            except Exception as exc:  # pragma: no cover
                sim = {"error": type(exc).__name__}
            detail["battle_sim"] = {
                "error": sim.get("error") if isinstance(sim, dict) else None,
                "result": (sim or {}).get("result") if isinstance(sim, dict) else None,
                "hp_multiplier": (
                    (sim or {}).get("hp_multiplier") if isinstance(sim, dict) else None),
            }
            result = (sim or {}).get("result") if isinstance(sim, dict) else None
            if isinstance(result, dict):
                wave_ok = (
                    int(result.get("leaked") or 0) == 0
                    and str(result.get("reason") or "") == "cleared"
                )
                detail["leaked"] = result.get("leaked")
                detail["reason"] = result.get("reason")
                # Surface reservoir signals for P6/P7 objective pressure terms.
                try:
                    total = int(result.get("total") or 0)
                    killed = int(result.get("killed") or 0)
                    leaked_n = int(result.get("leaked") or 0)
                except (TypeError, ValueError):
                    total = killed = leaked_n = 0
                max_overflow = 0.0
                pressure = result.get("pressure")
                if isinstance(pressure, dict):
                    for tile in pressure.values():
                        if not isinstance(tile, dict):
                            continue
                        try:
                            max_overflow = max(
                                max_overflow,
                                float(tile.get("overflow_seconds") or 0.0))
                        except (TypeError, ValueError):
                            pass
                clear_frac = None
                if total > 0:
                    resolved = max(killed + leaked_n, total)
                    clear_frac = max(
                        0.0, min(1.0, killed / float(resolved)))
                detail["reservoir"] = {
                    "clear_frac": None if clear_frac is None else round(clear_frac, 4),
                    "max_overflow_s": round(max_overflow, 3),
                    "killed": killed,
                    "leaked": leaked_n,
                    "total": total,
                }
                detail["clear_frac"] = detail["reservoir"]["clear_frac"]
                detail["max_overflow_s"] = detail["reservoir"]["max_overflow_s"]
        # Always log paper clear_margin (margin proxy) for objective sensitivity
        # even when battle decides ok/fail — knobs move paper margin earlier.
        paper = clear_margin(st, ds=ds)
        paper = apply_reservoir_pressure(paper, detail.get("battle_sim"))
        if isinstance(paper, dict):
            detail["clear_margin"] = {
                "band": paper.get("band"),
                "margin": paper.get("margin"),
            }
            try:
                detail["margin"] = (
                    None if paper.get("margin") is None
                    else float(paper.get("margin")))
            except (TypeError, ValueError):
                detail["margin"] = None
            if isinstance(paper.get("reservoir"), dict):
                res = paper["reservoir"]
                if detail.get("clear_frac") is None and res.get("clear_frac") is not None:
                    detail["clear_frac"] = res.get("clear_frac")
                if detail.get("max_overflow_s") is None and res.get("max_overflow_s") is not None:
                    detail["max_overflow_s"] = res.get("max_overflow_s")
                detail.setdefault("reservoir", res)
        if not use_battle:
            wave_ok = bool(paper) and isinstance(paper, dict) and paper.get("band") != "critical"

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
            "frozen_end": st.frozen,
            "shop_kinds": [c.kind for c in st.shop],
            "merge_rewards_so_far": int(act_ctx.get("merge_rewards") or 0),
            **shop_meta,
            **detail,
        })
        # Rest end: leftover gold discarded next iteration; freeze flag may
        # remain True so the next rest keeps locked shop cards.
        st.gold = 0
        if not wave_ok:
            break
        cleared = round_no

    return {
        "max_round_cleared": cleared,
        "regulation_level": regulation_level,
        "seed": seed,
        "season": season,
        "enemy_hp_scale": hp_scale,
        "income_note": income_mod.ASSUMED_INCOME_NOTE,
        "income_disclaimer": income_mod.income_disclaimer(),
        "shop_odds": odds_disclaimer(),
        "action_epsilon": float(action_epsilon),
        "merge_rewards": int(act_ctx.get("merge_rewards") or 0),
        "log": log,
    }
