# -*- coding: utf-8 -*-
"""Extract trigger-timing tags the generic clean() pipeline drops.

The source wikitext marks WHEN an operator trait fires with angle-bracket tags
inside the c-tr cell, e.g.
    <span class="kind">持续叠加</span><div class="desc">
      <休整期结束时>使已激活的【伊比利亚】【迅捷】层数+12</div>
parse_weishu.clean() treats every <...> as an HTML tag and deletes it, so the
timing axis (休整期结束时 / 获得时 / 进入休整期时 / 售出时 / 战斗开始时 /
战斗结束时 / 刷新时 / 开启技能时 / 休整期开始时) is missing from operators.json.

This reads the raw vendored wikitext directly and emits one record per
(operator, form, trait-kind) carrying the timing tags, so stack parsing can
distinguish end-of-rest growth from on-acquire growth without a hand-written
override table. Stdlib only, deterministic.

Output: data/operator_timing.json
Run   : python tools/parse_timing.py
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "source", "sweep.wikitext")
OUT = os.path.join(ROOT, "data", "operator_timing.json")

# The nine real trigger-timing tags (anything else in angle brackets is HTML or
# a milestone condition and is ignored here).
TIMING_TAGS = [
    "休整期结束时", "进入休整期时", "休整期开始时", "获得时", "售出时",
    "刷新时", "开启技能时", "战斗开始时", "战斗结束时",
]
TIMING_RE = re.compile(r"<(" + "|".join(TIMING_TAGS) + r")>")
OPROW_RE = re.compile(r'<tr class="oprow"([^>]*)>(.*?)</tr>', re.S)
HEAD_RE = {
    "name": re.compile(r'data-name="([^"]+)"'),
    "kind": re.compile(r'data-kind="([^"]+)"'),
    "form": re.compile(r'data-form="([^"]+)"'),
}
CTR_RE = re.compile(r'<td class="c-tr">(.*?)</td>', re.S)
KIND_SPAN_RE = re.compile(r'<span class="kind">(.*?)</span>')


def strip_html(s):
    """Reduce a c-tr cell to readable text, preserving timing tags."""
    # keep timing tags by temporarily tokenizing them
    tokens = {}

    def keep(m):
        key = "\x00%d\x00" % len(tokens)
        tokens[key] = m.group(1)
        return key

    s = TIMING_RE.sub(keep, s)
    s = re.sub(r"<[^>]+>", "", s)          # drop genuine HTML
    s = re.sub(r"\{\{[^}]*\}\}", "", s)    # drop leftover color2 templates
    s = s.replace("&#123;", "{").replace("&#125;", "}")
    for key, tag in tokens.items():
        s = s.replace(key, "<%s>" % tag)
    return s.strip()


def main():
    txt = open(SRC, encoding="utf-8").read()
    records = []
    seen = set()
    per_operator = {}

    for m in OPROW_RE.finditer(txt):
        head, body = m.group(1), m.group(2)
        name_m = HEAD_RE["name"].search(head)
        if not name_m:
            continue
        name = name_m.group(1)
        kind = (HEAD_RE["kind"].search(head).group(1)
                if HEAD_RE["kind"].search(head) else "")
        form = (HEAD_RE["form"].search(head).group(1)
                if HEAD_RE["form"].search(head) else "")
        ctr = CTR_RE.search(body)
        if not ctr:
            continue
        cell = ctr.group(1)
        tags = TIMING_RE.findall(cell)
        if not tags:
            continue
        readable = strip_html(cell)
        key = (name, form, kind, readable)
        if key in seen:
            continue
        seen.add(key)
        rec = {
            "operator": name, "form": form, "kind": kind,
            "timing": sorted(set(tags)), "trait": readable,
        }
        records.append(rec)
        per_operator.setdefault(name, {}).setdefault(form, set()).update(tags)

    # compact per-operator lookup: {name: {form: [tags]}}
    compact = {name: {form: sorted(tags) for form, tags in forms.items()}
               for name, forms in sorted(per_operator.items())}
    out = {
        "_meta": {
            "description": "干员特质的触发时机标签。clean() 会删尖括号，故直接从原始 "
                           "sweep.wikitext 提取；timing 取值见 timing_tags。",
            "timing_tags": TIMING_TAGS,
            "operator_count": len(compact),
            "record_count": len(records),
        },
        "records": records,
        "by_operator": compact,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # console summary
    from collections import Counter
    c = Counter(t for r in records for t in r["timing"])
    print("operators with timing:", len(compact), "| records:", len(records))
    for tag in TIMING_TAGS:
        n = len({r["operator"] for r in records if tag in r["timing"]})
        if n:
            print("  %-8s %d 干员" % (tag, n))
    print("written", OUT)


if __name__ == "__main__":
    main()
