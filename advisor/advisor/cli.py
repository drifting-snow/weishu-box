# -*- coding: utf-8 -*-
"""Command-line entry.

Manual mode (works today, no calibration):
  python -m advisor.cli --state state.json
  python -m advisor.cli --state state.json --rounds-at-level 2

Vision mode (OCR primary, MAA-style; needs rapidocr_onnxruntime):
  pip install -r requirements.txt
  python -m advisor.cli --shot screenshot.png --target-bond 乌萨斯 --ui-scale 100%

state.json follows advisor.model.GameState, e.g.
{
  "round": 4, "gold": 9, "dispatch_level": 2, "difficulty": "standard",
  "target_bond": "乌萨斯",
  "shop": [
    {"kind": "operator", "name": "真理", "tier": 2, "price": 3},
    {"kind": "item", "name": "坚守盾牌", "tier": 1, "price": 1}
  ],
  "board": [
    {"name": "烈夏", "count": 2, "tier": 1, "bonds": ["乌萨斯"]}
  ]
}
"""
import argparse
import json
import sys
from dataclasses import asdict

from .data import Dataset
from .engine import Advisor
from .model import state_from_dict
from .board_io import load_board_file
from vision.keybinds import verb_to_key


def _force_utf8_stdio():
    """Make stdout/stderr emit UTF-8 even on a legacy GBK/cp936 Windows console.

    Without this, ``ensure_ascii=False`` JSON with Chinese names renders as
    mojibake in the default Windows terminal. Reconfiguring the existing
    wrappers works for consoles, pipes and file redirects alike; guarded for
    exotic streams without ``reconfigure``.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _resolve_enemy_shot(enemy_shot_path):
    """OCR an enemy magnifier-panel screenshot to tactical trait keys.

    Returns (trait_keys, enemy_names, log_lines). enemy_names holds every
    recognized canonical name (tactical + ordinary filler) in OCR order, so the
    concrete wave reaches the decision layer alongside the compressed keys.
    Vision imports are lazy so the advisor core stays stdlib-only. Only enemy
    NAMES are OCR'd against the FULL enemy name index (ordinary filler
    included); the tactical catalog then decides which names contribute counter
    trait keys. Three states are logged: tactical (typed), untyped (known
    ordinary enemy), unknown (new/OCR error).
    """
    from PIL import Image
    from advisor.enemy_catalog import (
        load_enemy_catalog, load_enemy_name_index, resolve_enemies)
    from vision.enemy_panel_ocr import EnemyPanelRecognizer
    catalog = load_enemy_catalog()
    name_index = load_enemy_name_index()
    img = Image.open(enemy_shot_path).convert("RGB")
    all_names = list(name_index.get("names", {}).keys())
    ocr_names = EnemyPanelRecognizer(all_names).recognize_names(img)
    resolved = resolve_enemies(ocr_names, catalog, name_index)
    log = ["[enemy] OCR 敌人名: %s" % (ocr_names or "（未识别到官方敌人）")]
    for r in resolved["resolutions"]:
        if r["status"] == "tactical":
            log.append("[enemy] %s -> 战术类 %s trait=%s" % (
                r["name"], r["ac_types"], r["trait_keys"]))
            if r.get("warning"):
                log.append("[enemy] 注意: " + r["warning"])
        elif r["status"] == "untyped":
            log.append("[enemy] %s -> 普通敌人，无战术分类（不触发对策）" % r["name"])
        else:
            log.append("[enemy] 警告: " + (r["warning"] or "未知名"))
    return resolved["trait_keys"], resolved["names"], log


def run(state_path=None, shot_path=None, rounds_at_level=0,
        target_bond=None, difficulty="standard", ui_scale="100%",
        round_no=1, gold=0, dispatch_level=1, enemy_types=None,
        out_path=None, board_path=None, enemy_shot_path=None,
        banned_operators=None, banned_bonds=None):
    ds = Dataset()
    adv = Advisor(ds)

    # Optional owned-board input (hand JSON today; board OCR reuses this later).
    board_units, board_warnings = ([], [])
    if board_path:
        board_units, board_warnings = load_board_file(board_path, ds)
        for w in board_warnings:
            print("[board] " + w, file=sys.stderr)

    # Enemy magnifier panel: OCR names -> canonical names + catalog trait
    # keys, then merge any manual --enemy-types (manual first; OCR supplements;
    # de-duplicated). Concrete enemy names are kept separately for per-enemy
    # stats and special-ability counters.
    ocr_enemy_types = []
    ocr_enemy_names = []
    resource_payload = None
    if enemy_shot_path:
        ocr_enemy_types, ocr_enemy_names, enemy_log = _resolve_enemy_shot(enemy_shot_path)
        for line in enemy_log:
            print(line, file=sys.stderr)
    merged_enemy_types = list(enemy_types or [])
    for key in ocr_enemy_types:
        if key not in merged_enemy_types:
            merged_enemy_types.append(key)
    enemy_types = merged_enemy_types or None
    enemy_names = list(ocr_enemy_names)  # OCR is the only source of concrete names

    if state_path:
        with open(state_path, encoding="utf-8") as fh:
            obj = json.load(fh)
        st = state_from_dict(obj)
        if board_path:
            # explicit --board wins over any board embedded in the state file
            st.board = board_units
        if enemy_types:
            st.enemy_types = enemy_types
        if enemy_names:
            st.enemy_names = enemy_names
    elif shot_path:
        # Shop-band OCR (dynamic slot count) + resource-number OCR from the
        # SAME screenshot. Round/gold/level now come from ResourceRecognizer;
        # manual flags only fill gaps when a field cannot be recognized.
        # Prices are still derived from the dataset, not OCR'd.
        from PIL import Image
        from vision.shop_band_ocr import ShopBandRecognizer
        from vision.resource_ocr import ResourceRecognizer
        img = Image.open(shot_path).convert("RGB")
        rec = ShopBandRecognizer(ds)
        resources = ResourceRecognizer().read_resources(img)
        for w in resources.warnings:
            print("[resource] " + w, file=sys.stderr)
        eff_round = resources.round if resources.round is not None else round_no
        eff_gold = resources.gold if resources.gold is not None else gold
        eff_level = (resources.dispatch_level if resources.dispatch_level is not None
                     else dispatch_level)
        st = rec.recognize(
            img, difficulty=difficulty, target_bond=target_bond,
            board=[asdict(u) for u in board_units],
            round=eff_round, gold=eff_gold, dispatch_level=eff_level,
            enemy_types=enemy_types, enemy_names=enemy_names)
        resource_payload = resources.as_dict()
    elif enemy_shot_path:
        # Enemy panel supplied without a shop/state input: advise on an empty
        # manual state so the counter scoring still runs for the wave profile.
        from advisor.model import GameState
        st = GameState(
            round=round_no, gold=gold, dispatch_level=dispatch_level,
            difficulty=difficulty, target_bond=target_bond, shop=[],
            board=board_units, enemy_types=list(enemy_types or []),
            enemy_names=list(enemy_names))
    else:
        raise SystemExit("provide --state, --shot or --enemy-shot")

    if target_bond:
        st.target_bond = target_bond
    # Draft bans: merge CLI-supplied bans on top of any embedded in a --state
    # JSON, de-duplicated while preserving order. Empty/absent -> no change,
    # so legacy states keep their empty ban lists.
    for field_name, cli_vals in (("banned_operators", banned_operators),
                                 ("banned_bonds", banned_bonds)):
        merged = list(getattr(st, field_name, []) or [])
        for v in (cli_vals or []):
            if v and v not in merged:
                merged.append(v)
        setattr(st, field_name, merged)
    result = adv.recommend(st, rounds_at_level=rounds_at_level)
    # Presentation-only: annotate each action with its in-game hotkey. buy/merge
    # have none (manual card interaction) -> hotkey is null. Does not touch the
    # engine objects or their byte-stable tests; the advisor never presses keys.
    for rec in result.get("recommendations", []):
        rec["hotkey"] = verb_to_key(rec.get("verb", ""))
    if result.get("top_pick"):
        result["top_pick"]["hotkey"] = verb_to_key(
            result["top_pick"].get("verb", ""))
    # Echo the resolved shop cards back. The engine's state block is
    # intentionally minimal and omits input-only fields, but external UIs
    # (the overlay shell) need state.shop to mirror cards and anchor glow
    # highlights onto the right slot. asdict keeps raw OCR payloads intact.
    if getattr(st, "shop", None):
        result["state"]["shop"] = [asdict(c) for c in st.shop]
    # Vision-only resource read (enemy count / upgrade cost are not consumed by
    # the engine yet; round/gold/level already drive the state above).
    if resource_payload is not None:
        result["resources"] = resource_payload
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if out_path:
        # BOM-less UTF-8 file; stable for downstream tooling and version control.
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload + "\n")
    else:
        print(payload)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description="Wei Shu Guard Protocol advisor")
    p.add_argument("--state", help="path to a manual GameState JSON")
    p.add_argument("--shot", help="path to a shop screenshot (vision mode)")
    p.add_argument("--ui-scale", default="100%", choices=["90%", "100%"],
                   help="retained for compatibility; band OCR is scale-free")
    p.add_argument("--rounds-at-level", type=int, default=0)
    p.add_argument("--target-bond")
    p.add_argument("--difficulty", default="standard")
    # Manual numerics for --shot mode until small-number OCR lands.
    p.add_argument("--round", type=int, default=1, dest="round_no")
    p.add_argument("--gold", type=int, default=0)
    p.add_argument("--dispatch-level", type=int, default=1)
    p.add_argument("--enemy-types", default=None,
                   help="comma-separated enemy trait keys, e.g. flying,stealth")
    p.add_argument("--ban-operator", default=None,
                   help="comma-separated banned operator names; never recommended as buys")
    p.add_argument("--ban-bond", default=None,
                   help="comma-separated banned bonds; lineups built on them are excluded")
    p.add_argument("--out", default=None,
                   help="write the UTF-8 JSON result to this file instead of stdout")
    p.add_argument("--board", default=None, dest="board_path",
                   help="path to an owned-board JSON (names or {name,count,...} "
                        "list); drives bond headcount / merge / milestone scoring")
    p.add_argument("--enemy-shot", default=None, dest="enemy_shot_path",
                   help="screenshot of the magnifier enemy panel; OCRs enemy names "
                        "and resolves their tactical trait keys via data/enemy_catalog.json")
    args = p.parse_args(argv)
    _force_utf8_stdio()
    enemy_types = ([s.strip() for s in args.enemy_types.split(",") if s.strip()]
                   if args.enemy_types else None)
    banned_operators = ([s.strip() for s in args.ban_operator.split(",") if s.strip()]
                        if args.ban_operator else None)
    banned_bonds = ([s.strip() for s in args.ban_bond.split(",") if s.strip()]
                    if args.ban_bond else None)
    run(args.state, args.shot, args.rounds_at_level,
        args.target_bond, args.difficulty, args.ui_scale,
        args.round_no, args.gold, args.dispatch_level, enemy_types, args.out,
        args.board_path, args.enemy_shot_path,
        banned_operators, banned_bonds)


if __name__ == "__main__":
    main()
