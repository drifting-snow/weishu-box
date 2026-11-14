# -*- coding: utf-8 -*-
"""Build data/operator_ranges.json: REAL attack-range grids per operator.

Why this exists
---------------
The clean-room battle kernel first used coarse profession radius guesses
(melee 1 tile / ranged 3 tiles, Euclidean). That is the single biggest fidelity
loss in the discrete simulation: real Arknights ranges are axis-aligned tile
sets, not circles, so a circular radius both invents diagonal cells and misses
the true shape. The official unpacked tables already carry the exact grids:

  character_table.json  -> each operator phase has a `rangeId`
  range_table.json      -> rangeId -> grids[{row, col}] offsets (col+ = forward)

This builder resolves, for every advisor operator, the basic and elite normal
attack range as an explicit offset-cell set, plus skill range ids (stored but
not yet consumed by the kernel). Only MIT-clean derived facts are written; the
two source tables stay git-ignored and are rebuilt via fetch_game_data.py.

Coverage is asserted: all 141 advisor operators must resolve a valid range, so a
season data change that breaks a join fails the build loudly instead of silently
degrading the simulation. Stdlib only.
"""
import argparse, io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GD = os.path.join(ROOT, "data", "source", "gamedata")
DEFAULT_OUT = os.path.join(ROOT, "data", "operator_ranges.json")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _is_ranged(position):
    # char_table position is one of ALL / MELEE / RANGED (some dumps concatenate
    # the profession, so match on the leading token robustly).
    return str(position).upper().startswith("RANGED")


def _cells(range_table, range_id):
    rec = range_table.get(range_id)
    if not rec:
        return None
    return [[int(g["row"]), int(g["col"])] for g in rec.get("grids", [])]


def build():
    char_table = load(os.path.join(GD, "character_table.json"))
    range_table = load(os.path.join(GD, "range_table.json"))
    skill_table = load(os.path.join(GD, "skill_table.json"))
    sys.path.insert(0, ROOT)
    from advisor import effdps
    metrics = effdps.load_combat_metrics()

    operators = {}
    missing_range, missing_char, changed_with_elite = [], [], 0
    for name, rec in metrics.items():
        cid = rec.get("char_id")
        op = char_table.get(cid)
        if not op or not op.get("phases"):
            missing_char.append(name)
            continue
        phases = op["phases"]
        base_id = phases[0].get("rangeId")
        elite_id = phases[-1].get("rangeId")
        base_cells = _cells(range_table, base_id)
        elite_cells = _cells(range_table, elite_id)
        if base_cells is None or elite_cells is None:
            missing_range.append((name, base_id, elite_id))
            continue
        if base_id != elite_id:
            changed_with_elite += 1

        # Skill range ids are resolved lazily later; store the id per skill so
        # the skill-tick stage does not have to re-read the giant skill table.
        skill_ranges = {}
        for s in op.get("skills", []):
            sid = s.get("skillId")
            sk = skill_table.get(sid)
            if not sk or not sk.get("levels"):
                continue
            rid = sk["levels"][-1].get("rangeId")
            if rid and rid in range_table:
                skill_ranges[sid] = rid

        chosen = elite_cells
        forward_reach = max((c for _, c in chosen), default=0)
        operators[name] = {
            "char_id": cid,
            "position": op.get("position"),
            "is_melee": not _is_ranged(op.get("position")),
            "base_range_id": base_id,
            "elite_range_id": elite_id,
            "range_cells": chosen,           # elite normal-attack offsets
            "base_range_cells": base_cells,  # pre-promotion offsets
            "forward_reach": forward_reach,
            "cell_count": len(chosen),
            "skill_range_ids": skill_ranges,
        }

    if missing_char:
        raise ValueError("operators missing a character_table entry: %s"
                         % sorted(missing_char))
    if missing_range:
        raise ValueError("operators with an unresolvable rangeId: %s"
                         % missing_range[:10])

    distinct_shapes = len({tuple(map(tuple, o["range_cells"]))
                           for o in operators.values()})
    out = {
        "_meta": {
            "description": "卫戍协议干员真实普攻射程网格，由官方解包 character_table.rangeId + "
                           "range_table.grids 经 tools/build_operator_ranges.py 自有解析生成；"
                           "不含第三方/GPL 数据。网格为相对自身格(0,0)的 (row,col) 偏移，col+ 为朝向方向。",
            "generated_by": "tools/build_operator_ranges.py",
            "source_tables": "character_table.json + range_table.json + skill_table.json (gitignored)",
            "convention": "range_cells = elite normal-attack offsets; base_range_cells = pre-promotion; "
                          "col+ points forward (toward the red gate at deployment)",
            "operator_count": len(operators),
            "distinct_range_shapes": distinct_shapes,
            "operators_whose_range_changes_on_elite": changed_with_elite,
            "orientation_note": "forward orientation toward the red gate is a first-cut single-lane "
                                "assumption pending in-game verification (needs_review).",
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
    print("wrote %s : %d operators, %d distinct shapes, %d change on elite"
          % (args.out, m["operator_count"], m["distinct_range_shapes"],
             m["operators_whose_range_changes_on_elite"]))


if __name__ == "__main__":
    main()
