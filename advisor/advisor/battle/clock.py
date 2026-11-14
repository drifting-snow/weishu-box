# -*- coding: utf-8 -*-
"""Deterministic tick clock."""

from .constants import TICK


class Clock:
    """Integer tick counter; game time is derived, never accumulated by +=."""

    def __init__(self):
        self.tick_count = 0

    @property
    def dt(self):
        return TICK

    @property
    def time(self):
        # Derived from the integer tick count: no float drift over long runs.
        return self.tick_count * TICK

    def advance(self):
        self.tick_count += 1
        return self.time

    def seconds_to_ticks(self, seconds):
        """Round a game-time duration to the nearest whole tick."""
        return int(round(seconds / TICK))
