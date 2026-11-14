# -*- coding: utf-8 -*-
"""Parse PRTS wikitext cache into per-operator native profile fields.

Adds data the BWiki weishu dataset lacks: the Arknights base profession
branch (角色分支), native 特性, combat position/tags, and the native 天赋
(talents, e.g. 拉普兰德/霍尔海雅 silence). These feed anti-air and silence
counter logic later.

Input : data/source/prts/<name>.wiki  (cached by fetch_prts_wiki.py)
Output: data/operator_profiles.json   (one record per operator)
Stdlib only. Fields that still contain unresolved wiki templates are flagged
in `needs_review` for manual checking rather than silently trusted.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "data", "source", "prts")
OPS = os.path.join(ROOT, "data", "operators.json")
OUT = os.path.join(ROOT, "data", "operator_profiles.json")

TEMPLATE_LEFT = re.compile(r"\{\{")


def _resolve_template(inner: str) -> str:
    """Resolve one brace-free template body (content between {{ and }})."""
    parts = [p.strip() for p in inner.split("|")]
    tag = parts[0] if parts else ""
    args = parts[1:]
    if tag == "color" and args:
        return args[-1]                       # color|#hex|TEXT -> TEXT
    if tag == "术语" and args:
        return args[-1]                       # 术语|key|TEXT -> TEXT
    if tag == "修正":
        for a in args:
            if a.startswith("原文="):
                return a.split("=", 1)[1]
        return ""
    if tag in ("+", "*", "-", "/", "%", "**", "±") and args:
        return args[-1]                       # numeric display value
    if args:                                  # unknown template: keep readable tail
        return args[-1] if not tag[:1].isalpha() else ""
    return ""


def clean_inline(s: str) -> str:
    s = s.replace("<br/>", " ").replace("<br />", " ").replace("<br>", " ")
    # repeatedly collapse the innermost {{...}} (no nested braces inside)
    while "{{" in s:
        m = re.search(r"\{\{[^{}]*\}\}", s)
        if not m:
            break
        s = s[:m.start()] + _resolve_template(m.group(0)[2:-2]) + s[m.end():]
    # after every template is collapsed, any stray brace delimiters are noise
    s = s.replace("{{", "").replace("}}", "")
    s = re.sub(r"'''+?", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def split_top_level(block: str) -> dict:
    """Split a {{template|k=v|...}} body on pipes that are NOT inside a nested
    template. Brace depth is driven strictly by two-char {{ / }} tokens so
    runs like }}}} (nested closers) cannot drive depth negative."""
    depth, i, tokens, cur = 0, 0, [], ""
    n = len(block)
    while i < n:
        if block[i:i+2] == "{{":
            depth += 1
            cur += "{{"; i += 2
        elif block[i:i+2] == "}}":
            depth -= 1
            cur += "}}"; i += 2
        elif block[i] == "|" and depth == 1:
            tokens.append(cur); cur = ""; i += 1
        else:
            cur += block[i]; i += 1
    if cur.strip():
        tokens.append(cur)
    fields = {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            fields[k.strip()] = v.strip()
    return fields


def field(wt: str, key: str):
    """Infobox field value, terminated by the next '|key=' or newline-pipe."""
    m = re.search(r"\|%s=(.*?)(?=\n\||\n\}\}|\n==)" % re.escape(key), wt, re.S)
    return m.group(1).strip() if m else None


def parse_talents(wt: str):
    """Extract numbered talents from the {{天赋列表...}} template using
    brace-depth-aware splitting so nested value templates are not truncated.
    Keeps the strongest (highest-elite) condition per talent name."""
    i = wt.find("==天赋==")
    if i < 0:
        return []
    # grab the template: from {{天赋列表 to its matching closing }}
    start = wt.find("{{天赋列表", i)
    if start < 0:
        return []
    depth, j = 0, start
    while j < len(wt) - 1:
        if wt[j:j+2] == "{{":
            depth += 1; j += 2
        elif wt[j:j+2] == "}}":
            depth -= 1; j += 2
            if depth == 0:
                break
        else:
            j += 1
    block = wt[start:j]
    fields = split_top_level(block)
    talents, order = {}, []
    idx = 1
    while ("天赋%s" % idx) in fields:
        tname = fields.get("天赋%s" % idx, "").strip()
        cond = fields.get("天赋%s条件" % idx, "").strip()
        eff = clean_inline(fields.get("天赋%s效果" % idx, ""))
        key = tname or ("天赋%s" % idx)
        rec = {"name": tname, "condition": cond, "effect": eff}
        if key not in talents:
            talents[key] = rec; order.append(key)
        elif "精英2" in cond and "精英2" not in talents[key]["condition"]:
            talents[key] = rec
        idx += 1
    return [talents[k] for k in order]


SKILL_OPEN = re.compile(r"\{\{技能(?:\d+)?(?=[|}\s])")


def _skill_blocks(wt: str, start: int):
    """Yield spans of {{技能}}/{{技能2}} blocks only, excluding 技能升级材料 /
    技能类型 templates (the opening lookahead requires |, space or }} right
    after the optional digit)."""
    for m in SKILL_OPEN.finditer(wt, start):
        s = m.start()
        depth, j = 0, s
        while j < len(wt) - 1:
            if wt[j:j+2] == "{{":
                depth += 1; j += 2
            elif wt[j:j+2] == "}}":
                depth -= 1; j += 2
                if depth == 0:
                    yield s, j
                    break
            else:
                j += 1


def parse_skills(wt: str):
    """Extract each distinct skill (2-3 per operator). Keep the highest-level
    (专精3, else max 技能N) description for static scoring, while storing SP
    cost / initial SP / duration separately for future combat training."""
    m0 = re.search(r"==技能==[^\n]*\n", wt)
    if not m0:
        return []
    region_start = m0.end()
    # stop at the next section heading so material/paradox sections never leak
    nxt = re.search(r"\n==[^=]", wt[region_start:])
    region = (wt[region_start: region_start + nxt.start()]
              if nxt else wt[region_start:])
    skills = []
    for s, e in _skill_blocks(region, 0):
        f = split_top_level(region[s:e])
        name = f.get("技能名", "").strip()
        if not name:
            continue
        # prefer mastery-3 (专精3) description; else the highest 技能N描述
        if "技能专精3描述" in f:
            prefix = "技能专精3"
        else:
            num_keys = [k for k in f if re.fullmatch(r"技能\d+描述", k)]
            prefix = ("技能" + max(num_keys, key=lambda k: int(re.search(r"\d+", k).group()))[2:-2]) \
                if num_keys else None
        effect = clean_inline(f[prefix + "描述"]) if prefix else ""
        sp_cost = clean_inline(f.get(prefix + "消耗", "")) if prefix else ""
        init_sp = clean_inline(f.get(prefix + "初始", "")) if prefix else ""
        duration = clean_inline(f.get(prefix + "持续", "")) if prefix else ""
        skills.append({
            "name": name, "effect": effect, "sp_cost": sp_cost,
            "initial_sp": init_sp, "duration": duration,
        })
    seen, uniq = set(), []
    for sk in skills:
        if sk["name"] not in seen:
            seen.add(sk["name"]); uniq.append(sk)
    return uniq


# Mechanic-tag keyword rules applied across trait + talents + skills.
# Each tag marks a counter capability later matched against enemy types.
MECHANIC_RULES = [
    ("anti_stealth", re.compile(r"隐匿.{0,6}失效|隐匿.{0,4}免疫|反隐|隐形.{0,6}失效")),
    ("silence",      re.compile(r"特殊能力失效|沉默")),
    ("true_damage",  re.compile(r"真实伤害")),
    ("dot",          re.compile(r"每秒.{0,8}伤害|持续.{0,4}伤害|毒素|侵蚀|流血|生命流失")),
    ("cc",           re.compile(r"冻结|寒冷|停顿|减速|束缚|晕眩|眩晕|麻痹|沉睡|浮空|恐惧")),
    ("def_pierce",   re.compile(r"无视.{0,6}防御|无视.{0,8}法术抗性|防御力降低|法术抗性降低")),
    ("shield_heal",  re.compile(r"护盾|庇护|治疗|回复.{0,4}生命|生命回复|屏障")),
    ("revive",       re.compile(r"复活|重生|击倒.{0,8}重新部署")),
    ("crit_burst",   re.compile(r"暴击|攻击力提升至\d{3}|概率.{0,6}攻击力提升")),
    ("anti_air_bonus", re.compile(r"优先攻击空中|攻击空中|对空中|飞行敌人")),
]


def derive_mechanic_tags(trait: str, talents: list, skills: list):
    text = " ".join([trait] + [t["effect"] for t in talents] +
                    [s["effect"] for s in skills])
    tags = [tag for tag, rx in MECHANIC_RULES if rx.search(text)]
    return sorted(set(tags))


def infer_anti_air(profession: str, position: str, trait: str) -> bool:
    """Whether the operator can DAMAGE airborne enemies.

    Ranged damage dealers attack air; melee operators only when their branch
    trait grants ranged attack (领主/哨戒铁卫). Medics are ranged but do not
    deal damage, so they are explicitly excluded. Conservative otherwise."""
    if profession == "医疗":
        return False
    if trait and ("远程攻击" in trait or "攻击空中" in trait):
        return True
    if position and "远程" in position:
        return True
    return False


def parse_one(name: str, wt: str):
    prof = field(wt, "职业")
    branch = field(wt, "分支")
    trait_raw = field(wt, "特性")
    position = field(wt, "位置")
    tags_raw = field(wt, "标签")
    trait = clean_inline(trait_raw) if trait_raw else ""
    tags = tags_raw.split() if tags_raw else []
    talents = parse_talents(wt)
    skills = parse_skills(wt)
    mechanic_tags = derive_mechanic_tags(trait, talents, skills)

    needs_review = []
    if TEMPLATE_LEFT.search(trait):
        needs_review.append("trait")
    for t in talents:
        if TEMPLATE_LEFT.search(t["effect"]):
            needs_review.append("talent:" + (t["name"] or "?"))
    for s in skills:
        if TEMPLATE_LEFT.search(s["effect"]):
            needs_review.append("skill:" + s["name"])

    return {
        "name": name,
        "profession": prof,
        "branch": branch,
        "position": position,
        "tags": tags,
        "trait": trait,
        "anti_air": infer_anti_air(prof or "", position or "", trait),
        "talents": talents,
        "skills": skills,
        "mechanic_tags": mechanic_tags,
        "needs_review": sorted(set(needs_review)),
    }


def main():
    names = [o["name"] for o in json.load(open(OPS, encoding="utf-8"))]
    out, missing = [], []
    for n in names:
        p = os.path.join(CACHE, n + ".wiki")
        if not os.path.exists(p):
            missing.append(n)
            continue
        wt = open(p, encoding="utf-8").read()
        out.append(parse_one(n, wt))
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    review = [r["name"] for r in out if r["needs_review"]]
    aa = sum(1 for r in out if r["anti_air"])
    no_branch = [r["name"] for r in out if not r["branch"]]
    nskill = sum(len(r["skills"]) for r in out)
    tagged = [r["name"] for r in out if "anti_stealth" in r["mechanic_tags"]]
    print("parsed %d, missing %d, anti_air %d, no_branch %d, skills %d, needs_review %d"
          % (len(out), len(missing), aa, len(no_branch), nskill, len(review)))
    print("anti_stealth operators:", "、".join(tagged) or "(none)")
    if missing:
        print("MISSING:", "、".join(missing))
    if no_branch:
        print("NO_BRANCH:", "、".join(no_branch[:20]))
    if review:
        print("NEEDS_REVIEW:", "、".join(review[:20]))
    print("written", OUT)


if __name__ == "__main__":
    main()
