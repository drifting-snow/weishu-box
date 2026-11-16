# -*- coding: utf-8 -*-
"""CLI: self-play episode / eval cards / hillclimb.

Examples:
  python tools/selfplay_hillclimb.py episode --seed 1 --max-rounds 5
  python tools/selfplay_hillclimb.py eval --suite smoke
  python tools/selfplay_hillclimb.py hillclimb --suite smoke --param gap.cap
  python tools/selfplay_hillclimb.py list-params
  python tools/selfplay_hillclimb.py list-cards --suite core
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Allow `python tools/selfplay_hillclimb.py` from advisor/ without install -e.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Advisor self-play / hillclimb scaffold")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ep = sub.add_parser("episode", help="Run one episode")
    p_ep.add_argument("--seed", type=int, default=0)
    p_ep.add_argument("--max-rounds", type=int, default=8)
    p_ep.add_argument("--regulation-level", type=int, default=1)
    p_ep.add_argument("--income-flat", type=int, default=None)
    p_ep.add_argument("--no-battle", action="store_true")

    p_ev = sub.add_parser("eval", help="Run fixed-seed eval card suite")
    p_ev.add_argument("--suite", type=str, default="smoke")
    p_ev.add_argument("--full", action="store_true",
                      help="Include per-card episode logs (large)")

    p_hc = sub.add_parser("hillclimb", help="One random 1-D hillclimb step")
    p_hc.add_argument("--seed", type=int, default=0)
    p_hc.add_argument("--episodes", type=int, default=2)
    p_hc.add_argument("--max-rounds", type=int, default=5)
    p_hc.add_argument("--regulation-level", type=int, default=1)
    p_hc.add_argument("--param", type=str, default=None)
    p_hc.add_argument("--suite", type=str, default="smoke",
                      help="Eval card suite (default smoke). Use '' for seed sweep.")

    sub.add_parser("list-params", help="List tunable knobs")

    p_lc = sub.add_parser("list-cards", help="List eval cards in a suite")
    p_lc.add_argument("--suite", type=str, default="smoke")

    args = parser.parse_args(argv)

    if args.cmd == "list-params":
        from advisor.selfplay.params import list_params, param_catalog
        catalog = {row["key"]: row for row in param_catalog()}
        for key, note, lo, hi, step in list_params():
            default = catalog.get(key, {}).get("default")
            print("%s\t[%s,%s] step=%s\tdefault=%s\t%s" % (
                key, lo, hi, step, default, note))
        return 0

    if args.cmd == "list-cards":
        from advisor.selfplay.eval_harness import list_cards, load_eval_doc
        doc = load_eval_doc()
        cards = list_cards(doc, suite=args.suite)
        for c in cards:
            print("%s\tseed=%s\tmax_rounds=%s\t%s" % (
                c.get("id"), c.get("seed"), c.get("max_rounds"), c.get("note") or ""))
        return 0

    if args.cmd == "episode":
        from advisor.selfplay.episode import run_episode
        from advisor.selfplay.objective import score_episode
        out = run_episode(
            seed=args.seed,
            max_rounds=args.max_rounds,
            regulation_level=args.regulation_level,
            income_flat=args.income_flat,
            use_battle=not args.no_battle,
        )
        out = dict(out)
        out["score"] = score_episode(out)
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    if args.cmd == "eval":
        from advisor.selfplay.eval_harness import evaluate_on_cards
        out = evaluate_on_cards(suite=args.suite)
        if not args.full:
            out = dict(out)
            out.pop("detail", None)
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    if args.cmd == "hillclimb":
        from advisor.selfplay.hillclimb import hillclimb_step
        import random
        suite = args.suite if args.suite not in ("", "none", "null") else None
        out = hillclimb_step(
            seed0=args.seed,
            episodes=args.episodes,
            max_rounds=args.max_rounds,
            regulation_level=args.regulation_level,
            param_key=args.param,
            rng=random.Random(args.seed),
            suite=suite,
        )
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
