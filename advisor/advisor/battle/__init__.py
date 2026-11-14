# -*- coding: utf-8 -*-
"""Clean-room battlefield simulation kernel (independent Python rewrite).

This package re-implements the *methodology* observed in the Stronghold-Protocol
reference (tick loop, stat aggregation, damage pipeline, blocking, spawn/wave
pressure). No source code or data file from that GPL-3.0 project is imported or
copied; every numeric constant here is a public Arknights game-mechanics fact,
and the structure is our own design. See docs/stronghold_engine_mapping.md for
the field/method cross-reference used during validation.

First-cut scope: deterministic tick clock, stat aggregation (with the correct
BAT/ASPD interval rule), damage trunk, contact blocking and a spawn/wave
pressure (reservoir) model. DP, projectiles, element gauges and boss pools are
left as explicit extension points.
"""

from .clock import TICK, Clock
from .unit import Unit, Stats
from . import damage
from . import blocking
from .wave import WaveScheduler, ReservoirPressure
from .battle import Battle

__all__ = [
    "TICK",
    "Clock",
    "Unit",
    "Stats",
    "damage",
    "blocking",
    "WaveScheduler",
    "ReservoirPressure",
    "Battle",
]
