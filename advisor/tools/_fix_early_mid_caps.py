# -*- coding: utf-8 -*-
"""Fix early (~3 race + small splashes), mid splash-flex, never exceed bond max."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data"
PATH = ROOT / "lineups.json"
OFF = {"远见", "奇迹", "投资人"}
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
    bmax: dict[str, int] = {}
    bact: dict[str, int] = {}
    for b in bs["core"] + bs["attached"]:
        act = int(b.get("activation_need") or 0)
        dist = [
            int(m["threshold"])
            for m in (b.get("milestones") or [])
            if m.get("trigger_type") == "distinct_operator"
            and isinstance(m.get("threshold"), int)
        ]
        bact[b["name"]] = act
        bmax[b["name"]] = max([act] + dist) if (act or dist) else act

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
        off = [b for b in bonds(n) if b in OFF]
        tag = ("场下·" + "/".join(off) + " · ") if off else ""
        return {
            "name": n,
            "tier": int(o.get("shop_tier") or 1),
            "role": role,
            "note": note or (tag + "/".join(bonds(n)[:3])),
            "off_board_ok": bool(off),
        }

    def cnt(names: list[str]) -> Counter:
        c: Counter = Counter()
        for n in names:
            for b in bonds(n):
                c[b] += 1
        return c

    def validate(names: list[str], where: str, lid: str) -> None:
        c = cnt(names)
        for b, n in c.items():
            mx = bmax.get(b)
            if mx is not None and n > mx:
                raise SystemExit(f"{lid} {where} OVER {b}{n}/{mx} names={names}")

    def progress(names: list[str], focus: list[str]) -> dict:
        c = cnt(names)
        out = {}
        for b in list(dict.fromkeys(focus + list(c.keys()))):
            n = c.get(b, 0)
            if n <= 0:
                continue
            mx = bmax.get(b, n)
            n = min(n, mx)  # store capped
            out[b] = {
                "n": n,
                "max": mx,
                "act": bact.get(b, 0),
                "off_board": b in OFF,
                "label": f"{b}{n}/{mx}",
            }
        return {b: out[b] for b in out if out[b]["n"] > 0}

    def counts_capped(names: list[str], focus: list[str]) -> dict:
        c = cnt(names)
        out = {}
        for b in focus:
            if c.get(b):
                out[b] = min(c[b], bmax.get(b, c[b]))
        for b, n in c.most_common():
            if b not in out:
                out[b] = min(n, bmax.get(b, n))
        return out

    def apply_stage(L, sk, units, goal):
        names = [u["name"] for u in units]
        focus = list(L.get("core_bonds") or []) + list(L.get("splash_bonds") or [])
        validate(names, sk, L["id"])
        L["stages"][sk]["units"] = units
        L["stages"][sk]["pop"] = str(len(units))
        L["stages"][sk]["plan_fielded"] = len(units)
        L["stages"][sk]["bond_counts"] = counts_capped(names, focus)
        L["stages"][sk]["bond_progress"] = progress(names, focus)
        L["stages"][sk]["goal"] = goal

    # Explicit fixed plans: early ~3 primary race + smalls; mid splash-flex; late race≤6
    # primary race for dual-core: first racial core or None for attached-only
    PLANS = {
        "arts_anti_stealth": {
            "splash": ["聚合", "莱塔尼亚", "奇迹"],
            "early": [
                U("卡达", "carry", "奥术1"),
                U("Miss.Christine", "carry", "奥术2"),
                U("伊桑", "control", "奥术3/3"),
                U("褐果", "heal", "聚合小溅射"),
                U("星极", "econ", "奇迹场下"),
            ],
            "mid": [
                U("卡达", "carry", "奥术"),
                U("Miss.Christine", "carry", "奥术"),
                U("伊桑", "control", "奥术3/3"),
                U("褐果", "heal", "聚合"),
                U("星极", "econ", "奇迹"),
                U("流明", "heal", "聚合/奶 · flex"),
                U("车尔尼", "tank", "莱塔尼亚坦 · flex"),
                U("夜莺", "heal", "聚合3/3 · flex"),
            ],
            "late": [
                U("逻各斯", "carry", "奥术大核"),
                U("艾雅法拉", "carry", "奥术3/3"),
                U("夕", "carry", "奥术"),
                U("流明", "heal", "聚合奶"),
                U("夜莺", "heal", "聚合"),
                U("车尔尼", "tank", "莱坦"),
                U("黑键", "carry", "莱/精准 · 非奥术"),
                U("星极", "econ", "奇迹"),
            ],
            "reserve": [U("星极", "econ", "整备·奇迹"), U("云迹", "econ", "整备·奇迹")],
        },
        "physical_pierce_kazimierz": {
            "splash": ["助力", "突袭", "奇迹"],
            "early": [
                U("灰喉", "carry", "精准1"),
                U("雪猎", "carry", "精准2"),
                U("承曦格雷伊", "support", "精准3/3"),
                U("野鬃", "support", "卡西米尔/助力"),
                U("星极", "econ", "奇迹场下"),
            ],
            "mid": [
                U("灰喉", "carry", "精准"),
                U("雪猎", "carry", "精准"),
                U("承曦格雷伊", "support", "精准3/3"),
                U("野鬃", "support", "卡西/助力"),
                U("星极", "econ", "奇迹"),
                U("瑕光", "tank", "卡西坦 · flex"),
                U("砾", "tank", "不屈flex"),
                U("焰尾", "support", "卡西/迅捷 · 非精准flex"),
            ],
            "late": [
                U("耀骑士临光", "carry", "卡西主C"),
                U("玛恩纳", "carry", "卡西"),
                U("迷迭香", "carry", "精准"),
                U("远牙", "carry", "卡西/精准"),
                U("瑕光", "tank", "坦"),
                U("灰喉", "carry", "精准3/3 · 非空弦超标"),
                U("野鬃", "support", "助力"),
                U("砾", "tank", "卡西6/6"),
            ],
            # late 精准: 迷迭香+远牙+灰喉 = 3/3 (空弦也会精准，勿叠第四)
            "reserve": [U("星极", "econ", "整备·奇迹")],
        },
        "dot_iberia_ursus": {
            "splash": ["聚合", "奇迹", "不屈"],
            "early": [
                U("蓝毒", "carry", "伊比利亚"),
                U("烈夏", "carry", "乌萨斯"),
                U("折桠", "tank", "乌萨斯/不屈 · 双核~3"),
                U("褐果", "heal", "聚合小溅射"),
                U("复奏", "econ", "奇迹场下"),
            ],
            "mid": [
                U("蓝毒", "carry", "伊比"),
                U("烈夏", "carry", "乌萨斯"),
                U("折桠", "tank", "乌萨斯"),
                U("褐果", "heal", "聚合"),
                U("复奏", "econ", "奇迹"),
                U("棘刺", "carry", "伊比冲3"),
                U("深巡", "tank", "伊比坦 · flex"),
                U("流明", "heal", "聚合flex"),
            ],
            "late": [
                U("引星棘刺", "carry", "伊比核"),
                U("棘刺", "carry", "DOT"),
                U("塔露拉", "carry", "乌萨斯"),
                U("怒潮凛冬", "carry", "乌萨斯"),
                U("蓝毒", "carry", "伊比"),
                U("流明", "heal", "奶"),
                U("深巡", "tank", "坦"),
                U("折桠", "tank", "不屈"),
            ],
            "reserve": [U("复奏", "econ", "整备·奇迹"), U("星极", "econ", "整备·奇迹")],
        },
        "bulwark_sustain": {
            "splash": ["不屈", "远见", "奇迹", "聚合"],
            "early": [
                U("角峰", "tank", "坚守1"),
                U("蛇屠箱", "tank", "坚守2"),
                U("泡泡", "tank", "坚守3/3"),
                U("褐果", "heal", "聚合"),
                U("渡桥", "econ", "远见场下"),
            ],
            "mid": [
                U("角峰", "tank", "坚守"),
                U("蛇屠箱", "tank", "坚守"),
                U("泡泡", "tank", "坚守3/3"),
                U("褐果", "heal", "聚合"),
                U("渡桥", "econ", "远见"),
                U("夜莺", "heal", "聚合flex"),
                U("流明", "heal", "聚合3/3 flex"),
                U("星极", "econ", "奇迹flex"),
            ],
            "late": [
                U("塞雷娅", "tank", "主坦/协防"),
                U("机械师", "tank", "坚守/协防"),
                U("蛇屠箱", "tank", "坚守3/3"),
                U("流明", "heal", "聚合"),
                U("褐果", "heal", "聚合"),
                U("纯烬艾雅法拉", "heal", "聚合3/3 · 非夜莺叠协防"),
                U("斥罪", "tank", "不屈"),
                U("森蚺", "tank", "不屈肉"),
            ],
            "reserve": [U("渡桥", "econ", "整备·远见"), U("星极", "econ", "整备·奇迹")],
        },
        "economy_investor_miracle": {
            "splash": ["助力", "迅捷"],
            "early": [
                U("锡人", "econ", "投资人场下"),
                U("星极", "econ", "奇迹1"),
                U("云迹", "econ", "奇迹2/2场下"),
                U("渡桥", "econ", "远见场下"),
                U("野鬃", "support", "助力战力"),
            ],
            "mid": [
                U("锡人", "econ", "投资人"),
                U("星极", "econ", "奇迹"),
                U("云迹", "econ", "奇迹"),
                U("渡桥", "econ", "远见"),
                U("野鬃", "support", "助力"),
                U("山", "tank", "投资人战力"),
                U("空弦", "carry", "远见输出"),
                U("可露希尔", "econ", "投资人3/3"),
            ],
            "late": [
                U("山", "tank", "投资人"),
                U("可露希尔", "econ", "投资人"),
                U("凛御银灰", "support", "投资人3/3"),
                U("维娜·维多利亚", "carry", "奇迹"),
                U("空弦", "carry", "远见"),
                U("凯瑟琳", "support", "远见2/2"),
                U("耶拉", "econ", "奇迹2/2"),
                U("野鬃", "support", "助力"),
            ],
            "reserve": [
                U("锡人", "econ", "整备·投资人"),
                U("星极", "econ", "整备·奇迹"),
                U("渡桥", "econ", "整备·远见"),
            ],
        },
        "growth_aegir_devour": {
            "splash": ["聚合", "突袭", "奇迹"],
            "early": [
                U("幽灵鲨", "carry", "阿戈尔1"),
                U("深巡", "tank", "阿戈尔2"),
                U("歌蕾蒂娅", "carry", "阿戈尔3/6"),
                U("褐果", "heal", "聚合"),
                U("星极", "econ", "奇迹场下"),
            ],
            "mid": [
                U("幽灵鲨", "carry", "阿戈尔"),
                U("深巡", "tank", "阿戈尔"),
                U("歌蕾蒂娅", "carry", "阿戈尔3"),
                U("褐果", "heal", "聚合"),
                U("星极", "econ", "奇迹"),
                U("流明", "heal", "聚合flex"),
                U("夜莺", "heal", "聚合3/3 flex"),
                U("砾", "tank", "不屈flex · 非阿戈尔"),
            ],
            "late": [
                U("乌尔比安", "carry", "阿戈尔大核"),
                U("浊心斯卡蒂", "heal", "阿戈尔"),
                U("克莱门莎", "carry", "阿戈尔"),
                U("斯卡蒂", "carry", "阿戈尔/突袭"),
                U("归溟幽灵鲨", "carry", "阿戈尔"),
                U("深巡", "tank", "阿戈尔6/6"),
                U("流明", "heal", "聚合奶"),
                U("星极", "econ", "奇迹"),
            ],
            "reserve": [U("星极", "econ", "整备·奇迹")],
        },
        "yan_elemental": {
            "splash": ["聚合", "坚守", "远见", "奇迹"],
            "early": [
                U("拜松", "tank", "炎1"),
                U("矩", "support", "炎2"),
                U("乌有", "carry", "炎3/6"),
                U("褐果", "heal", "聚合"),
                U("渡桥", "econ", "远见场下"),
            ],
            "mid": [
                U("拜松", "tank", "炎"),
                U("矩", "support", "炎"),
                U("乌有", "carry", "炎3/6"),
                U("褐果", "heal", "聚合"),
                U("渡桥", "econ", "远见"),
                U("风絮", "heal", "炎/聚合flex"),
                U("流明", "heal", "聚合flex · 非炎"),
                U("星极", "econ", "奇迹flex"),
            ],
            "late": [
                U("烛煌", "carry", "炎主C"),
                U("夕", "carry", "炎"),
                U("黍", "support", "炎/远见"),
                U("仇白", "carry", "炎"),
                U("余", "tank", "炎"),
                U("风絮", "heal", "炎6/6"),
                U("褐果", "heal", "聚合"),
                U("星极", "econ", "奇迹"),
            ],
            "reserve": [U("渡桥", "econ", "整备·远见"), U("星极", "econ", "整备·奇迹")],
        },
        "sargon_quicksand": {
            "splash": ["迅捷", "聚合", "精准", "奇迹"],
            "early": [
                U("泡泡", "tank", "萨尔贡1"),
                U("至简", "carry", "萨尔贡2"),
                U("艾丝黛尔", "tank", "萨尔贡3/6"),
                U("褐果", "heal", "聚合"),
                U("云迹", "econ", "奇迹场下"),
            ],
            "mid": [
                U("泡泡", "tank", "萨尔贡"),
                U("至简", "carry", "萨尔贡"),
                U("艾丝黛尔", "tank", "萨尔贡"),
                U("褐果", "heal", "聚合"),
                U("云迹", "econ", "奇迹"),
                U("流明", "heal", "聚合flex"),
                U("卡涅利安", "carry", "萨/迅捷"),
                U("星极", "econ", "奇迹≤2 — wait duplicate 奇迹"),
            ],
        },
    }

    # Fix sargon mid - can't have 云迹+星极 both 奇迹 if that makes 奇迹>2. 云迹+星极=2 OK.
    PLANS["sargon_quicksand"]["mid"] = [
        U("泡泡", "tank", "萨尔贡"),
        U("至简", "carry", "萨尔贡"),
        U("艾丝黛尔", "tank", "萨尔贡"),
        U("褐果", "heal", "聚合"),
        U("云迹", "econ", "奇迹"),
        U("流明", "heal", "聚合flex"),
        U("卡涅利安", "carry", "萨/迅捷"),
        U("灰喉", "carry", "精准flex"),
    ]
    PLANS["sargon_quicksand"]["late"] = [
        U("真言", "carry", "萨核"),
        U("鸿雪", "carry", "萨/精准"),
        U("佩佩", "carry", "萨"),
        U("异客", "carry", "萨"),
        U("卡涅利安", "carry", "萨/迅捷"),
        U("森蚺", "tank", "萨6/6"),
        U("流明", "heal", "聚合"),
        U("云迹", "econ", "奇迹"),
    ]
    PLANS["sargon_quicksand"]["reserve"] = [U("星极", "econ", "整备·奇迹")]

    PLANS["victoria_equip"] = {
        "splash": ["奇迹", "助力", "远见", "坚守"],
        "early": [
            U("慕斯", "carry", "维1"),
            U("水灯心", "support", "维2"),
            U("哈洛德", "heal", "维3/6"),
            U("星极", "econ", "奇迹"),
            U("渡桥", "econ", "远见场下"),
        ],
        "mid": [
            U("慕斯", "carry", "维"),
            U("水灯心", "support", "维"),
            U("哈洛德", "heal", "维3/6"),
            U("星极", "econ", "奇迹"),
            U("渡桥", "econ", "远见"),
            U("凯瑟琳", "support", "维/远见"),
            U("野鬃", "support", "助力flex"),
            U("砾", "tank", "不屈flex · 非维"),
        ],
        "late": [
            U("维娜·维多利亚", "carry", "维核"),
            U("烛煌", "carry", "维"),
            U("酒神", "carry", "维"),
            U("涤火杰西卡", "tank", "坦"),
            U("哈洛德", "heal", "奶"),
            U("白铁", "carry", "维6/6"),
            U("星极", "econ", "奇迹"),
            U("渡桥", "econ", "远见"),
        ],
        "reserve": [U("渡桥", "econ", "整备·远见"), U("云迹", "econ", "整备·奇迹")],
    }

    PLANS["kjerag_freeze"] = {
        "splash": ["精准", "奥术", "奇迹", "灵巧"],
        "early": [
            U("角峰", "tank", "谢1"),
            U("雪猎", "carry", "谢2/精准"),
            U("哈洛德", "heal", "谢3/6"),
            U("承曦格雷伊", "support", "精准"),
            U("星极", "econ", "奇迹"),
        ],
        "mid": [
            U("角峰", "tank", "谢"),
            U("雪猎", "carry", "谢/精准"),
            U("哈洛德", "heal", "谢"),
            U("承曦格雷伊", "support", "精准"),
            U("星极", "econ", "奇迹"),
            U("极光", "tank", "谢坦"),
            U("Miss.Christine", "carry", "奥术flex"),
            U("灰喉", "carry", "精准flex"),
        ],
        "late": [
            U("圣聆初雪", "carry", "谢/奥术"),
            U("凛御银灰", "support", "谢"),
            U("锏", "carry", "谢枢纽"),
            U("雪猎", "carry", "精准"),
            U("极光", "tank", "坦"),
            U("哈洛德", "heal", "谢6/6"),
            U("星极", "econ", "奇迹"),
            U("Miss.Christine", "carry", "奥术"),
        ],
        "reserve": [U("耶拉", "econ", "整备·奇迹"), U("云迹", "econ", "整备·奇迹")],
    }

    PLANS["siracusa_anomaly"] = {
        "splash": ["精准", "迅捷", "奇迹", "不屈"],
        "early": [
            U("奥斯塔", "carry", "叙1"),
            U("忍冬", "carry", "叙2/迅捷"),
            U("斥罪", "tank", "叙3/不屈"),
            U("砾", "tank", "不屈"),
            U("星极", "econ", "奇迹"),
        ],
        "mid": [
            U("奥斯塔", "carry", "叙"),
            U("忍冬", "carry", "叙"),
            U("斥罪", "tank", "叙"),
            U("砾", "tank", "不屈"),
            U("星极", "econ", "奇迹"),
            U("伺夜", "carry", "叙/精准"),
            U("灰喉", "carry", "精准flex"),
            U("褐果", "heal", "聚合flex"),
        ],
        "late": [
            U("荒芜拉普兰德", "carry", "叙主C"),
            U("贝洛内", "carry", "叙"),
            U("斥罪", "tank", "坦"),
            U("忍冬", "carry", "迅捷"),
            U("伺夜", "carry", "精准"),
            U("奥斯塔", "carry", "叙6/6"),
            U("砾", "tank", "不屈"),
            U("星极", "econ", "奇迹≤2"),
        ],
        "reserve": [U("复奏", "econ", "整备·奇迹"), U("云迹", "econ", "整备·奇迹")],
    }

    PLANS["leithanien_summon"] = {
        "splash": ["奥术", "聚合", "精准", "奇迹"],
        "early": [
            U("地灵", "support", "莱1"),
            U("折光", "carry", "莱2"),
            U("车尔尼", "tank", "莱3/6"),
            U("褐果", "heal", "聚合"),
            U("星极", "econ", "奇迹"),
        ],
        "mid": [
            U("地灵", "support", "莱"),
            U("折光", "carry", "莱"),
            U("车尔尼", "tank", "莱"),
            U("褐果", "heal", "聚合"),
            U("星极", "econ", "奇迹"),
            U("黑键", "carry", "莱/精准"),
            U("流明", "heal", "聚合flex"),
            U("灰喉", "carry", "精准flex"),
        ],
        "late": [
            U("纯烬艾雅法拉", "heal", "莱奶核"),
            U("薇薇安娜", "carry", "莱枢纽"),
            U("锏", "carry", "莱/卡"),
            U("艾雅法拉", "carry", "奥术"),
            U("黑键", "carry", "精准"),
            U("车尔尼", "tank", "莱6/6"),
            U("褐果", "heal", "聚合"),
            U("星极", "econ", "奇迹"),
        ],
        "reserve": [U("复奏", "econ", "整备·奇迹"), U("渡桥", "econ", "整备·远见")],
    }

    PLANS["tiaoe_mowang_flex"] = {
        "splash": ["卡西米尔", "莱塔尼亚", "谢拉格", "奥术", "奇迹", "投资人"],
        "early": [
            U("复奏", "econ", "莱/奇迹"),
            U("野鬃", "support", "卡西/助力"),
            U("哈洛德", "heal", "谢奶"),
            U("星极", "econ", "奇迹≤2"),
            U("Miss.Christine", "carry", "奥术"),
        ],
        "mid": [
            U("复奏", "econ", "莱/奇迹"),
            U("野鬃", "support", "卡西"),
            U("哈洛德", "heal", "谢"),
            U("星极", "econ", "奇迹"),
            U("Miss.Christine", "carry", "奥术"),
            U("魔王", "heal", "调和"),
            U("锏", "carry", "三栖"),
            U("褐果", "heal", "聚合flex"),
        ],
        "late": [
            U("魔王", "heal", "调和"),
            U("锏", "carry", "三栖"),
            U("薇薇安娜", "carry", "卡/奥/莱"),
            U("凛御银灰", "support", "投资/谢"),
            U("圣聆初雪", "carry", "奥/谢"),
            U("瑕光", "tank", "卡西坦"),
            U("山", "tank", "投资人"),
            U("复奏", "econ", "莱/奇迹"),
        ],
        "reserve": [
            U("星极", "econ", "整备·奇迹"),
            U("锡人", "econ", "整备·投资人"),
            U("云迹", "econ", "整备·奇迹"),
        ],
    }

    # Remove duplicate key artifact in arts plan - already fixed with second late

    for L in data["lineups"]:
        plan = PLANS[L["id"]]
        early, mid, late = plan["early"], plan["mid"], plan["late"]
        assert 4 <= len(early) <= 6
        assert len(mid) == 8 and len(late) == 8
        assert set(u["name"] for u in early) <= set(u["name"] for u in mid), (
            L["id"],
            set(u["name"] for u in early) - set(u["name"] for u in mid),
        )
        # race mid: primary racial cores should not consume entire board
        core_r = [b for b in (L.get("core_bonds") or []) if b in RACIAL]
        if len(core_r) == 1:
            r = core_r[0]
            mid_n = sum(1 for u in mid if r in bonds(u["name"]))
            if mid_n >= 7:
                raise SystemExit(f"{L['id']} mid mono {r}={mid_n}")
            late_n = sum(1 for u in late if r in bonds(u["name"]))
            if late_n > 6:
                raise SystemExit(f"{L['id']} late race {r}={late_n}")

        L["splash_bonds"] = plan["splash"]
        L["reserve_plan"] = plan["reserve"]
        L["off_board_bonds"] = [b for b in plan["splash"] + list(L.get("core_bonds") or []) if b in OFF]
        seen = set()
        L["off_board_bonds"] = [b for b in L["off_board_bonds"] if not (b in seen or seen.add(b))]
        L["bond_thresholds"] = {
            b: {
                "activation_need": bact[b],
                "display_max": bmax[b],
                "off_board": b in OFF,
            }
            for b in list(L.get("core_bonds") or []) + plan["splash"]
            if b in bmax
        }

        apply_stage(L, "early", early, "过渡：核心约3人激活档 + 1–3 小溅射/场下（小羁绊≤max）。")
        apply_stage(L, "mid", mid, "满编8含early：必须带溅射flex，禁止单羁绊堆满。")
        apply_stage(L, "late", late, "满编8：种族≤6；小羁绊人数不超过阈值。")

        L["carry"] = [u["name"] for u in late if u["role"] == "carry"][:4]
        L["tank"] = [u["name"] for u in late if u["role"] == "tank"][:3]
        L["heal"] = [u["name"] for u in late if u["role"] == "heal"][:3]
        print(L["id"], "OK", "early", [u["name"] for u in early], "mid_prog", {k: v["label"] for k, v in L["stages"]["mid"]["bond_progress"].items() if k in (L.get("core_bonds") or []) + plan["splash"]})

    meta = data.setdefault("_meta", {})
    meta["version"] = "2.1-early3-splash-cap"
    meta["bond_count_rule"] = "never exceed display_max (no 5/3); early≈3 core + small splashes; mid must include splash flex"
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", PATH)


if __name__ == "__main__":
    main()
