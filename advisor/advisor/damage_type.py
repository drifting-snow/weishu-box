# -*- coding: utf-8 -*-
"""Stage-B damage-type classifier (pure logic, no I/O).

The unpacked skill table has no clean ``damageType`` field (it is null for every
mode skill), so damage type is resolved with a three-tier rule, strongest signal
first:

  1. explicit keyword in the Rank7 skill description (法术伤害 / 物理伤害 /
     真实伤害 / 元素损伤...)  -> per-skill verdict, source="text"
  2. operator trait / native_trait keyword                       -> source="trait"
  3. profession default + audited subProfession exceptions       -> source="default"

Elemental damage (神经/侵蚀/灼燃/凋亡) is a *secondary* flag: it is attached on
top of a physical/arts primary (e.g. primcaster deals arts + elemental), never a
replacement. Verdicts that fall through to a default are still returned, but the
caller can treat ``source == "default"`` as lower confidence. No hard guessing:
if even the branch default is unknown the verdict is ``None`` + needs_review.

The branch exceptions below are derived from tools/_b_branch_audit.py output
(real game text), not memory.
"""

PHYSICAL = "physical"
ARTS = "arts"
TRUE = "true"
HEAL = "heal"

# primary damage families; ELEMENT is tracked separately as a secondary flag
PRIMARY_TYPES = (PHYSICAL, ARTS, TRUE, HEAL)

ELEMENTAL_KEYWORDS = ("神经", "侵蚀", "灼燃", "凋亡", "元素损伤")
TRUE_KEYWORDS = ("真实伤害",)
ARTS_KEYWORDS = ("法术伤害",)
PHYSICAL_KEYWORDS = ("物理伤害",)
HEAL_KEYWORDS = ("治疗", "回复", "恢复友方", "生命")

# profession-level baseline when no text/trait signal exists
PROFESSION_DEFAULT = {
    "CASTER": ARTS,
    "MEDIC": HEAL,
    "SNIPER": PHYSICAL,
    "WARRIOR": PHYSICAL,
    "TANK": PHYSICAL,
    "PIONEER": PHYSICAL,
    "SPECIAL": PHYSICAL,
    "SUPPORT": PHYSICAL,
}

# subProfession exceptions to the profession baseline (from branch text audit)
BRANCH_EXCEPTION = {
    # casters that couple arts attacks with elemental damage stay arts; flag set
    # at skill level. No caster branch leaves the arts family.
    # snipers whose attacks are arts
    "bombarder": ARTS,
    # guards / defenders that deal arts damage
    "artsfghter": ARTS,
    "artsprotector": ARTS,
    "primprotector": ARTS,
    # specialists: alchemist deals arts/elemental
    "alchemist": ARTS,
    # support branches whose basic attacks are arts
    "slower": ARTS,
    "blessing": ARTS,
    "ritualist": ARTS,
    "underminer": ARTS,
    # bard attacks are true damage (no normal attack, performance damage)
    "bard": TRUE,
    # ringhealer (咒愈师) attacks deal arts while healing
    "ringhealer": ARTS,
    # primguard (本源卫) deals arts + elemental
    "primguard": ARTS,
}


def branch_default(profession, sub_profession):
    """Default primary damage type for a profession branch."""
    if sub_profession in BRANCH_EXCEPTION:
        return BRANCH_EXCEPTION[sub_profession]
    return PROFESSION_DEFAULT.get(profession)


def _has_any(text, keywords):
    return any(k in text for k in keywords)


def classify_text(description):
    """Resolve a primary type + elemental flag from a single description string.

    Returns ``(primary_or_None, has_element)``. Multiple primary keywords in one
    description return ``None`` so the caller can flag a genuinely mixed skill
    instead of silently picking one.
    """
    text = description or ""
    has_element = _has_any(text, ELEMENTAL_KEYWORDS)
    primaries = []
    if _has_any(text, TRUE_KEYWORDS):
        primaries.append(TRUE)
    if _has_any(text, ARTS_KEYWORDS):
        primaries.append(ARTS)
    if _has_any(text, PHYSICAL_KEYWORDS):
        primaries.append(PHYSICAL)
    if len(primaries) == 1:
        return primaries[0], has_element
    if len(primaries) > 1:
        return None, has_element  # genuinely mixed within one skill -> review
    return None, has_element


def _mentions_primary(text):
    return _has_any(text or "", TRUE_KEYWORDS + ARTS_KEYWORDS + PHYSICAL_KEYWORDS)


def classify_skill(description, profession, sub_profession):
    """Classify one offensive skill. Returns type/source/element/review.

    Explicit single-keyword text is authoritative. Silent text falls back to the
    branch default. A *mixed* primary (e.g. arts hit + true-damage side effect)
    is NOT silently forced to the branch default -- that would mislabel a skill
    whose text explicitly names another family; it returns None + review so it
    can be adjudicated in the targeted override table.
    """
    review = []
    primary, has_element = classify_text(description)
    if primary is not None:
        return {"damage_type": primary, "source": "text",
                "has_elemental": has_element, "needs_review": review}
    if _mentions_primary(description):
        review.append("单技能文本含多种伤害类型，需人工裁定(不套分支默认)")
        return {"damage_type": None, "source": "mixed_text",
                "has_elemental": has_element, "needs_review": review}
    # no damage-type keyword -> branch default
    default = branch_default(profession, sub_profession)
    if default is None:
        review.append("无文本信号且无分支默认，无法判定")
        return {"damage_type": None, "source": "none",
                "has_elemental": has_element, "needs_review": review}
    return {"damage_type": default, "source": "default",
            "has_elemental": has_element, "needs_review": review}


def classify_operator_baseline(native_trait, profession, sub_profession):
    """Operator-level basic-attack damage type from trait text then branch."""
    review = []
    primary, has_element = classify_text(native_trait or "")
    if primary is not None:
        return {"damage_type": primary, "source": "trait",
                "has_elemental": has_element, "needs_review": review}
    default = branch_default(profession, sub_profession)
    if default is None:
        review.append("特性无伤害关键词且无分支默认")
        return {"damage_type": None, "source": "none",
                "has_elemental": has_element, "needs_review": review}
    return {"damage_type": default, "source": "default",
            "has_elemental": has_element, "needs_review": review}
