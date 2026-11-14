# -*- coding: utf-8 -*-
"""Reshape early (~4-6) and mid (exactly 8, includes early) from late=8 comps."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "data"
PATH = ROOT / "lineups.json"


def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    ops = {
        o["name"]: o
        for o in json.loads((ROOT / "operators.json").read_text(encoding="utf-8"))
    }

    def bonds_of(name: str) -> list[str]:
        return list((ops.get(name) or {}).get("bonds") or [])

    def bond_counts(names: list[str], focus: list[str] | None = None) -> dict[str, int]:
        c: Counter[str] = Counter()
        for n in names:
            for b in bonds_of(n):
                c[b] += 1
        if focus:
            # core + splash first, then others with count>0
            out = {b: c[b] for b in focus if c.get(b)}
            for b, n in c.most_common():
                if b not in out and n > 0:
                    out[b] = n
            return out
        return dict(c.most_common())

    def unit_map(lineup: dict) -> dict[str, dict]:
        m: dict[str, dict] = {}
        for sk in ("late", "mid", "early"):
            for u in ((lineup.get("stages") or {}).get(sk) or {}).get("units") or []:
                if u.get("name") in ops:
                    m[u["name"]] = dict(u)
        for lst, role in (
            (lineup.get("carry") or [], "carry"),
            (lineup.get("tank") or [], "tank"),
            (lineup.get("heal") or [], "heal"),
        ):
            for n in lst:
                if n in ops and n not in m:
                    m[n] = {
                        "name": n,
                        "tier": int(ops[n].get("shop_tier") or 1),
                        "role": role,
                        "note": "",
                    }
        return m

    def make_unit(name: str, umap: dict[str, dict], note: str = "") -> dict:
        base = umap.get(name) or {}
        o = ops[name]
        return {
            "name": name,
            "tier": int(base.get("tier") or o.get("shop_tier") or 1),
            "role": base.get("role")
            or (
                "heal"
                if "医疗" in (o.get("prof") or "")
                else "tank"
                if "重装" in (o.get("prof") or "")
                else "carry"
            ),
            "note": note or base.get("note") or ("/".join(bonds_of(name)[:3])),
        }

    for L in data["lineups"]:
        stages = L["stages"]
        late_names = [u["name"] for u in stages["late"]["units"] if u.get("name") in ops]
        assert len(late_names) == 8, L["id"]
        umap = unit_map(L)
        cores = list(L.get("core_bonds") or [])
        splash = list(L.get("splash_bonds") or [])
        focus = cores + splash

        old_early = [
            u["name"]
            for u in (stages.get("early") or {}).get("units") or []
            if u.get("name") in ops
        ]
        # Prefer low-tier late members for early transition; keep old early if in late
        late_by_tier = sorted(
            late_names,
            key=lambda n: (
                0 if n in old_early else 1,
                int(ops[n].get("shop_tier") or 9),
                n,
            ),
        )
        # early size 4-6: aim 5, clamp by needing at least 1 of each core if possible
        early_n = 5
        if len(late_names) < 5:
            early_n = len(late_names)
        early: list[str] = []
        # seed with old early that appear in late
        for n in old_early:
            if n in late_names and n not in early:
                early.append(n)
            if len(early) >= early_n:
                break
        for n in late_by_tier:
            if len(early) >= early_n:
                break
            if n not in early:
                early.append(n)
        # ensure each core has >=1 in early when late has that bond
        for c in cores:
            if any(c in bonds_of(n) for n in early):
                continue
            cand = next((n for n in late_names if c in bonds_of(n) and n not in early), None)
            if cand is None:
                continue
            # swap highest-tier non-core-unique
            swap_i = None
            for i in range(len(early) - 1, -1, -1):
                # don't remove if it is the only holder of another core
                early[i]  # noqa
                swap_i = i
                break
            if swap_i is not None and len(early) >= early_n:
                early[swap_i] = cand
            elif cand not in early and len(early) < 6:
                early.append(cand)
        early = early[:6]
        if len(early) < 4:
            for n in late_by_tier:
                if n not in early:
                    early.append(n)
                if len(early) >= 4:
                    break

        # mid = best 8: start with early, fill from late (prefer remaining late order)
        mid: list[str] = []
        for n in early:
            if n not in mid:
                mid.append(n)
        for n in late_names:
            if n not in mid:
                mid.append(n)
            if len(mid) >= 8:
                break
        # if early had units not in late (shouldn't), drop them
        mid = [n for n in mid if n in late_names][:8]
        while len(mid) < 8:
            for n in late_names:
                if n not in mid:
                    mid.append(n)
                if len(mid) >= 8:
                    break

        assert 4 <= len(early) <= 6, (L["id"], early)
        assert len(mid) == 8, (L["id"], mid)
        assert set(early).issubset(set(late_names))
        assert set(early).issubset(set(mid))

        stages["early"]["units"] = [
            make_unit(n, umap, note="过渡 · " + "/".join(bonds_of(n)[:2])) for n in early
        ]
        stages["early"]["pop"] = str(len(early))
        stages["early"]["plan_fielded"] = len(early)
        stages["early"]["bond_counts"] = bond_counts(early, focus)
        eg = (stages["early"].get("goal") or "").split("；")[0]
        stages["early"]["goal"] = (
            f"{eg}；过渡上场 {len(early)} 人（含核心种子）。"
            if eg
            else f"过渡上场 {len(early)} 人。"
        )

        stages["mid"]["units"] = [
            make_unit(
                n,
                umap,
                note=("承接 early · " if n in early else "中期补强 · ")
                + "/".join(bonds_of(n)[:2]),
            )
            for n in mid
        ]
        stages["mid"]["pop"] = "8"
        stages["mid"]["plan_fielded"] = 8
        stages["mid"]["bond_counts"] = bond_counts(mid, focus)
        mg = (stages["mid"].get("goal") or "").split("；")[0]
        stages["mid"]["goal"] = (
            f"{mg}；中期满编 8（含 early {len(early)} 人）。"
            if mg
            else f"中期满编 8（含 early {len(early)} 人）。"
        )

        stages["late"]["bond_counts"] = bond_counts(late_names, focus)
        # also annotate late units lightly
        for u in stages["late"]["units"]:
            u.setdefault("note", "/".join(bonds_of(u["name"])[:3]))

        print(
            L["id"],
            f"e={len(early)}",
            early,
            "m=8",
            mid,
            "bonds_late",
            stages["late"]["bond_counts"],
        )

    meta = data.setdefault("_meta", {})
    meta["population"] = (
        "游戏板位恒 8。early=过渡 4–6 人（late 子集）；"
        "mid=满编 8 且包含 early；late=满编 8。"
    )
    meta["stage_curve"] = "early_4to6_subset → mid_8_includes_early → late_8"
    ver = str(meta.get("version") or "1.0")
    if "+em8" not in ver:
        meta["version"] = ver + "+em8"

    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("WROTE", PATH)


if __name__ == "__main__":
    main()
