# -*- coding: utf-8 -*-
"""Extract per-operator bond-stack attack scaling from 作战能力 entries.

Only the explicit, machine-readable rule form is parsed:
    【盟约】每叠加 N 层，本干员攻击力 +X%
(进阶 form gives the advanced X). These are real published percentages in the
operator dataset. Entries with no clean per-stack percentage (weak-point damage,
control, merge shortcuts, SP recovery, etc.) are not attack multipliers and are
counted as unparsed; the scaling layer treats them as neutral rather than
inventing a number.

Defense/HP bond multipliers have NO published per-stack value in the local wiki
(core bonds only say "受层数影响"), so they are intentionally not produced here.
Stdlib only. Output: data/bond_scaling.json
"""
import io, json, os, re, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OPERATORS = os.path.join(ROOT, "data/operators.json")
OUT_PATH = os.path.join(ROOT, "data/bond_scaling.json")

# 每(叠加)?N层 ... 攻击力 +X%
PAT = re.compile(r"每(?:叠加)?\s*(\d+)\s*层[^。]*?攻击力[^。]*?(\d+(?:\.\d+)?)\s*%")


def main():
    ops = json.load(open(OPERATORS, encoding="utf-8"))
    records, unparsed_combat = [], 0
    for o in ops:
        # dedupe by form: the same rule is repeated across each of the operator's
        # bonds, but the per-stack attack rule itself is form-specific.
        by_form = {}
        for e in o.get("entries", []):
            if e.get("kind") != "作战能力":
                continue
            form = e.get("form", "基础")
            trait = e.get("trait", "")
            m = PAT.search(trait)
            if not m:
                continue
            step, pct = int(m.group(1)), float(m.group(2))
            prev = by_form.get(form)
            # keep one rule per form; verify consistency if duplicated
            if prev and (prev["stack_step"] != step or prev["atk_pct_per_step"] != pct):
                prev.setdefault("conflict", []).append(trait[:40])
            else:
                by_form[form] = {
                    "bond": e.get("bond"),
                    "stack_step": step,
                    "atk_pct_per_step": pct,
                    "rule_text": trait,
                }
        if by_form:
            records.append({
                "name": o["name"], "shop_tier": o.get("shop_tier"),
                "scaling": {
                    "basic": _view(by_form.get("基础")),
                    "advanced": _view(by_form.get("进阶")),
                },
            })
        # count non-parseable combat entries for the coverage report
        for e in o.get("entries", []):
            if e.get("kind") == "作战能力" and not PAT.search(e.get("trait", "")):
                unparsed_combat += 1

    out = {
        "_meta": {
            "description": "羁绊层数->干员攻击力乘数（仅作战能力条目中明确的每N层+X%规则；防御/生命无公布逐层值，不产出）。",
            "source": "operators.json 作战能力条目（BWiki 干员数据集）",
            "formula": "atk_multiplier = 1 + (active_stacks // stack_step) * atk_pct_per_step/100，按当前形态(basic/advanced)取参数",
            "coverage_note": "仅攻击力有可解析规则；防御/生命的羁绊加成官方只写「受层数影响」无具体数值，乘数层对其保持中性(1.0)。",
            "operator_count_with_rule": len(records),
            "unparsed_combat_entries": unparsed_combat,
        },
        "operators": sorted(records, key=lambda r: r["name"]),
    }
    json.dump(out, open(OUT_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("operators with bond attack rule:", len(records),
          "| unparsed combat entries:", unparsed_combat)
    for r in out["operators"][:6]:
        print(" ", r["name"], r["scaling"])


def _view(rule):
    if not rule:
        return None
    return {"stack_step": rule["stack_step"],
            "atk_pct_per_step": rule["atk_pct_per_step"],
            "bond": rule.get("bond")}


if __name__ == "__main__":
    main()
