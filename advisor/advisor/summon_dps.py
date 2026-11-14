# -*- coding: utf-8 -*-
"""Leithanien bond-summon DPS ("一个小节" / "一个乐部").

The Garrison-Protocol Leithanien (Leytaniya) core bond spawns temporary
artificial-caster units when enemies are knocked down. They are not mechanics
"summons" but enemy-type units (SP32/SP33) carrying a normal enemy attribute
table, plus a hard-coded decay rule:

    forbidden heal + lose 10% of MAX HP every second  -> ~10 s lifespan

All static stats come from data/leithanien_summons.json (transcribed from the
PRTS unit pages, URLs recorded there). This module only does deterministic
arithmetic on those facts; every modelling assumption that is NOT a published
number lives in an explicit, named constant below so it can be replaced once
in-game measurements arrive. Nothing here fabricates a stat.

Coverage today: single-summon panel/effective DPS, lifetime hit & damage
estimates, and bond ATK-buff scaling. Not covered (and returned as None /
flagged, never guessed): per-enemy arts mitigation, movement-to-contact time,
actual spawn count per wave, and the (待补充) ownership rule.
"""
import json
import os

# Reuse the battle kernel's exact mitigation constants so summon tanking uses
# the SAME 5% floor / RES cap as advisor/battle/damage.py (single source).
try:
    from .damage_calc import MIN_DAMAGE_RATIO, RES_CAP
except ImportError:  # pragma: no cover - allow bare-path tooling
    MIN_DAMAGE_RATIO, RES_CAP = 0.05, 95.0

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")

# --- Explicit assumptions (NOT published numbers; replace when measured) -----
# Decal: lose 10% max HP/s with heal forbidden and 0 regen -> nominal lifespan.
DRAIN_PCT_PER_SEC = 0.10
# A unit is removed once accumulated drain reaches its full max HP.
NOMINAL_LIFETIME_SEC = round(1.0 / DRAIN_PCT_PER_SEC, 3)  # 10.0
# Assume a summon is already in range and attacking for its whole life. Real
# contact time is shorter because it must walk to an enemy first; we expose the
# raw (upper-bound) figure and let callers apply an uptime factor.
DEFAULT_UPTIME = 1.0
# Lebu double-hit cycle: 3 single attacks then 1 double attack = 4 attack
# actions / 5 hits. Sourced from its skill text ("3 次攻击后下一次 2 连击").
LEBU_CYCLE_ACTIONS = 4
LEBU_CYCLE_HITS = 5


def _load_summons():
    with open(os.path.join(DATA_DIR, "leithanien_summons.json"), encoding="utf-8") as f:
        doc = json.load(f)
    return doc["summons"], doc["bond_mechanic"]


SUMMONS, BOND_MECHANIC = _load_summons()


def summon_ids():
    return list(SUMMONS.keys())


def get_summon(sid):
    return SUMMONS.get(sid)


def bond_atk_multiplier(stacks):
    """Leithanien ATK buff: +(30 + 1*stack)% for operators AND summons."""
    stacks = max(0, int(stacks))
    return 1.0 + (30.0 + stacks) / 100.0


def panel_dps(sid):
    """Unbuffed single-target DPS from ATK / attack interval.

    xiaojie: one hit per action. lebu: uses its double-hit cycle average, so
    panel DPS already accounts for the periodic 2-hit attack.
    """
    s = SUMMONS[sid]
    atk = s["stats"]["atk"]
    interval = s["stats"]["attack_interval"]
    if sid == "lebu":
        hits_per_action = LEBU_CYCLE_HITS / LEBU_CYCLE_ACTIONS  # 1.25
    else:
        hits_per_action = 1.0
    return round(atk * hits_per_action / interval, 3)


def buffed_attack(sid, stacks):
    """ATK after the Leithanien bond percentage multiplier."""
    return round(SUMMONS[sid]["stats"]["atk"] * bond_atk_multiplier(stacks), 3)


def effective_dps(sid, stacks=0, uptime=DEFAULT_UPTIME):
    """Expected DPS over the summon's life.

    stacks : Leithanien bond stack count (ATK buff applies to summons too).
    uptime : fraction of life spent actually attacking (0..1); 1.0 = in-range
             immediately (upper bound). Reduce to model walk-to-contact loss.
    """
    uptime = min(1.0, max(0.0, float(uptime)))
    return round(panel_dps(sid) * bond_atk_multiplier(stacks) * uptime, 3)


def lifetime_estimate(sid, stacks=0, uptime=DEFAULT_UPTIME):
    """How many hits and how much raw damage one summon deals before decay.

    Returns a dict with the nominal 10 s window, estimated attack actions,
    hits (lebu double-hit counted), and total unmitigated arts damage.
    """
    s = SUMMONS[sid]
    interval = s["stats"]["attack_interval"]
    uptime = min(1.0, max(0.0, float(uptime)))
    active_sec = NOMINAL_LIFETIME_SEC * uptime
    actions = int(active_sec // interval)
    if sid == "lebu":
        cycles, rem = divmod(actions, LEBU_CYCLE_ACTIONS)
        hits = cycles * LEBU_CYCLE_HITS + rem  # remainder actions are singles
    else:
        hits = actions
    atk = buffed_attack(sid, stacks)
    return {
        "sid": sid,
        "display_name": s["display_name"],
        "nominal_lifetime_sec": NOMINAL_LIFETIME_SEC,
        "uptime": uptime,
        "active_attack_sec": round(active_sec, 3),
        "attack_actions": actions,
        "hits": hits,
        "buffed_atk": atk,
        "lifetime_damage_raw": round(atk * hits, 2),
        "effective_dps": effective_dps(sid, stacks, uptime),
        "forbidden_heal": s["lifespan"]["forbidden_heal"],
        "drain_pct_per_sec": DRAIN_PCT_PER_SEC,
    }


def board_cap(six_member=False):
    """Max simultaneous Leithanien summons on the field."""
    return BOND_MECHANIC["summon_cap_six_member" if six_member
                         else "summon_cap_base"]


# --- Tanking / damage absorption --------------------------------------------
# A summon leaves the field at the EARLIER of two clocks: the fixed 10 s HP
# decay (forbidden heal, -10% max HP/s) or being killed by incoming damage.
# These units actively path to and block ground enemies (xiaojie blocks 1,
# lebu blocks 2), so their HP/DEF/RES/block are a real temporary-frontline
# contribution, not just their outgoing DPS.

def tank_stats(sid):
    """Frontline-relevant attributes for one summon (facts from the data file)."""
    s = SUMMONS[sid]
    st = s["stats"]
    return {
        "sid": sid,
        "display_name": s["display_name"],
        "max_hp": st["max_hp"],
        "def": st["def"],
        "res": st["res"],
        "block_count": s["block_count"],
        "attack_style": s["attack_style"],
        "forbidden_heal": s["lifespan"]["forbidden_heal"],
        "drain_pct_per_sec": DRAIN_PCT_PER_SEC,
    }


def damage_per_hit(sid, enemy_atk, family):
    """Actual HP lost from one enemy hit, using the kernel mitigation trunk.

    family: 'phys' or 'arts'. Mirrors advisor/battle/damage.mitigate:
      phys -> max(atk - DEF, 5% floor); arts -> max(atk*(1-RES/100), 5% floor).
    True damage would pass through unchanged; callers rarely need it here.
    """
    s = SUMMONS[sid]
    atk = float(enemy_atk)
    floor = atk * MIN_DAMAGE_RATIO
    if family == "phys":
        return round(max(atk - s["stats"]["def"], floor), 3)
    if family == "arts":
        r = min(max(s["stats"]["res"], 0.0), RES_CAP)
        return round(max(atk * (1.0 - r / 100.0), floor), 3)
    # true / unknown: no mitigation
    return round(atk, 3)


def incoming_dps_from(sid, enemy_atk, family, enemy_attack_interval=1.0):
    """Mitigated per-second damage if one enemy of this profile attacks it."""
    interval = max(0.01, float(enemy_attack_interval))
    return round(damage_per_hit(sid, enemy_atk, family) / interval, 3)


def survival_seconds(sid, incoming_dps=0.0):
    """Expected time on field given mitigated incoming DPS.

    Net HP loss per second = decay (10% max HP) + incoming damage, so:
        t = max_hp / (0.10*max_hp + incoming_dps), capped at the 10 s decay.
    With zero incoming damage this returns exactly NOMINAL_LIFETIME_SEC.
    """
    hp = SUMMONS[sid]["stats"]["max_hp"]
    drain_per_sec = DRAIN_PCT_PER_SEC * hp
    net = drain_per_sec + max(0.0, float(incoming_dps))
    if net <= 0:
        return NOMINAL_LIFETIME_SEC
    return round(min(NOMINAL_LIFETIME_SEC, hp / net), 3)


def hits_survived(sid, enemy_atk, family):
    """How many enemy hits kill it IGNORING the decay clock (pure soak count).

    Useful to read DEF/RES quality directly; the real field life also respects
    the 10 s decay (see survival_seconds / tank_profile).
    """
    per = damage_per_hit(sid, enemy_atk, family)
    if per <= 0:
        return None
    import math
    return max(1, math.ceil(SUMMONS[sid]["stats"]["max_hp"] / per))


def tank_profile(sid, enemy_atk_phys=None, enemy_atk_arts=None,
                 enemy_attack_interval=1.0, simultaneous_enemies=1):
    """Decision-ready frontline summary for one summon.

    Pass the wave's representative physical and/or arts enemy ATK (the same
    picture used by effDps). Returns mitigation per hit, hits-to-kill, the
    decay-aware survival window, and how much enemy damage it absorbs over that
    window (the protection it buys the real operators behind it).
    """
    s = SUMMONS[sid]
    hp = s["stats"]["max_hp"]
    out = {"sid": sid, "display_name": s["display_name"],
           "block_count": s["block_count"], "max_hp": hp,
           "def": s["stats"]["def"], "res": s["stats"]["res"],
           "nominal_lifetime_sec": NOMINAL_LIFETIME_SEC, "profiles": {}}
    # Block caps how many ground enemies can hit it at once.
    simultaneous_enemies = max(1, min(int(simultaneous_enemies),
                                      s["block_count"]))
    total_incoming = 0.0
    for label, atk in (("phys", enemy_atk_phys), ("arts", enemy_atk_arts)):
        if atk is None:
            continue
        per = damage_per_hit(sid, atk, label)
        one = incoming_dps_from(sid, atk, label, enemy_attack_interval)
        total_incoming += one * simultaneous_enemies
        out["profiles"][label] = {
            "enemy_atk": atk,
            "damage_per_hit": per,
            "hits_to_kill_ignore_decay": hits_survived(sid, atk, label),
            "incoming_dps_per_enemy": one,
        }
    t = survival_seconds(sid, total_incoming)
    out["simultaneous_enemies_modeled"] = simultaneous_enemies
    out["total_incoming_dps"] = round(total_incoming, 3)
    out["expected_field_time_sec"] = t
    # Damage this summon soaks for the team before it leaves (decay + kills it).
    out["damage_absorbed_for_team"] = round(total_incoming * t, 2)
    return out


def formation_upper_bound(sid, stacks=0, six_member=False, uptime=DEFAULT_UPTIME):
    """Upper-bound combined DPS if every summon slot were this unit.

    This is a capacity ceiling, NOT a prediction: spawns depend on kills and
    xiaojie/lebu mix, which are wave-driven and not published. Kept explicit so
    callers never mistake it for an expected value.
    """
    cap = board_cap(six_member)
    return {
        "sid": sid,
        "slots": cap,
        "per_summon_dps": effective_dps(sid, stacks, uptime),
        "aggregate_dps_ceiling": round(effective_dps(sid, stacks, uptime) * cap, 2),
        "ceiling_only": True,
    }


# --- Engine adapter: summon-line synergy for Leithanien operators ----------
# The summons are a DERIVED combat line of the Leithanien bond, not buyable
# cards, so their engine entry point values the OPERATORS that grow the bond.
# Scoring is driven by the two headcount milestones (3 = engine on, 6 = lebu
# upgrade + cap 20); the summon DPS/tank numbers above are used only as
# explainability anchors. Fully inert outside a Leithanien build context so
# every non-Leithanien engine recommendation is byte-for-byte unchanged.
SUMMON_BOND = "莱塔尼亚"
SYNERGY_BASE = 4.0        # any Leithanien member inside a Leithanien build
ACTIVATION_AWARD = 10.0   # reaching 3 members turns on kill->summon
SIX_MEMBER_AWARD = 12.0   # reaching 6 unlocks lebu upgrade + cap 20 + on-death
_ADAPTER_LOCKED_FACTOR = 0.5


def in_leithanien_context(state, bond_counts):
    """True when the player is committed to (or already running) Leithanien."""
    return (getattr(state, "target_bond", None) == SUMMON_BOND
            or bond_counts.get(SUMMON_BOND, 0) > 0)


def summon_synergy_value(ds, operator, state, bond_counts):
    """Buy-score contribution of one operator via the Leithanien summon line.

    Mirrors econ_bonds.econ_bond_value's contract: returns {score, reasons,
    active}. `active=False` means the term is inert (no points, no reasons),
    which keeps the engine deterministic and the non-Leithanien path untouched.
    `ds` is accepted for signature parity / future enemy-panel wiring; the
    current milestone logic only needs the operator's bonds and the board.
    """
    inert = {"score": 0.0, "reasons": [], "active": False}
    bonds = operator.get("bonds", []) if operator else []
    if SUMMON_BOND not in bonds or not in_leithanien_context(state, bond_counts):
        return inert

    name = operator.get("name", "")
    already_owned = any(getattr(u, "name", None) == name for u in state.board)
    have = bond_counts.get(SUMMON_BOND, 0)
    prospective = have + (0 if already_owned else 1)
    need = BOND_MECHANIC["activation_need"]        # 3
    six = BOND_MECHANIC["six_member_threshold"]    # 6

    score = SYNERGY_BASE
    reasons = []

    # 3-member activation: the kill -> xiaojie summon engine switches on.
    if have < need and prospective >= need:
        score += ACTIVATION_AWARD
        reasons.append("凑齐%d名莱塔尼亚激活召唤：击倒敌人召“小节”(场上限%d)"
                       % (need, board_cap(False)))
    elif prospective < need:
        progress = min(1.0, prospective / need)
        score += ACTIVATION_AWARD * progress * _ADAPTER_LOCKED_FACTOR
        reasons.append("莱塔尼亚%d/%d，差%d人启动召唤体系"
                       % (prospective, need, need - prospective))

    # 6-member milestone: xiaojie can upgrade to the tanky lebu, cap 10 -> 20,
    # and an operator being knocked down also spawns a xiaojie.
    if have < six and prospective >= six:
        score += SIX_MEMBER_AWARD
        reasons.append("达6人里程碑：可升级“乐部”(HP%d/阻挡%d临时前排)，召唤上限提升到%d，干员倒地也召小节"
                       % (SUMMONS["lebu"]["stats"]["max_hp"],
                          SUMMONS["lebu"]["block_count"], board_cap(True)))
    elif need <= prospective < six:
        progress = (prospective - need) / (six - need)
        score += SIX_MEMBER_AWARD * progress * _ADAPTER_LOCKED_FACTOR

    # Short numeric anchor so the suggestion shows what the summon line buys.
    lebu = SUMMONS["lebu"]["stats"]
    reasons.append("召唤物补输出+临时前排(乐部ATK%d/阻挡%d，小节铺量挡1)"
                   % (lebu["atk"], SUMMONS["lebu"]["block_count"]))

    return {"score": round(score, 1), "reasons": reasons, "active": True}
