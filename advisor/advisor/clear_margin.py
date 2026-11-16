# -*- coding: utf-8 -*-
"""Stage-1 continuous clear-margin: can the board kill the wave in time?

Gate-0 (team_gaps) answers a boolean question ("does the board have ANY answer
for anti-air / refraction / silence"). This module answers the continuous one:
even with an answer, is the team's effective damage enough to clear the wave's
total HP before the last enemy reaches the exit?

Everything is driven by real unpacked data precomputed in data/act3_waves.json
(tools/build_act3_waves.py): per-level spawn count, level-0 HP, spawn timing and
a data-derived clear window. Enemy HP is then scaled by the act3 regulation HP
curve (advisor/regulation_hp); the team's damage is the sum of each board
operator's mitigated effective DPS (advisor/effdps, same worst-case resistance
rule as the armor-fit term), so no new damage model is introduced.

Key quantities:
    enemy_hp = level.total_hp_level0 * regulation_hp_multiplier(L)
    team_dps = sum over board of effdps(name, enemy_types)      # None -> skip
    kill_time = enemy_hp / team_dps
    margin_paper = team_dps * clear_window / enemy_hp           # >1 clears in time
Reservoir wire (apply_reservoir_pressure): when battle_sim is present, the
effective margin is margin_paper * (killed/total), then clamped with the same
CRITICAL_AT / COMFORTABLE_AT band thresholds so leaks / reservoir overflow
cannot report a comfortable frontline. Missing sim -> paper-only fallback.
A margin of 1.0 is the break-even line; bands turn the continuous value into a
coarse economy-vs-damage steering signal. The module is inert (returns None)
whenever the level cannot be resolved, the board has no measurable DPS, or no
enemy picture is set, so legacy scoring is untouched on any incomplete input.
"""
import json
import os
from typing import Optional

from . import effdps
from . import buffs
from . import regulation_hp as rhp

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data")
WAVES_PATH = os.path.join(DATA_DIR, "act3_waves.json")

# Difficulty (GameState.difficulty) -> multiplayer battleDataDict mode used when
# no explicit regulation level (mode_single_1..20) is supplied.
DIFFICULTY_MODE = {
    "standard": "mode_multi_normal",
    "hard_abyss": "mode_multi_abyss",
    "speed": "mode_multi_funny",
}

# Margin bands (break-even = 1.0). Tunable constants, kept explicit.
BAND_CRITICAL = "critical"      # margin < CRITICAL_AT: very likely to leak
BAND_TIGHT = "tight"            # CRITICAL_AT <= margin < 1.0
BAND_ADEQUATE = "adequate"      # 1.0 <= margin < COMFORTABLE_AT
BAND_COMFORTABLE = "comfortable"
CRITICAL_AT = 0.6
COMFORTABLE_AT = 1.5

# Additive steering terms (kept below bond/merge priorities, same discipline as
# gate-0). Only fire on the two stress bands for damage cards; economy/upgrade
# is nudged only when the board is clearly comfortable, and held back when the
# wave is critical so the advisor never says "level up" while about to leak.
DAMAGE_BONUS = {BAND_CRITICAL: 12.0, BAND_TIGHT: 6.0}
_DAMAGE_REASON = {BAND_CRITICAL: "清场吃紧·优先补输出",
                  BAND_TIGHT: "清场偏紧·优先输出"}
UPGRADE_ADJUST = {BAND_COMFORTABLE: 10.0, BAND_CRITICAL: -15.0}

_cache = None


def load_waves(path: str = WAVES_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _waves(doc: Optional[dict]) -> dict:
    global _cache
    if doc is None:
        if _cache is None:
            _cache = load_waves()
        doc = _cache
    return doc


def resolve_mode(st) -> Optional[str]:
    """Pick a battleDataDict mode key from the game state.

    Explicit regulation level (1..20, chosen at run start) wins and maps to
    mode_single_<L>; otherwise fall back to the difficulty-based multiplayer
    mode. Returns None when nothing usable is set.
    """
    level = getattr(st, "regulation_level", None)
    if isinstance(level, int) and rhp.is_supported_level(level):
        return "mode_single_%d" % level
    return DIFFICULTY_MODE.get(getattr(st, "difficulty", None))


def resolve_level_stem(doc: dict, mode: str, round_no: int) -> Optional[str]:
    """Map (mode, round) to a concrete level stem via battleDataDict.

    A round can list several bosses/prepare entries; prefer the first
    non-prepare level. Returns None if the mode/round is absent.
    """
    rounds = doc.get("round_to_level", {}).get(mode)
    if not rounds:
        return None
    entries = rounds.get(str(round_no))
    if not entries:
        return None
    non_prep = [e for e in entries if not e.get("is_prepare")]
    chosen = (non_prep or entries)[0]
    return chosen["level"]


def classify_margin(margin: float) -> str:
    if margin < CRITICAL_AT:
        return BAND_CRITICAL
    if margin < 1.0:
        return BAND_TIGHT
    if margin < COMFORTABLE_AT:
        return BAND_ADEQUATE
    return BAND_COMFORTABLE


def team_effective_dps(ds, st, profiles, metrics) -> (float, int, int, list):
    """Sum mitigated effDps across board operators, including real buffs.

    Each board operator's armor-fit effDps (initial panel) is scaled by:
      * elite panel ratio (elite.base_dps / initial.base_dps) when promoted
      * advisor/buffs damage multiplier (activated bond panel formulas + per-
        stack bond rules + equipped items), neutral 1.0 when no buff applies.
    Physical mitigation is kept at the base panel, so the second-order factor
    gain from higher ATK is ignored -- a deliberately conservative estimate.
    Operators with no measurable effDps (healers / no damage matrix / unknown
    names) are skipped, not faked. Returns (dps, counted, skipped, detail).
    """
    total = 0.0
    counted = skipped = 0
    detail = []
    for unit in st.board:
        eff, _factor, raw = effdps.effective_dps(
            profiles, metrics, unit.name, st.enemy_types)
        if eff is None:
            skipped += 1
            continue
        scale = 1.0
        mult_info = buffs.operator_damage_multiplier(ds, st, unit.name)
        scale *= mult_info["dps_mult"]
        # elite promotion panel ratio (same operator, E2/L50 vs E1/L55 DPS)
        mrec = metrics.get(unit.name)
        if getattr(unit, "elite", False) and mrec:
            elite_dps = (mrec.get("elite") or {}).get("base_dps")
            init_dps = (mrec.get("initial") or {}).get("base_dps")
            if isinstance(elite_dps, (int, float)) and init_dps:
                scale *= elite_dps / init_dps
        scaled = eff * scale
        total += scaled
        counted += 1
        detail.append({"name": unit.name, "base_eff_dps": eff,
                       "scale": round(scale, 4), "scaled_eff_dps": round(scaled, 2),
                       "buff_notes": mult_info["notes"],
                       "activated_bonds": mult_info["activated_bonds"]})
    return round(total, 2), counted, skipped, detail


def clear_margin(st, profiles=None, metrics=None, doc: Optional[dict] = None, ds=None):
    """Compute the wave clear-margin record, or None when not determinable."""
    if not st.enemy_types and not st.enemy_names:
        return None
    if not st.board:
        return None

    if ds is None:
        from .data import Dataset
        ds = Dataset()
    doc = _waves(doc)
    mode = resolve_mode(st)
    if mode is None:
        return None
    stem = resolve_level_stem(doc, mode, st.round)
    if stem is None:
        return None
    level = doc.get("level_stems", {}).get(stem)
    if not level or level.get("clear_window_t") is None:
        return None

    if profiles is None or metrics is None:
        profiles = effdps.load_damage_profiles()
        metrics = effdps.load_combat_metrics()
    team_dps, counted, skipped, dps_detail = team_effective_dps(
        ds, st, profiles, metrics)
    if team_dps <= 0 or counted == 0:
        return None

    reg_level = getattr(st, "regulation_level", None)
    hp_mult = rhp.regulation_hp_multiplier(reg_level) if isinstance(
        reg_level, int) else 1.0
    enemy_hp = level["total_hp_level0"] * hp_mult
    window = level["clear_window_t"]
    kill_time = enemy_hp / team_dps
    margin = team_dps * window / enemy_hp
    band = classify_margin(margin)

    return {
        "mode": mode,
        "round": st.round,
        "level_stem": stem,
        "enemy_hp_base": level["total_hp_level0"],
        "hp_multiplier": round(hp_mult, 4),
        "enemy_hp_total": round(enemy_hp, 1),
        "team_eff_dps": team_dps,
        "board_dps_counted": counted,
        "board_dps_skipped": skipped,
        "board_dps_detail": dps_detail,
        "clear_window_t": window,
        "kill_time_t": round(kill_time, 2),
        "margin": round(margin, 3),
        "margin_paper": round(margin, 3),
        "band": band,
        "band_paper": band,
        "reservoir": {
            "applied": False,
            "reason": "pending",
            "notes": [],
        },
        "approximations": list(doc.get("_meta", {}).get("approximations", [])),
    }


def _max_overflow_seconds(pressure) -> float:
    """Largest TileReservoir.overflow_time from battle.result pressure snapshot."""
    if not isinstance(pressure, dict) or not pressure:
        return 0.0
    best = 0.0
    for tile in pressure.values():
        if not isinstance(tile, dict):
            continue
        try:
            best = max(best, float(tile.get("overflow_seconds") or 0.0))
        except (TypeError, ValueError):
            continue
    return best


def apply_reservoir_pressure(margin_rec, battle_sim):
    """Fold 蓄水池 discrete outcome into a paper clear_margin record.

    Effective margin = margin_paper * (killed / total). Band clamps reuse the
    existing CRITICAL_AT / COMFORTABLE_AT thresholds (no new game constants):
      * any leak        -> cannot stay in comfortable
      * clear_frac < CRITICAL_AT -> force critical band
      * overflow_seconds > 0 with no leak -> cannot stay comfortable
    Missing / errored / empty battle_sim leaves paper margin unchanged.
    Returns a new dict (or None if margin_rec is None).
    """
    if margin_rec is None:
        return None
    out = dict(margin_rec)
    paper = float(out.get("margin_paper", out.get("margin") or 0.0))
    out["margin_paper"] = round(paper, 3)
    out.setdefault("band_paper", out.get("band"))

    notes = []
    absent = {
        "applied": False,
        "clear_frac": None,
        "killed": None,
        "leaked": None,
        "total": None,
        "max_overflow_s": None,
        "notes": notes,
    }

    if not isinstance(battle_sim, dict):
        notes.append("无 battle_sim·回退纸面裕度")
        absent["reason"] = "absent"
        out["reservoir"] = absent
        return out
    if battle_sim.get("error"):
        notes.append("仿真错误·回退纸面裕度")
        absent["reason"] = "error"
        absent["error"] = battle_sim.get("error")
        out["reservoir"] = absent
        return out

    result = battle_sim.get("result")
    if not isinstance(result, dict):
        notes.append("无仿真 result·回退纸面裕度")
        absent["reason"] = "empty"
        out["reservoir"] = absent
        return out

    try:
        total = int(result.get("total") or 0)
        killed = int(result.get("killed") or 0)
        leaked = int(result.get("leaked") or 0)
    except (TypeError, ValueError):
        notes.append("仿真计数不可解析·回退纸面裕度")
        absent["reason"] = "empty"
        out["reservoir"] = absent
        return out

    if total <= 0:
        notes.append("仿真 total=0·回退纸面裕度")
        absent["reason"] = "empty"
        out["reservoir"] = absent
        return out

    # Resolve bookkeeping drift (killed+leaked may be < total on early exit).
    resolved = max(killed + leaked, total)
    clear_frac = max(0.0, min(1.0, killed / float(resolved)))
    max_overflow = _max_overflow_seconds(result.get("pressure"))
    margin_eff = paper * clear_frac
    notes.append("蓄水池·清场率%.0f%%×纸面裕度" % (clear_frac * 100.0))

    # Use 1e-3 headroom so round(..., 3) cannot land exactly on a band edge.
    if leaked > 0:
        if margin_eff >= COMFORTABLE_AT:
            margin_eff = COMFORTABLE_AT - 0.001
        notes.append("有漏怪·禁止舒适带")
    if clear_frac < CRITICAL_AT:
        if margin_eff >= CRITICAL_AT:
            margin_eff = CRITICAL_AT - 0.001
        notes.append("清场率<%.0f%%·压入critical" % (CRITICAL_AT * 100.0))
    if max_overflow > 0 and leaked == 0:
        if margin_eff >= COMFORTABLE_AT:
            margin_eff = COMFORTABLE_AT - 0.001
        notes.append("阵线溢出%.1fs·禁止舒适带" % max_overflow)

    band = classify_margin(margin_eff)
    out["margin"] = round(margin_eff, 3)
    out["band"] = band
    out["kill_time_t"] = (
        round(out["enemy_hp_total"] / out["team_eff_dps"], 2)
        if out.get("team_eff_dps") else out.get("kill_time_t")
    )
    out["reservoir"] = {
        "applied": True,
        "reason": "ok",
        "clear_frac": round(clear_frac, 4),
        "killed": killed,
        "leaked": leaked,
        "total": total,
        "max_overflow_s": round(max_overflow, 3),
        "sim_reason": result.get("reason"),
        "notes": notes,
    }
    return out


def operator_margin_bonus(profiles, metrics, name, enemy_types, band):
    """Additive points for a shop operator card from the clear-margin band.

    Damage dealers (measurable armor-fit effDps) get a bonus only on a stress
    band; healers / non-damage cards and comfortable/adequate waves get nothing.
    Returns (points, reasons); inert (0.0, []) whenever it does not apply.
    """
    if band not in DAMAGE_BONUS:
        return 0.0, []
    eff, _f, _r = effdps.effective_dps(profiles, metrics, name, enemy_types)
    if eff is None:
        return 0.0, []
    return DAMAGE_BONUS[band], [_DAMAGE_REASON[band]]


def upgrade_margin_adjustment(band):
    """Signed adjustment to the dispatch-upgrade action from the margin band."""
    return UPGRADE_ADJUST.get(band, 0.0)
