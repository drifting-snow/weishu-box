# -*- coding: utf-8 -*-
"""Unified marginal-impact ruler (step 1; NOT wired into engine yet).

Every shop decision is scored on the SAME ruler as a *marginal* change to the
current board. The impact is split into three explainable axes, each normalized
to 0..100 so that buying an operator, buying an item, and (later) refreshing or
upgrading the dispatch center become directly comparable:

  power   : combat strength against the CURRENT enemy picture.
            shop-tier/star baseline + counters.counter_score fit.
  economy : expected resource return on the gold spent.
            economy.investment_tags + econ_bonds engines (+ item_economy for
            item buys), each already discounted by payback window/feasibility.
  growth  : build progression on the current board.
            bond-activation headway + 3-copy merge + target-bond consistency +
            stack_feasibility growability of the bond being built.

total_impact = context-weighted sum of the three axes; impact_per_gold divides
by the action cost so a cheap and an expensive action are comparable on ROI.

Ownership (each existing module feeds exactly one axis, so no value is counted
twice):
  counters            -> power
  tier / star         -> power
  economy investment  -> economy
  econ_bonds engine   -> economy
  item_economy        -> economy (item buys)
  rules bond headway  -> growth
  merge progress      -> growth
  target bond         -> growth
  stack_feasibility   -> growth

This module only AGGREGATES the existing rule/economy modules and introduces no
new game facts. Stdlib only, deterministic. The engine keeps the hard tier-gate
veto (see Impact.legal); this ruler ranks, it does not override hard rules.
"""
from dataclasses import dataclass
from typing import Optional, Tuple, List

from .model import GameState, ShopCard
from .data import Dataset
from .rules import Rules
from . import economy as econ
from . import item_economy as ie
from . import counters as ctr
from . import econ_bonds as eb
from . import stack_feasibility as sf

# ---------------------------------------------------------------------------
# normalization caps (raw sub-score -> 0..100 axis). Centralized so the ruler
# stays stable and tunable in one place; raw module scales differ by design.
# ---------------------------------------------------------------------------
# power axis
TIER_BASE_FULL = 50.0          # tier 6 baseline contribution
STAR_MICRO = 3.0               # per star above 3-star (3/4/5 -> +0/+3/+6)
COUNTER_FULL_RAW = 30.0        # counter raw score mapped to COUNTER_PTS_FULL
COUNTER_PTS_FULL = 45.0
COUNTER_RAW_FLOOR = -10.0
# economy axis
INVEST_FULL_RAW = 30.0
INVEST_PTS_CAP = 60.0
ECONBOND_FULL_RAW = 25.0
ECONBOND_PTS_CAP = 40.0
# growth axis
MERGE_PTS = {0: 0.0, 1: 30.0, 2: 100.0}   # copies already held toward a triple
BOND_ACTIVATE_PTS = 60.0                  # this buy completes the activation
BOND_STACK_PTS = 15.0                     # bond already active, just adds layers
BOND_PROGRESS_FULL = 30.0                 # scaled by prospective/need
TARGET_BOND_PTS = 15.0
FEAS_PTS_CAP = 15.0

# ---- item axis weights (heuristic starting knobs, centralized for calibrate) ----
# numeric combat stat -> power-axis points. Negative stat_mods subtract naturally.
ITEM_STAT_WEIGHT = {
    "atk_pct": 1.0,        # +50% attack -> 50
    "hp_pct": 0.5,         # defensive stats count for less than raw damage
    "def_pct": 0.6,
    "aspd_flat": 0.5,
    "aspd_pct": 0.5,
    "sp_cost_pct": -0.8,   # negative sp cost is a benefit -> invert sign below
    "sp_regen": 80.0,      # +0.15/sec -> 12
    "block": 8.0,
    "res": 0.8,
    "redeploy_pct": -0.4,  # negative redeploy time is a benefit
}
# qualitative drawback -> flat power penalty
ITEM_DRAWBACK_PENALTY = {
    "unhealable": 15.0,
    "hp_drain_pct": 2.0,       # per 1% max-hp drained per second
    "taunt_up": 8.0,
}
HP_DRAIN_FLAT_PER_60 = 10.0   # 60 flat hp/sec drain -> -10
# economy items get a slight deliberate boost per user (gold is scarce). The
# neutral floor is intentionally 0: a break-even consumable (1g -> 1g) earns no
# base score, so economy items rank by REAL expected net gold instead of a
# constant floor that let them outrank early board-building operators.
ECON_ITEM_BOOST = 1.15
ECON_ITEM_NEUTRAL = 0.0

# ---- Plan-A structural corrections (carrier-first, spare-gold investment) ----
# 1) board-presence: an operator that adds a NEW unit is the 0->1 skeleton of
#    the build. Highest on an empty board, decays as deploy slots fill. Booked
#    onto the growth axis (it is build construction, not combat power).
PRESENCE_FULL = 35.0
# 2) carrier maturity: an item's +X% is a multiplier with no value without a
#    mature holder. Empty board -> CARRIER_BASE (only future/hoard value);
#    a high-tier core on the board raises it toward 1.0. Applied to the item
#    POWER axis only; bond/stack growth synergy is not carrier-discounted.
CARRIER_BASE = 0.40
CARRIER_MAX_TIER = 6.0
# growth-axis points for item-driven covenant progression
ITEM_BOND_TARGET_PTS = 60.0
ITEM_BOND_HELD_PTS = 35.0
ITEM_STACK_GAIN_PTS = 28.0       # non-consumable layer grant (推荐信/补剂)
ITEM_CONSUMABLE_STACK_PTS = 35.0  # consumable layer grant (随身身份牌)

# default context weights (sum to 1). Order matches (power, growth, economy).
DEFAULT_WEIGHTS = (0.40, 0.35, 0.25)
# enemy keys that demand an immediate combat answer -> shift weight to power.
HIGH_PRESSURE_ENEMIES = {"lethal", "revival", "special"}
EARLY_ROUND = 3


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _deploy_slots(ds: Dataset, state: GameState) -> int:
    """Distinct-operator deploy capacity for the current dispatch level."""
    slots = ds.slots(state.dispatch_level, state.difficulty)
    return max(1, int(slots or 1))


def board_fill(ds: Dataset, state: GameState) -> float:
    """Fraction of deploy slots occupied by distinct held operators (0..1)."""
    held = len({u.name for u in state.board})
    return _clamp(held / _deploy_slots(ds, state), 0.0, 1.0)


def carrier_maturity(ds: Dataset, state: GameState) -> float:
    """How good a holder the current board offers an equipment multiplier.

    Empty board -> CARRIER_BASE (item can only be hoarded); otherwise scale by
    the highest shop tier present, so a real high-tier core approaches 1.0.
    """
    if not state.board:
        return CARRIER_BASE
    max_tier = 0
    for u in state.board:
        op = ds.operator(u.name)
        if op:
            max_tier = max(max_tier, op.get("shop_tier") or 1)
    return _clamp(CARRIER_BASE + (1.0 - CARRIER_BASE) *
                  (max_tier / CARRIER_MAX_TIER), CARRIER_BASE, 1.0)


def axis_weights(state: GameState) -> Tuple[float, float, float]:
    """(power, growth, economy) weights adapted to the current board context.

    High-pressure enemy pictures raise power; the opening rounds favor economy/
    growth investment. Adjustments are deliberately small and renormalized so
    the three weights always sum to 1 (keeps total_impact on a 0..100 scale).
    """
    wp, wg, we = DEFAULT_WEIGHTS
    if set(state.enemy_types) & HIGH_PRESSURE_ENEMIES:
        wp += 0.10
        wg -= 0.05
        we -= 0.05
    if state.round <= EARLY_ROUND:
        we += 0.05
        wp -= 0.05
    vals = [max(0.05, w) for w in (wp, wg, we)]
    s = sum(vals)
    return tuple(round(w / s, 4) for w in vals)


@dataclass
class Impact:
    target: str
    kind: str                     # "operator" | "item"
    cost: int
    affordable: bool
    legal: bool                   # passes the hard tier gate (engine vetoes False)
    power: float
    economy: float
    growth: float
    weights: Tuple[float, float, float]
    total_impact: float
    impact_per_gold: Optional[float]
    reasons: List[str]

    def as_dict(self) -> dict:
        return {
            "target": self.target, "kind": self.kind, "cost": self.cost,
            "affordable": self.affordable, "legal": self.legal,
            "power": round(self.power, 1), "economy": round(self.economy, 1),
            "growth": round(self.growth, 1), "weights": self.weights,
            "total_impact": round(self.total_impact, 1),
            "impact_per_gold": (round(self.impact_per_gold, 2)
                                if self.impact_per_gold is not None else None),
            "reasons": self.reasons,
        }


def _counter_pts(ds: Dataset, op: dict, state: GameState,
                 bond_counts: dict) -> (float, List[str]):
    """Normalize counters.counter_score onto the power axis (0 if no picture)."""
    if not state.enemy_types:
        return 0.0, []
    cs = ctr.counter_score(ds, op, state.enemy_types, bond_counts)
    if cs.get("neutral"):
        return 0.0, []
    raw = max(COUNTER_RAW_FLOOR, min(COUNTER_FULL_RAW, cs["score"]))
    pts = (raw / COUNTER_FULL_RAW) * COUNTER_PTS_FULL
    reasons = ["克制[%s]" % h["tag"] for h in cs["hits"]]
    reasons += ["⚠" + a for a in cs["anti_synergy"]]
    return pts, reasons


def _bond_headway(ds: Dataset, op: dict, state: GameState,
                  bond_counts: dict) -> (float, str, Optional[str]):
    """Best bond-activation marginal across the operator's bonds.

    Returns (points, reason, focus_bond) where focus_bond is the bond driving
    the score (used for the feasibility add-on).
    """
    already = any(u.name == op["name"] for u in state.board)
    best_pts, best_reason, focus = 0.0, "", None
    for bond in op.get("bonds", []):
        need = ds.bond_need(bond)
        if not need:
            continue
        have = bond_counts.get(bond, 0)
        prospective = have + (0 if already else 1)
        if have >= need:
            pts, why = BOND_STACK_PTS, "%s已激活，叠加层数" % bond
        elif prospective >= need:
            pts, why = BOND_ACTIVATE_PTS, "%s差1人激活，买入即点亮(%d/%d)" % (bond, have, need)
        else:
            pts = BOND_PROGRESS_FULL * (prospective / need)
            why = "凑%s盟约(%d/%d)" % (bond, prospective, need)
        if pts > best_pts:
            best_pts, best_reason, focus = pts, why, bond
    return best_pts, best_reason, focus


def operator_impact(ds: Dataset, rules: Rules, card: ShopCard,
                    state: GameState) -> Impact:
    """Three-axis marginal impact of buying one shop operator."""
    op = ds.operator(card.name) or {"name": card.name,
                                    "bonds": [card.bond] if card.bond else [],
                                    "shop_tier": card.tier, "star": None,
                                    "mechanic_tags": [], "anti_air": False}
    bond_counts = rules.bond_counts(state)
    reasons: List[str] = []

    # ---- POWER axis: tier/star baseline + enemy-counter fit ----
    tier = op.get("shop_tier") or card.tier or 1
    tier_base = TIER_BASE_FULL * (tier / 6.0)
    star = op.get("star")
    star_micro = (int(star) - 3) * STAR_MICRO if star else 0.0
    counter_pts, counter_reasons = _counter_pts(ds, op, state, bond_counts)
    power = _clamp(tier_base + star_micro + counter_pts)
    if counter_reasons:
        reasons += ["战力:" + r for r in counter_reasons]

    # ---- ECONOMY axis: per-card investment + off-field economy-bond engine ----
    inv_tags = econ.investment_tags(op)
    inv_raw = sum(t["weight"] for t in inv_tags)
    inv_pts = min(INVEST_PTS_CAP, (inv_raw / INVEST_FULL_RAW) * INVEST_PTS_CAP)
    ebv = eb.econ_bond_value(ds, op, state, bond_counts)
    eb_pts = min(ECONBOND_PTS_CAP,
                 (max(0.0, ebv["score"]) / ECONBOND_FULL_RAW) * ECONBOND_PTS_CAP)
    economy = _clamp(inv_pts + eb_pts)
    if inv_tags:
        reasons.append("经济:投资型(" + "、".join(sorted({t["tag"] for t in inv_tags})) + ")")
    for a in ebv["active"]:
        reasons.append("经济:%s引擎已激活(时机%.0f%%,可养性%.2f)" %
                       (a["bond"], ebv["timing_factor"] * 100, a.get("feasibility", 1.0)))

    # ---- GROWTH axis: merge + bond headway + target + feasibility ----
    held = next((u.count for u in state.board if u.name == card.name), 0)
    merge_pts = MERGE_PTS.get(min(held, 2), 0.0)
    if merge_pts:
        reasons.append("成长:已有%d张，向三合一推进" % held)
    headway_pts, headway_reason, focus_bond = _bond_headway(ds, op, state, bond_counts)
    if headway_reason:
        reasons.append("成长:" + headway_reason)
    target_pts = TARGET_BOND_PTS if state.target_bond and \
        state.target_bond in op.get("bonds", []) else 0.0
    if target_pts:
        reasons.append("成长:契合目标盟约%s" % state.target_bond)
    feas_bond = state.target_bond if state.target_bond in op.get("bonds", []) \
        else focus_bond
    feas_pts = sf.feasibility_factor(feas_bond) * FEAS_PTS_CAP if feas_bond else 0.0

    # Plan-A mechanism 1: board-presence marginal. A NEW distinct unit is the
    # 0->1 build skeleton; strongest on an empty board, decaying as slots fill.
    # A duplicate copy (merge fodder) adds no new presence.
    is_new_unit = not any(u.name == card.name for u in state.board)
    fill = board_fill(ds, state)
    presence_pts = PRESENCE_FULL * (1.0 - fill) if is_new_unit else 0.0
    if presence_pts:
        reasons.append("成长:新单位铺场边际%.0f(板填充%.0f%%)" % (presence_pts, fill * 100))
    growth = _clamp(merge_pts + headway_pts + target_pts + feas_pts + presence_pts)

    # ---- combine on the context-weighted ruler ----
    wp, wg, we = axis_weights(state)
    # Plan-A mechanism 3 (single-card proxy): economy investment is discounted
    # while the board is empty (build skeleton first) and recovers as the board
    # fills and leftover gold is better spent on economy. Applies to all kinds.
    econ_factor = 0.5 + 0.5 * fill
    economy = _clamp(economy * econ_factor)
    total = wp * power + wg * growth + we * economy
    cost = rules.card_buy_price(card)
    per_gold = round(total / cost, 2) if cost > 0 else None
    legal = not rules.violates_tier_gate(card, state.dispatch_level)

    return Impact(
        target=card.name, kind="operator", cost=cost,
        affordable=state.gold >= cost, legal=legal,
        power=round(power, 1), economy=round(economy, 1), growth=round(growth, 1),
        weights=(wp, wg, we), total_impact=round(total, 1),
        impact_per_gold=per_gold, reasons=reasons,
    )


def _item_power(struct):
    """Power-axis points from parsed numeric stats and qualitative drawbacks.

    Only the regex-extracted numeric part is scored. When needs_review is set
    the conditional/mechanic portion is deliberately excluded (no fake constant),
    so this stays honest for the state-dependent items.
    """
    if not struct:
        return 0.0, ["战力:装备效果未结构化，暂不计分"]
    pts = 0.0
    details = []
    for key, val in struct.get("stat_mods", {}).items():
        w = ITEM_STAT_WEIGHT.get(key)
        if w is None:
            continue
        # uniform signed product: benefit stats (sp cost / redeploy) store a
        # negative weight, so negative value * negative weight -> positive pts;
        # genuine drawbacks keep a positive weight and subtract naturally.
        pts += w * val
    for d in struct.get("drawbacks", []):
        kind, val = d["kind"], d.get("value")
        if kind == "hp_drain_flat":
            pts -= HP_DRAIN_FLAT_PER_60 * ((val or 60) / 60.0)
        elif kind == "hp_drain_pct":
            pts -= ITEM_DRAWBACK_PENALTY["hp_drain_pct"] * (val or 1)
        elif kind in ITEM_DRAWBACK_PENALTY:
            pts -= ITEM_DRAWBACK_PENALTY[kind]
    if struct.get("stat_mods"):
        details.append("战力:数值属性合计%.0f" % pts)
    for d in struct.get("drawbacks", []):
        details.append("战力:⚠负面[%s]" % d["kind"])
    if struct.get("needs_review"):
        details.append("战力:含条件/组合效果，条件部分后置不计分")
    return _clamp(pts), details


def item_impact(ds: Dataset, rules: Rules, card: ShopCard,
                state: GameState) -> Impact:
    """Three-axis marginal impact of buying one shop item.

    Consumables (销毁) are economy material valued round-aware by item_economy
    and given a slight boost (gold is scarce). Combat items score their parsed
    numeric stats on the power axis (drawbacks subtract); bond-dedicated and
    layer-grant items feed growth. Conditional/mechanic/combo effects are
    flagged needs_review and not scored until a combat/state layer exists.
    """
    it = ds.item(card.name) or {}
    struct = ds.item_structured(card.name)
    # item price may be stored as a string in items.json; coerce defensively.
    cost = int(card.price) if str(card.price).isdigit() else 0
    reasons: List[str] = []
    wp, wg, we = axis_weights(state)
    bond = it.get("bond")
    counts = rules.bond_counts(state)
    fill = board_fill(ds, state)          # Plan-A: spare-gold / board context
    carrier = carrier_maturity(ds, state)  # Plan-A: holder quality for a multiplier
    econ_factor = 0.5 + 0.5 * fill

    if struct and struct.get("consumable"):
        # ---- economy material: round-aware valuation, slightly boosted ----
        ev = ie.value_item(it, state.round) if it else None
        if ev is not None:
            economy = _clamp(ECON_ITEM_NEUTRAL + ev["score"] * ECON_ITEM_BOOST)
            reasons.append("经济:" + ev["rationale"])
        else:
            economy = ECON_ITEM_NEUTRAL
        # Plan-A mechanism 3: economy is spare-gold investment; discount while
        # the build skeleton is still empty, recover as deploy slots fill.
        economy = _clamp(economy * econ_factor)
        power, power_notes = 0.0, []
        growth = 0.0
        if struct.get("stack_gain"):
            growth = ITEM_CONSUMABLE_STACK_PTS
            reasons.append("成长:销毁即给盟约层数%+d" % struct["stack_gain"]["amount"])
    else:
        # ---- combat / bond equipment ----
        raw_power, power_notes = _item_power(struct)
        # Plan-A mechanism 2: a +X% multiplier needs a mature holder. Discount
        # the POWER axis on an empty/weak board; bond/stack growth is untouched.
        power = _clamp(raw_power * carrier)
        if raw_power > 0:
            power_notes.append("战力:携带者成熟度%.0f%%折减" % (carrier * 100))
        reasons += power_notes
        economy = 0.0  # non-consumables do not produce gold; no fake baseline
        growth = 0.0
        if bond and bond == state.target_bond:
            growth = ITEM_BOND_TARGET_PTS
            reasons.append("成长:目标盟约%s专属装备" % bond)
        elif bond and counts.get(bond, 0) > 0:
            growth = ITEM_BOND_HELD_PTS
            reasons.append("成长:适配%s体系" % bond)
        if struct and struct.get("stack_gain"):
            growth += ITEM_STACK_GAIN_PTS
            sg = struct["stack_gain"]
            reasons.append("成长:盟约层数%+d(%s)" %
                           (sg["amount"], "临时层" if sg["transient"] else "固定层"))
        if growth == 0.0:
            reasons.append("成长:无盟约/叠层协同")

    total = wp * power + wg * growth + we * economy
    per_gold = round(total / cost, 2) if cost > 0 else None

    return Impact(
        target=card.name, kind="item", cost=cost,
        affordable=state.gold >= cost, legal=True,
        power=round(power, 1), economy=round(economy, 1), growth=round(growth, 1),
        weights=(wp, wg, we), total_impact=round(total, 1),
        impact_per_gold=per_gold, reasons=reasons,
    )


def evaluate_shop(ds: Dataset, rules: Rules, state: GameState) -> List[Impact]:
    """Convenience: rank every current shop slot on the unified ruler."""
    out = []
    for card in state.shop:
        out.append(operator_impact(ds, rules, card, state)
                   if card.kind == "operator"
                   else item_impact(ds, rules, card, state))
    out.sort(key=lambda im: im.total_impact, reverse=True)
    return out
