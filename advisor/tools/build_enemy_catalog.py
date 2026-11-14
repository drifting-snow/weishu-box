# -*- coding: utf-8 -*-
"""Build data/enemy_catalog.json from the official unpacked game tables.

Data flow (all inputs are git-ignored, rebuildable, NOT committed):
  activity_table.json
    activity.AUTOCHESS.act3autochess.V3_1.enemyInfoDict      -> training enemies, type -> ids
    activity.AUTOCHESS.act3autochess.V3_1.specialEnemyInfoDict -> special enemies (own `type`)
      + attachedNormal/EliteEnemyKeys inherit the host's type
  enemy_handbook_table.json -> authoritative Simplified-Chinese name per enemy id
  enemy_database.json       -> motion (FLY/WALK), levelType (rank), applyWay

The official in-mode tactical types are mapped to our 9 trait keys
(data/enemy_traits.json). No third-party/GPL table is read: this only parses
the official Kengxxiao unpacked data through our own code. Names that collide
across ids are merged (trait keys unioned; highest rank kept).

Stdlib only.
"""
import argparse, io, json, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GD = os.path.join(ROOT, "data", "source", "gamedata")
DEFAULT_OUT = os.path.join(ROOT, "data", "enemy_catalog.json")
DEFAULT_NAMES_OUT = os.path.join(ROOT, "data", "enemy_names.json")

# Official in-mode tactical type -> our enemy_traits.json trait key.
TYPE_TO_TRAIT = {
    "SPECIAL": "special",
    "FLY": "flying",
    "TIMES": "multi_hit",
    "ELEMENT": "elemental",
    "DOT": "sustained",
    "INVISIBLE": "stealth",
    "REFLECTION": "refraction",
    "CRITIC": "lethal",
    "REBORN": "revival",
}
RANK_ORDER = {"BOSS": 3, "ELITE": 2, "NORMAL": 1}
# How an enemy got its type, in decreasing trust order.
SOURCE_RANK = {"training": 3, "special": 2, "attached": 1, "manual": 0}


def mv(field, default=None):
    """Unwrap the official {m_defined, m_value} envelope."""
    if isinstance(field, dict) and "m_value" in field:
        return field["m_value"]
    return default if field is None else field


def load(name):
    with open(os.path.join(GD, name), encoding="utf-8") as fh:
        return json.load(fh)


def build():
    at = load("activity_table.json")
    hb = load("enemy_handbook_table.json")["enemyData"]
    ed_rows = load("enemy_database.json")["enemies"]
    ed = {r["Key"]: r["Value"][0]["enemyData"] for r in ed_rows if r.get("Value")}

    v31 = at["activity"]["AUTOCHESS"]["act3autochess"]["V3_1"]

    # Official tactical-type metadata (sortId + Chinese name); fail loudly if a
    # future season adds a type we have not mapped to our 9 trait keys yet.
    type_meta = at["autoChessData"]["enemyTypeDatas"]
    official_types = set(type_meta.keys())
    unmapped = official_types - set(TYPE_TO_TRAIT)
    if unmapped:
        raise ValueError("官方新增未映射战术类型，请补 TYPE_TO_TRAIT: %s"
                         % sorted(unmapped))
    type_sort = {t: type_meta[t]["sortId"] for t in official_types}

    def name_of(eid):
        # handbook (enemy manual) is the authoritative display name: it is what
        # the in-game panel/OCR shows and covers every autochess id. database
        # names occasionally differ (30 translation drifts), so use it only as
        # fallback -- this keeps the tactical catalog and full name index keyed
        # by the exact same Chinese name.
        h = hb.get(eid)
        if h and h.get("name"):
            return h.get("name")
        rec = ed.get(eid)
        if rec:
            n = mv(rec.get("name"))
            if n:
                return n
        return None

    def raw_attrs(eid):
        rec = ed.get(eid)
        if not rec:
            return {"is_flying": False, "rank": None, "apply_way": None}
        return {
            "is_flying": mv(rec.get("motion")) == "FLY",
            "rank": mv(rec.get("levelType")),
            "apply_way": mv(rec.get("applyWay")),
        }

    # eid -> {"types": set, "sources": set}
    cls = {}

    def add(eid, otype, source):
        if otype not in TYPE_TO_TRAIT:
            raise ValueError("unknown official type %r for %s" % (otype, eid))
        rec = cls.setdefault(eid, {"types": set(), "sources": set()})
        rec["types"].add(otype)
        rec["sources"].add(source)

    # 1) training enemies (explicit type -> id lists)
    for otype, ids in v31["enemyInfoDict"].items():
        for eid in ids:
            add(eid, otype, "training")

    # 2) special enemies (own type) + attached minions inherit host type
    for eid, info in v31["specialEnemyInfoDict"].items():
        add(eid, info["type"], "special")
        for grp in ("attachedNormalEnemyKeys", "attachedEliteEnemyKeys"):
            for attached in (info.get(grp) or []):
                add(attached, info["type"], "attached")

    # aggregate by Chinese name (merge duplicate-name ids)
    enemies = {}
    unresolved = []
    for eid, info in cls.items():
        name = name_of(eid)
        if not name:
            unresolved.append(eid)
            continue
        attrs = raw_attrs(eid)
        trait_keys = []
        for t in sorted(info["types"], key=lambda t: type_sort[t]):
            tk = TYPE_TO_TRAIT[t]
            if tk not in trait_keys:
                trait_keys.append(tk)
        if name not in enemies:
            enemies[name] = {
                "enemy_ids": [], "ac_types": sorted(info["types"], key=lambda t: type_sort[t]),
                "trait_keys": trait_keys, "rank": attrs["rank"],
                "is_flying": attrs["is_flying"], "apply_way": attrs["apply_way"],
                "sources": sorted(info["sources"],
                                  key=lambda s: -SOURCE_RANK[s]),
                "inherited_type": "attached" in info["sources"]
                                  and not (info["sources"] - {"attached"}),
                "needs_review": False,
            }
        else:
            agg = enemies[name]
            agg["enemy_ids"]  # touch
            for t in info["types"]:
                if t not in agg["ac_types"]:
                    agg["ac_types"].append(t)
            for tk in trait_keys:
                if tk not in agg["trait_keys"]:
                    agg["trait_keys"].append(tk)
            for s in info["sources"]:
                if s not in agg["sources"]:
                    agg["sources"].append(s)
            if attrs["rank"] and (not agg["rank"] or
                    RANK_ORDER.get(attrs["rank"], 0) > RANK_ORDER.get(agg["rank"], 0)):
                agg["rank"] = attrs["rank"]
            agg["is_flying"] = agg["is_flying"] or attrs["is_flying"]
            agg["inherited_type"] = agg["inherited_type"] and (
                "attached" in info["sources"] and not (info["sources"] - {"attached"}))
        enemies[name]["enemy_ids"].append(eid)

    # normalize every entry: order types by official sortId and derive trait
    # keys in the exact same order (set semantics, deterministic output).
    for entry in enemies.values():
        entry["ac_types"] = sorted(set(entry["ac_types"]),
                                   key=lambda t: type_sort[t])
        entry["trait_keys"] = [TYPE_TO_TRAIT[t] for t in entry["ac_types"]]

    # stable ordering: primary official type sortId, then Chinese name
    enemies = dict(sorted(enemies.items(), key=lambda kv: (
        type_sort.get(kv[1]["ac_types"][0], 99), kv[0])))

    type_counts = {}
    for e in enemies.values():
        for t in e["ac_types"]:
            type_counts[t] = type_counts.get(t, 0) + 1

    catalog = {
        "_meta": {
            "description": "卫戍协议敌人名录：把放大镜面板 OCR 到的敌人名解析成 enemy_traits.json 的战术分类 trait key。由官方解包表(Kengxxiao)经 tools/build_enemy_catalog.py 自动重建，不含任何第三方/GPL 复刻数据；源表在 data/source/gamedata(gitignored)。",
            "generated_by": "tools/build_enemy_catalog.py",
            "season": "act3autochess V3_1（卫戍协议·规程第三赛季，随官方版本重建）",
            "category_bridge": TYPE_TO_TRAIT,
            "trait_key_to_name": {
                "special": "特异", "flying": "飞行", "multi_hit": "频次",
                "elemental": "元素", "sustained": "持续", "stealth": "隐匿",
                "refraction": "折射", "lethal": "致命", "revival": "复苏",
            },
            "counts": {
                "classified_enemy_ids": len(cls),
                "unique_names": len(enemies),
                "by_official_type": dict(sorted(type_counts.items())),
                "unresolved_ids": unresolved,
            },
            "field_notes": {
                "sources": "training=特训敌人池官方分类；special=特殊敌人(自带 type)；attached=特殊敌人关联的普通/精英，类型继承自宿主(inherited_type=true)。",
                "untyped": "普通杂兵(如源石虫)不属于任何战术特训类，不在本名录；其名字仍收录在 data/enemy_names.json 全量索引中，OCR 可识别但不贡献 trait key。",
            },
        },
        "enemies": enemies,
    }
    return catalog, cls


def build_name_index(cls):
    """All official enemy names (handbook) with rank/flying and any tactical
    types, so OCR can recognize ordinary untyped filler too (three-state:
    tactical-typed / known-untyped / truly-unknown). Keyed by Chinese name."""
    hb = load("enemy_handbook_table.json")["enemyData"]
    ed_rows = load("enemy_database.json")["enemies"]
    ed = {r["Key"]: r["Value"][0]["enemyData"] for r in ed_rows if r.get("Value")}

    eid_types = {eid: sorted(info["types"]) for eid, info in cls.items()}

    def _union(entry, key, values):
        bucket = entry.setdefault(key, [])
        for v in values:
            if v and v not in bucket:
                bucket.append(v)

    names = {}
    for eid, hrec in hb.items():
        name = hrec.get("name")
        if not name:
            continue
        raw = ed.get(eid)
        is_flying = bool(raw and mv(raw.get("motion")) == "FLY")
        rank = (mv(raw.get("levelType")) if raw else None) or hrec.get("enemyLevel")
        # Qualitative (non-numeric) fields for recognition/counter logic.
        damage_types = list(hrec.get("damageType") or [])      # PHYSIC/MAGIC/NO_DAMAGE/HEAL
        apply_way = mv(raw.get("applyWay")) if raw else None   # MELEE/RANGED/ALL/NONE
        race_tags = list(mv(raw.get("enemyTags")) or []) if raw else []
        boss_invisible = bool(hrec.get("invisibleDetail"))    # boss-level permanent stealth
        entry = names.setdefault(name, {
            "enemy_ids": [], "rank": rank, "is_flying": is_flying,
            "tactical_types": [], "damage_types": [], "apply_ways": [],
            "race_tags": [], "boss_invisible": False,
        })
        entry["enemy_ids"].append(eid)
        if eid in eid_types:
            _union(entry, "tactical_types", eid_types[eid])
        _union(entry, "damage_types", damage_types)
        if apply_way:
            _union(entry, "apply_ways", [apply_way])
        _union(entry, "race_tags", race_tags)
        entry["is_flying"] = entry["is_flying"] or is_flying
        entry["boss_invisible"] = entry["boss_invisible"] or boss_invisible
        if rank and (not entry["rank"] or
                RANK_ORDER.get(rank, 0) > RANK_ORDER.get(entry["rank"], 0)):
            entry["rank"] = rank

    names = dict(sorted(names.items()))
    typed = sum(1 for e in names.values() if e["tactical_types"])
    flying = sum(1 for e in names.values() if e["is_flying"])
    boss_invis = sum(1 for e in names.values() if e["boss_invisible"])
    return {
        "_meta": {
            "description": "全量官方敌人中文名索引(解包表 handbook+database 自动生成)，供 OCR 模糊匹配与定性判断。tactical_types 非空者另见 enemy_catalog.json 的对策映射；为空表示无战术分类的普通敌人。不含 HP/ATK/DEF/RES 等数值。",
            "generated_by": "tools/build_enemy_catalog.py",
            "counts": {
                "unique_names": len(names), "with_tactical_type": typed,
                "flying": flying, "boss_invisible": boss_invis,
            },
            "field_glossary": {
                "enemy_ids": "同名(如精英变体)对应的所有官方 enemy id，可溯源",
                "rank": "NORMAL/ELITE/BOSS，同名多 id 取最高",
                "is_flying": "database motion=FLY（空中单位，需对空）",
                "tactical_types": "官方自走棋战术分类(9 类)，空=无战术分类",
                "damage_types": "handbook damageType：PHYSIC 物理/MAGIC 法术/NO_DAMAGE 无伤害/HEAL 治疗",
                "apply_ways": "database applyWay：MELEE 近战/RANGED 远程/ALL 全位/NONE",
                "race_tags": "database enemyTags 种族/性质：infection/sarkaz/machine/drone 等",
                "boss_invisible": "handbook invisibleDetail=true 的 Boss 级隐匿单位",
            },
        },
        "names": names,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT, help="output catalog path")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--names-out", default=DEFAULT_NAMES_OUT,
                    help="full enemy-name index path")
    args = ap.parse_args()
    catalog, cls = build()
    name_index = build_name_index(cls)
    for path, doc in ((args.out, catalog), (args.names_out, name_index)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
    if not args.quiet:
        c = catalog["_meta"]["counts"]
        n = name_index["_meta"]["counts"]
        print("wrote %s" % args.out)
        print("classified ids=%d unique names=%d unresolved=%d" %
              (c["classified_enemy_ids"], c["unique_names"], len(c["unresolved_ids"])))
        print("by official type:", c["by_official_type"])
        print("wrote %s | full name index: %s" % (args.names_out, n))


if __name__ == "__main__":
    main()
