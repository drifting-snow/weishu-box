# -*- coding: utf-8 -*-
"""Build data/operator_skills.json: deterministic timed burst skills.

Scope (honest first cut)
------------------------
The battle kernel previously modelled operators as basic-attack-only, which
systematically understates damage. The official skill_table carries, per skill
level, the SP recovery model (spData) and duration, while operator_combat_metrics
carries the damage multiplier. We can deterministically drive a skill when:

  * spType == INCREASE_WITH_TIME (auto SP recovery; charge = spCost / increment)
  * the skill_metrics row has a numeric damage multiplier and a finite duration

In Guard Protocol the auto-battle has no manual skill button, so a skill fires
as soon as SP reaches its cost and repeats on a charge -> active -> charge cycle.
Attack-recovery (INCREASE_WHEN_ATTACK), hit-taken recovery and the numeric
spType=8 special skills depend on combat events not modelled yet, so they are
counted in `untimed_skill_ids` and excluded rather than guessed.

When an operator has several eligible skills we keep the highest-multiplier one
as the representative burst (the nuke a player would line up against a wave);
the choice itself is flagged for review in _meta. Only MIT-clean derived facts
are committed; the source tables stay git-ignored. Stdlib only.
"""
import argparse, io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GD = os.path.join(ROOT, "data", "source", "gamedata")
DEFAULT_OUT = os.path.join(ROOT, "data", "operator_skills.json")

AUTO_SP = "INCREASE_WITH_TIME"


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build():
    sys.path.insert(0, ROOT)
    from advisor import effdps
    metrics = effdps.load_combat_metrics()
    skill_table = load(os.path.join(GD, "skill_table.json"))

    operators, covered, untimed = {}, 0, 0
    for name, rec in metrics.items():
        ini = rec.get("initial") or {}
        eligible = []
        untimed_ids = []
        special_ids = []
        for sm in ini.get("skill_metrics") or []:
            sid = sm.get("skill_id")
            raw = skill_table.get(sid)
            if not raw or not raw.get("levels"):
                untimed_ids.append(sid); untimed += 1; continue
            spd = raw["levels"][-1].get("spData") or {}
            mult = sm.get("multiplier")
            duration = sm.get("duration")
            ok = (spd.get("spType") == AUTO_SP
                  and spd.get("spCost") and spd.get("increment")
                  and isinstance(mult, (int, float))
                  and isinstance(duration, (int, float)) and duration > 0)
            if not ok:
                untimed_ids.append(sid); untimed += 1; continue
            cost = float(spd["spCost"]); incr = float(spd["increment"])
            row = {
                "skill_id": sid,
                "name": sm.get("name"),
                "skill_type": sm.get("skill_type"),
                "sp_type": AUTO_SP,
                "charge_time": round(cost / incr, 3),
                "initial_sp": float(spd.get("initSp", 0) or 0),
                "initial_charge": round(float(spd.get("initSp", 0) or 0) / incr, 3),
                "duration": float(duration),
                "multiplier": float(mult),
                "mult_source": sm.get("mult_source"),
                "hit_count": sm.get("hit_count"),
                "targets": sm.get("targets"),
            }
            # Only additive ATK-up skills with multiplier > 1 map cleanly onto the
            # basic-attack loop as a burst-window ATK multiplier. total-source skills
            # with multiplier <= 1 (e.g. 钙质化 0.2, 沸血燎原 0.35) are DoT/control/
            # multi-hit arts whose number is a per-tick ATK share, not an ATK buff;
            # driving them as ATK*0.2 would be wrong, so archive them for later.
            if sm.get("mult_source") == "additive" and float(mult) > 1.0:
                eligible.append(row)
            else:
                special_ids.append(sid); untimed += 1
        chosen = max(eligible, key=lambda s: s["multiplier"]) if eligible else None
        if chosen:
            covered += 1
        operators[name] = {
            "burst_skill": chosen,
            "eligible_skill_count": len(eligible),
            "special_skill_ids": special_ids,
            "untimed_skill_ids": [s for s in untimed_ids if s],
        }

    out = {
        "_meta": {
            "description": "卫戍协议干员可确定性驱动的定时爆发技能（自动回复 SP，SP 满自动触发，充能=spCost/increment），"
                           "由 skill_table.spData + operator_combat_metrics.skill_metrics 经 tools/build_operator_skills.py 自有解析生成；不含第三方/GPL 数据。",
            "generated_by": "tools/build_operator_skills.py",
            "source_tables": "skill_table.json + operator_combat_metrics.json (gitignored source for the former)",
            "model": "auto-battle: skill fires at SP=spCost, active for duration, then recharges; "
                     "burst applies multiplier to ATK (mult_source additive vs total preserved).",
            "operators_with_burst_skill": covered,
            "operator_count": len(operators),
            "untimed_skill_rows": untimed,
            "needs_review": [
                "only INCREASE_WITH_TIME skills are driven; attack/hit-taken recovery and spType=8 wait for combat-event modeling",
                "only additive ATK-up skills with multiplier>1 become burst_skill; total-source DoT/control skills (multiplier<=1) are parked in special_skill_ids",
                "when several skills qualify the highest multiplier is used as the representative burst (manual choice is strategic)",
                "AUTO vs MANUAL label is ignored: autochess auto-fires every skill when SP is full",
                "AoE hit_count/targets and control side-effects are not yet applied to the kernel (damage multiplier only)",
            ],
        },
        "operators": operators,
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    out = build()
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, sort_keys=True)
    m = out["_meta"]
    print("wrote %s : %d/%d operators with a burst skill, %d untimed skill rows"
          % (args.out, m["operators_with_burst_skill"], m["operator_count"],
             m["untimed_skill_rows"]))


if __name__ == "__main__":
    main()
