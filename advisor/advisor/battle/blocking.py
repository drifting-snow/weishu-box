# -*- coding: utf-8 -*-
"""Contact blocking (clean-room).

An unblocked enemy is blocked when its centre is inside the blocker's block
radius (squared-distance compare) and the blocker has free capacity for the
enemy's block weight. Checked every tick over the blocker's 3x3 neighbour
tiles; the nearest qualifying blocker wins, ties broken by scan order.

The first cut models ground blocking plus an explicit flying flag; fence-tile
and stealth-restore nuances are kept as extension points.
"""

from .constants import (
    BLOCK_RADIUS_GROUND_SQ, BLOCK_RADIUS_FLY_SQ, BLOCK_RADIUS_DEVICE_SQ,
)


def _radius_sq(kind, flying):
    if kind == "device":
        return BLOCK_RADIUS_DEVICE_SQ
    if flying:
        return BLOCK_RADIUS_FLY_SQ
    return BLOCK_RADIUS_GROUND_SQ


def _used_capacity(blocker):
    total = 0
    for e in blocker.blocking:
        total += getattr(e, "block_weight", 1)
    return total


def _can_block(blocker, enemy, flying):
    """Capacity / eligibility gate excluding the contact distance."""
    if not blocker.alive or not blocker.deployed:
        return False
    if getattr(blocker, "hidden", False):
        return False
    flags = getattr(blocker, "flags", {}) or {}
    if flags.get("noBlock") or flags.get("sleep") or flags.get("noNewBlock"):
        return False
    if flying and not (flags.get("blockFly")
                       or getattr(blocker, "block_fly", False)):
        return False
    if not flying:
        # Ground enemies need a ground unit that has not lifted off.
        if not getattr(blocker, "ground", True) or flags.get("liftoff"):
            return False
    cap = blocker.stats.block_cnt
    if cap <= 0:
        return False
    weight = getattr(enemy, "block_weight", 1)
    return _used_capacity(blocker) + weight <= cap


def check_block(enemy, occupancy):
    """Try to block `enemy` given an occupancy map {(row, col): blocker Unit}.

    Returns the blocker that now holds the enemy, or None. Mutates
    `enemy.blocked_by` and `blocker.blocking` exactly like the reference.
    """
    if getattr(enemy, "blocked_by", None) is not None:
        return enemy.blocked_by
    if not enemy.alive:
        return None
    flags = getattr(enemy, "flags", {}) or {}
    if flags.get("unblockable") or flags.get("levitate") \
            or flags.get("fear") or flags.get("sleep"):
        return None

    flying = bool(getattr(enemy, "is_flying", False))
    r0 = round(enemy.y)
    c0 = round(enemy.x)
    radius_sq = _radius_sq(getattr(enemy, "kind", "enemy"), flying)

    best = None
    best_d2 = float("inf")
    for r in range(r0 - 1, r0 + 2):
        for c in range(c0 - 1, c0 + 2):
            # Diagonal neighbours are beyond the ground/device radius.
            if not flying and r != r0 and c != c0:
                continue
            blocker = occupancy.get((r, c))
            if blocker is None:
                continue
            if not _can_block(blocker, enemy, flying):
                continue
            d2 = (enemy.x - c) ** 2 + (enemy.y - r) ** 2
            limit = _radius_sq(getattr(blocker, "kind", "op"), flying)
            if d2 < limit and d2 < best_d2:
                best = blocker
                best_d2 = d2

    if best is None:
        return None

    enemy.blocked_by = best
    best.blocking.append(enemy)
    enemy.moving = False
    return best


def unblock(enemy):
    """Release one enemy from its blocker (block end)."""
    blocker = getattr(enemy, "blocked_by", None)
    if blocker is None:
        return
    if enemy in blocker.blocking:
        blocker.blocking.remove(enemy)
    enemy.blocked_by = None


def release_blocked(blocker):
    """Release every enemy a blocker holds (death / retreat / capacity drop)."""
    for e in list(blocker.blocking):
        if getattr(e, "blocked_by", None) is blocker:
            e.blocked_by = None
    blocker.blocking = []
