# -*- coding: utf-8 -*-
"""Build compact engine JSON from the BWiki parsed dataset.

Input : data source parsed.json (produced by the wiki extract pipeline)
Output: data/operators.json, bonds.json, items.json, economy.json, meta.json
Stdlib only. Re-run whenever a new season dataset is pulled.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Portable: only repo-relative paths. A fresh clone obtains parsed.json from the
# documented data pipeline (see README "Data pipeline"), never from a machine path.
SRC_PATH = os.path.join(ROOT, "data", "parsed.json")

def load_source():
    if os.path.exists(SRC_PATH):
        return json.load(open(SRC_PATH, encoding="utf-8")), SRC_PATH
    raise SystemExit(
        "parsed.json not found at %s. " % SRC_PATH
        + "Run the wiki extract pipeline first (see README 'Data pipeline').")

def main():
    d, src = load_source()
    out = os.path.join(ROOT, "data")
    os.makedirs(out, exist_ok=True)

    # ---- operators: dedupe 480 rows -> per operator, keep all bond/form/trait ----
    ops = {}
    for r in d["operators"]:
        name = r["name"]
        o = ops.setdefault(name, {
            "name": name, "prof": r["prof"], "star": r["star"],
            "bonds": set(), "entries": [],
        })
        o["bonds"].add(r["bond"])
        o["entries"].append({
            "tier": int(r["tier"]), "bond": r["bond"], "kind": r["kind"],
            "form": r["form"], "trait": r["trait"],
        })
    operators = []
    for o in ops.values():
        # canonical tier = the tier at which this operator appears (min over entries)
        tiers = sorted({e["tier"] for e in o["entries"]})
        o["bonds"] = sorted(o["bonds"])
        o["tiers"] = tiers
        o["shop_tier"] = min(tiers)
        operators.append(o)
    operators.sort(key=lambda x: (x["shop_tier"], x["name"]))

    # ---- merge native PRTS profile (branch, trait, position, anti-air, talents) ----
    # The BWiki weishu dataset only carries bond traits; native Arknights
    # profession branch and talents (e.g. silence) come from tools/parse_prts.py.
    profile_path = os.path.join(out, "operator_profiles.json")
    if os.path.exists(profile_path):
        profiles = {p["name"]: p for p in json.load(open(profile_path, encoding="utf-8"))}
        merged, no_profile = 0, []
        for o in operators:
            p = profiles.get(o["name"])
            if not p:
                no_profile.append(o["name"])
                continue
            o["branch"] = p["branch"]
            o["native_trait"] = p["trait"]
            o["position"] = p["position"]
            o["anti_air"] = p["anti_air"]
            o["native_tags"] = p["tags"]
            o["native_talents"] = p["talents"]
            o["skills"] = p["skills"]
            o["mechanic_tags"] = p["mechanic_tags"]
            merged += 1
        print("PRTS profiles merged: %d/%d" % (merged, len(operators)))
        if no_profile:
            print("WARN no native profile for:", "、".join(no_profile))
    else:
        print("WARN operator_profiles.json absent; native branch/talents not merged")

    json.dump(operators, open(os.path.join(out, "operators.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ---- bonds ----
    # Prefer the dedicated structured parser (preserves milestone markers that
    # the generic cleaner would delete); fall back to parsed.json if absent.
    structured_path = os.path.join(out, "bonds_structured.json")
    if os.path.exists(structured_path):
        sb = json.load(open(structured_path, encoding="utf-8"))
        def _legacy(b):
            # keep need/effect for the engine while adding structured fields
            milestone_text = "；".join(
                "【%s%s】%s" % (m["condition"], "", m["effect"]) for m in b["milestones"])
            effect = b["base_effect"]
            if milestone_text:
                effect = (effect + " " + milestone_text).strip()
            return {
                "name": b["name"],
                "need": b["activation_need"],
                "effect": effect,
                "operators": b["operators"],
                "base_effect": b["base_effect"],
                "milestones": b["milestones"],
            }
        bonds = {
            "core": [_legacy(b) for b in sb["core"]],
            "attached": [_legacy(b) for b in sb["attached"]],
        }
    else:
        bonds = {"core": d["core"], "attached": d["attached"]}
    json.dump(bonds, open(os.path.join(out, "bonds.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ---- items ----
    items = [{
        "tier": int(x["tier"]), "name": x["name"], "price": x["price"],
        "base": x["base"], "advanced": x["adv"], "bond": x["bond"],
    } for x in d["items"]]
    json.dump(items, open(os.path.join(out, "items.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    # ---- economy: hard rule tables copied from mechanism doc (official) ----
    # NOTE on buy price: the wiki mechanism page only states a blanket
    # "recruit costs 3 资金" (in an HTML comment). In-game observation gives a
    # tiered schedule, which is more accurate and is used as the default; the
    # flat 3 is kept only as a fallback. Special operators override this via
    # their 整备能力 entry (e.g. 真理/至简 "购买价格为1"), handled in advisor/economy.py.
    economy = {
        "refresh_cost": 1,
        "buy_operator_cost": 3,  # generic wiki fallback; prefer the table below
        "buy_price_by_shop_tier": {
            # shop_tier -> actual buy price (player-observed, season 规程·序列I)
            "1": 2, "2": 3, "3": 3, "4": 3, "5": 4, "6": 4,
        },
        "buy_price_source": "in_game_observation; wiki only gives flat 3",
        "sell_operator_gain": 1,
        "default_sell_price": 1,
        "max_hand": 10,
        "items_per_operator": 2,
        "merge_operator_count": 3,
        "merge_item_count": 2,
        "unspent_carryover": False,
        "upgrade_price": {
            # current dispatch level -> initial price to reach next level
            "standard":       {1: 5, 2: 8, 3: 10, 4: 11, 5: 11, 6: None},
            "hard_abyss":     {1: 5, 2: 8, 3: 11, 4: 12, 5: 13, 6: None},
            "speed":          {1: 1, 2: 1, 3: 5, 4: 8, 5: 10, 6: 11},
        },
        "slots": {
            "standard":   {1: 3, 2: 4, 3: 4, 4: 4, 5: 4, 6: 5},
            "hard_abyss": {1: 3, 2: 4, 3: 4, 4: 5, 5: 5, 6: 5},
            "speed":      {1: 3, 2: 4, 3: 4, 4: 4, 5: 4, 6: 5},
        },
        "shop_tier_gate": "shop operator tier <= dispatch level",
        "pull_probability": "NOT_PUBLISHED_OFFICIAL",
    }
    json.dump(economy, open(os.path.join(out, "economy.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    meta = {
        "season": "卫戍协议·规程·序列I",
        "source": "BWiki S.W.E.E.P. report + mechanism page",
        "operator_records": len(d["operators"]),
        "unique_operators": len(operators),
        "core_bonds": len(d["core"]),
        "attached_bonds": len(d["attached"]),
        "items": len(items),
    }
    json.dump(meta, open(os.path.join(out, "meta.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("source:", src)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    print("written to", out)

    # ---- trigger-timing tags recovered from raw wikitext (clean() drops them);
    #      must run before parse_stacks, which consumes operator_timing.json ----
    from parse_timing import main as build_timing
    build_timing()

    # ---- universal bond-stack source registry (reads the operators just built) ----
    from parse_stacks import main as build_stack_sources
    build_stack_sources()

    # ---- all-bond stack feasibility factors (advisor module over the registry) ----
    sys_path = sys.path[:]
    sys.path.insert(0, ROOT)
    try:
        from advisor.stack_feasibility import write_report as build_feasibility
        build_feasibility()
    finally:
        sys.path = sys_path

    # ---- structured equipment effects (three-axis item scoring material) ----
    from parse_items import main as build_items_structured
    build_items_structured()

    # ---- operator combat power: precise base stats + relative buff tiers ----
    from parse_power import main as build_operator_power
    build_operator_power()

    # ---- bond-stack attack scaling rules (operators.json only, always built) ----
    from parse_bond_scaling import main as build_bond_scaling
    build_bond_scaling()

    # ---- exact fixed-level panels from unpacked game table (optional stage) ----
    # character_table.json is git-ignored and rebuilt via fetch_game_data.py, so
    # this stage is skipped with a clear hint when the cache is absent instead of
    # breaking the rest of the build for users who only need the wiki-based data.
    gamedata_dir = os.path.join(ROOT, "data", "source", "gamedata")
    gamedata_char = os.path.join(gamedata_dir, "character_table.json")
    gamedata_skill = os.path.join(gamedata_dir, "skill_table.json")
    if os.path.exists(gamedata_char):
        from parse_mode_stats import main as build_mode_stats
        build_mode_stats()
        if os.path.exists(gamedata_skill):
            from parse_combat_metrics import main as build_combat_metrics
            build_combat_metrics()
            # Stage-B damage profiles depend on combat metrics + operators +
            # the override table; all are present once the above stages ran.
            override_path = os.path.join(out, "damage_type_overrides.json")
            if os.path.exists(override_path):
                from parse_damage_profiles import main as build_damage_profiles
                build_damage_profiles()
            else:
                print("SKIP operator_damage_profiles: damage_type_overrides.json absent.")

            # Real per-operator attack-range grids (rangeId -> offset cells).
            # range_table.json sits beside character/skill in the same cache;
            # skipped cleanly when the optional unpacked cache is incomplete.
            gamedata_range = os.path.join(gamedata_dir, "range_table.json")
            if os.path.exists(gamedata_range):
                from build_operator_ranges import build as build_ranges_doc, DEFAULT_OUT as RANGES_OUT
                ranges_doc = build_ranges_doc()
                with open(RANGES_OUT, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(ranges_doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
                print("operator ranges rebuilt: %d operators -> %s" %
                      (ranges_doc["_meta"]["operator_count"], os.path.basename(RANGES_OUT)))
            else:
                print("SKIP operator_ranges: range_table.json absent; run 'python tools/fetch_game_data.py'.")

            # Real enemy attack fields (atk / attack interval / applyWay /
            # reach) keyed by the act3 spawn ids, from the full enemy table.
            enemy_db_path = os.path.join(gamedata_dir, "enemy_database.json")
            if os.path.exists(enemy_db_path):
                from build_enemy_attack import build as build_enemy_attack_doc, DEFAULT_OUT as ENEMY_ATK_OUT
                atk_doc = build_enemy_attack_doc()
                with open(ENEMY_ATK_OUT, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(atk_doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
                print("enemy attack rebuilt: %d enemies -> %s" %
                      (atk_doc["_meta"]["enemy_count"], os.path.basename(ENEMY_ATK_OUT)))
            else:
                print("SKIP enemy_attack: enemy_database.json absent; run 'python tools/fetch_game_data.py'.")

            # Deterministic periodic enemy AoE skill bursts (pure physical).
            # Same enemy_database source; parks arts/nerve/control/summon skills.
            if os.path.exists(enemy_db_path):
                from build_enemy_skills import build as build_enemy_skill_doc, DEFAULT_OUT as ENEMY_SKILL_OUT
                esk_doc = build_enemy_skill_doc()
                with open(ENEMY_SKILL_OUT, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(esk_doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
                print("enemy skills rebuilt: %d drivable, %d parked -> %s" %
                      (esk_doc["_meta"]["enemy_count_with_burst"],
                       esk_doc["_meta"]["parked_skill_count"], os.path.basename(ENEMY_SKILL_OUT)))
            else:
                print("SKIP enemy_skills: enemy_database.json absent; run 'python tools/fetch_game_data.py'.")

            # Deterministic timed operator burst skills (auto-recover SP).
            # Needs skill_table.json alongside the combat metrics cache.
            skill_table_path = os.path.join(gamedata_dir, "skill_table.json")
            if os.path.exists(skill_table_path):
                from build_operator_skills import build as build_skills_doc, DEFAULT_OUT as SKILLS_OUT
                skills_doc = build_skills_doc()
                with open(SKILLS_OUT, "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(skills_doc, fh, ensure_ascii=False, indent=1, sort_keys=True)
                print("operator skills rebuilt: %d/%d with burst -> %s" %
                      (skills_doc["_meta"]["operators_with_burst_skill"],
                       skills_doc["_meta"]["operator_count"], os.path.basename(SKILLS_OUT)))
            else:
                print("SKIP operator_skills: skill_table.json absent; run 'python tools/fetch_game_data.py'.")
        else:
            print("SKIP operator_combat_metrics/damage_profiles: skill_table.json absent; "
                  "run 'python tools/fetch_game_data.py' to include it.")
    else:
        print("SKIP operator_mode_stats/combat_metrics/damage_profiles: run "
              "'python tools/fetch_game_data.py' first to build exact fixed-level panels.")

    # ---- enemy tactical catalog + full name index from official autochess tables.
    # Optional like the stage above: the three source tables are git-ignored and
    # fetched via fetch_game_data.py. Rebuilds data/enemy_catalog.json (179 typed
    # enemies -> 9 trait keys) and data/enemy_names.json (all ~1.8k names). No
    # third-party/GPL data is read; only the official Kengxxiao unpacked tables.
    enemy_src = [
        os.path.join(gamedata_dir, "activity_table.json"),
        os.path.join(gamedata_dir, "enemy_handbook_table.json"),
        os.path.join(gamedata_dir, "enemy_database.json"),
    ]
    if all(os.path.exists(p) for p in enemy_src):
        from build_enemy_catalog import (
            build as build_enemy_catalog_doc, build_name_index,
            DEFAULT_OUT as ENEMY_CATALOG_OUT, DEFAULT_NAMES_OUT as ENEMY_NAMES_OUT)
        enemy_catalog, enemy_cls = build_enemy_catalog_doc()
        enemy_name_index = build_name_index(enemy_cls)
        for path, doc in ((ENEMY_CATALOG_OUT, enemy_catalog),
                          (ENEMY_NAMES_OUT, enemy_name_index)):
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(doc, fh, ensure_ascii=False, indent=2)
        ec = enemy_catalog["_meta"]["counts"]
        print("enemy catalog rebuilt: %d typed names; full index %d names -> %s, %s" %
              (ec["unique_names"],
               enemy_name_index["_meta"]["counts"]["unique_names"],
               os.path.basename(ENEMY_CATALOG_OUT), os.path.basename(ENEMY_NAMES_OUT)))

        # Real level-0 enemy stats (def/res/hp/atk) from the same official
        # tables; depends on the catalog just rebuilt, so run right after it.
        from build_enemy_stats import build as build_enemy_stats_doc, DEFAULT_OUT as ENEMY_STATS_OUT
        stats_doc = build_enemy_stats_doc()
        with open(ENEMY_STATS_OUT, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(stats_doc, fh, ensure_ascii=False, indent=2)
        print("enemy stats rebuilt: %d enemies -> %s" %
              (stats_doc["_meta"]["enemy_count"], os.path.basename(ENEMY_STATS_OUT)))

        # Per-name special-counter extension (ice death-explosion -> silence,
        # etc.); evidence-gated against the official SILENCE abilityList.
        from build_enemy_special_cases import build as build_special_cases_doc, DEFAULT_OUT as SPECIAL_CASES_OUT
        special_doc = build_special_cases_doc()
        with open(SPECIAL_CASES_OUT, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(special_doc, fh, ensure_ascii=False, indent=2)
        print("enemy special cases rebuilt: %d cases -> %s" %
              (special_doc["_meta"]["case_count"], os.path.basename(SPECIAL_CASES_OUT)))

        # act3 spawn timelines + data-derived clear windows; needs the fetched
        # per-level files (tools/fetch_act3_levels.py), so degrade gracefully.
        level_dir = os.path.join(gamedata_dir, "levels", "activities", "act3autochess")
        if os.path.isdir(level_dir):
            from build_act3_waves import build as build_waves_doc, DEFAULT_OUT as WAVES_OUT
            waves_doc = build_waves_doc()
            with open(WAVES_OUT, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(waves_doc, fh, ensure_ascii=False, indent=2)
            print("act3 waves rebuilt: %d levels -> %s" %
                  (waves_doc["_meta"]["level_count"], os.path.basename(WAVES_OUT)))
        else:
            print("SKIP act3_waves: run 'python tools/fetch_act3_levels.py' first.")
    else:
        print("SKIP enemy_catalog/enemy_names: run 'python tools/fetch_game_data.py' "
              "to fetch activity_table/enemy_handbook_table/enemy_database first.")

if __name__ == "__main__":
    main()
