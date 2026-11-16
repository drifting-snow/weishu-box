# -*- coding: utf-8 -*-
"""Heuristic decision engine.

Deterministic, explainable scoring over a GameState. No LLM here: the model
(optional, later) only narrates these validated candidates.

Priority order (mirrors community-tested auto-chess priorities):
  1. merge progress  -> complete 3-copy elite promotions
  2. bond threshold  -> push owned bonds to their activation count
  3. comp gap        -> fill missing role / raise dispatch level
  4. stat fit        -> generic power, item synergy
"""
from dataclasses import dataclass
from typing import List, Optional

from .model import GameState, ShopCard
from .data import Dataset
from .rules import Rules
from . import economy as econ
from . import item_economy as ie
from . import counters as ctr
from . import econ_bonds as eb
from . import impact as impact_mod
from . import effdps
from . import summon_dps
from . import compass as compass_mod
from . import roadmap as roadmap_mod
from . import team_gaps
from . import clear_margin
from . import shop_odds
from .battle import adapter as battle_adapter


@dataclass
class Action:
    verb: str            # buy | refresh | freeze | upgrade | skip
    target: str          # card name / "dispatch" / "-"
    score: float
    reason: str
    cost: int = 0
    # Step-2 parallel ruler: the unified marginal-impact breakdown, attached
    # for comparison only. Legacy `score` still drives ordering until step 3.
    impact: dict = None


# Per-star rarity bonus used only as an in-tier tie-breaker (3-star = 0).
# Deliberately small: a 5-star white-slate must never outrank a counter card.
STAR_TIER_WEIGHT = 1.0

# Armor-fit (effDps) scoring, active ONLY when an enemy picture is set.
# Full points are awarded to the shop's best armor-fitting damage dealer; the
# cap stays below bond-threshold (60) and merge (100) priorities so armor fit
# refines choices inside a round rather than overriding build direction. Tanks
# and healers have no damage matrix and simply earn no fit points.
EFFDPS_FULL = 18.0

# Refresh EV bands (2026-11-13 scoring direction):
# - Soft ceiling covers bare 1-copy merge (+40) plus weak bond-progress (+12) /
#   tier / star micro — refresh MAY outrank these non-critical merges.
# - Critical floor ~ bond-one-away (+60) and above: refresh stays below.
# 2→3 merge (+100) and merge-ready callout (120) remain untouched / dominant.
REFRESH_SOFT_CEILING = 58.0
REFRESH_CRITICAL_FLOOR = 70.0
# Hunt / spare-gold levers inside ``_score_refresh`` (hillclimb P6 knobs).
REFRESH_HUNT_PER_TIER = 8.0
REFRESH_SPARE_RICH_BONUS = 10.0   # spare gold >= 8
REFRESH_SPARE_OK_BONUS = 5.0      # spare gold >= 4
REFRESH_SPARE_TIGHT_PENALTY = 8.0  # spare gold <= 1



class Advisor:
    def __init__(self, ds: Dataset):
        self.ds = ds
        self.rules = Rules(ds)
        # Lazily-loaded stage-B data for armor-fit scoring; never read while
        # the enemy picture is empty, so a plain recommendation costs no extra IO.
        self._eff_profiles = None
        self._eff_metrics = None
        # Lazily-cached curated lineup library for build-direction inference.
        self._lineups = None

    def _get_lineups(self):
        if self._lineups is None:
            self._lineups = compass_mod.load_lineups()
        return self._lineups

    def _ensure_eff_data(self):
        if self._eff_profiles is None:
            self._eff_profiles = effdps.load_damage_profiles()
            self._eff_metrics = effdps.load_combat_metrics()
        return self._eff_profiles, self._eff_metrics

    def _shop_eff_max(self, st: GameState):
        """Highest armor-fit effDps among the shop's damage dealers this round.

        Returns None when there is no enemy picture or no usable effDps, which
        keeps the armor-fit term fully disabled and engine output unchanged.
        """
        if not st.enemy_types:
            return None
        profiles, metrics = self._ensure_eff_data()
        best = None
        for card in st.shop:
            if card.kind != "operator":
                continue
            eff, _, _ = effdps.effective_dps(
                profiles, metrics, card.name, st.enemy_types)
            if eff is not None and (best is None or eff > best):
                best = eff
        return best

    # -- individual card scoring --
    def _score_operator(self, card: ShopCard, st: GameState, eff_max=None,
                        plan=None, gaps=None, margin_band=None) -> (float, str):
        score = 0.0
        reasons = []
        op = self.ds.operator(card.name)
        bonds = op["bonds"] if op else ([card.bond] if card.bond else [])
        bond_counts = self.rules.bond_counts(st)
        owned_names = {u.name for u in st.board}
        owned_copies = {u.name: u.count for u in st.board}

        # 1. merge progress: 2→3 (三连) stays HIGH as early-core via higher-tier
        #    三选一 / 三合一 — do NOT nerf into the soft band. 1-copy progress is
        #    intentionally softer so refresh/econ EV can outrank non-critical
        #    merges when the shop has no hard hit (prefs 2026-11-13).
        if card.name in owned_copies:
            c = owned_copies[card.name]
            if c == 2:
                score += 100; reasons.append("凑齐3合1升精锐")
            elif c == 1:
                score += 40; reasons.append("已有1张，向三合一推进")
            else:
                score += 15; reasons.append("重复持有")

        # 2. bond threshold contribution
        for b in bonds:
            need = self.ds.bond_need(b)
            have = bond_counts.get(b, 0)
            if not need:
                continue
            if have >= need:
                score += 8; reasons.append(f"{b}已激活，叠加层数")
            elif have == need - 1:
                score += 60; reasons.append(f"{b}差1人激活({have}/{need})")
            else:
                score += 12; reasons.append(f"凑{b}盟约({have}/{need})")

        # target build gets a strong bonus
        if st.target_bond and st.target_bond in bonds:
            score += 30; reasons.append(f"契合目标盟约{st.target_bond}")

        # 2b. lineup compass: reward operators that belong to the inferred build
        # plan so picks converge on one composition instead of scattering one
        # card into every bond. Inert (0/None) when no plan was inferred, which
        # preserves the legacy scoring on directionless/empty boards.
        if op is not None and plan is not None:
            plan_bonus, plan_why = compass_mod.on_plan_bonus(
                plan, card.name, bonds)
            if plan_bonus:
                score += plan_bonus
                reasons.append(plan_why)

        # 3. tier-gate sanity (illegal cards should never be bought)
        if self.rules.violates_tier_gate(card, st.dispatch_level):
            return -999.0, "超过当前调度等级，规则上不应出现"

        # 4. generic power: higher available tier within level is slightly better
        if card.tier:
            score += card.tier
            # 4b. rarity (star) micro-adjustment, ONLY to break ties inside the
            # same shop tier. Star and shop_tier are strongly collinear (tier 6 is
            # all 5-star), so a large independent star bonus would double-count the
            # tier power already added above. Keep it tiny so mechanic/counter score
            # always dominates. Normalized to 3/4/5 -> +0/+1/+2 within a tier.
            if op and op.get("star"):
                star_bonus = (int(op["star"]) - 3) * STAR_TIER_WEIGHT
                score += star_bonus
                if star_bonus > 0:
                    reasons.append("%s星底子(同本内微调)" % op["star"])

        # 5. investment value: economy-type 整备能力 (refresh/gold/free recruit/
        #    special price/item generation) counts as a buy reason on its own.
        if op:
            inv_tags = econ.investment_tags(op)
            if inv_tags:
                inv = sum(t["weight"] for t in inv_tags)
                score += inv
                labels = sorted({t["tag"] for t in inv_tags})
                reasons.append("投资型(" + "、".join(labels) + ")")
            # cheap cards (especially 1-gold specials) get an ROI nudge: value
            # delivered per gold spent is higher.
            actual_cost = self.rules.card_buy_price(card)
            if actual_cost <= 1:
                score += 12
                reasons.append("仅%d金，高性价比" % actual_cost)
            elif actual_cost == 2:
                score += 5
                reasons.append("低价易入手")

        # 5b. economy-bond engine (远见/奇迹/投资人). These activate from the
        #    reserve zone too, so they are valued as off-field economy, scaled by
        #    the remaining payback window. Distinct from per-card investment_tags.
        if op:
            ev = eb.econ_bond_value(self.ds, op, st, bond_counts)
            score += ev["score"]
            for a in ev["active"]:
                reasons.append("经济羁绊·%s已激活(%s,时机%.0f%%,可养性%.2f)" %
                               (a["bond"], a["label"], ev["timing_factor"] * 100,
                                a.get("feasibility", 1.0)))
            for l in ev["locked"]:
                if l.get("no_window"):
                    reasons.append("%s经济引擎已无回本回合，不建议为引擎拿" % l["bond"])
                else:
                    reasons.append("%s经济引擎差%d人激活(%s)" %
                                   (l["bond"], l["missing"], l["label"]))

        # 5c. Leithanien summon-line synergy. Inert outside a Leithanien build
        #    (no target bond and zero Leithanien on board), so every other
        #    recommendation is unchanged. Values the operators that reach the
        #    3-member summon activation and 6-member lebu/cap-20 milestones.
        if op:
            sv = summon_dps.summon_synergy_value(self.ds, op, st, bond_counts)
            if sv["active"]:
                score += sv["score"]
                reasons.extend(sv["reasons"])

        # 6. enemy-type weakness matching (only when a RunProfile enemy picture
        #    is set). Native/talent/skill counters weigh most; bond-milestone
        #    counters give partial credit and surface "N more to unlock" so the
        #    advisor values building toward a needed answer (future score).
        if st.enemy_types:
            cs = ctr.counter_score(self.ds, op or {"name": card.name,
                                   "bonds": ([card.bond] if card.bond else [])},
                                   st.enemy_types, bond_counts)
            if not cs.get("neutral"):
                score += cs["score"] * 0.6
                for h in cs["hits"]:
                    src = "盟约" if h["source"] == "bond" else "本体"
                    extra = ("·" + h["bond"]) if h.get("bond") else ""
                    reasons.append("克制[%s]%s%s" % (h["tag"], src, extra))
                for l in cs["locked"][:2]:
                    reasons.append("%s差%d人解锁%s反制" % (l["bond"], l["missing"], l["tag"]))
                for a in cs["anti_synergy"]:
                    reasons.append("⚠" + a)

        # 7. armor fit (effDps): only with an enemy picture. Raw panel DPS is
        #    mitigated by the wave's DEF/RES band via the stage-B matrix, then
        #    normalized to the best dealer in THIS shop so physical/arts dealers
        #    re-rank as the enemy armor profile changes. No data -> no points.
        if st.enemy_types and eff_max:
            profiles, metrics = self._ensure_eff_data()
            eff, factor, _raw = effdps.effective_dps(
                profiles, metrics, card.name, st.enemy_types)
            if eff is not None and factor is not None:
                fit_pts = round(EFFDPS_FULL * min(1.0, eff / eff_max), 1)
                score += fit_pts
                reasons.append("护甲契合effDps%.0f(抗性折减%.0f%%)" %
                               (eff, factor * 100))

        # 8. gate-0 team capability gap: a deterministic board-level blind spot
        #    (no anti-air on a flying wave, no arts/pierce on refraction, no
        #    silence for a named special ability). Only a card that actually
        #    closes a currently-open gap earns this additive bonus; inert (0) the
        #    moment the board covers the need or no enemy picture is set.
        if gaps:
            gap_pts, gap_why = team_gaps.operator_gap_bonus(
                self.ds, card.name, gaps)
            if gap_pts:
                score += gap_pts
                reasons.extend(gap_why)

        # 9. stage-1 clear-margin: on a tight/critical wave (real spawn-window
        #    margin < 1), nudge damage dealers over non-damage cards. Inert on
        #    comfortable/adequate waves or for healers (no measurable effDps).
        if margin_band:
            profiles, metrics = self._ensure_eff_data()
            m_pts, m_why = clear_margin.operator_margin_bonus(
                profiles, metrics, card.name, st.enemy_types, margin_band)
            if m_pts:
                score += m_pts
                reasons.extend(m_why)

        if not reasons:
            reasons.append("通用战力补充")
        return score, "；".join(reasons)

    def _score_item(self, card: ShopCard, st: GameState, gaps=None) -> (float, str):
        it = self.ds.item(card.name)
        score = 5.0
        reasons = ["装备补强"]
        if it:
            # 1) round-aware valuation for consumable economy items. This owns
            #    delayed-payoff timing (immediate / next_round / recurring) and
            #    replaces the old flat 'economy item +15' heuristic.
            ev = ie.value_item(it, st.round)
            if ev is not None:
                score += ev["score"]
                reasons.append(ev["rationale"])
                if ev["time_sensitive"]:
                    reasons.append("延时生效·回本窗口%d回合" % ev["window"])
            if it.get("bond"):
                # synergy with an active/target bond
                if it["bond"] == st.target_bond:
                    score += 25; reasons.append(f"目标盟约{it['bond']}专属")
                if self.rules.bond_counts(st).get(it["bond"], 0) > 0:
                    score += 12; reasons.append(f"适配{it['bond']}体系")
            # non-consumable generic economy text (e.g. persistent gold tools)
            if ev is None:
                txt = (it.get("base", "") or "") + (it.get("advanced", "") or "")
                if "资金" in txt or "刷新" in txt:
                    score += 15; reasons.append("经济装，加速运营")
        # cheap items when gold is tight still acceptable. Coerce price: OCR /
        # items.json may carry it as a string, which would crash the int compare.
        price = int(card.price) if str(card.price).isdigit() else 0
        if card.price is not None and price <= st.gold:
            score += 2
        # gate-0 gap closure via equipment (currently only silence -> 奥术法阵).
        if gaps:
            gap_pts, gap_why = team_gaps.item_gap_bonus(self.ds, card.name, gaps)
            if gap_pts:
                score += gap_pts
                reasons.extend(gap_why)
        return score, "；".join(reasons)

    # -- full recommendation --
    def recommend(self, st: GameState, rounds_at_level: int = 0) -> dict:
        actions: List[Action] = []
        buy_cost = self.rules.buy_operator_cost()
        # Armor-fit reference for this round's shop (None without an enemy
        # picture, in which case the term is inert and all legacy tests hold).
        eff_max = self._shop_eff_max(st)
        # Gate-0 team capability gaps for this wave (deterministic booleans).
        # Empty when there is no enemy picture or no blind spot, which makes the
        # additive gap bonus inert and keeps legacy scoring byte-identical.
        gaps = team_gaps.detect_team_gaps(self.ds, st)
        # Stage-1 continuous clear margin (paper DPS × clear window). None when
        # the level/board/picture is incomplete -> every margin term is inert.
        eff_profiles, eff_metrics = self._ensure_eff_data()
        margin_rec = clear_margin.clear_margin(st, eff_profiles, eff_metrics, ds=self.ds)
        # Stage-2 discrete battle simulation (蓄水池 / blocking / leak). Its
        # result folds into margin via apply_reservoir_pressure so buy/upgrade
        # steering sees frontline overflow — not paper DPS alone. Defensively
        # guarded so a simulation issue falls back to paper margin.
        try:
            battle_sim = battle_adapter.simulate(
                st, self.ds, eff_profiles, eff_metrics)
        except Exception as exc:  # pragma: no cover - safety net only
            battle_sim = {"error": "simulation skipped: %s" % type(exc).__name__}
        margin_rec = clear_margin.apply_reservoir_pressure(margin_rec, battle_sim)
        margin_band = margin_rec["band"] if margin_rec else None
        # Infer the curated lineup this board is building, so shop picks steer
        # toward one coherent composition. None on a directionless board -> the
        # compass contributes nothing and legacy scoring is unchanged.
        plan = compass_mod.infer_lineup(self.ds, st, self._get_lineups())

        banned_ops = set(st.banned_operators or [])
        for card in st.shop:
            # Draft-banned operator: never surface a buy recommendation.
            if card.kind == "operator" and card.name in banned_ops:
                continue
            if card.kind == "operator":
                s, why = self._score_operator(card, st, eff_max, plan, gaps,
                                              margin_band)
                cost = self.rules.card_buy_price(card)
                # parallel ruler score (not used for ordering yet)
                imp = impact_mod.operator_impact(self.ds, self.rules, card, st)
            else:
                s, why = self._score_item(card, st, gaps)
                # coerce string price (items.json / OCR) to int
                cost = int(card.price) if str(card.price).isdigit() else 0
                imp = impact_mod.item_impact(self.ds, self.rules, card, st)
            affordable = st.gold >= cost
            actions.append(Action(
                verb="buy", target=card.name, score=round(s, 1),
                reason=why + ("" if affordable else "（资金不足）"),
                cost=cost, impact=imp.as_dict(),
            ))

        # upgrade (升本) recommendation
        up_price = self.rules.current_upgrade_price(st, rounds_at_level)
        if up_price is not None:
            urgency = self._upgrade_urgency(st, up_price)
            if margin_band:
                urgency = max(0.0,
                    urgency + clear_margin.upgrade_margin_adjustment(margin_band))
            actions.append(Action(
                verb="upgrade", target="调度中心",
                score=round(urgency, 1),
                reason=f"升本价当前{up_price}（每停留1回合-1，升后重置）",
                cost=up_price,
            ))
        else:
            actions.append(Action("upgrade", "调度中心", 0, "已满级", 0))

        # refresh EV: ASSUMED tier probs × slot count × spare-gold timing.
        # Can outrank soft / non-critical 1-copy buys; stays below 2→3 / bond hits.
        best_buy = max((a for a in actions if a.verb == "buy"),
                       key=lambda a: a.score, default=None)
        best_buy_score = best_buy.score if best_buy else None
        if st.gold >= self.rules.refresh_cost():
            refresh_score, refresh_why = self._score_refresh(st, best_buy_score)
            actions.append(Action("refresh", "调度中心", round(refresh_score, 1),
                                  refresh_why, self.rules.refresh_cost()))

        # freeze reminder when a strong card cannot be afforded now
        if best_buy and best_buy.score >= 60 and best_buy.cost > st.gold:
            actions.append(Action("freeze", best_buy.target, 70.0,
                                  "高分牌买不起，冻结保留下回合", 0))

        # merge-ready callout (no cost)
        for name in self.rules.merge_ready(st):
            actions.append(Action("merge", name, 120.0, "三张同名，立即合成精锐", 0))

        actions.sort(key=lambda a: a.score, reverse=True)

        return {
            "state": {
                "round": st.round, "gold": st.gold,
                "dispatch_level": st.dispatch_level,
                "difficulty": st.difficulty, "target_bond": st.target_bond,
                "enemy_types": list(st.enemy_types or []),
                "enemy_names": list(st.enemy_names or []),
            },
            "team_gaps": gaps,
            "clear_margin": margin_rec,
            "battle_sim": battle_sim,
            "lineup": self._lineup_summary(plan),
            "roadmap": roadmap_mod.build_roadmap(
                self.ds, st, plan, self._get_lineups()),
            "pivot": self._pivot_dict(
                roadmap_mod.evaluate_pivot(
                    self.ds, st, plan, self._get_lineups())),
            "bond_status": self.rules.bond_status(st),
            "recommendations": [a.__dict__ for a in actions],
            "top_pick": actions[0].__dict__ if actions else None,
            "notes": [
                "抽棋各等阶具体百分比官方未公布，建议基于等级门控与实测记录，勿采信固定概率。",
                "未花完资金下回合清零；要保留货物请用冻结。",
            ],
        }

    def _pivot_dict(self, pivot) -> Optional[dict]:
        return pivot.as_dict() if pivot is not None else None

    def _lineup_summary(self, plan) -> Optional[dict]:
        """Serializable description of the inferred build direction (or None)."""
        if plan is None:
            return None
        return {
            "id": plan.lineup_id, "name": plan.name,
            "archetype": plan.archetype, "confidence": plan.confidence,
            "source": plan.source, "core_bonds": plan.core_bonds,
            "named_overlap": plan.named_overlap,
            "core_covered": plan.core_covered,
            "counters": plan.counters, "weak": plan.weak,
        }

    def _upgrade_urgency(self, st: GameState, price: int) -> float:
        # higher when low level relative to round and gold is available
        score = 0.0
        if st.dispatch_level <= 2 and st.round >= 3:
            score += 35
        if st.dispatch_level == 3 and st.round >= 6:
            score += 25
        if st.dispatch_level >= 5:
            score += 10
        # discount depth makes waiting cheaper; mild nudge to buy when near 0
        if price == 0:
            score += 30
        if price > st.gold:
            score -= 40
        return max(0.0, score)

    def _score_refresh(self, st: GameState, best_buy_score: Optional[float]):
        """Expected value of spending 1 gold to re-roll the shop.

        Uses ASSUMED ``shop_odds.tier_probs`` (fan priors; not official) plus
        slot count and spare-gold timing. Designed so:
          * soft / bare 1-copy buys (≤ REFRESH_SOFT_CEILING) can lose to refresh
          * bond-one-away / 2→3 (≥ REFRESH_CRITICAL_FLOOR) keep beating refresh
        """
        cost = self.rules.refresh_cost()
        difficulty = st.difficulty or "standard"
        try:
            probs = shop_odds.tier_probs(st.dispatch_level)
        except (KeyError, ValueError, OSError, TypeError):
            probs = {"1": 1.0}
        n_slots = self.ds.slots(st.dispatch_level, difficulty)
        try:
            n_slots = int(n_slots) if n_slots is not None else 3
        except (TypeError, ValueError):
            n_slots = 3

        # Expected unlocked tier quality (1..6); higher levels hunt better cards.
        ev_tier = sum(int(t) * float(p) for t, p in probs.items())
        hunt = ev_tier * float(REFRESH_HUNT_PER_TIER) * (0.55 + 0.12 * n_slots)

        if best_buy_score is None or best_buy_score < 20:
            base = 32.0
        elif best_buy_score <= REFRESH_SOFT_CEILING:
            # Contests bare 1-copy merge (~40+tier) without touching 2→3.
            base = 30.0
        elif best_buy_score < REFRESH_CRITICAL_FLOOR:
            base = 16.0
        else:
            base = 6.0

        score = base + hunt
        spare = st.gold - cost
        if spare >= 8:
            score += float(REFRESH_SPARE_RICH_BONUS)
            gold_note = "余钱滚店"
        elif spare >= 4:
            score += float(REFRESH_SPARE_OK_BONUS)
            gold_note = "资金尚可刷新"
        elif spare <= 1:
            score -= float(REFRESH_SPARE_TIGHT_PENALTY)
            gold_note = "资金紧·慎刷/留金"
        else:
            gold_note = "刷新找高价值牌"

        # Never let refresh outrank hard merge / bond-threshold bands.
        score = max(0.0, min(score, REFRESH_CRITICAL_FLOOR - 1.0))
        why = "刷新EV(等阶期望%.1f·%d槽)·%s" % (ev_tier, n_slots, gold_note)
        return score, why
