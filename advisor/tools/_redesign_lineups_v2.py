# -*- coding: utf-8 -*-
"""Full lineup redesign from weishu-bonds-mechanics: 3/6 race, splash, off-board."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data"
PATH = ROOT / "lineups.json"
OFF_BOARD = {"远见", "奇迹", "投资人"}
RACIAL = {
    "炎",
    "萨尔贡",
    "维多利亚",
    "谢拉格",
    "阿戈尔",
    "叙拉古",
    "卡西米尔",
    "乌萨斯",
    "伊比利亚",
    "莱塔尼亚",
}


def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    ops = {
        o["name"]: o
        for o in json.loads((ROOT / "operators.json").read_text(encoding="utf-8"))
    }
    bs = json.loads((ROOT / "bonds_structured.json").read_text(encoding="utf-8"))

    bond_meta: dict[str, dict] = {}
    for b in bs["core"] + bs["attached"]:
        name = b["name"]
        act = int(b.get("activation_need") or 0)
        dist = [
            int(m["threshold"])
            for m in (b.get("milestones") or [])
            if m.get("trigger_type") == "distinct_operator"
            and isinstance(m.get("threshold"), int)
        ]
        max_n = max([act] + dist) if (act or dist) else act
        bond_meta[name] = {
            "activation_need": act,
            "distinct_tiers": sorted(set(([act] if act else []) + dist)),
            "display_max": max_n,
            "off_board": "整备区" in (b.get("base_effect") or ""),
            "racial": name in RACIAL,
        }

    def bonds(n: str) -> list[str]:
        return list((ops.get(n) or {}).get("bonds") or [])

    def U(n: str, role: str | None = None, note: str = "") -> dict:
        assert n in ops, n
        o = ops[n]
        prof = o.get("prof") or ""
        if role is None:
            role = (
                "heal"
                if "医疗" in prof
                else "tank"
                if "重装" in prof
                else "support"
                if ("辅助" in prof or "特种" in prof or "先锋" in prof)
                else "carry"
            )
        off = [b for b in bonds(n) if b in OFF_BOARD]
        tag = ("场下可激活·" + "/".join(off) + " · ") if off else ""
        return {
            "name": n,
            "tier": int(o.get("shop_tier") or 1),
            "role": role,
            "note": note or (tag + "/".join(bonds(n)[:3])),
            "off_board_ok": bool(off),
        }

    def counts(names: list[str], focus: list[str]) -> dict:
        c: Counter[str] = Counter()
        for n in names:
            for b in bonds(n):
                c[b] += 1
        out = {}
        for b in focus:
            if c.get(b):
                out[b] = c[b]
        for b, n in c.most_common():
            if b not in out:
                out[b] = n
        return out

    def bond_progress(names: list[str], focus: list[str]) -> dict:
        c = counts(names, focus)
        prog = {}
        for b, n in c.items():
            meta = bond_meta.get(b) or {}
            mx = int(meta.get("display_max") or n)
            act = int(meta.get("activation_need") or 0)
            prog[b] = {
                "n": n,
                "max": mx,
                "act": act,
                "tiers": meta.get("distinct_tiers") or ([act] if act else []),
                "off_board": bool(meta.get("off_board")),
                "label": f"{b}{n}/{mx}",
            }
        return prog

    def race_n(names: list[str], race: str) -> int:
        return sum(1 for n in names if race in bonds(n))

    def apply(L: dict, early, mid, late, reserve, splash, fantasy=None, tips=None):
        assert 4 <= len(early) <= 6, (L["id"], len(early))
        assert len(mid) == 8 and len(late) == 8
        e_names = [u["name"] for u in early]
        m_names = [u["name"] for u in mid]
        assert set(e_names) <= set(m_names), (L["id"], set(e_names) - set(m_names))
        for u in early + mid + late + reserve:
            assert u["name"] in ops

        # race cap
        for race in RACIAL:
            for label, names in (
                ("mid", m_names),
                ("late", [u["name"] for u in late]),
            ):
                n = race_n(names, race)
                assert n <= 6, (L["id"], label, race, n, names)

        L["splash_bonds"] = splash
        if fantasy:
            L["fantasy"] = fantasy
        if tips:
            L["key_tips"] = tips
        L["off_board_bonds"] = [b for b in splash + list(L.get("core_bonds") or []) if b in OFF_BOARD]
        # unique
        seen = set()
        L["off_board_bonds"] = [b for b in L["off_board_bonds"] if not (b in seen or seen.add(b))]
        L["reserve_plan"] = reserve
        L["bond_thresholds"] = {
            b: {
                "activation_need": bond_meta[b]["activation_need"],
                "distinct_tiers": bond_meta[b]["distinct_tiers"],
                "display_max": bond_meta[b]["display_max"],
                "off_board": bond_meta[b]["off_board"],
            }
            for b in list(L.get("core_bonds") or []) + splash
            if b in bond_meta
        }

        focus = list(L.get("core_bonds") or []) + splash
        for sk, units, goal in (
            (
                "early",
                early,
                f"过渡 {len(early)}：核心先冲激活档 + 小溅射/场下经济。",
            ),
            (
                "mid",
                mid,
                f"满编 8（含 early {len(early)}）：冲 3→6 或附加 2→3；种族≤6。",
            ),
            (
                "late",
                late,
                "满编 8：核心达大成档(≤6) + 角色位；经济可转整备区。",
            ),
        ):
            names = [u["name"] for u in units]
            L["stages"][sk]["units"] = units
            L["stages"][sk]["pop"] = str(len(units))
            L["stages"][sk]["plan_fielded"] = len(units)
            L["stages"][sk]["bond_counts"] = counts(names, focus)
            L["stages"][sk]["bond_progress"] = bond_progress(names, focus)
            L["stages"][sk]["goal"] = goal

        L["carry"] = [u["name"] for u in late if u["role"] == "carry"][:4]
        L["tank"] = [u["name"] for u in late if u["role"] == "tank"][:3]
        L["heal"] = [u["name"] for u in late if u["role"] == "heal"][:3]

        # core activation check on late (+ reserve for off-board cores)
        late_n = [u["name"] for u in late]
        res_n = [u["name"] for u in reserve]
        for c in L.get("core_bonds") or []:
            act = bond_meta[c]["activation_need"]
            have = race_n(late_n, c) if c not in OFF_BOARD else race_n(late_n + res_n, c)
            # for off-board, count late+reserve; for on-board racial use late only
            if c in OFF_BOARD:
                have = sum(1 for n in late_n + res_n if c in bonds(n))
            else:
                have = sum(1 for n in late_n if c in bonds(n))
            if have < act:
                raise SystemExit(f"{L['id']} core {c} {have}<act{act}")

        print(
            L["id"],
            "e",
            e_names,
            "late_prog",
            {k: v["label"] for k, v in L["stages"]["late"]["bond_progress"].items() if k in focus},
        )

    # -------- curated redesigns (preserve ids / counters / weak / archetype) --------
    PLANS = {
        "arts_anti_stealth": dict(
            splash=["聚合", "莱塔尼亚", "奇迹"],
            early=[
                U("卡达", "carry", "奥术种子 → 冲 2/3"),
                U("Miss.Christine", "carry", "奥术低本"),
                U("伊桑", "control", "奥术控"),
                U("褐果", "heal", "聚合 2/3"),
                U("星极", "econ", "奇迹场下 2/2"),
            ],
            mid_extra=[
                U("艾雅法拉", "carry", "奥术主C 冲 3/3 反隐"),
                U("流明", "heal", "聚合奶"),
                U("霍尔海雅", "carry", "奥术"),
            ],
            late=[
                U("逻各斯", "carry", "奥术大核"),
                U("艾雅法拉", "carry", "法C · 奥术 3/3"),
                U("夕", "carry", "奥术输出"),
                U("流明", "heal", "聚合奶"),
                U("夜莺", "heal", "聚合群奶"),
                U("纯烬艾雅法拉", "heal", "聚合/远见"),
                U("褐果", "heal", "聚合 3/3"),
                U("车尔尼", "tank", "莱塔尼亚坦"),
            ],
            reserve=[U("星极", "econ", "整备区·奇迹"), U("云迹", "econ", "整备区·奇迹")],
            fantasy="奥术 2 激活 / 3 人里程碑解锁反隐+削法抗（counters）。战场奥术刚好 3/3，聚合奶坦，奇迹挂整备区。",
            tips=[
                "early 卡达+Christine+伊桑冲奥术 3/3 反隐",
                "奇迹用星极/云迹放整备区，不占板",
                "late 奥术保持 3/3 即可，勿堆到 6",
            ],
        ),
        "physical_pierce_kazimierz": dict(
            splash=["助力", "突袭", "奇迹"],
            early=[
                U("灰喉", "carry", "精准种子"),
                U("雪猎", "carry", "精准"),
                U("野鬃", "support", "卡西米尔/助力"),
                U("承曦格雷伊", "support", "精准"),
                U("星极", "econ", "奇迹场下"),
            ],
            mid_extra=[
                U("空弦", "carry", "精准 3/3 穿甲"),
                U("远牙", "carry", "卡西米尔/精准"),
                U("瑕光", "tank", "卡西米尔坦"),
            ],
            late=[
                U("耀骑士临光", "carry", "卡西米尔主C"),
                U("玛恩纳", "carry", "卡西米尔"),
                U("迷迭香", "carry", "精准炮"),
                U("远牙", "carry", "穿甲"),
                U("瑕光", "tank", "坦/突袭"),
                U("空弦", "carry", "精准 3/3"),
                U("野鬃", "support", "助力"),
                U("砾", "tank", "卡西米尔/不屈"),
            ],
            reserve=[U("星极", "econ", "整备区·奇迹")],
            fantasy="精准 3 穿甲 + 卡西米尔 3→6 真伤里程碑，克折射/飞行。奇迹场下。",
            tips=["mid 凑精准 3/3", "late 卡西米尔 6/6 大成", "星极整备区奇迹"],
        ),
        "dot_iberia_ursus": dict(
            splash=["聚合", "奇迹", "不屈"],
            early=[
                U("蓝毒", "carry", "伊比利亚"),
                U("烈夏", "carry", "乌萨斯"),
                U("折桠", "tank", "乌萨斯/不屈"),
                U("莎草", "heal", "聚合"),
                U("复奏", "econ", "奇迹场下"),
            ],
            mid_extra=[
                U("棘刺", "carry", "伊比利亚冲 3"),
                U("乌啾", "heal", "乌萨斯/聚合"),
                U("深巡", "tank", "伊比利亚坦"),
            ],
            late=[
                U("引星棘刺", "carry", "伊比利亚核"),
                U("棘刺", "carry", "DOT"),
                U("塔露拉", "carry", "乌萨斯"),
                U("怒潮凛冬", "carry", "乌萨斯/奇迹"),
                U("蓝毒", "carry", "伊比利亚"),
                U("流明", "heal", "伊比利亚奶"),
                U("深巡", "tank", "坦"),
                U("折桠", "tank", "不屈"),
            ],
            reserve=[U("复奏", "econ", "整备区·奇迹"), U("云迹", "econ", "整备区·奇迹")],
            fantasy="双核心各冲 3 激活；伊比利亚/乌萨斯大成需取舍。板位给 DOT+坦奶，奇迹场下。",
            tips=["双核先各 3/6 激活", "勿强求双 6", "复奏整备区奇迹"],
        ),
        "bulwark_sustain": dict(
            splash=["不屈", "协防干员", "远见", "奇迹"],
            early=[
                U("角峰", "tank", "坚守"),
                U("蛇屠箱", "tank", "坚守"),
                U("褐果", "heal", "聚合"),
                U("泡泡", "tank", "坚守"),
                U("渡桥", "econ", "远见场下"),
            ],
            mid_extra=[
                U("塞雷娅", "tank", "铁壁"),
                U("夜莺", "heal", "聚合 3/3"),
                U("深巡", "tank", "不屈"),
            ],
            late=[
                U("塞雷娅", "tank", "主坦"),
                U("机械师", "tank", "坚守 3/3"),
                U("森蚺", "tank", "不屈肉"),
                U("纯烬艾雅法拉", "heal", "聚合/远见"),
                U("夜莺", "heal", "群奶"),
                U("流明", "heal", "奶"),
                U("斥罪", "tank", "不屈"),
                U("蛇屠箱", "tank", "坚守"),
            ],
            reserve=[U("渡桥", "econ", "整备区·远见"), U("星极", "econ", "整备区·奇迹")],
            fantasy="坚守/聚合冲 3 人档承伤+庇护；经济远见/奇迹整备区。",
            tips=["坚守与聚合都冲 3/3", "远见渡桥放整备区"],
        ),
        "economy_investor_miracle": dict(
            splash=["助力", "迅捷"],
            early=[
                U("锡人", "econ", "投资人 · 场下"),
                U("星极", "econ", "奇迹场下"),
                U("云迹", "econ", "奇迹场下"),
                U("渡桥", "econ", "远见场下"),
                U("野鬃", "support", "助力战力"),
            ],
            mid_extra=[
                U("山", "tank", "投资人战力"),
                U("空弦", "carry", "远见输出"),
                U("可露希尔", "econ", "投资人"),
            ],
            late=[
                U("山", "tank", "投资人主战"),
                U("老鲤", "support", "投资人"),
                U("可露希尔", "econ", "投资人 3/3"),
                U("凛御银灰", "support", "投资人"),
                U("维娜·维多利亚", "carry", "奇迹叠层"),
                U("空弦", "carry", "远见"),
                U("凯瑟琳", "support", "远见"),
                U("耶拉", "econ", "奇迹整备"),
            ],
            reserve=[
                U("锡人", "econ", "整备区·投资人"),
                U("星极", "econ", "整备区·奇迹"),
                U("渡桥", "econ", "整备区·远见"),
            ],
            fantasy="三经济盟约均可整备区激活：投资人 3、奇迹 2、远见 2。战场放战力，低本经济挂后面。",
            tips=["锡人/星极/渡桥优先整备区", "上场山+可露希尔+凛御银灰凑投资人", "别为经济占满 8 格"],
        ),
        "growth_aegir_devour": dict(
            splash=["聚合", "突袭", "奇迹"],
            early=[
                U("幽灵鲨", "carry", "阿戈尔种子"),
                U("深巡", "tank", "阿戈尔"),
                U("瑰盐", "heal", "聚合"),
                U("安哲拉", "support", "助力低本"),
                U("星极", "econ", "奇迹场下"),
            ],
            mid_extra=[
                U("斯卡蒂", "carry", "阿戈尔/突袭"),
                U("归溟幽灵鲨", "carry", "吞噬"),
                U("歌蕾蒂娅", "carry", "阿戈尔冲 3→6"),
            ],
            late=[
                U("乌尔比安", "carry", "阿戈尔大核"),
                U("浊心斯卡蒂", "heal", "阿戈尔奶C"),
                U("克莱门莎", "carry", "阿戈尔"),
                U("斯卡蒂", "carry", "突袭"),
                U("归溟幽灵鲨", "carry", "吞噬"),
                U("深巡", "tank", "坦"),
                U("流明", "heal", "聚合"),
                U("瑰盐", "heal", "奶"),
            ],
            reserve=[U("星极", "econ", "整备区·奇迹")],
            fantasy="阿戈尔 3→6 复活里程碑；聚合奶+奇迹场下。",
            tips=["late 阿戈尔 6/6", "第 7–8 格奶，不塞第 7 个阿戈尔"],
        ),
        "yan_elemental": dict(
            splash=["聚合", "坚守", "远见", "奇迹"],
            early=[
                U("拜松", "tank", "炎/坚守"),
                U("矩", "support", "炎"),
                U("乌有", "carry", "炎冲 3"),
                U("风絮", "heal", "炎/聚合"),
                U("渡桥", "econ", "远见场下"),
            ],
            mid_extra=[
                U("余", "tank", "炎坦"),
                U("仇白", "carry", "炎输出 · 炎满 6"),
                U("褐果", "heal", "聚合奶 · 非炎"),
            ],
            late=[
                U("烛煌", "carry", "炎主C"),
                U("夕", "carry", "炎"),
                U("黍", "support", "炎/远见"),
                U("仇白", "carry", "输出"),
                U("余", "tank", "坦"),
                U("风絮", "heal", "炎/聚合"),
                U("褐果", "heal", "聚合溅射"),
                U("星极", "econ", "奇迹场下可转整备"),
            ],
            reserve=[U("渡桥", "econ", "整备区·远见"), U("星极", "econ", "整备区·奇迹")],
            fantasy="炎 3→6 元素损伤；余 2 格聚合/奇迹，不塞 8 炎。",
            tips=["late 炎恰好 6/6", "褐果+星极功能位"],
        ),
        "sargon_quicksand": dict(
            splash=["迅捷", "聚合", "精准", "奇迹"],
            early=[
                U("泡泡", "tank", "萨尔贡"),
                U("至简", "carry", "萨尔贡"),
                U("艾丝黛尔", "tank", "萨尔贡冲 3"),
                U("褐果", "heal", "聚合 · 非萨尔贡"),
                U("云迹", "econ", "奇迹场下"),
            ],
            mid_extra=[
                U("卡涅利安", "carry", "萨尔贡/迅捷"),
                U("异客", "carry", "萨尔贡"),
                U("森蚺", "tank", "萨尔贡肉 · 萨满 6"),
            ],
            late=[
                U("真言", "carry", "萨尔贡核"),
                U("鸿雪", "carry", "萨尔贡/精准"),
                U("佩佩", "carry", "萨尔贡"),
                U("异客", "carry", "法伤"),
                U("卡涅利安", "carry", "迅捷"),
                U("森蚺", "tank", "坦"),
                U("流明", "heal", "聚合奶"),
                U("云迹", "econ", "奇迹"),
            ],
            reserve=[U("星极", "econ", "整备区·奇迹")],
            fantasy="萨尔贡 3→6 流沙控制；聚合奶+奇迹，种族≤6。",
            tips=["late 萨尔贡 6/6 + 流明/云迹"],
        ),
        "victoria_equip": dict(
            splash=["奇迹", "助力", "远见", "坚守"],
            early=[
                U("慕斯", "carry", "维多利亚"),
                U("Miss.Christine", "carry", "维多利亚/奥术"),
                U("哈洛德", "heal", "维多利亚奶"),
                U("水灯心", "support", "维多利亚"),
                U("星极", "econ", "奇迹场下"),
            ],
            mid_extra=[
                U("凯瑟琳", "support", "维多利亚/远见"),
                U("涤火杰西卡", "tank", "维多利亚坦 · 维满 6"),
                U("渡桥", "econ", "远见场下 · 非维"),
            ],
            late=[
                U("维娜·维多利亚", "carry", "维多利亚/奇迹核"),
                U("烛煌", "carry", "维多利亚"),
                U("酒神", "carry", "维多利亚"),
                U("涤火杰西卡", "tank", "坦"),
                U("哈洛德", "heal", "奶"),
                U("白铁", "carry", "输出"),
                U("星极", "econ", "奇迹"),
                U("渡桥", "econ", "远见场下"),
            ],
            reserve=[U("渡桥", "econ", "整备区·远见"), U("云迹", "econ", "整备区·奇迹")],
            fantasy="维多利亚 3→6 装备体系；奇迹/远见可整备区。",
            tips=["late 维多利亚 6/6", "渡桥/云迹可整备区"],
        ),
        "kjerag_freeze": dict(
            splash=["精准", "奥术", "奇迹", "灵巧"],
            early=[
                U("角峰", "tank", "谢拉格"),
                U("雪猎", "carry", "谢拉格/精准"),
                U("哈洛德", "heal", "谢拉格奶"),
                U("耶拉", "econ", "奇迹/谢拉格整备"),
                U("承曦格雷伊", "support", "精准"),
            ],
            mid_extra=[
                U("极光", "tank", "谢拉格"),
                U("初雪", "carry", "谢拉格控 · 谢满 6"),
                U("星极", "econ", "奇迹场下 · 非谢"),
            ],
            late=[
                U("圣聆初雪", "carry", "谢拉格/奥术"),
                U("凛御银灰", "support", "谢拉格/投资人"),
                U("锏", "carry", "谢拉格枢纽"),
                U("雪猎", "carry", "精准"),
                U("极光", "tank", "坦"),
                U("哈洛德", "heal", "奶"),
                U("星极", "econ", "奇迹"),
                U("Miss.Christine", "carry", "奥术溅射 · 非谢"),
            ],
            reserve=[U("耶拉", "econ", "整备区·奇迹"), U("云迹", "econ", "整备区·奇迹")],
            fantasy="谢拉格 3→6 冻结控制；精准/奥术溅射，奇迹场下。",
            tips=["late 谢拉格 6/6", "耶拉整备区奇迹"],
        ),
        "siracusa_anomaly": dict(
            splash=["精准", "迅捷", "奇迹", "不屈"],
            early=[
                U("奥斯塔", "carry", "叙拉古"),
                U("复奏", "econ", "叙拉古/奇迹场下"),
                U("忍冬", "carry", "叙拉古/迅捷"),
                U("砾", "tank", "不屈"),
                U("星极", "econ", "奇迹场下"),
            ],
            mid_extra=[
                U("伺夜", "carry", "叙拉古/精准"),
                U("斥罪", "tank", "叙拉古不屈"),
                U("安洁莉娜", "support", "叙拉古/奇迹"),
            ],
            late=[
                U("荒芜拉普兰德", "carry", "叙拉古主C"),
                U("贝洛内", "carry", "叙拉古"),
                U("斥罪", "tank", "坦"),
                U("忍冬", "carry", "迅捷"),
                U("伺夜", "carry", "精准"),
                U("安洁莉娜", "support", "奇迹"),
                U("砾", "tank", "不屈溅射"),
                U("星极", "econ", "奇迹 · 叙满 6"),
            ],
            reserve=[U("复奏", "econ", "整备区·奇迹"), U("星极", "econ", "整备区·奇迹")],
            fantasy="叙拉古 3→6 异常真伤；精准/不屈溅射，奇迹场下。",
            tips=["late 叙拉古 6/6 + 砾", "复奏可整备区"],
        ),
        "leithanien_summon": dict(
            splash=["奥术", "聚合", "精准", "奇迹"],
            early=[
                U("地灵", "support", "莱塔尼亚"),
                U("折光", "carry", "莱塔尼亚"),
                U("车尔尼", "tank", "莱塔尼亚/坚守"),
                U("复奏", "econ", "莱塔尼亚/奇迹场下"),
                U("褐果", "heal", "聚合"),
            ],
            mid_extra=[
                U("卡涅利安", "carry", "莱塔尼亚"),
                U("黑键", "carry", "莱塔尼亚/精准 · 莱满 6"),
                U("星极", "econ", "奇迹场下 · 非莱"),
            ],
            late=[
                U("纯烬艾雅法拉", "heal", "莱塔尼亚奶核"),
                U("薇薇安娜", "carry", "莱塔尼亚枢纽"),
                U("锏", "carry", "莱塔尼亚/卡"),
                U("艾雅法拉", "carry", "奥术"),
                U("黑键", "carry", "精准"),
                U("车尔尼", "tank", "坦"),
                U("褐果", "heal", "聚合"),
                U("星极", "econ", "奇迹"),
            ],
            reserve=[U("复奏", "econ", "整备区·奇迹"), U("渡桥", "econ", "整备区·远见")],
            fantasy="莱塔尼亚 3→6 召唤里程碑；奥术/聚合溅射，奇迹场下。",
            tips=["late 莱塔尼亚 6/6", "复奏/渡桥整备区"],
        ),
        "tiaoe_mowang_flex": dict(
            splash=["卡西米尔", "莱塔尼亚", "谢拉格", "奥术", "奇迹", "投资人"],
            early=[
                U("复奏", "econ", "莱/奇迹场下枢纽"),
                U("卡涅利安", "carry", "莱/迅捷"),
                U("野鬃", "support", "卡西米尔/助力"),
                U("哈洛德", "heal", "谢拉格奶"),
                U("星极", "econ", "奇迹场下"),
                U("Miss.Christine", "carry", "奥术种子"),
            ],
            mid_extra=[
                U("魔王", "heal", "调和 1/1 · 核心激活+1"),
                U("锏", "carry", "卡/莱/谢三栖"),
            ],
            late=[
                U("魔王", "heal", "调和"),
                U("锏", "carry", "三栖主C"),
                U("薇薇安娜", "carry", "卡/奥/莱"),
                U("凛御银灰", "support", "投资人/谢"),
                U("圣聆初雪", "carry", "奥/谢"),
                U("瑕光", "tank", "卡西米尔坦"),
                U("山", "tank", "投资人战力"),
                U("复奏", "econ", "莱/奇迹"),
            ],
            reserve=[
                U("星极", "econ", "整备区·奇迹"),
                U("锡人", "econ", "整备区·投资人"),
                U("云迹", "econ", "整备区·奇迹"),
            ],
            fantasy=(
                "调和 1 激活使场上核心盟约激活人数+1。枢纽点亮卡/莱/谢/奥；"
                "投资人/奇迹多余件整备区。不为单一种族堆到 6，靠+1 跨激活线。"
            ),
            tips=[
                "early 复奏+星极场下奇迹",
                "mid 插入魔王+锏",
                "投资人 凛御银灰+山上场，锡人可整备区",
            ],
        ),
    }

    for L in data["lineups"]:
        plan = PLANS[L["id"]]
        early = plan["early"]
        mid = early + plan["mid_extra"]
        # arts late has 6 奥术 — display_max 3, that's fine
        # Fix arts: 奥术 is not racial, cap doesn't apply. Good.
        # yan late: 炎 count — 烛煌夕黍仇白余风絮 = 6, 褐果星极 non — good
        apply(
            L,
            early,
            mid,
            plan["late"],
            plan["reserve"],
            plan["splash"],
            fantasy=plan.get("fantasy"),
            tips=plan.get("tips"),
        )

    meta = data.setdefault("_meta", {})
    meta["version"] = "2.0-mechanics-redesign"
    meta["board_cap"] = 8
    meta["race_cap"] = 6
    meta["population"] = (
        "板位恒 8。early 4–6 冲激活+溅射/场下经济；"
        "mid/late 满 8；种族核心目标 3→6（≤6）；显示 n/max。"
    )
    meta["design_ref"] = "docs/weishu-bonds-mechanics.md + counters.BOND_COUNTERS"
    meta["off_board_bonds"] = sorted(OFF_BOARD)
    meta["stage_curve"] = "early_4to6 → mid_8_includes_early → late_8_race≤6"

    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", PATH)


if __name__ == "__main__":
    main()
