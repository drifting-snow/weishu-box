# -*- coding: utf-8 -*-
"""Persistent kernel worker (run with weishu-advisor venv python).

Keeps Dataset + RapidOCR warm. Protocol: one JSON object per stdin line,
one JSON object per stdout line.

Request:  {"op":"shot","path":"...","round":1,"gold":0,"dispatch_level":1,...}
          {"op":"state","state":{...}}
          {"op":"ping"}
Response: {"ok":true,"result":{...},"latency_ms":N} or {"ok":false,"error":"..."}
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Allow importing sibling overlay modules (opening_parse) when cwd is kernel.
_SHELL_DIR = Path(__file__).resolve().parent
if str(_SHELL_DIR) not in sys.path:
    sys.path.insert(0, str(_SHELL_DIR))


def _board_owned_names(board_list: list) -> set[str]:
    return {str(u.get("name")) for u in (board_list or []) if u.get("name")}


def _refine_procedure_level_roi(img, ocr_engine, parsed: dict) -> dict:
    """If full-frame miss, re-OCR bottom bar / red channel for 规程等级N."""
    from opening_parse import PROCEDURE_RE, pick_procedure_level

    if parsed.get("procedure_level") is not None:
        return parsed
    w, h = img.size
    crops = [
        img.crop((int(0.01 * w), int(0.86 * h), int(0.48 * w), int(0.99 * h))),
        img.crop((int(0.01 * w), int(0.00 * h), int(0.35 * w), int(0.10 * h))),
    ]
    try:
        import numpy as np
        from PIL import Image as PILImage
        from PIL import ImageOps
    except Exception:
        np = None  # type: ignore
        PILImage = None  # type: ignore
        ImageOps = None  # type: ignore

    boxes: list[dict] = []
    for crop in crops:
        try:
            for b in ocr_engine.detect(crop) or []:
                boxes.append(b)
        except Exception:
            continue
        if np is not None and PILImage is not None and ImageOps is not None:
            try:
                arr = np.asarray(crop.convert("RGB"))
                r = arr[:, :, 0].astype(int)
                g = arr[:, :, 1].astype(int)
                bl = arr[:, :, 2].astype(int)
                mask = (r > 140) & ((r - g) > 40) & ((r - bl) > 40)
                red = np.zeros_like(arr)
                red[mask] = 255
                inv = ImageOps.invert(PILImage.fromarray(red).convert("L")).convert(
                    "RGB"
                )
                inv = inv.resize((max(1, inv.width * 2), max(1, inv.height * 2)))
                for b in ocr_engine.detect(inv) or []:
                    boxes.append(b)
            except Exception:
                pass
    # Normalize crop-local boxes loosely for pick (cx/cy unused if single).
    norm = []
    for b in boxes:
        t = str(b.get("text") or "")
        if not PROCEDURE_RE.search(t):
            continue
        norm.append(
            {
                "text": t,
                "cx": 0.1,
                "cy": 0.9,
                "score": float(b.get("score") or 0),
            }
        )
    lv = pick_procedure_level(norm, parsed.get("screen") or "difficulty_select")
    if lv is not None:
        parsed = dict(parsed)
        parsed["procedure_level"] = lv
        parsed.setdefault("warnings", [])
        if isinstance(parsed["warnings"], list):
            parsed["warnings"] = list(parsed["warnings"]) + [
                "procedure_level from ROI/red refine"
            ]
    return parsed


def _parse_opening_image(img, ocr_engine, ds) -> dict:
    """Half-res RapidOCR → opening_parse (difficulty_select / 1-3)."""
    from opening_parse import parse_opening_detections

    w, h = img.size
    small = img.resize((max(1, w // 2), max(1, h // 2)))
    raw = ocr_engine.detect(small)
    sw, sh = small.size
    bond_names: list[str] = []
    try:
        for grp in ("core", "attached"):
            for b in (ds.bonds or {}).get(grp, []) or []:
                n = b.get("name") if isinstance(b, dict) else None
                if n:
                    bond_names.append(n)
    except Exception:
        bond_names = []
    op_names = [
        o.get("name")
        for o in (ds.operators or [])
        if isinstance(o, dict) and o.get("name")
    ]
    et_meta = {}
    try:
        p = Path("data") / "enemy_traits.json"
        if p.is_file():
            et_meta = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        et_meta = {}
    parsed = parse_opening_detections(
        raw,
        img_w=float(sw),
        img_h=float(sh),
        bond_names=bond_names,
        operator_names=op_names,
        enemy_types_meta=et_meta,
        image=small,
    )
    parsed["ocr_box_count"] = len(raw)
    if parsed.get("procedure_level") is None:
        parsed = _refine_procedure_level_roi(img, ocr_engine, parsed)
    return parsed


def _apply_regulation_level(st, req: dict) -> None:
    """Inject run_env procedure_level → GameState.regulation_level."""
    raw = req.get("regulation_level")
    if raw is None:
        return
    try:
        lv = int(raw)
    except (TypeError, ValueError):
        return
    if 1 <= lv <= 20:
        st.regulation_level = lv


def _recognize_enemy_panel(img, ocr_engine, name_index: dict, catalog: dict) -> dict:
    """Magnifier-panel enemy names → tactical trait keys (advisor enemy API).

    Uses vision.enemy_panel_ocr.EnemyPanelRecognizer + advisor.enemy_catalog.
    Returns empty names/traits when the panel is closed (ROI has no catalog hits).
    """
    from vision.enemy_panel_ocr import EnemyPanelRecognizer
    from advisor.enemy_catalog import resolve_enemies

    all_names = list((name_index or {}).get("names", {}).keys())
    if not all_names:
        return {
            "names": [],
            "trait_keys": [],
            "resolutions": [],
            "unknown": [],
            "panel_open": False,
        }
    rec = EnemyPanelRecognizer(all_names, ocr_engine=ocr_engine)
    names = rec.recognize_names(img)
    resolved = resolve_enemies(names, catalog, name_index)
    resolutions = []
    for r in resolved.get("resolutions") or []:
        resolutions.append(
            {
                "input": r.get("input"),
                "name": r.get("name"),
                "status": r.get("status"),
                "trait_keys": list(r.get("trait_keys") or []),
                "ac_types": list(r.get("ac_types") or []),
                "warning": r.get("warning"),
            }
        )
    return {
        "names": list(names),
        "trait_keys": list(resolved.get("trait_keys") or []),
        "resolutions": resolutions,
        "unknown": list(resolved.get("unknown") or []),
        "panel_open": bool(names),
    }


def _stage_coverage(stages: dict, owned: set[str]) -> dict:
    """Owned / missing counts for late (fallback mid/early) stage."""
    stages = stages or {}
    stage = stages.get("late") or stages.get("mid") or stages.get("early") or {}
    units = list(stage.get("units") or [])
    names = [u.get("name") for u in units if u.get("name")]
    # Unique names within the stage list (defensive; stages rarely duplicate).
    uniq = list(dict.fromkeys(names))
    have = [n for n in uniq if n in owned]
    miss = [n for n in uniq if n not in owned]
    return {
        "stage": "late" if stages.get("late") else ("mid" if stages.get("mid") else "early"),
        "have": have,
        "missing": miss,
        "have_n": len(have),
        "need_n": len(uniq),
    }


def _unique_ownership(stages: dict, owned: set[str]) -> dict:
    """Unique operator names across early/mid/late (not stage-row totals)."""
    all_names: set[str] = set()
    for stage in (stages or {}).values():
        for u in stage.get("units") or []:
            n = u.get("name")
            if n:
                all_names.add(str(n))
    owned_names = sorted(all_names & owned)
    return {
        "owned": len(owned_names),
        "planned": len(all_names),
        "owned_names": owned_names,
    }


def _attach_roadmap_chase(comp: dict, owned: set[str], dispatch_level: int) -> dict:
    """Fill next_targets / off_board_targets / ownership from advisor.roadmap.

    next_targets = on-board chase only (excludes role=econ).
    off_board_targets = 场下经济 siblings — must not feed shop board glow.
    """
    try:
        from advisor.lineup import get_lineup
        from advisor.roadmap import (
            current_stage,
            next_targets,
            off_board_targets,
        )
    except Exception:
        return comp

    full = get_lineup(comp.get("id") or "") or {}
    stages = full.get("stages") or comp.get("stages") or {}
    if not stages:
        return comp
    try:
        level = max(1, min(6, int(dispatch_level or 1)))
    except (TypeError, ValueError):
        level = 1
    stage = current_stage(level)
    # Build a lineup-shaped dict for roadmap helpers (need stages + id).
    L = {"id": comp.get("id"), "stages": stages}
    chase_by_stage = {}
    for sk in ("early", "mid", "late"):
        if sk not in stages:
            continue
        chase_by_stage[sk] = {
            "next_targets": next_targets(L, sk, owned, level),
            "off_board_targets": off_board_targets(L, sk, owned, level),
        }
    cur = chase_by_stage.get(stage) or {"next_targets": [], "off_board_targets": []}
    comp["current_stage"] = stage
    comp["next_targets"] = list(cur.get("next_targets") or [])
    comp["off_board_targets"] = list(cur.get("off_board_targets") or [])
    comp["stage_chase"] = chase_by_stage
    comp["ownership"] = _unique_ownership(stages, owned)
    return comp

def _build_target_comps(
    result: dict,
    st,
    board_list: list,
    prefer_bonds: list | None = None,
) -> list:
    """Wire compass inferred plan + recommend_lineups(enemy/bans) for roster UI."""
    from advisor.lineup import get_lineup, load_lineups, recommend_lineups

    owned = _board_owned_names(board_list)
    target_comps: list = []
    lineup_sum = (result or {}).get("lineup") if isinstance(result, dict) else None

    if lineup_sum and lineup_sum.get("id"):
        full = get_lineup(lineup_sum["id"])
        if full:
            cov = _stage_coverage(full.get("stages") or {}, owned)
            target_comps.append(
                {
                    "id": full["id"],
                    "name": full["name"],
                    "archetype": full.get("archetype"),
                    "archetype_label": full.get("archetype_label"),
                    "core_bonds": full.get("core_bonds", []),
                    "splash_bonds": full.get("splash_bonds", []),
                    "off_board_bonds": full.get("off_board_bonds", []),
                    "bond_thresholds": full.get("bond_thresholds", {}),
                    "reserve_plan": full.get("reserve_plan", []),
                    "fantasy": full.get("fantasy") or full.get("counter_why") or "",
                    "stages": full.get("stages", {}),
                    "carry": full.get("carry", []),
                    "tank": full.get("tank", []),
                    "heal": full.get("heal", []),
                    "key_tips": full.get("key_tips", []),
                    "inferred": True,
                    "confidence": lineup_sum.get("confidence"),
                    "why": lineup_sum.get("why") or lineup_sum.get("reason"),
                    "coverage": cov,
                    "source": "compass",
                }
            )

    try:
        ranked = recommend_lineups(
            enemy_types=list(getattr(st, "enemy_types", None) or []),
            banned_bonds=list(getattr(st, "banned_bonds", None) or []),
            available_operators=None,
        )
        prefer = {str(b) for b in (prefer_bonds or []) if b}
        tb = getattr(st, "target_bond", None)
        if tb:
            prefer.add(str(tb))
        for L in ranked:
            if any(c["id"] == L["id"] for c in target_comps):
                # enrich existing inferred entry with fit info
                for c in target_comps:
                    if c["id"] == L["id"]:
                        c["fit_score"] = L.get("fit_score")
                        c["counter_hits"] = L.get("counter_hits")
                        c["weakness_hits"] = L.get("weakness_hits")
                        c["counter_why"] = L.get("counter_why")
                        c["archetype_label"] = L.get("archetype_label") or c.get(
                            "archetype_label"
                        )
                continue
            # Soft boost: core bond overlap with preferred bonds
            cores = set(L.get("core_bonds") or [])
            bond_boost = 3.0 if (prefer & cores) else 0.0
            cov = _stage_coverage(L.get("stages") or {}, owned)
            # Pull fantasy from full catalog when recommend_lineups omits it
            full = get_lineup(L["id"]) or {}
            target_comps.append(
                {
                    "id": L["id"],
                    "name": L["name"],
                    "archetype": L.get("archetype"),
                    "archetype_label": L.get("archetype_label"),
                    "core_bonds": L.get("core_bonds", []),
                    "splash_bonds": full.get("splash_bonds", L.get("splash_bonds", [])),
                    "off_board_bonds": full.get("off_board_bonds", []),
                    "bond_thresholds": full.get("bond_thresholds", {}),
                    "reserve_plan": full.get("reserve_plan", []),
                    "fantasy": full.get("fantasy")
                    or L.get("counter_why")
                    or "",
                    "stages": full.get("stages") or L.get("stages", {}),
                    "carry": L.get("carry", []),
                    "tank": L.get("tank", []),
                    "heal": L.get("heal", []),
                    "key_tips": L.get("key_tips", []),
                    "fit_score": (L.get("fit_score") or 0) + bond_boost,
                    "counter_hits": L.get("counter_hits"),
                    "weakness_hits": L.get("weakness_hits"),
                    "counter_why": L.get("counter_why"),
                    "weak_why": L.get("weak_why"),
                    "inferred": False,
                    "coverage": cov,
                    "source": "recommend_lineups",
                    "bond_prefer": bool(bond_boost),
                }
            )
        # Include any catalog lineup recommend_lineups filtered out (e.g. no enemy
        # picture) — roster window must list the full lineups.json set.
        have = {c["id"] for c in target_comps}
        for full in load_lineups():
            if full["id"] in have:
                continue
            cov = _stage_coverage(full.get("stages") or {}, owned)
            target_comps.append(
                {
                    "id": full["id"],
                    "name": full["name"],
                    "archetype": full.get("archetype"),
                    "archetype_label": full.get("archetype_label"),
                    "core_bonds": full.get("core_bonds", []),
                    "splash_bonds": full.get("splash_bonds", []),
                    "off_board_bonds": full.get("off_board_bonds", []),
                    "bond_thresholds": full.get("bond_thresholds", {}),
                    "reserve_plan": full.get("reserve_plan", []),
                    "fantasy": full.get("fantasy") or full.get("counter_why") or "",
                    "stages": full.get("stages", {}),
                    "carry": full.get("carry", []),
                    "tank": full.get("tank", []),
                    "heal": full.get("heal", []),
                    "key_tips": full.get("key_tips", []),
                    "fit_score": 0,
                    "inferred": False,
                    "coverage": cov,
                    "source": "lineups_catalog",
                }
            )
    except Exception:
        pass

    # Re-score every comp against run enemy_types (mirror shop counter ranking).
    # Counter hits first; then inferred / bond prefer as light tie-breakers.
    try:
        from advisor.lineup import ARCHETYPE_LABEL, counter_fit, get_lineup

        enemy = list(getattr(st, "enemy_types", None) or [])
        for c in target_comps:
            full = get_lineup(c["id"]) or {}
            fit = counter_fit(full if full else c, enemy)
            base = float(fit.get("score") or 0.0)
            if c.get("bond_prefer"):
                base += 3.0
            if c.get("inferred"):
                base += 1.5
            c["fit_score"] = base
            c["counter_hits"] = fit.get("hits") or c.get("counter_hits") or []
            c["weakness_hits"] = fit.get("weaknesses") or c.get("weakness_hits") or []
            if full.get("counter_why"):
                c["counter_why"] = full.get("counter_why")
            if full.get("weak_why"):
                c["weak_why"] = full.get("weak_why")
            if not c.get("archetype_label") and full.get("archetype"):
                c["archetype_label"] = ARCHETYPE_LABEL.get(
                    full.get("archetype"), full.get("archetype")
                )
            c["enemy_sort"] = list(enemy)
    except Exception:
        pass

    # Roadmap chase: on-board next_targets vs 场下 off_board_targets + unique ownership.
    try:
        level = int(getattr(st, "dispatch_level", 1) or 1)
    except (TypeError, ValueError):
        level = 1
    engine_rm = (result or {}).get("roadmap") if isinstance(result, dict) else None
    for c in target_comps:
        _attach_roadmap_chase(c, owned, level)
        # Prefer engine roadmap fields when this is the active inferred plan.
        if (
            isinstance(engine_rm, dict)
            and engine_rm.get("lineup_id")
            and engine_rm.get("lineup_id") == c.get("id")
        ):
            if "next_targets" in engine_rm:
                c["next_targets"] = list(engine_rm.get("next_targets") or [])
            if "off_board_targets" in engine_rm:
                c["off_board_targets"] = list(engine_rm.get("off_board_targets") or [])
            if isinstance(engine_rm.get("ownership"), dict):
                c["ownership"] = {
                    "owned": int(engine_rm["ownership"].get("owned") or 0),
                    "planned": int(engine_rm["ownership"].get("planned") or 0),
                    "owned_names": list(
                        (c.get("ownership") or {}).get("owned_names") or []
                    ),
                }
            if engine_rm.get("current_stage"):
                c["current_stage"] = engine_rm["current_stage"]
            c["roadmap"] = engine_rm

    def _key(c):
        # Higher fit (counter match) first — same spirit as shop counter scoring.
        return (
            -(c.get("fit_score") if c.get("fit_score") is not None else -999),
            0 if c.get("inferred") else 1,
            c.get("id") or "",
        )

    target_comps.sort(key=_key)
    return target_comps


def _upgrade_cost_from_shop_band(img, ocr_engine) -> int | None:
    """Read the hex cost pip above the LEVEL/升级 tile from shop-band OCR."""
    w, h = img.size
    y0 = int(0.68 * h)
    band = img.crop((0, y0, w, h))
    raw = ocr_engine.detect(band)
    level_cx = None
    digits = []
    for b in raw:
        text = str(b.get("text") or "").strip()
        cx = (float(b["x0"]) + float(b["x1"])) / 2.0 / w
        cy = (float(b["y0"]) + y0 + float(b["y1"]) + y0) / 2.0 / h
        if text.upper().startswith("LEV") or text == "升级":
            level_cx = cx if level_cx is None else (level_cx + cx) / 2.0
        if text.isdigit() and 0.70 <= cy <= 0.78:
            try:
                digits.append((abs(cx - (level_cx or cx)), int(text), cx, cy))
            except ValueError:
                pass
    if not digits:
        return None
    # Prefer digit nearest the LEVEL/升级 column
    digits.sort(key=lambda t: t[0])
    val = digits[0][1]
    # Sanity: upgrade costs in this mode are typically 1..20
    if 1 <= val <= 30:
        return val
    return None


def main() -> int:
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    from PIL import Image
    from advisor.data import Dataset
    from advisor.engine import Advisor
    from advisor.model import state_from_dict
    from vision.shop_band_ocr import ShopBandRecognizer
    from vision.resource_ocr import ResourceRecognizer
    from vision.keybinds import verb_to_key

    # board_strip_ocr was never landed in the public monorepo (HANDOFF: ??).
    # Hard-importing it killed the whole sidecar → CLI fallback (no 开始模拟
    # sniff) and broke 录入本局 / procedure_level → regulation_level. Strip OCR
    # stays optional; shop + opening paths must still warm.
    try:
        from vision.board_strip_ocr import BoardStripRecognizer
    except ModuleNotFoundError:  # pragma: no cover - missing in scrubbed tip
        class BoardStripRecognizer:  # type: ignore[no-redef]
            def __init__(self, *args, **kwargs):
                pass

            def recognize_board(self, img):
                return []

    ds = Dataset()
    adv = Advisor(ds)
    shop_rec = ShopBandRecognizer(ds)
    # One RapidOCR instance for shop + board + resources + enemy panel.
    shared_ocr = shop_rec._engine()
    board_rec = BoardStripRecognizer(ds, ocr_engine=shared_ocr)
    res_rec = ResourceRecognizer(ocr_engine=shared_ocr)
    _ = res_rec.read_resources(Image.new("RGB", (64, 64), (0, 0, 0)))
    # Enemy name index / tactical catalog (warm once).
    try:
        from advisor.enemy_catalog import load_enemy_catalog, load_enemy_name_index

        enemy_name_index = load_enemy_name_index()
        enemy_catalog = load_enemy_catalog()
    except Exception:
        enemy_name_index, enemy_catalog = {"names": {}}, {"enemies": {}}
    # Last successfully OCR'd gold (never invent 0 from a miss).
    last_good_gold: int | None = None

    print(json.dumps({"ok": True, "ready": True}, ensure_ascii=False), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        t0 = time.perf_counter()
        try:
            req = json.loads(line)
            op = req.get("op")
            if op == "ping":
                out = {"ok": True, "pong": True}
            elif op == "shot":
                timing: dict = {}
                path = req["path"]
                t_load = time.perf_counter()
                img = Image.open(path).convert("RGB")
                timing["load_ms"] = int((time.perf_counter() - t_load) * 1000)

                # Cheap CTA sniff (bottom-right) — only then full opening parse.
                # Keeps normal shop OCR fast when not on 难度选择.
                t_sniff = time.perf_counter()
                opening = None
                try:
                    iw, ih = img.size
                    cta = img.crop(
                        (
                            int(0.68 * iw),
                            int(0.82 * ih),
                            int(0.99 * iw),
                            int(0.99 * ih),
                        )
                    )
                    cta_texts = [
                        str(b.get("text") or "")
                        for b in (shared_ocr.detect(cta) or [])
                    ]
                    if any("开始模拟" in t for t in cta_texts):
                        opening = _parse_opening_image(img, shared_ocr, ds)
                except Exception as oe:
                    opening = {"screen": None, "warnings": [str(oe)]}
                timing["opening_sniff_ms"] = int(
                    (time.perf_counter() - t_sniff) * 1000
                )
                if isinstance(opening, dict) and opening.get("screen") == "difficulty_select":
                    pl = opening.get("procedure_level")
                    out = {
                        "ok": True,
                        "result": {
                            "scene": "difficulty_select",
                            "skip_shop": True,
                            "procedure_level": pl,
                            "regulation_level": pl,
                            "opening": opening,
                            "recommendations": [],
                            "top_pick": None,
                            "shop": [],
                            "board": [],
                            "state": {
                                "regulation_level": pl,
                                "dispatch_level": int(
                                    req.get("dispatch_level") or 1
                                ),
                                "difficulty": req.get("difficulty") or "standard",
                            },
                            "resources": {},
                            "timing": timing,
                            "note": "规程难度选择：已读规程等级，跳过商店 OCR",
                        },
                    }
                    out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
                    print(json.dumps(out, ensure_ascii=False), flush=True)
                    continue

                t_res = time.perf_counter()
                # skip_enemy_count: top chess-icon N unused by shop decide (~0.5s).
                # Real enemy *names* come from magnifier panel OCR below.
                resources = res_rec.read_resources(img, skip_enemy=True)
                timing["resources_ms"] = int((time.perf_counter() - t_res) * 1000)
                # If LEVEL-anchor OCR missed upgrade_cost, recover digit near
                # the upgrade tile from the shop-band RapidOCR pass later.
                round_no = (
                    resources.round
                    if resources.round is not None
                    else int(req.get("round") or 1)
                )
                # Prefer OCR gold (incl. explicit 0). On miss: keep last good;
                # never coerce unrecognized → 0 (that falsely triggers 开战).
                gold_status = "unknown"
                if resources.gold is not None:
                    gold = int(resources.gold)
                    last_good_gold = gold
                    gold_status = "ocr"
                elif last_good_gold is not None:
                    gold = int(last_good_gold)
                    gold_status = "last_good"
                elif req.get("last_gold") is not None:
                    try:
                        gold = int(req["last_gold"])
                        last_good_gold = gold
                        gold_status = "last_good"
                    except (TypeError, ValueError):
                        gold = int(req.get("gold") or 0)
                        gold_status = "unknown"
                else:
                    # Soft form fallback for engine scoring only — shell must
                    # see gold_status=unknown and must NOT gold0-battle.
                    gold = int(req.get("gold") or 0)
                    gold_status = "unknown"
                level = (
                    resources.dispatch_level
                    if resources.dispatch_level is not None
                    else int(req.get("dispatch_level") or 1)
                )

                # Magnifier enemy panel (names → trait keys). Empty if panel closed.
                t_enemy = time.perf_counter()
                try:
                    enemy_panel = _recognize_enemy_panel(
                        img, shared_ocr, enemy_name_index, enemy_catalog
                    )
                except Exception as ee:
                    enemy_panel = {
                        "names": [],
                        "trait_keys": [],
                        "resolutions": [],
                        "unknown": [],
                        "panel_open": False,
                        "error": str(ee),
                    }
                timing["enemy_panel_ms"] = int(
                    (time.perf_counter() - t_enemy) * 1000
                )

                # Merge: panel traits first, then run_env / request types.
                merged_enemy: list[str] = []
                for k in list(enemy_panel.get("trait_keys") or []) + list(
                    req.get("enemy_types") or []
                ):
                    ks = str(k).strip()
                    if ks and ks not in merged_enemy:
                        merged_enemy.append(ks)

                # Owned roster: strip OCR is fallback only. When shell locks a
                # 「读阵容」cache (board_locked), strip must not overwrite it.
                board_units = []
                board_err = None
                board_source = "strip"
                req_board = list(req.get("board") or [])
                board_locked = bool(req.get("board_locked"))
                t_board = time.perf_counter()
                if board_locked and req_board:
                    board_payload = req_board
                    board_source = str(req.get("board_source") or "click_panel")
                else:
                    try:
                        board_units = board_rec.recognize_board(img)
                    except Exception as be:
                        board_units = []
                        board_err = str(be)
                    board_payload = (
                        [asdict(u) for u in board_units]
                        if board_units
                        else list(req_board)
                    )
                    board_source = "strip" if board_units else (
                        "request" if req_board else "empty"
                    )
                timing["board_ms"] = int((time.perf_counter() - t_board) * 1000)

                t_shop = time.perf_counter()
                st = shop_rec.recognize(
                    img,
                    difficulty=req.get("difficulty") or "standard",
                    target_bond=req.get("target_bond") or None,
                    board=board_payload,
                    round=round_no,
                    gold=gold,
                    dispatch_level=level,
                    enemy_types=merged_enemy,
                )
                # Equipment from 「读阵容」session (kernel GameState.equipment).
                req_eq = req.get("equipment")
                if isinstance(req_eq, dict) and req_eq:
                    try:
                        st.equipment = {
                            str(k): [str(x) for x in (v or [])]
                            for k, v in req_eq.items()
                            if k
                        }
                    except Exception:
                        pass
                timing["shop_ms"] = int((time.perf_counter() - t_shop) * 1000)
                if req.get("target_bond"):
                    st.target_bond = req["target_bond"]
                # Opening-env / panel merge — panel wins when open.
                if merged_enemy:
                    st.enemy_types = list(merged_enemy)
                if req.get("banned_operators"):
                    st.banned_operators = list(req["banned_operators"])
                if req.get("banned_bonds"):
                    st.banned_bonds = list(req["banned_bonds"])
                _apply_regulation_level(st, req)
                # Ensure board units are BoardUnit instances with bonds filled
                if board_units and not st.board:
                    st.board = board_units
                elif board_units:
                    st.board = board_units

                t_adv = time.perf_counter()
                result = adv.recommend(
                    st, rounds_at_level=int(req.get("rounds_at_level") or 0)
                )
                timing["advise_ms"] = int((time.perf_counter() - t_adv) * 1000)
                for rec in result.get("recommendations", []):
                    rec["hotkey"] = verb_to_key(rec.get("verb", ""))
                if result.get("top_pick"):
                    result["top_pick"]["hotkey"] = verb_to_key(
                        result["top_pick"].get("verb", "")
                    )
                res_dict = resources.as_dict()
                res_dict["gold_status"] = gold_status
                if gold_status == "ocr":
                    res_dict["gold"] = gold
                elif gold_status == "last_good":
                    res_dict["gold"] = gold
                    res_dict.setdefault("warnings", []).append(
                        "gold using last_good=%s (OCR miss this frame)" % gold
                    )
                else:
                    # Keep gold None so shell won't gold0-battle
                    res_dict["gold"] = None
                    res_dict.setdefault("warnings", []).append(
                        "gold unrecognized — not treating as 0"
                    )
                # Fallback: upgrade hex cost sits above LEVEL (~cy 0.73, near tile).
                if res_dict.get("upgrade_cost") is None:
                    try:
                        uc = _upgrade_cost_from_shop_band(img, shop_rec._engine())
                        if uc is not None:
                            res_dict["upgrade_cost"] = uc
                            res_dict.setdefault("warnings", []).append(
                                "upgrade_cost from shop-band digit fallback"
                            )
                    except Exception:
                        pass
                # Patch upgrade action costs before shell filter sees them
                if res_dict.get("upgrade_cost") is not None:
                    uc_i = int(res_dict["upgrade_cost"])
                    tp = result.get("top_pick")
                    if isinstance(tp, dict) and str(tp.get("verb") or "").lower() in (
                        "upgrade", "升本", "升级", "level"
                    ):
                        tp = dict(tp)
                        tp["cost"] = max(int(tp.get("cost") or 0), uc_i)
                        result["top_pick"] = tp
                    new_recs = []
                    for r in result.get("recommendations") or []:
                        rr = dict(r)
                        if str(rr.get("verb") or "").lower() in (
                            "upgrade", "升本", "升级", "level"
                        ):
                            rr["cost"] = max(int(rr.get("cost") or 0), uc_i)
                        new_recs.append(rr)
                    result["recommendations"] = new_recs

                result["resources"] = res_dict
                # Capture size for glow: normalize OCR x0 → cx_frac on THIS frame
                # so shop_layout never divides by a stale hard-coded 2560.
                cap_w, cap_h = int(img.width), int(img.height)
                result["capture"] = {
                    "width": cap_w,
                    "height": cap_h,
                    "path": path,
                }
                shop_list = []
                for c in st.shop or []:
                    d = asdict(c)
                    raw = dict(d.get("raw") or {}) if isinstance(d.get("raw"), dict) else {}
                    x0 = raw.get("x0")
                    try:
                        x0f = float(x0) if x0 is not None else None
                    except (TypeError, ValueError):
                        x0f = None
                    if x0f is not None and cap_w > 0:
                        raw["image_width"] = cap_w
                        raw["image_height"] = cap_h
                        if x0f > 1.5:
                            raw["cx_frac"] = round(x0f / float(cap_w), 5)
                        else:
                            raw["cx_frac"] = round(x0f, 5)
                    d["raw"] = raw
                    shop_list.append(d)
                result["shop"] = shop_list
                board_list = [asdict(u) for u in (st.board or [])]
                result["board"] = board_list
                result["board_source"] = board_source
                result["equipment"] = dict(getattr(st, "equipment", None) or {})
                if board_err:
                    result.setdefault("notes", []).append(
                        "board_ocr: " + board_err
                    )

                # Enrich lineup: compass inferred + recommend_lineups(run_env)
                t_comps = time.perf_counter()
                result["target_comps"] = _build_target_comps(
                    result,
                    st,
                    board_list,
                    prefer_bonds=list(req.get("core_bonds") or []),
                )
                timing["comps_ms"] = int((time.perf_counter() - t_comps) * 1000)
                timing["vision_ms"] = int(
                    timing.get("resources_ms", 0)
                    + timing.get("enemy_panel_ms", 0)
                    + timing.get("board_ms", 0)
                    + timing.get("shop_ms", 0)
                )
                result["timing"] = timing
                result["enemy_panel"] = enemy_panel

                if isinstance(result.get("state"), dict):
                    result["state"]["shop"] = shop_list
                    result["state"]["board"] = board_list
                    result["state"]["dispatch_level"] = st.dispatch_level
                    result["state"]["round"] = st.round
                    # Only publish gold into state when OCR/last_good confirmed
                    if gold_status in ("ocr", "last_good"):
                        result["state"]["gold"] = gold
                    result["state"]["enemy_types"] = list(st.enemy_types or [])
                    result["state"]["banned_operators"] = list(
                        st.banned_operators or []
                    )
                    result["state"]["banned_bonds"] = list(st.banned_bonds or [])
                    result["state"]["equipment"] = dict(
                        getattr(st, "equipment", None) or {}
                    )
                    result["state"]["board_source"] = board_source
                out = {"ok": True, "result": result}
            elif op == "board_scan":
                # Ordinary-state head badges only (no click). Shell drives clicks.
                from vision.board_badge import detect_badges

                path = req["path"]
                t_load = time.perf_counter()
                img = Image.open(path).convert("RGB")
                load_ms = int((time.perf_counter() - t_load) * 1000)
                t_b = time.perf_counter()
                badges = detect_badges(img)
                scan_ms = int((time.perf_counter() - t_b) * 1000)
                rows = []
                for b in badges or []:
                    rows.append(
                        {
                            "cx": int(b.cx),
                            "cy": int(b.cy),
                            "cx_f": float(b.cx_f),
                            "cy_f": float(b.cy_f),
                            "score": float(b.score),
                            "tier_hint": int(b.tier) if b.tier is not None else None,
                        }
                    )
                out = {
                    "ok": True,
                    "result": {
                        "badges": rows,
                        "count": len(rows),
                        "capture": {"width": img.width, "height": img.height},
                        "timing": {"load_ms": load_ms, "board_scan_ms": scan_ms},
                    },
                }
            elif op == "panel_ocr":
                # Left detail panel: operator name + equipment (shell ROIs).
                from panel_unit_ocr import recognize_panel_unit

                path = req["path"]
                t_load = time.perf_counter()
                img = Image.open(path).convert("RGB")
                load_ms = int((time.perf_counter() - t_load) * 1000)
                op_names = [
                    o.get("name")
                    for o in (ds.operators or [])
                    if isinstance(o, dict) and o.get("name")
                ]
                item_names = [
                    i.get("name")
                    for i in (ds.items or [])
                    if isinstance(i, dict) and i.get("name")
                ]
                t_p = time.perf_counter()
                panel = recognize_panel_unit(
                    img,
                    operator_names=op_names,
                    item_names=item_names,
                    ocr_engine=shared_ocr,
                )
                panel_ms = int((time.perf_counter() - t_p) * 1000)
                panel["timing"] = {"load_ms": load_ms, "panel_ocr_ms": panel_ms}
                panel["capture"] = {"width": img.width, "height": img.height}
                out = {"ok": True, "result": panel}
            elif op == "enemy_panel":
                # Dedicated magnifier read (本局环境 refresh) — same API as shot.
                path = req["path"]
                t_load = time.perf_counter()
                img = Image.open(path).convert("RGB")
                load_ms = int((time.perf_counter() - t_load) * 1000)
                t_en = time.perf_counter()
                panel = _recognize_enemy_panel(
                    img, shared_ocr, enemy_name_index, enemy_catalog
                )
                panel_ms = int((time.perf_counter() - t_en) * 1000)
                panel["timing"] = {"load_ms": load_ms, "enemy_panel_ms": panel_ms}
                out = {"ok": True, "result": panel}
            elif op == "state":
                st = state_from_dict(req["state"])
                result = adv.recommend(
                    st, rounds_at_level=int(req.get("rounds_at_level") or 0)
                )
                for rec in result.get("recommendations", []):
                    rec["hotkey"] = verb_to_key(rec.get("verb", ""))
                if result.get("top_pick"):
                    result["top_pick"]["hotkey"] = verb_to_key(
                        result["top_pick"].get("verb", "")
                    )
                board_list = [asdict(u) for u in (st.board or [])]
                result["board"] = board_list
                prefer = list(req.get("core_bonds") or [])
                result["target_comps"] = _build_target_comps(
                    result, st, board_list, prefer_bonds=prefer
                )
                out = {"ok": True, "result": result}
            elif op == "lineups":
                # Refresh companion comps from board + run_env without shop OCR.
                board_payload = list(req.get("board") or [])
                prefer = list(req.get("core_bonds") or [])
                eq = req.get("equipment") if isinstance(req.get("equipment"), dict) else {}
                st = state_from_dict(
                    {
                        "round": int(req.get("round") or 1),
                        "gold": int(req.get("gold") or 0),
                        "dispatch_level": int(req.get("dispatch_level") or 1),
                        "difficulty": req.get("difficulty") or "standard",
                        "target_bond": req.get("target_bond") or None,
                        "enemy_types": list(req.get("enemy_types") or []),
                        "banned_operators": list(req.get("banned_operators") or []),
                        "banned_bonds": list(req.get("banned_bonds") or []),
                        "board": board_payload,
                        "equipment": eq,
                        "shop": [],
                    }
                )
                _apply_regulation_level(st, req)
                result = adv.recommend(
                    st, rounds_at_level=int(req.get("rounds_at_level") or 0)
                )
                board_list = [asdict(u) for u in (st.board or [])]
                result["board"] = board_list
                result["target_comps"] = _build_target_comps(
                    result, st, board_list, prefer_bonds=prefer
                )
                result["state"] = st.to_dict()
                out = {"ok": True, "result": result}
            elif op == "opening":
                # Capture→parse 难度选择 / 合约/策略/自选. Reuses warm RapidOCR.
                path = req["path"]
                img = Image.open(path).convert("RGB")
                parsed = _parse_opening_image(img, shop_rec._engine(), ds)
                out = {"ok": True, "result": parsed}
            else:
                out = {"ok": False, "error": f"unknown op {op!r}"}
        except Exception as e:
            out = {"ok": False, "error": str(e)}
        out["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
