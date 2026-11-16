# -*- coding: utf-8 -*-
"""CLI: minimal self-play episode / one hillclimb step.

Examples:
  python tools/selfplay_hillclimb.py episode --seed 1 --max-rounds 5
  python tools/selfplay_hillclimb.py hillclimb --episodes 2 --max-rounds 5
  python tools/selfplay_hillclimb.py list-params
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

    p_hc = sub.add_parser("hillclimb", help="One random 1-D hillclimb step")
    p_hc.add_argument("--seed", type=int, default=0)
    p_hc.add_argument("--episodes", type=int, default=2)
    p_hc.add_argument("--max-rounds", type=int, default=5)
    p_hc.add_argument("--regulation-level", type=int, default=1)
    p_hc.add_argument("--param", type=str, default=None)

    sub.add_parser("list-params", help="List tunable knobs")

    args = parser.parse_args(argv)

    if args.cmd == "list-params":
        from advisor.selfplay.params import list_params
        for key, note, lo, hi, step in list_params():
            print("%s\t[%s,%s] step=%s\t%s" % (key, lo, hi, step, note))
        return 0

    if args.cmd == "episode":
        from advisor.selfplay.episode import run_episode
        out = run_episode(
            seed=args.seed,
            max_rounds=args.max_rounds,
            regulation_level=args.regulation_level,
            income_flat=args.income_flat,
            use_battle=not args.no_battle,
        )
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    if args.cmd == "hillclimb":
        from advisor.selfplay.hillclimb import hillclimb_step
        import random
        out = hillclimb_step(
            seed0=args.seed,
            episodes=args.episodes,
            max_rounds=args.max_rounds,
            regulation_level=args.regulation_level,
            param_key=args.param,
            rng=random.Random(args.seed),
        )
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
