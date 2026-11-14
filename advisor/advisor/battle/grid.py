# -*- coding: utf-8 -*-
"""Tile grid and occupancy map (clean-room, first cut).

A lightweight rectangle grid that tracks which ally occupies each tile and
exposes passability/deployability. Full ASCII-map parsing (red/blue gates,
routes, high/low tiles) is an extension point fed later by range/stage tables.
"""


class Grid:
    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols
        # (row, col) -> Unit occupant (blockers).
        self.occupancy = {}
        # Per-tile passability: 'ALL' | 'GROUND' | 'NONE'. Default all passable.
        self.pass_map = {}

    def in_bounds(self, r, c):
        return 0 <= r < self.rows and 0 <= c < self.cols

    def tile_pass(self, r, c):
        return self.pass_map.get((r, c), "ALL")

    def set_pass(self, r, c, passability):
        self.pass_map[(r, c)] = passability

    def occupy(self, unit, r, c):
        unit.tile_r, unit.tile_c = r, c
        unit.x, unit.y = float(c), float(r)
        self.occupancy[(r, c)] = unit

    def vacate(self, r, c):
        self.occupancy.pop((r, c), None)

    def occupant(self, r, c):
        return self.occupancy.get((r, c))
