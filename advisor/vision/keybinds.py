# -*- coding: utf-8 -*-
"""In-game hotkey facts for the auto-chess client (user-confirmed 2026-11-12).

Single source of truth mapping physical keys to engine actions / view entry
points. Two distinct groups:

  ACTION_KEYBINDS -- keys that perform an economy action the advisor already
                     recommends (upgrade/freeze/refresh). Used only to annotate
                     a recommendation with the key the human would press.
  VIEW_KEYBINDS   -- keys that open an information view. W opens the enemy
                     magnifier panel, which is exactly what enemy_panel_ocr
                     consumes; recording it documents the OCR entry point.

HARD RULE: this module is declarative facts only. The advisor never simulates
these key presses and never plays the game for the user -- buying, refreshing,
freezing and upgrading stay manual. It reads screenshots and gives advice.
"""

# key -> (engine Action.verb, human label in Chinese)
ACTION_KEYBINDS = {
    "G": ("upgrade", "升级（升本）"),
    "S": ("freeze", "冻结商店"),
    "D": ("refresh", "刷新商店"),
}

# key -> (view id, human label). view id names the OCR pipeline that consumes
# the screen reached via this key.
VIEW_KEYBINDS = {
    "W": ("enemy_panel", "查看敌方信息（敌人放大镜面板，OCR 入口）"),
}

# Keys observed on screenshots but not yet wired to any engine/pipeline action.
# Kept as facts; do NOT guess a purpose -- mark unknown until the user confirms.
OTHER_KEYBINDS = {
    "ESC": "返回/关闭",
    "A": "收起（右侧人物卡）",
    "C": None,  # seen top-right in prep UI; purpose unconfirmed
}

# Engine verbs that have no keyboard shortcut (buy = click card, merge = drag).
NO_SHORTCUT_VERBS = ("buy", "merge")


def verb_to_key(verb: str):
    """Reverse lookup: engine Action.verb -> the key that performs it, or None.

    buy/merge intentionally return None (no hotkey; manual card interaction).
    """
    for key, (v, _label) in ACTION_KEYBINDS.items():
        if v == verb:
            return key
    return None


def key_for_recommendation(verb: str):
    """Annotate an engine recommendation with its hotkey label, or ''.

    Returns a short Chinese suffix like '（按 G）' for action verbs, and '' for
    verbs without a shortcut so callers can append it unconditionally.
    """
    key = verb_to_key(verb)
    return ("（按 %s）" % key) if key else ""


def all_keybinds() -> dict:
    """Merged view of every known key, each tagged with its kind."""
    out = {}
    for key, (verb, label) in ACTION_KEYBINDS.items():
        out[key] = {"kind": "action", "verb": verb, "label": label}
    for key, (view, label) in VIEW_KEYBINDS.items():
        out[key] = {"kind": "view", "view": view, "label": label}
    for key, label in OTHER_KEYBINDS.items():
        out[key] = {"kind": "other", "view": None, "label": label}
    return out
