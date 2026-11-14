# -*- coding: utf-8 -*-
"""Parse bond (盟约) data from the raw BWiki wikitext.

The generic text cleaner treats <...> as HTML and deletes the in-game
condition markers such as <在场6名不同【炎】干员>, which destroyed milestone
data. This parser works on the RAW wikitext instead and turns every bond into
structured form:

  {
    name, kind (core|attached), activation_need, operators,
    base_effect,
    milestones: [ {trigger_type, threshold, unit, condition, effect}, ... ]
  }

Trigger kinds:
  distinct_operator : "<在场N名不同【X】干员>" / "<在场N名【X】干员>"
  elite_operator    : "<在场N名精锐状态的干员>"
  stack             : "<达到N层>" / "<每叠加N层>" / "<首次达到N层>"
Stdlib only.
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "source", "sweep.wikitext")
OUT = os.path.join(ROOT, "data", "bonds_structured.json")


def strip_color(s: str) -> str:
    s = re.sub(r"\{\{color2\|[^|]*\|([^}]*)\}\}", r"\1", s)
    s = re.sub(r"\{\{头像\|([^}]+)\}\}", r"\1", s)
    return s


def clean_text(s: str) -> str:
    s = strip_color(s)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"<span[^>]*>|</span>", "", s)
    s = s.replace("EFFECT", "").replace("OPERATORS", "")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


# condition marker inside angle brackets that must be preserved
COND = re.compile(r"<([^>]+)>")
# real HTML tags must NOT be treated as in-game condition markers
HTML_TAG = re.compile(r"^/?[a-zA-Z][a-zA-Z0-9]*(\s|$)")
# an in-game condition always contains one of these keywords
COND_KEYWORD = re.compile(r"在场|达到|叠加|精锐|干员|层")


def is_condition_marker(inner: str) -> bool:
    inner = inner.strip()
    if HTML_TAG.match(inner):
        return False
    return bool(COND_KEYWORD.search(inner))
DISTINCT = re.compile(r"在场\s*(\d+)\s*名不同?【([^】]*)】干员")
DISTINCT_PLAIN = re.compile(r"在场\s*(\d+)\s*名【([^】]*)】干员")
ELITE = re.compile(r"在场\s*(\d+)\s*名精锐状态的干员")
STACK_FIRST = re.compile(r"首次达到\s*(\d+)\s*层")
STACK_EACH = re.compile(r"每叠加\s*(\d+)\s*层")
STACK_REACH = re.compile(r"达到\s*(\d+)\s*层")


def split_segments(eff_raw: str):
    """Split an effect cell into text segments, keeping condition markers.

    Returns list of (condition_or_None, following_text). A condition marker
    applies to the text that follows it until the next marker.
    """
    # normalize: turn every condition marker into a split sentinel
    parts = re.split(r"(<[^>]+>)", strip_color(eff_raw))
    segments = []
    pending_cond = None
    for p in parts:
        if not p:
            continue
        m = COND.fullmatch(p.strip())
        if m and is_condition_marker(m.group(1)):
            pending_cond = m.group(1).strip()
        elif m:
            # real HTML tag (br/span/...): ignore as a condition, its text
            # (if any) is handled by clean_text on the next non-tag part
            continue
        else:
            txt = clean_text(p)
            if txt:
                segments.append((pending_cond, txt))
                pending_cond = None
    return segments


def classify_condition(cond: str):
    if not cond:
        return None
    m = DISTINCT.search(cond) or DISTINCT_PLAIN.search(cond)
    if m:
        return {"trigger_type": "distinct_operator", "threshold": int(m.group(1)),
                "unit": "distinct_operator", "condition": cond, "bond_ref": m.group(2)}
    m = ELITE.search(cond)
    if m:
        return {"trigger_type": "elite_operator", "threshold": int(m.group(1)),
                "unit": "elite_operator", "condition": cond}
    m = STACK_FIRST.search(cond)
    if m:
        return {"trigger_type": "stack_first", "threshold": int(m.group(1)),
                "unit": "stack", "condition": cond}
    m = STACK_EACH.search(cond)
    if m:
        return {"trigger_type": "stack_each", "threshold": int(m.group(1)),
                "unit": "stack", "condition": cond}
    m = STACK_REACH.search(cond)
    if m:
        return {"trigger_type": "stack_reach", "threshold": int(m.group(1)),
                "unit": "stack", "condition": cond}
    return {"trigger_type": "other", "threshold": None,
            "unit": "other", "condition": cond}


def extract_operators(chunk: str):
    """Pull avatar names ONLY from the acb-ops container of this bond card.

    Counting avatars across the whole chunk is wrong for the last card: its
    block runs to end-of-file and swallows every later operator detail (the
    奥术 494-avatar bug). The authoritative list lives inside acb-ops, whose
    label also states the count (OPERATORS · N) for cross-checking.
    """
    m = re.search(r'<div class="acb-ops">(.*?)</div>\s*</div>', chunk, re.S)
    region = m.group(1) if m else ""
    names = [x.strip() for x in re.findall(r"\{\{头像\|([^}]+)\}\}", region)]
    label = re.search(r'OPERATORS\s*·\s*(\d+)', chunk)
    expected = int(label.group(1)) if label else None
    if expected is not None and len(names) != expected:
        # fall back to the acb-row sub-container, then warn if still off
        row = re.search(r'<div class="acb-row">(.*?)</div>', region, re.S)
        if row:
            names = [x.strip() for x in re.findall(r"\{\{头像\|([^}]+)\}\}", row.group(1))]
        if len(names) != expected:
            print("WARN operator count mismatch: got %d expected %s" %
                  (len(names), expected))
    return names


def parse_bonds():
    with open(SRC, encoding="utf-8") as fh:
        text = fh.read()
    blocks = re.split(r'<div class="acb-card">', text)
    core, attached = [], []
    current = core
    for chunk in re.split(r"(核心盟约=|附加盟约=|<div class=\"acb-card\">)", text):
        if chunk == "核心盟约=":
            current = core
            continue
        if chunk == "附加盟约=":
            current = attached
            continue
        if chunk == '<div class="acb-card">':
            continue
        if 'acb-name' not in chunk:
            continue
        nm = re.search(r'<div class="acb-name">(.*?)</div>', chunk, re.S)
        need = re.search(r'<div class="acb-meta"><b>(.*?)</b>', chunk, re.S)
        eff = re.search(r'<div class="acb-eff">(.*?)</div>\s*<div class="acb-ops"',
                        chunk, re.S)
        ops = extract_operators(chunk)
        if not nm:
            continue
        segments = split_segments(eff.group(1)) if eff else []
        base_parts = [txt for cond, txt in segments if cond is None]
        milestones = []
        for cond, txt in segments:
            if cond is None:
                continue
            spec = classify_condition(cond)
            spec["effect"] = txt
            milestones.append(spec)
        current.append({
            "name": nm.group(1).strip(),
            "activation_need": int(need.group(1).strip()) if need and
            need.group(1).strip().isdigit() else need.group(1).strip() if need else None,
            "operators": [o.strip() for o in ops],
            "base_effect": " ".join(base_parts),
            "milestones": milestones,
        })
    return {"core": core, "attached": attached}


def main():
    data = parse_bonds()
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("core=%d attached=%d -> %s" %
          (len(data["core"]), len(data["attached"]), OUT))
    # quick audit
    for grp in ("core", "attached"):
        for b in data[grp]:
            ms = [(m["trigger_type"], m["threshold"]) for m in b["milestones"]]
            print("[%s] %-5s need=%s milestones=%s" %
                  (grp, b["name"], b["activation_need"], ms))


if __name__ == "__main__":
    main()
