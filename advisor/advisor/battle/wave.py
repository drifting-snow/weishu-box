# -*- coding: utf-8 -*-
"""Spawn scheduling and wave-pressure (reservoir) model (clean-room).

WaveScheduler turns a declarative spawn table into time-ordered spawn events,
mirroring the structure of the reference waves (time / enemy / count / interval
/ route) without reading any of its data files.

ReservoirPressure quantifies front-line pressure when a later wave arrives
before an earlier wave is cleared: each blocking tile is a reservoir whose
level L(t) fills at the enemy inflow rate lambda and drains at the defenders'
effective kill rate mu, discretised per tick.
"""

from dataclasses import dataclass, field
from typing import List, Dict

from .clock import TICK
from .constants import MOVE_SCALE


@dataclass
class SpawnSpec:
    """One spawn line: `count` enemies of `enemy_key`, first at `start_time`,
    one every `interval` seconds, travelling `route_index`."""
    start_time: float
    enemy_key: str
    count: int = 1
    interval: float = 0.0
    route_index: int = 0
    # Per-enemy travel time (s) from red gate to the blocking tile / blue gate.
    travel_time: float = 0.0


@dataclass
class SpawnEvent:
    time: float
    enemy_key: str
    route_index: int
    seq: int


class WaveScheduler:
    """Expands SpawnSpec lines into an ordered, tick-aligned event queue."""

    def __init__(self, specs: List[SpawnSpec]):
        self._queue = self._expand(specs)
        self._cursor = 0

    @staticmethod
    def _expand(specs):
        events = []
        seq = 0
        for spec in specs:
            for i in range(max(1, spec.count)):
                t = spec.start_time + i * max(0.0, spec.interval)
                events.append(SpawnEvent(t, spec.enemy_key,
                                         spec.route_index, seq))
                seq += 1
        events.sort(key=lambda e: (e.time, e.seq))
        return events

    def due(self, now):
        """Pop and return every event due at or before game time `now`."""
        out = []
        while self._cursor < len(self._queue) \
                and self._queue[self._cursor].time <= now + 1e-9:
            out.append(self._queue[self._cursor])
            self._cursor += 1
        return out

    def pending(self):
        return len(self._queue) - self._cursor


@dataclass
class TileReservoir:
    """Pressure accumulator for one blocking tile (the 'reservoir')."""
    key: object
    level: float = 0.0                 # enemies currently pressing the tile
    capacity: int = 0                  # blocker capacity (for leak threshold)
    inflow: float = 0.0                # lambda: enemies arriving per second
    kill_rate: float = 0.0             # mu: effective kills per second
    peak: float = 0.0
    overflow_time: float = 0.0         # seconds spent over capacity (leak risk)

    def update(self, dt):
        # Discrete reservoir balance: fill at inflow, drain at kill rate.
        self.level = max(0.0, self.level + (self.inflow - self.kill_rate) * dt)
        self.peak = max(self.peak, self.level)
        if self.capacity > 0 and self.level > self.capacity:
            self.overflow_time += dt


class ReservoirPressure:
    """Holds one TileReservoir per blocking tile and advances them each tick.

    Inflow is supplied externally (from spawn events + route travel delay), and
    kill rate from the defenders' effective DPS / enemy effective HP. This is
    the mathematical form of 'first 10s normal spawn, 10-20s the uncleared prior
    wave stacks with the next wave': stacking simply raises `level` whenever
    inflow exceeds the drain.
    """

    def __init__(self):
        self.tiles: Dict[object, TileReservoir] = {}

    def reservoir(self, key, capacity=0):
        if key not in self.tiles:
            self.tiles[key] = TileReservoir(key=key, capacity=capacity)
        return self.tiles[key]

    def set_inflow(self, key, rate):
        self.reservoir(key).inflow = max(0.0, rate)

    def set_kill_rate(self, key, effective_dps, enemy_effective_hp):
        """mu = effective DPS / effective HP (enemies cleared per second)."""
        res = self.reservoir(key)
        if enemy_effective_hp > 0:
            res.kill_rate = max(0.0, effective_dps / enemy_effective_hp)
        else:
            res.kill_rate = 0.0

    def step(self, dt=TICK):
        for res in self.tiles.values():
            res.update(dt)

    def leak_risk(self):
        """Tiles whose level exceeds blocker capacity (front line breaking)."""
        return {k: r for k, r in self.tiles.items()
                if r.capacity > 0 and r.level > r.capacity}

    def snapshot(self):
        return {
            str(k): {
                "level": round(r.level, 3),
                "peak": round(r.peak, 3),
                "capacity": r.capacity,
                "inflow_per_s": round(r.inflow, 3),
                "kill_per_s": round(r.kill_rate, 3),
                "overflow_seconds": round(r.overflow_time, 2),
            }
            for k, r in self.tiles.items()
        }


def travel_seconds(move_speed, distance_tiles):
    """Reference movement conversion: tiles/s = moveSpeed * MOVE_SCALE."""
    speed = move_speed * MOVE_SCALE
    if speed <= 0:
        return float("inf")
    return distance_tiles / speed
