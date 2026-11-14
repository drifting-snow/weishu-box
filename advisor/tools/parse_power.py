# -*- coding: utf-8 -*-
"""Operator combat-power extraction, split into precise base stats and
relative buff tiers (independent module; not wired into the impact ruler yet).

Two deliberately separate dimensions, because a high white-value operator and
a buff-amplifying operator are different things and faking one combined DPS
would need SP cycle/uptime data we do not have:

  base (precise, from PRTS {{属性}} infobox, elite-2 max level):
      atk / atk_with_trust / attack interval / base_dps / hp / def / res /
      block / trust attack bonus / module attack bonus. In 卫戍协议 every
      operator (including 3-star) carries a valid elite-2 stat block in the
      source data; an elite-1 fallback is kept only defensively (never hit).
  buff_self (relative S/A/B/C tier, from skill effect text):
      the operator's OWN skill burst amplifier — largest attack multiplier
      (normalizing "+80%" -> 1.8 and "提高至250%" -> 2.5), aspd gain, multi-
      target / extra-hit signals. Ranked across the whole library by percentile.
  buff_external (relative S/A/B/C tier):
      how well the operator carries EXTERNAL % attack buffs (team/equipment).
      An external atk% scales the white value and benefits on every hit, so the
      carrier capacity is the white-value DPS = (atk+trust)/interval, ranked by
      percentile; attack interval (frequency) is kept for explanation.

Anything the regex cannot see (liberation forms, summons, special mechanics —
e.g. 玛恩纳 / 浊心斯卡蒂) is flagged needs_review with the reason, never guessed.

Stdlib only, deterministic. Output: data/operator_power.json
Run   : python tools/parse_power.py
"""
import json
import os
import re
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRTS_DIR = os.path.join(ROOT, "data", "source", "prts")
PROFILES = os.path.join(ROOT, "data", "operator_profiles.json")
OPERATORS = os.path.join(ROOT, "data", "operators.json")
MODE_LEVELS = os.path.join(ROOT, "data", "mode_levels.json")
OUT = os.path.join(ROOT, "data", "operator_power.json")

# Percentile cutoffs (fraction of the library at or below which a value sits).
# >= S_CUT -> S, >= A_CUT -> A, >= B_CUT -> B, else C. Centralized for tuning.
S_CUT, A_CUT, B_CUT = 0.85, 0.65, 0.30

# ---- PRTS {{属性}} field patterns ----
_RE_ATK_E2 = re.compile(r"精英2_满级_攻击=(\d+)")
_RE_HP_E2 = re.compile(r"精英2_满级_生命上限=(\d+)")
_RE_DEF_E2 = re.compile(r"精英2_满级_防御=(\d+)")
_RE_RES_E2 = re.compile(r"精英2_满级_法术抗性=(\d+)")
_RE_ATK_E1 = re.compile(r"精英1_满级_攻击=(\d+)")
_RE_HP_E1 = re.compile(r"精英1_满级_生命上限=(\d+)")
_RE_DEF_E1 = re.compile(r"精英1_满级_防御=(\d+)")
_RE_RES_E1 = re.compile(r"精英1_满级_法术抗性=(\d+)")
_RE_INTERVAL = re.compile(r"攻击速度=([\d.]+)\s*s")
_RE_BLOCK = re.compile(r"阻挡数=(\d+)")
_RE_TRUST_ATK = re.compile(r"信赖加成_攻击=(\d+)")
_RE_MODULE = re.compile(r"模组\d+数据=([^\n]+)")
# skill amplifier signals
_RE_ATK_PLUS = re.compile(r"攻击力\s*\+\s*(\d+)\s*%")
_RE_ATK_TO = re.compile(r"攻击力(?:提升|提高)?至\s*(\d+)\s*%")
_RE_DMG_PCT = re.compile(r"相当于攻击力\s*(\d+)\s*%.*?伤害")
# word-order variants the canonical pattern misses:
_RE_DMG_PCT_V2 = re.compile(r"攻击力\s*(\d+)\s*%[^。\n]{0,8}伤害")   # 攻击力150%的物理伤害
_RE_DMG_PCT_V3 = re.compile(r"相当于\s*(\d+)\s*%\s*攻击力")        # 相当于200%攻击力
_RE_ASPD = re.compile(r"攻击速度\s*\+\s*(\d+)")
_RE_TARGETS = re.compile(r"攻击\s*(\d+)\s*个(?:目标|敌人)")
_RE_TARGETS_V2 = re.compile(r"对\s*(\d+)\s*个目标")
_RE_EXTRA_HIT = re.compile(r"额外攻击\s*(\d+)\s*次")
_RE_EXTRA_TARGET = re.compile(r"额外攻击\s*一?个?目标")
_RE_COMBO = re.compile(r"二连击|连击")

# ---- level-7 (Rank 7) skill rows inside the ==技能== section ----
# The mode caps skills at Rank 7 with NO mastery (no M1/M2/M3). The wiki also
# carries 技能专精1/2/3 rows which the mode never enables; we deliberately read
# only 技能7 (the non-mastery ceiling), never the 专精 rows.
_RE_SKILL_SECTION = re.compile(r"==技能==(.*?)(?:\n==[^=])", re.S)
_RE_SKILL_NAME = re.compile(r"\|技能名=(.+)\n")
_RE_SKILL_TYPE = re.compile(r"\|技能类型1=([^\n]+)")
_RE_S7_DESC = re.compile(r"\|技能7描述=(.+)")
_RE_S7_INIT = re.compile(r"\|技能7初始=([^\n]*)")
_RE_S7_COST = re.compile(r"\|技能7消耗=([^\n]*)")
_RE_S7_DUR = re.compile(r"\|技能7持续=([^\n]*)")
# normalized-text numeric signals
_RE_NM_ATK_PLUS = re.compile(r"攻击力\+?(\d+)%")
_RE_NM_ATK_TO = re.compile(r"攻击力提升至(\d+)%")
_RE_NM_DMG_MULT = re.compile(r"(?:相当于)?(\d+)%攻击力|攻击力(\d+)%的?物理伤害")
_RE_NM_INTERVAL = re.compile(r"攻击间隔[^\d]*([+\-]?[\d.]+)")
_RE_NM_TARGET_PLUS = re.compile(r"攻击目标数\+?(\d+)")
_RE_NM_TARGET_EXACT = re.compile(r"对(\d+)个目标")
_RE_NM_EXTRA_TARGET = re.compile(r"额外攻击(\d+)个目标")
_RE_NM_DOUBLE = re.compile(r"二连击|连击")
_RE_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")


def _strip_templates(text):
    """Recursively unwrap PRTS templates, keeping each template's LAST arg
    (the display value). Innermost {{color|#hex|200%}} resolves first, then
    wrappers like {{*|50%|+50%}} keep their now-resolved last arg."""
    s = text.replace("<br/>", " ").replace("<br>", " ")
    # resolve innermost templates until none remain
    for _ in range(20):
        m = _RE_TEMPLATE.search(s)
        if not m:
            break
        inner = m.group(0)[2:-2]
        args = inner.split("|")
        # last arg is the human-facing value; drop empty/template-name-only cases
        display = args[-1] if len(args) > 1 else ""
        s = s[:m.start()] + display + s[m.end():]
    return s.replace("{{", "").replace("}}", "").strip()


def _max_atk_multiplier(norm):
    """Largest attack multiplier (fraction, e.g. 2.4) in normalized text."""
    mult = 0.0
    m = _RE_NM_ATK_TO.search(norm)
    if m:
        mult = max(mult, int(m.group(1)) / 100.0)
    m = _RE_NM_ATK_PLUS.search(norm)
    if m:
        mult = max(mult, 1.0 + int(m.group(1)) / 100.0)
    for mm in _RE_NM_DMG_MULT.finditer(norm):
        val = mm.group(1) or mm.group(2)
        if val:
            mult = max(mult, int(val) / 100.0)
    return mult


def _target_count(norm, base_block):
    """Distinct targets hit per attack. Default 1; plus/exact/extra raise it."""
    n = 1
    m = _RE_NM_TARGET_EXACT.search(norm)
    if m:
        n = max(n, int(m.group(1)))
    m = _RE_NM_TARGET_PLUS.search(norm)
    if m:
        n = max(n, 1 + int(m.group(1)))
    m = _RE_NM_EXTRA_TARGET.search(norm)
    if m:
        n = max(n, 1 + int(m.group(1)))
    if _RE_EXTRA_TARGET.search(norm):
        n = max(n, 2)
    return n


def parse_skill_dps(wiki_text, base):
    """Theoretical level-7 skill DPS, single-target vs multi-target split.

    Fixed assumptions (recorded in output meta): max-level skill, no external
    buff, full duration, enemy defense/resistance ignored (panel theoretical).
    Instant/next-attack skills (empty duration) and special mechanics are
    flagged via needs_review rather than forced into a sustained DPS.
    """
    sec_m = _RE_SKILL_SECTION.search(wiki_text)
    if not sec_m:
        return []
    section = sec_m.group(1)
    # split into per-skill chunks at each 技能名 marker
    chunks = re.split(r"(?=\|技能名=)", section)
    out = []
    atk = base["atk_with_trust"]
    base_interval = base["interval"]
    for chunk in chunks:
        nm = _RE_SKILL_NAME.search(chunk)
        d7 = _RE_S7_DESC.search(chunk)
        if not nm or not d7:
            continue
        name = nm.group(1).strip()
        norm = _strip_templates(d7.group(1))
        dur_m = _RE_S7_DUR.search(chunk)
        dur_raw = dur_m.group(1).strip() if dur_m else ""
        cost_m = _RE_S7_COST.search(chunk)
        type_m = _RE_SKILL_TYPE.search(chunk)
        multiplier = _max_atk_multiplier(norm)
        combo_hits = 2 if _RE_NM_DOUBLE.search(norm) else 1
        targets = _target_count(norm, base.get("block", 1))
        iv_m = _RE_NM_INTERVAL.search(norm)
        interval_delta = float(iv_m.group(1)) if iv_m else 0.0
        # classify WHY there is no sustained DPS; this is normal, not a warning.
        is_next_attack = "下次攻击" in norm or "下次" in norm
        if dur_raw and dur_raw.replace(".", "", 1).isdigit():
            skill_mode = "sustained"
        elif is_next_attack:
            skill_mode = "instant_next_attack"   # one charged hit, no duration
        else:
            skill_mode = "infinite_or_special"   # e.g. 黄昏 (manual toggle / no fixed duration)
        # needs_review is reserved for mechanics where panel math can mislead,
        # NOT for the common no-duration case above.
        review = []
        if "召唤" in norm or "浮游单元" in norm or "狼群" in norm or "海嗣" in norm:
            review.append("召唤/独立单位机制，面板DPS不含召唤物")
        if "特性" in norm and "倍" in norm:
            review.append("特性倍率解放类，需结合特性面板，静态估算可能偏差")
        # interval_delta is already applied in the DPS formula, so it is a
        # transparent assumption stored as a field, not a manual-review item.
        duration = float(dur_raw) if dur_raw.replace(".", "", 1).isdigit() else None
        rec = {
            "skill": name,
            "recovery": type_m.group(1).strip() if type_m else None,
            "sp_cost": int(cost_m.group(1)) if cost_m and cost_m.group(1).isdigit() else None,
            "duration": duration,
            "skill_mode": skill_mode,
            "atk_mult": round(multiplier, 2) if multiplier else None,
            "combo_hits": combo_hits,
            "targets": targets,
            "interval_delta": interval_delta or None,
            "single_dps": None, "aoe_dps": None,
            "needs_review": review,
        }
        # sustained DPS only when a multiplier and a real duration exist
        if multiplier and duration:
            skill_interval = max(0.1, base_interval + interval_delta)
            per_hit = atk * multiplier * combo_hits
            single = round(per_hit / skill_interval, 1)
            rec["single_dps"] = single
            rec["aoe_dps"] = round(single * targets, 1) if targets > 1 else single
        out.append(rec)
    return out


def _first(rx, text, cast=int, default=None):
    m = rx.search(text)
    return cast(m.group(1)) if m else default


def parse_base(wiki_text):
    """Precise elite-2-max (or elite-1-max for 3-star) white stats."""
    e2 = _RE_ATK_E2.search(wiki_text)
    if e2:
        elite_cap = "精英2"
        atk = _first(_RE_ATK_E2, wiki_text)
        hp = _first(_RE_HP_E2, wiki_text)
        dfn = _first(_RE_DEF_E2, wiki_text)
        res = _first(_RE_RES_E2, wiki_text, default=0)
    else:
        elite_cap = "精英1"
        atk = _first(_RE_ATK_E1, wiki_text)
        hp = _first(_RE_HP_E1, wiki_text)
        dfn = _first(_RE_DEF_E1, wiki_text)
        res = _first(_RE_RES_E1, wiki_text, default=0)
    interval = _first(_RE_INTERVAL, wiki_text, cast=float)
    block = _first(_RE_BLOCK, wiki_text)
    trust_atk = _first(_RE_TRUST_ATK, wiki_text, default=0)
    # module attack bonus: "atk:60;magic_resistance:5"
    module_atk = 0
    for mm in _RE_MODULE.finditer(wiki_text):
        am = re.search(r"atk:(\d+)", mm.group(1))
        if am:
            module_atk += int(am.group(1))
    atk_with_trust = (atk or 0) + (trust_atk or 0)
    base_dps = round(atk_with_trust / interval, 1) if interval and atk else None
    # elite-1-max anchor (the closest local data for tier-1/2 operators whose
    # in-mode initial state is elite-1). Trust stays at 100% in the mode.
    e1_atk = _first(_RE_ATK_E1, wiki_text)
    e1_hp = _first(_RE_HP_E1, wiki_text)
    e1_def = _first(_RE_DEF_E1, wiki_text)
    e1_res = _first(_RE_RES_E1, wiki_text, default=0)
    e1_atk_trust = (e1_atk or 0) + (trust_atk or 0)
    e1_dps = round(e1_atk_trust / interval, 1) if interval and e1_atk else None
    return {
        "elite_cap": elite_cap,
        "atk": atk, "atk_with_trust": atk_with_trust,
        "interval": interval, "base_dps": base_dps,
        "hp": hp, "def": dfn, "res": res, "block": block,
        "trust_atk": trust_atk, "module_atk": module_atk,
        # elite-1-max anchor (local infobox ceiling for the E1 phase)
        "e1_atk": e1_atk, "e1_atk_with_trust": e1_atk_trust,
        "e1_hp": e1_hp, "e1_def": e1_def, "e1_res": e1_res, "e1_base_dps": e1_dps,
    }


def parse_self_buff(skills):
    """Own-skill burst amplifier signals across all skills."""
    max_mult, max_aspd, max_targets, extra_hits = 0.0, 0, 0, 0
    source_skill, signals = None, []
    for s in skills:
        eff = s.get("effect", "") or ""
        name = s.get("name", "")
        local_mult = 0.0
        m = _RE_ATK_TO.search(eff)
        if m:
            local_mult = max(local_mult, int(m.group(1)) / 100.0)
        m = _RE_ATK_PLUS.search(eff)
        if m:
            local_mult = max(local_mult, 1.0 + int(m.group(1)) / 100.0)
        for rx in (_RE_DMG_PCT, _RE_DMG_PCT_V2, _RE_DMG_PCT_V3):
            for dm in rx.finditer(eff):
                local_mult = max(local_mult, int(dm.group(1)) / 100.0)
        if local_mult > max_mult:
            max_mult, source_skill = local_mult, name
        aspd = _first(_RE_ASPD, eff, default=0)
        max_aspd = max(max_aspd, aspd)
        tg = max(_first(_RE_TARGETS, eff, default=0),
                 _first(_RE_TARGETS_V2, eff, default=0))
        max_targets = max(max_targets, tg)
        if _RE_EXTRA_HIT.search(eff):
            extra_hits = max(extra_hits, int(_RE_EXTRA_HIT.search(eff).group(1)))
        if _RE_EXTRA_TARGET.search(eff) or _RE_COMBO.search(eff):
            extra_hits = max(extra_hits, 1)
        if local_mult or aspd or tg:
            signals.append(name)
    return {
        "max_atk_mult": round(max_mult, 2) if max_mult else None,
        "max_aspd": max_aspd or None,
        "max_targets": max_targets or None,
        "extra_hits": extra_hits or None,
        "source_skill": source_skill,
        "signal_count": len(set(signals)),
    }


def mode_level_context(shop_tier, star, base, mode_levels, elite_max):
    """Map an operator to the mode's FIXED elite/level/skill/module state, and
    honestly label how the local wiki anchor relates to that real level.

    The wiki only exposes phase-ceiling anchors (E1 max, E2 max), not the exact
    fixed levels (E1 Lv55/60, E2 Lv1/60), so no interpolation is faked; we record
    the anchor used and the direction of any over/under-estimate.
    """
    spec = mode_levels[str(shop_tier)]
    star = str(star)
    cap = elite_max.get(star, {"e1_max": 70, "e2_max": 80})

    def anchor_for(phase, level):
        if phase == 1:
            return {
                "phase": 1, "fixed_level": level,
                "anchor_label": "精英1满级(Lv%d)" % cap["e1_max"],
                "anchor_atk_with_trust": base["e1_atk_with_trust"],
                "anchor_base_dps": base["e1_base_dps"],
                "bias": "wiki锚点为E1满级Lv%d，高于模式固定Lv%d，轻微高估" % (cap["e1_max"], level),
            }
        # phase 2: mode level is E2 Lv1 (initial) or Lv60 (elite), wiki anchor is E2 max
        return {
            "phase": 2, "fixed_level": level,
            "anchor_label": "精英2满级(Lv%d)" % cap["e2_max"],
            "anchor_atk_with_trust": base["atk_with_trust"],
            "anchor_base_dps": base["base_dps"],
            "bias": ("wiki锚点为E2满级Lv%d，模式固定仅Lv%d，明显高估(待逐级数据修正)" % (cap["e2_max"], level))
                   if level < cap["e2_max"] else "模式固定Lv%d即接近E2满级，偏差小" % level,
        }

    return {
        "shop_tier": shop_tier,
        "initial": {**spec["initial"], "anchor": anchor_for(spec["initial"]["phase"], spec["initial"]["level"])},
        "elite": {**spec["elite"], "anchor": anchor_for(spec["elite"]["phase"], spec["elite"]["level"])},
    }


def percentile_tier(value, ordered):
    """S/A/B/C by the value's percentile within a sorted list (None -> None)."""
    if value is None or not ordered:
        return None
    below = sum(1 for v in ordered if v <= value)
    pct = below / len(ordered)
    if pct >= S_CUT:
        return "S"
    if pct >= A_CUT:
        return "A"
    if pct >= B_CUT:
        return "B"
    return "C"


def main():
    profiles = {p["name"]: p for p in json.load(open(PROFILES, encoding="utf-8"))}
    operators = json.load(open(OPERATORS, encoding="utf-8"))
    mode_doc = json.load(open(MODE_LEVELS, encoding="utf-8"))
    mode_levels = mode_doc["tiers"]
    elite_max = mode_doc["elite_max_level"]
    wiki_paths = {os.path.splitext(os.path.basename(p))[0]: p
                  for p in glob.glob(os.path.join(PRTS_DIR, "*.wiki"))}

    records, missing_wiki = [], []
    for op in operators:
        name = op["name"]
        wp = wiki_paths.get(name)
        if not wp:
            missing_wiki.append(name)
            continue
        wiki_text = open(wp, encoding="utf-8").read()
        base = parse_base(wiki_text)
        prof = profiles.get(name, {})
        self_buff = parse_self_buff(prof.get("skills", []))
        skill_dps = parse_skill_dps(wiki_text, base)
        skill_review = ["《%s》%s" % (s["skill"], msg)
                        for s in skill_dps for msg in s["needs_review"]]
        mode_ctx = mode_level_context(op.get("shop_tier"), op.get("star"),
                                      base, mode_levels, elite_max)
        records.append({
            "name": name, "prof": op.get("prof"), "branch": op.get("branch"),
            "star": op.get("star"), "shop_tier": op.get("shop_tier"),
            "bonds": op.get("bonds", []),
            "base": base, "buff_self_raw": self_buff,
            "skill_dps": skill_dps,
            "mode_level": mode_ctx,
            "needs_review": skill_review,
        })

    # ---- percentile ranking across the whole library ----
    dps_list = sorted(r["base"]["base_dps"] for r in records
                      if r["base"]["base_dps"] is not None)
    mult_list = sorted(r["buff_self_raw"]["max_atk_mult"] for r in records
                       if r["buff_self_raw"]["max_atk_mult"] is not None)
    for r in records:
        r["buff_external"] = {
            "base_dps": r["base"]["base_dps"],
            "interval": r["base"]["interval"],
            "tier": percentile_tier(r["base"]["base_dps"], dps_list),
        }
        raw = r["buff_self_raw"]
        r["buff_self"] = {
            "max_atk_mult": raw["max_atk_mult"], "max_aspd": raw["max_aspd"],
            "max_targets": raw["max_targets"], "extra_hits": raw["extra_hits"],
            "source_skill": raw["source_skill"],
            "tier": percentile_tier(raw["max_atk_mult"], mult_list),
        }
        del r["buff_self_raw"]
        # needs_review: a combat-class operator with no parseable self amplifier
        combat_prof = r["prof"] in ("近卫", "狙击", "术师")
        if combat_prof and r["buff_self"]["max_atk_mult"] is None:
            r["needs_review"].append("输出职业但技能无正则倍率，疑特殊机制(解放/召唤/条件爆发)待人工核")
        # convenience: best sustained single/AoE theoretical skill DPS. The two
        # maxima can come from different skills, so each carries its own source.
        sustained = [s for s in r["skill_dps"] if s["single_dps"] is not None]
        best_single = max(sustained, key=lambda s: s["single_dps"], default=None)
        best_aoe = max(sustained, key=lambda s: s["aoe_dps"], default=None)
        r["best_skill_dps"] = {
            "single": best_single["single_dps"] if best_single else None,
            "single_skill": best_single["skill"] if best_single else None,
            "aoe": best_aoe["aoe_dps"] if best_aoe else None,
            "aoe_skill": best_aoe["skill"] if best_aoe else None,
        }

    review = [r for r in records if r["needs_review"]]
    out = {
        "_meta": {
            "description": "干员战力：base=PRTS精2满级白值(精确，裸DPS=(攻击+信赖)/间隔)；"
                           "buff_self=自身技能爆发放大档(全库分位S/A/B/C)；buff_external=外部%攻击拐承载档；"
                           "skill_dps=满级(技能7)理论DPS，single_dps(对单)与aoe_dps(对群=对单×目标数)分开，"
                           "供后续怪海/单体判断。理论DPS固定假设：满级技能、无外部拐、打满持续时间、忽略敌人防御/法抗；"
                           "瞬时/下次攻击类(持续为空)与召唤/解放类不给持续DPS而在needs_review标注，真实减防/覆盖率属战斗模拟层。",
            "dps_assumptions": ["wiki锚点面板(含信赖)，非模式固定等级实战值",
                                "技能7满级(对应精锐Rank7口径)", "无外部buff",
                                "打满技能持续时间", "忽略敌人防御与法术抗性",
                                "aoe_dps=single_dps×同次攻击目标数(满目标理论值)"],
            "mode_fixity_note": "卫戍协议内干员练度按等阶固定(见 mode_level 字段与 data/mode_levels.json)："
                                "t1/t2初始=精英1(Lv55/60)，t3~t6初始=精英2Lv1，精锐统一精英2；技能初始Rank4/精锐Rank7。"
                                "因本地wiki仅有精英1满级/精英2满级锚点、缺逐级面板，本文件DPS是锚点理论值，"
                                "相对模式固定等级普遍偏高(bias字段逐干员标注方向)，精确逐级面板待数据源补全。",
            "tier_cutoffs": {"S": S_CUT, "A": A_CUT, "B": B_CUT},
            "operator_count": len(records),
            "missing_wiki": missing_wiki,
            "needs_review_count": len(review),
        },
        "operators": records,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---- console summary ----
    print("operators:", len(records), "| missing wiki:", missing_wiki)
    print("needs_review:", len(review), "->", [r["name"] for r in review])
    from collections import Counter
    print("buff_self 档位:", dict(Counter(r["buff_self"]["tier"] for r in records)))
    print("buff_external 档位:", dict(Counter(r["buff_external"]["tier"] for r in records)))
    print("\n-- 外部拐承载 Top8 (白值DPS) --")
    for r in sorted(records, key=lambda x: -(x["base"]["base_dps"] or 0))[:8]:
        b = r["base"]
        print("  %-8s %s DPS%.0f 攻%s 间隔%.2fs 档%s" %
              (r["name"], r["prof"], b["base_dps"], b["atk_with_trust"],
               b["interval"], r["buff_external"]["tier"]))
    print("\n-- 自身爆发倍率 Top8 --")
    rated = [r for r in records if r["buff_self"]["max_atk_mult"]]
    for r in sorted(rated, key=lambda x: -x["buff_self"]["max_atk_mult"])[:8]:
        s = r["buff_self"]
        print("  %-8s %s 倍率%.2f 档%s 《%s》 aspd=%s 目标=%s" %
              (r["name"], r["prof"], s["max_atk_mult"], s["tier"],
               s["source_skill"], s["max_aspd"], s["max_targets"]))
    print("\nwritten", OUT)


if __name__ == "__main__":
    main()
