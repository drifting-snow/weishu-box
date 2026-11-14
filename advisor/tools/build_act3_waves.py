# -*- coding: utf-8 -*-
"""Build data/act3_waves.json: real spawn timelines + clear windows for act3.

Stage-1 clear-margin needs the wave's enemy total HP and the time available to
kill them before the last enemy reaches the exit. Both are derivable from the
official unpacked tables (no GPL data):

  * levels/activities/act3autochess/level_*.json (fetched by
    tools/fetch_act3_levels.py): each SPAWN action carries count / preDelay /
    interval / routeIndex; options.moveMultiplier globally slows movement;
    routes give grid start/end (and FLY checkpoints) for path length.
  * enemy_database.json: level-0 maxHp / moveSpeed / def / res for EVERY spawn
    id, including ordinary filler enemies absent from the 179-enemy tactical
    catalog (e.g. enemy_1007_slime). autochess enemyDbRefs all use level 0.
  * activity_table.json battleDataDict: mode -> round -> levelId, mapping a run
    round (and regulation level via mode_single_1..20) onto these level files.

Clear window per spawn = spawn time + path length / (moveSpeed * moveMultiplier);
the wave window is the max deadline across spawns. Ground WALK routes have no
checkpoints, so path length is the start->end Manhattan distance (an explicit,
documented approximation; FLY routes sum their checkpoint segments). moveSpeed
is the unpacked relative speed; its tiles/second calibration is a single named
constant in clear_margin, not baked here, so re-calibration never rebuilds data.

Stdlib only. Reads git-ignored official tables; the derived JSON is committed.
"""
import argparse, io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GD = os.path.join(ROOT, "data", "source", "gamedata")
LEVEL_DIR = os.path.join(GD, "levels", "activities", "act3autochess")
DEFAULT_OUT = os.path.join(ROOT, "data", "act3_waves.json")


def _mv(x):
    return x.get("m_value") if isinstance(x, dict) and "m_value" in x else x


def load_enemy_db():
    """id -> level-0 enemyData dict (attributes/name) for every enemy."""
    raw = json.load(open(os.path.join(GD, "enemy_database.json"),
                         encoding="utf-8"))["enemies"]
    out = {}
    for item in raw:
        rec = next((v for v in item["Value"] if v.get("level") == 0),
                   item["Value"][0])
        out[item["Key"]] = rec["enemyData"]
    return out


def route_length(route):
    """Grid path length. FLY: sum checkpoint segments; else Manhattan start-end."""
    def manh(a, b):
        return abs(a["row"] - b["row"]) + abs(a["col"] - b["col"])
    cps = route.get("checkpoints") or []
    if cps:
        pts = [route["startPosition"]] + [c.get("position", c) for c in cps] + \
              [route["endPosition"]]
        return sum(manh(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return manh(route["startPosition"], route["endPosition"])


def build_level(path, db):
    lvl = json.load(open(path, encoding="utf-8"))
    move_mult = float(lvl.get("options", {}).get("moveMultiplier", 1.0))
    routes = lvl.get("routes", [])
    rlen = [route_length(r) for r in routes]
    rmotion = [r.get("motionMode", "WALK") for r in routes]

    spawns = []
    missing = []
    for wave in lvl.get("waves", []):
        t_wave = float(wave.get("preDelay", 0.0))
        for frag in wave.get("fragments", []):
            t_frag = t_wave + float(frag.get("preDelay", 0.0))
            for a in frag.get("actions", []):
                if a.get("actionType") != "SPAWN":
                    continue
                eid = a["key"]
                ed = db.get(eid)
                if ed is None:
                    missing.append(eid)
                    continue
                attrs = ed.get("attributes", {})
                name = _mv(ed.get("name", {}))
                hp = _mv(attrs.get("maxHp")) or 0
                move = _mv(attrs.get("moveSpeed")) or 0
                df = _mv(attrs.get("def")) or 0
                res = _mv(attrs.get("magicResistance")) or 0
                n = int(a.get("count", 1))
                interval = float(a.get("interval", 0.0))
                first_t = t_frag + float(a.get("preDelay", 0.0))
                last_t = first_t + (n - 1) * interval
                ri = int(a.get("routeIndex", 0))
                tiles = rlen[ri] if ri < len(rlen) else 0
                eff_speed = move * move_mult if move else 0.0
                travel_t = (tiles / eff_speed) if eff_speed > 0 else None
                deadline_t = (last_t + travel_t) if travel_t is not None else None
                spawns.append({
                    "enemy_id": eid,
                    "enemy_name": name,
                    "count": n,
                    "first_spawn_t": round(first_t, 3),
                    "interval": round(interval, 3),
                    "last_spawn_t": round(last_t, 3),
                    "route_index": ri,
                    "motion": rmotion[ri] if ri < len(rmotion) else "WALK",
                    "route_tiles": tiles,
                    "move_speed": move,
                    "travel_t": round(travel_t, 3) if travel_t is not None else None,
                    "deadline_t": round(deadline_t, 3) if deadline_t is not None else None,
                    "level0_hp": hp,
                    "level0_def": df,
                    "level0_res": res,
                })

    deadlines = [s["deadline_t"] for s in spawns if s["deadline_t"] is not None]
    total_count = sum(s["count"] for s in spawns)
    total_hp = sum(s["count"] * s["level0_hp"] for s in spawns)
    return {
        "move_multiplier": move_mult,
        "total_count": total_count,
        "total_hp_level0": total_hp,
        "clear_window_t": round(max(deadlines), 3) if deadlines else None,
        "spawns": spawns,
        "_missing_ids": sorted(set(missing)),
    }


def build_round_map():
    act = json.load(open(os.path.join(GD, "activity_table.json"), encoding="utf-8"))
    bdd = act["activity"]["AUTOCHESS"]["act3autochess"]["V3_1"]["battleDataDict"]
    out = {}
    for mode, rounds in bdd.items():
        m = {}
        for r, entries in rounds.items():
            m[str(r)] = [{
                "level": os.path.basename(e["levelId"]).replace(".json", ""),
                "is_prepare": bool(e.get("isSpPrepare")),
            } for e in entries]
        out[mode] = m
    return out


def build():
    db = load_enemy_db()
    level_stems = {}
    all_missing = {}
    for fn in sorted(os.listdir(LEVEL_DIR)):
        if not fn.endswith(".json") or fn == "level_autochess_enemy_data.json":
            continue
        stem = fn[:-5]
        doc = build_level(os.path.join(LEVEL_DIR, fn), db)
        if doc["_missing_ids"]:
            all_missing[stem] = doc.pop("_missing_ids")
        else:
            doc.pop("_missing_ids")
        level_stems[stem] = doc

    return {
        "_meta": {
            "description": "act3 卫戍协议·规程 每关真实出怪时间线与清场窗口，由官方解包关卡/敌人/活动表自有派生（无 GPL 数据）。",
            "generated_by": "tools/build_act3_waves.py",
            "source_tables": "gamedata levels/act3autochess + enemy_database + activity_table (gitignored)",
            "window_rule": "deadline_t = last_spawn_t + route_tiles/(moveSpeed*moveMultiplier); clear_window_t=max(deadline)",
            "approximations": [
                "地面 WALK 路线无 checkpoints，路径长按起终点 Manhattan 格数（FLY 按 checkpoint 折线段求和）",
                "moveSpeed 为解包相对速度，格/秒标定常数在 advisor/clear_margin.py 单点维护，重标定无需重建本数据",
            ],
            "level_count": len(level_stems),
            "levels_with_unmapped_ids": all_missing,
        },
        "round_to_level": build_round_map(),
        "level_stems": level_stems,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    doc = build()
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    m = doc["_meta"]
    print("wrote %s | levels=%d | unmapped=%d" %
          (args.out, m["level_count"], len(m["levels_with_unmapped_ids"])))
    s = doc["level_stems"]["level_act3autochess_01"]
    print("level_01: count=%d hp0=%d window=%s mult=%s" %
          (s["total_count"], s["total_hp_level0"], s["clear_window_t"], s["move_multiplier"]))
    for sp in s["spawns"]:
        print("  %-18s n=%d last=%.1fs travel=%s deadline=%s hp=%d" %
              (sp["enemy_name"], sp["count"], sp["last_spawn_t"],
               sp["travel_t"], sp["deadline_t"], sp["level0_hp"]))


if __name__ == "__main__":
    main()
