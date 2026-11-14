# -*- coding: utf-8 -*-
# Validate data/lineups.json against the real dataset: names, tiers, bonds, enemy keys.
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.chdir(Path(__file__).resolve().parents[1])

ops = {o["name"]: o for o in json.load(open("data/operators.json", encoding="utf-8"))}
bonds_doc = json.load(open("data/bonds_structured.json", encoding="utf-8"))
valid_bonds = {b["name"] for b in bonds_doc["core"]} | {b["name"] for b in bonds_doc["attached"]}
enemy_keys = set(json.load(open("data/enemy_traits.json", encoding="utf-8"))["enemy_types"].keys())
lu = json.load(open("data/lineups.json", encoding="utf-8"))

errors, warnings = [], []
seen_ids = set()
for L in lu["lineups"]:
    lid = L["id"]
    if lid in seen_ids: errors.append(f"{lid}: 重复 id")
    seen_ids.add(lid)
    # bonds valid
    for b in L.get("core_bonds", []) + L.get("splash_bonds", []):
        if b not in valid_bonds: errors.append(f"{lid}: 未知羁绊 {b}")
    for k in L.get("counters", []) + L.get("weak", []):
        if k not in enemy_keys: errors.append(f"{lid}: 未知敌人 key {k}")
    # stages
    all_names = []
    for stage in ("early", "mid", "late"):
        st = L["stages"][stage]
        units = st["units"]
        if not (3 <= len(units) <= 6):
            warnings.append(f"{lid}/{stage}: 单位数 {len(units)} 不在 3-6")
        for u in units:
            n = u["name"]; all_names.append(n)
            if n not in ops:
                errors.append(f"{lid}/{stage}: 干员不存在 '{n}'")
                continue
            real_t = ops[n].get("shop_tier")
            if u["tier"] != real_t:
                errors.append(f"{lid}/{stage}: {n} 本数标注 {u['tier']} != 数据集 {real_t}")
    # carry/tank/heal names exist
    for grp in ("carry", "tank", "heal"):
        for n in L.get(grp, []):
            if n not in ops: errors.append(f"{lid}: {grp} 引用不存在干员 {n}")
    # tier progression should be non-decreasing overall (early low -> late high)
    tiers = [ops[n]["shop_tier"] for n in all_names if n in ops]
    early_t = [u["tier"] for u in L["stages"]["early"]["units"]]
    late_t = [u["tier"] for u in L["stages"]["late"]["units"]]
    if max(late_t) < max(early_t):
        warnings.append(f"{lid}: 大成本数没有随阶段提升")
    # every lineup should have at least one carry or tank
    if not L.get("carry") and not L.get("tank"):
        errors.append(f"{lid}: 既无 carry 也无 tank")

print("阵容数:", len(lu["lineups"]))
print("archetype 分布:", {})
from collections import Counter
print(Counter(L["archetype"] for L in lu["lineups"]))
print("\n错误:", len(errors))
for e in errors: print("  ✗", e)
print("警告:", len(warnings))
for w in warnings: print("  !", w)
print("\n结果:", "全部通过 ✓" if not errors else "存在错误，需修正")
