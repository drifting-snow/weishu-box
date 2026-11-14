# -*- coding: utf-8 -*-
"""Cap racial cores at 6; protect carry/tank/heal when swapping."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data"
PATH = ROOT / "lineups.json"
# reload from git? use current and re-fetch stuffed from origin late lists via hardcoded originals

ops = {o["name"]: o for o in json.loads((ROOT / "operators.json").read_text(encoding="utf-8"))}
bs = json.loads((ROOT / "bonds_structured.json").read_text(encoding="utf-8"))
RACIAL = {b["name"] for b in bs["core"] if b["name"] != "调和"}
OFF_BOARD = {"远见", "奇迹", "投资人"}
RACE_CAP = 6

# Restore intended mid/late before bad trim, then trim with role protection
ORIGIN = {
    "yan_elemental": {
        "race": "炎",
        "mid": ["拜松", "风絮", "仇白", "余", "老鲤", "烛煌", "夕", "黍"],
        "late": ["烛煌", "夕", "黍", "仇白", "余", "拜松", "风絮", "老鲤"],
        "protect": ["烛煌", "夕", "仇白", "余", "风絮"],  # C/tank/heal
        "fillers": [("褐果", "heal", "聚合奶"), ("星极", "support", "奇迹场下")],
    },
    "sargon_quicksand": {
        "race": "萨尔贡",
        "mid": ["泡泡", "莎草", "卡涅利安", "异客", "森蚺", "佩佩", "鸿雪", "真言"],
        "late": ["森蚺", "佩佩", "鸿雪", "真言", "异客", "泡泡", "莎草", "卡涅利安"],
        "protect": ["真言", "鸿雪", "异客", "森蚺", "莎草"],
        "fillers": [("流明", "heal", "聚合奶"), ("云迹", "support", "奇迹场下")],
    },
    "victoria_equip": {
        "race": "维多利亚",
        "mid": ["哈洛德", "凯瑟琳", "水灯心", "涤火杰西卡", "白铁", "维娜·维多利亚", "烛煌", "酒神"],
        "late": ["维娜·维多利亚", "烛煌", "酒神", "涤火杰西卡", "哈洛德", "水灯心", "凯瑟琳", "白铁"],
        "protect": ["维娜·维多利亚", "烛煌", "酒神", "涤火杰西卡", "哈洛德"],
        "fillers": [("星极", "support", "奇迹场下"), ("渡桥", "support", "远见场下")],
    },
    "kjerag_freeze": {
        "race": "谢拉格",
        "mid": ["角峰", "雪猎", "哈洛德", "极光", "耶拉", "圣聆初雪", "凛御银灰", "锏"],
        "late": ["圣聆初雪", "凛御银灰", "锏", "雪猎", "极光", "角峰", "哈洛德", "耶拉"],
        "protect": ["圣聆初雪", "锏", "哈洛德", "极光", "角峰"],
        "fillers": [("星极", "support", "奇迹场下"), ("Miss.Christine", "carry", "奥术溅射")],
    },
    "siracusa_anomaly": {
        "race": "叙拉古",
        "mid": ["奥斯塔", "伺夜", "忍冬", "安洁莉娜", "斥罪", "铃兰", "贝洛内", "荒芜拉普兰德"],
        "late": ["铃兰", "贝洛内", "荒芜拉普兰德", "奥斯塔", "斥罪", "忍冬", "伺夜", "安洁莉娜"],
        "protect": ["荒芜拉普兰德", "贝洛内", "斥罪", "铃兰", "安洁莉娜"],
        "fillers": [("星极", "support", "奇迹场下"), ("砾", "tank", "不屈低本")],
    },
    "leithanien_summon": {
        "race": "莱塔尼亚",
        "mid": ["车尔尼", "复奏", "卡涅利安", "艾雅法拉", "黑键", "纯烬艾雅法拉", "薇薇安娜", "锏"],
        "late": ["纯烬艾雅法拉", "薇薇安娜", "锏", "艾雅法拉", "黑键", "车尔尼", "卡涅利安", "复奏"],
        "protect": ["纯烬艾雅法拉", "薇薇安娜", "锏", "艾雅法拉", "车尔尼"],
        "fillers": [("褐果", "heal", "聚合奶"), ("星极", "support", "奇迹场下")],
    },
}


def bonds(n):
    return list((ops.get(n) or {}).get("bonds") or [])


def has_race(n, race):
    return race in bonds(n)


def mk(n, role=None, note=""):
    o = ops[n]
    if role is None:
        prof = o.get("prof") or ""
        role = "heal" if "医疗" in prof else "tank" if "重装" in prof else "support" if ("辅助" in prof or "特种" in prof) else "carry"
    return {
        "name": n,
        "tier": int(o.get("shop_tier") or 1),
        "role": role,
        "note": note or "/".join(bonds(n)[:3]),
        "off_board_ok": bool(set(bonds(n)) & OFF_BOARD),
    }


def bond_counts(names, focus):
    c = Counter()
    for n in names:
        for b in bonds(n):
            c[b] += 1
    out = {b: c[b] for b in focus if c.get(b)}
    for b, n in c.most_common():
        if b not in out:
            out[b] = n
    return dict(out)


def cap(names, race, protect, fillers):
    protect = set(protect)
    racial = [n for n in names if has_race(n, race)]
    if len(racial) <= RACE_CAP:
        return names[:]
    # drop racial not in protect first; then lowest protect priority by tier
    droppable = [n for n in racial if n not in protect]
    # sort droppable: prefer low tier, support-ish names last in list order
    droppable.sort(key=lambda n: (int(ops[n].get("shop_tier") or 1), n))
    need = len(racial) - RACE_CAP
    to_drop = []
    for n in droppable:
        if len(to_drop) >= need:
            break
        to_drop.append(n)
    if len(to_drop) < need:
        # must drop some protected — drop lowest tier protected
        prot_r = sorted([n for n in racial if n in protect], key=lambda n: (int(ops[n].get("shop_tier") or 1), n))
        for n in prot_r:
            if len(to_drop) >= need:
                break
            if n not in to_drop:
                to_drop.append(n)
    out = [n for n in names if n not in to_drop]
    used = set(out)
    for fn, fr, fnote in fillers:
        if len(out) >= 8:
            break
        if fn in used or fn not in ops or has_race(fn, race):
            continue
        out.append(fn)
        used.add(fn)
    # pad if needed
    for fn, fr, fnote in fillers:
        if len(out) >= 8:
            break
    assert len(out) == 8, (names, out, to_drop)
    assert sum(1 for n in out if has_race(n, race)) <= RACE_CAP
    return out


data = json.loads(PATH.read_text(encoding="utf-8"))
filler_roles = {}
for lid, cfg in ORIGIN.items():
    for fn, fr, fnote in cfg["fillers"]:
        filler_roles[fn] = (fr, fnote)

for L in data["lineups"]:
    lid = L["id"]
    if lid not in ORIGIN:
        continue
    cfg = ORIGIN[lid]
    race = cfg["race"]
    splash = list(L.get("splash_bonds") or [])
    for fn, _, _ in cfg["fillers"]:
        for b in bonds(fn):
            if b != race and b not in splash:
                splash.append(b)
    L["splash_bonds"] = splash[:8]
    focus = list(L.get("core_bonds") or []) + L["splash_bonds"]

    for sk in ("mid", "late"):
        names = cap(cfg[sk], race, cfg["protect"], cfg["fillers"])
        units = []
        for n in names:
            if n in filler_roles:
                fr, fnote = filler_roles[n]
                units.append(mk(n, fr, fnote))
            else:
                units.append(mk(n))
        n_race = sum(1 for n in names if has_race(n, race))
        L["stages"][sk]["units"] = units
        L["stages"][sk]["bond_counts"] = bond_counts(names, focus)
        L["stages"][sk]["pop"] = "8"
        L["stages"][sk]["plan_fielded"] = 8
        L["stages"][sk]["goal"] = f"{race}上限6（里程碑够用）；余2位溅射/奇迹/功能位。"
        print(lid, sk, f"{race}={n_race}", names)

    reserve = []
    for fn, fr, fnote in cfg["fillers"]:
        if set(bonds(fn)) & OFF_BOARD:
            reserve.append(mk(fn, fr, "整备区·" + fnote))
    if reserve:
        L["reserve_plan"] = reserve
        L["off_board_bonds"] = sorted({b for u in reserve for b in bonds(u["name"]) if b in OFF_BOARD})

meta = data.setdefault("_meta", {})
meta["race_cap"] = 6
meta["race_cap_note"] = "Racial big-bond useful max 6; never 8 same-race on mid/late."
ver = str(meta.get("version") or "1.0")
if "+race6" not in ver:
    meta["version"] = ver + "+race6"

PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

bad = []
for x in data["lineups"]:
    for sk in ("mid", "late"):
        names = [u["name"] for u in x["stages"][sk]["units"]]
        c = Counter()
        for n in names:
            for b in bonds(n):
                if b in RACIAL:
                    c[b] += 1
        for b, n in c.items():
            if n > 6:
                bad.append((x["id"], sk, b, n))
print("BAD", bad)
print("WROTE OK")
