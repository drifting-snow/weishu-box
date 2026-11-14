# -*- coding: utf-8 -*-
"""Step-2 calibration: compare legacy engine score vs the new impact ruler.

Runs a library of representative GameState snapshots through Advisor.recommend
and, for each shop, ranks the same buy actions two ways:
  - legacy rank : engine Action.score (current production ordering)
  - impact rank : unified ruler total_impact (step-1 marginal three-axis score)
Both scores are already attached to every buy action (parallel mode), so this
tool is read-only and changes no recommendation behavior.

The output highlights rank flips so a human can judge which ordering matches
game intuition; weights are NOT tuned here, only measured.

Run: python tools/snapshot_compare.py
Stdlib only, deterministic.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from advisor.data import Dataset
from advisor.engine import Advisor
from advisor.model import GameState, ShopCard, BoardUnit


def op(name, tier=None, price=None):
    return ShopCard(kind="operator", name=name, tier=tier, price=price)


def item(name, price=None):
    ds = Dataset()
    it = ds.item(name)
    return ShopCard(kind="item", name=name, tier=it.get("tier"),
                    price=price if price is not None else it.get("price"))


def unit(name, count=1, bonds=None, elite=False):
    return BoardUnit(name=name, count=count, bonds=bonds or [], elite=elite)


# Each scenario: (label, note, GameState). Tiers are filled from the dataset
# where omitted, so only realistic shop cards appear.
def build_scenarios(ds):
    def tier_of(name):
        o = ds.operator(name)
        return o["shop_tier"] if o else 1

    S = []

    def add(label, note, **kw):
        st = GameState(**kw)
        for c in st.shop:
            if c.kind == "operator" and c.tier is None:
                c.tier = tier_of(c.name)
        S.append((label, note, st))

    add("S1 前期空板·资金紧", "round1 4金，低本卡抢启动",
        round=1, gold=4, dispatch_level=2,
        shop=[op("烈夏"), op("拜松"), item("盟约之币"), item("源石溶剂")])

    add("S2 盟约差1人激活", "乌萨斯已持2人，第三名买入即点亮",
        round=4, gold=8, dispatch_level=3, target_bond="乌萨斯",
        shop=[op("真理"), op("乌啾"), op("蓝毒"), item("坚守盾牌")],
        board=[unit("烈夏", bonds=["乌萨斯"]), unit("冻河", bonds=["乌萨斯"])])

    add("S3 三合一临界", "烈夏已持2张，第三张凑精锐",
        round=4, gold=8, dispatch_level=2, target_bond="乌萨斯",
        shop=[op("烈夏"), op("真理"), item("见钱眼开玩偶")],
        board=[unit("烈夏", count=2, bonds=["乌萨斯"])])

    add("S4 隐匿敌人局", "enemy=stealth，反隐干员应抬头",
        round=6, gold=10, dispatch_level=6, enemy_types=["stealth"],
        shop=[op("真言"), op("蓝毒"), op("拉普兰德"), item("奥术法阵", price=1)])

    add("S5 飞行敌人局", "enemy=flying，对空职业占优",
        round=5, gold=10, dispatch_level=5, enemy_types=["flying"],
        shop=[op("蓝毒"), op("幽灵鲨"), op("鸿雪"), item("源石溶剂")])

    add("S6 致命敌人局", "enemy=lethal，高压力→战力权重上调",
        round=7, gold=12, dispatch_level=5, enemy_types=["lethal"],
        shop=[op("斥罪"), op("玛恩纳"), item("M3茧甲"), item("见钱眼开玩偶")])

    add("S7 干员vs装备抢钱", "同一笔钱，跨品类取舍",
        round=4, gold=5, dispatch_level=4, target_bond="坚守",
        shop=[op("余"), item("坚守盾牌"), item("见钱眼开玩偶"), item("天马之枪")])

    add("S8 末期金币清零", "round14，延时经济装来不及回本",
        round=14, gold=10, dispatch_level=6,
        shop=[op("夕"), item("精打细算玩偶"), item("定期存折"),
              item("驮兽储蓄罐"), item("盟约之币")])

    add("S9 经济引擎投资", "前期锡人(投资人注入)与即时战力的取舍",
        round=2, gold=6, dispatch_level=3,
        shop=[op("锡人"), op("蓝毒"), item("驮兽储蓄罐"), item("盟约之币")])

    add("S10 折射敌人局", "enemy=refraction，穿甲/真伤占优，纯法术吃亏",
        round=6, gold=10, dispatch_level=6, enemy_types=["refraction"],
        shop=[op("玛恩纳"), op("真言"), op("黑键"), item("双模机械臂", price=3)])

    return S


def main():
    ds = Dataset()
    adv = Advisor(ds)
    scenarios = build_scenarios(ds)

    print("=" * 96)
    print("新旧排序比对（legacy=旧加分常数排序，impact=统一边际尺排序，分数均为各自标尺）")
    print("=" * 96)
    flip_total = 0
    for label, note, st in scenarios:
        res = adv.recommend(st)
        buys = [a for a in res["recommendations"] if a["verb"] == "buy"]
        legacy_order = sorted(buys, key=lambda a: a["score"], reverse=True)
        impact_order = sorted(buys, key=lambda a: (a["impact"]["total_impact"]
                                                   if a["impact"] else -1),
                              reverse=True)
        leg_rank = {a["target"]: i + 1 for i, a in enumerate(legacy_order)}
        imp_rank = {a["target"]: i + 1 for i, a in enumerate(impact_order)}

        print("\n■ %s  [%s]" % (label, note))
        print("  %-12s %6s | %6s %5s %5s %5s | %7s %5s" %
              ("卡/装", "旧分", "总影响", "战力", "成长", "经济", "ROI", "排名变动"))
        for a in legacy_order:
            imp = a["impact"] or {}
            d_rank = leg_rank[a["target"]] - imp_rank[a["target"]]
            arrow = ("↑%d" % d_rank) if d_rank > 0 else (("↓%d" % -d_rank) if d_rank < 0 else "=")
            print("  %-12s %6.1f | %6.1f %5.0f %5.0f %5.0f | %7s %5s" %
                  (a["target"][:12], a["score"],
                   imp.get("total_impact", 0), imp.get("power", 0),
                   imp.get("growth", 0), imp.get("economy", 0),
                   str(imp.get("impact_per_gold")), arrow))
        if legacy_order[0]["target"] != impact_order[0]["target"]:
            flip_total += 1
            print("  ⚠ 首选不同: 旧=%s  新=%s" %
                  (legacy_order[0]["target"], impact_order[0]["target"]))

    print("\n" + "=" * 96)
    print("首选分歧场景数: %d / %d（这些是需要人工判断哪边更合理的重点）" %
          (flip_total, len(scenarios)))


if __name__ == "__main__":
    main()
