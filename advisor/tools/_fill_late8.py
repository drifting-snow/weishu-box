# -*- coding: utf-8 -*-
"""Fill every lineup late stage to exactly 8 units from operators.json + bonds."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data"
PATH = ROOT / "lineups.json"


def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    ops_list = json.loads((ROOT / "operators.json").read_text(encoding="utf-8"))
    ops = {o["name"]: o for o in ops_list}
    bs = json.loads((ROOT / "bonds_structured.json").read_text(encoding="utf-8"))

    bond_ops: dict[str, list[str]] = {}
    bond_act: dict[str, int] = {}
    for b in bs["core"] + bs["attached"]:
        name = b["name"]
        pool = [n for n in (b.get("operators") or []) if n in ops]
        if not pool:
            pool = [n for n, o in ops.items() if name in (o.get("bonds") or [])]
        bond_ops[name] = pool
        bond_act[name] = int(b.get("activation_need") or 0)

    prefer = {
        "arts_anti_stealth": {
            "core_targets": {"奥术": 3},
            "prefer": ["艾雅法拉", "流明", "褐果", "薇薇安娜", "棘刺", "Miss.Christine"],
        },
        "physical_pierce_kazimierz": {
            "core_targets": {"精准": 3, "卡西米尔": 6},
            "prefer": ["玛恩纳", "瑕光", "远牙", "灰喉", "野鬃", "锏", "砾"],
        },
        "dot_iberia_ursus": {
            "core_targets": {"伊比利亚": 3, "乌萨斯": 3},
            "prefer": ["棘刺", "蓝毒", "深巡", "折桠", "乌啾", "赫拉格", "真理", "烈夏"],
        },
        "bulwark_sustain": {
            "core_targets": {"坚守": 3, "聚合": 3},
            "prefer": ["塞雷娅", "蛇屠箱", "夜莺", "流明", "深巡", "车尔尼", "泡泡", "涤火杰西卡"],
        },
        "economy_investor_miracle": {
            "core_targets": {"投资人": 3, "奇迹": 2, "远见": 2},
            "prefer": ["山", "可露希尔", "锡人", "维娜·维多利亚", "耶拉", "星极", "空弦", "凯瑟琳"],
        },
        "growth_aegir_devour": {
            "core_targets": {"阿戈尔": 6},
            "prefer": ["斯卡蒂", "归溟幽灵鲨", "深巡", "歌蕾蒂娅", "幽灵鲨", "瑰盐"],
        },
        "yan_elemental": {
            "core_targets": {"炎": 6},
            "prefer": ["仇白", "余", "拜松", "风絮", "老鲤", "乌有", "矩"],
        },
        "sargon_quicksand": {
            "core_targets": {"萨尔贡": 6},
            "prefer": ["异客", "泡泡", "莎草", "卡涅利安", "艾丝黛尔"],
        },
        "victoria_equip": {
            "core_targets": {"维多利亚": 6},
            "prefer": ["涤火杰西卡", "哈洛德", "Miss.Christine", "慕斯", "水灯心", "白铁"],
        },
        "kjerag_freeze": {
            "core_targets": {"谢拉格": 6},
            "prefer": ["雪猎", "极光", "角峰", "初雪", "灵知", "耶拉", "哈洛德"],
        },
        "siracusa_anomaly": {
            "core_targets": {"叙拉古": 6},
            "prefer": ["奥斯塔", "斥罪", "伺夜", "忍冬", "复奏"],
        },
        "leithanien_summon": {
            "core_targets": {"莱塔尼亚": 6},
            "prefer": ["艾雅法拉", "黑键", "车尔尼", "卡涅利安", "折光", "逻各斯"],
        },
        "tiaoe_mowang_flex": {
            "core_targets": {"调和": 1},
            "prefer": ["薇薇安娜", "角峰", "斥罪", "老鲤", "圣聆初雪", "逻各斯", "山"],
        },
    }

    def role_of(name: str, lineup: dict) -> str:
        if name in (lineup.get("carry") or []):
            return "carry"
        if name in (lineup.get("tank") or []):
            return "tank"
        if name in (lineup.get("heal") or []):
            return "heal"
        for sk in ("late", "mid", "early"):
            for u in ((lineup.get("stages") or {}).get(sk) or {}).get("units") or []:
                if u.get("name") == name and u.get("role"):
                    return str(u["role"])
        prof = (ops.get(name) or {}).get("prof") or ""
        if "医疗" in prof:
            return "heal"
        if "重装" in prof:
            return "tank"
        if "辅助" in prof:
            return "support"
        return "carry"

    def unit_entry(name: str, lineup: dict, note: str) -> dict:
        o = ops[name]
        return {
            "name": name,
            "tier": int(o.get("shop_tier") or 1),
            "role": role_of(name, lineup),
            "note": note,
        }

    def bond_count(names: list[str], bond: str) -> int:
        return sum(1 for n in names if bond in ((ops.get(n) or {}).get("bonds") or []))

    def pick_from(pool: list[str], chosen: list[str], need_n: int, pref: list[str]) -> list[str]:
        out: list[str] = []
        ordered: list[str] = []
        for n in pref:
            if n in pool and n not in chosen and n not in ordered:
                ordered.append(n)
        for n in pool:
            if n not in chosen and n not in ordered:
                ordered.append(n)
        for n in ordered:
            if len(out) >= need_n:
                break
            out.append(n)
        return out

    summary = []
    for L in data["lineups"]:
        lid = L["id"]
        stages = L["stages"]
        cfg = prefer.get(lid, {})
        pref_names = [n for n in cfg.get("prefer", []) if n in ops]
        core_targets = dict(cfg.get("core_targets") or {})
        for c in L.get("core_bonds") or []:
            core_targets.setdefault(c, bond_act.get(c) or 1)

        chosen: list[str] = []
        for u in stages["late"].get("units") or []:
            n = u.get("name")
            if n in ops and n not in chosen:
                chosen.append(n)
        for lst in (L.get("carry") or []), (L.get("tank") or []), (L.get("heal") or []):
            for n in lst:
                if n in ops and n not in chosen:
                    chosen.append(n)
        for sk in ("mid", "early"):
            for u in (stages.get(sk) or {}).get("units") or []:
                n = u.get("name")
                if n in ops and n not in chosen:
                    chosen.append(n)

        for bond, target in core_targets.items():
            have = bond_count(chosen, bond)
            if have >= target:
                continue
            pool = bond_ops.get(bond) or [
                n for n, o in ops.items() if bond in (o.get("bonds") or [])
            ]
            for n in pick_from(pool, chosen, target - have, pref_names):
                if len(chosen) >= 8:
                    break
                chosen.append(n)

        for bond in L.get("splash_bonds") or []:
            if len(chosen) >= 8:
                break
            if bond_count(chosen, bond) >= 1:
                continue
            pool = bond_ops.get(bond) or [
                n for n, o in ops.items() if bond in (o.get("bonds") or [])
            ]
            for n in pick_from(pool, chosen, 1, pref_names):
                if len(chosen) >= 8:
                    break
                chosen.append(n)

        for n in pref_names:
            if len(chosen) >= 8:
                break
            if n not in chosen:
                chosen.append(n)

        pad: list[str] = []
        for c in (L.get("core_bonds") or []) + (L.get("splash_bonds") or []):
            pad.extend(bond_ops.get(c) or [])
        for n in pad:
            if len(chosen) >= 8:
                break
            if n in ops and n not in chosen:
                chosen.append(n)

        # Ensure activation: rebuild front-loaded by core pools if needed
        def activation_fails(names: list[str]) -> list[str]:
            bad = []
            for c in L.get("core_bonds") or []:
                act = bond_act.get(c) or 1
                if bond_count(names, c) < act:
                    bad.append(f"{c}:{bond_count(names, c)}<act{act}")
            return bad

        fails = activation_fails(chosen[:8] if len(chosen) >= 8 else chosen)
        if fails or len(chosen) < 8:
            chosen2: list[str] = []
            for c in L.get("core_bonds") or []:
                act = max(bond_act.get(c) or 1, core_targets.get(c, 1))
                # for multi-core, don't over-claim beyond remaining slots
                pool = bond_ops.get(c) or []
                for n in chosen:
                    if n not in chosen2 and c in ((ops.get(n) or {}).get("bonds") or []):
                        chosen2.append(n)
                need = max(0, min(act, 8 - len(chosen2)) - 0)
                # ensure at least activation_need
                need = max(0, (bond_act.get(c) or 1) - bond_count(chosen2, c))
                for n in pick_from(pool, chosen2, need, pref_names):
                    chosen2.append(n)
            for n in chosen + pref_names + pad:
                if len(chosen2) >= 8:
                    break
                if n in ops and n not in chosen2:
                    chosen2.append(n)
            chosen = chosen2

        if len(chosen) < 8:
            raise SystemExit(f"FAILED {lid}: only {len(chosen)} -> {chosen}")
        chosen = chosen[:8]
        fails = activation_fails(chosen)
        if fails:
            # last resort: force-add activation members even if displacing splash pad
            forced: list[str] = []
            for c in L.get("core_bonds") or []:
                act = bond_act.get(c) or 1
                pool = bond_ops.get(c) or []
                for n in pick_from(pool, forced, act, pref_names + chosen):
                    forced.append(n)
            for n in chosen:
                if n not in forced:
                    forced.append(n)
            for n in pref_names + pad:
                if len(forced) >= 8:
                    break
                if n in ops and n not in forced:
                    forced.append(n)
            chosen = forced[:8]
            fails = activation_fails(chosen)
            if fails:
                raise SystemExit(f"ACTIVATION FAIL {lid}: {fails} names={chosen}")

        old_notes = {
            u["name"]: u.get("note", "") for u in stages["late"].get("units") or []
        }
        new_units = []
        for n in chosen:
            note = old_notes.get(n)
            if not note:
                bonds = "/".join((ops[n].get("bonds") or [])[:3])
                note = f"满编补位 · {bonds}"
            new_units.append(unit_entry(n, L, note))
        stages["late"]["units"] = new_units
        stages["late"]["pop"] = "8"
        goal = (stages["late"].get("goal") or "").rstrip("。； ")
        if "板位满编" not in goal:
            stages["late"]["goal"] = (goal + "；板位满编 8 人。") if goal else "板位满编 8 人。"
        for sk in ("early", "mid"):
            st = stages.get(sk) or {}
            if not st:
                continue
            n = len(st.get("units") or [])
            st["pop"] = str(n)
            st["plan_fielded"] = n

        splash_hit = [
            s for s in (L.get("splash_bonds") or []) if bond_count(chosen, s) > 0
        ]
        if splash_hit:
            L["splash_bonds"] = splash_hit

        counts = {c: bond_count(chosen, c) for c in (L.get("core_bonds") or [])}
        summary.append(
            {
                "id": lid,
                "name": L["name"],
                "late": chosen,
                "core_counts": counts,
                "splash": L.get("splash_bonds"),
            }
        )
        print(lid, chosen, counts)

    meta = data.setdefault("_meta", {})
    meta["population"] = (
        "游戏板位恒 8。early/mid 的 pop=计划上场人数（过渡子集）；"
        "late.pop 恒为 8（满编）。勿把 early/mid 数字当成解锁人口。"
    )
    meta["board_cap"] = 8
    meta["late_fill"] = (
        "late exactly 8 from operators.json + bonds_structured; "
        "core_bonds meet activation_need; early/mid kept as transition subsets"
    )
    ver = str(meta.get("version") or "1.0")
    if "+late8" not in ver:
        meta["version"] = ver + "+late8"

    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", PATH)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
