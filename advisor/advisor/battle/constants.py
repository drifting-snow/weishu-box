# -*- coding: utf-8 -*-
"""Public game-mechanics constants for the clean-room battle kernel.

Values are documented Arknights mechanics (the same facts the reference engine
encodes); they are tuning data, not copyrighted expression.
"""

# Fixed simulation step in game seconds (30 Hz). Time is always derived from an
# integer tick count so long battles accumulate no floating-point drift.
TICK = 1.0 / 30.0

# Damage.
MIN_DAMAGE_RATIO = 0.05      # 5% minimum-damage floor after mitigation.
RES_CAP = 95.0               # Arts resistance hard cap.
RES_FLOOR = 0.0              # Negative RES is clamped to 0 in our trunk.

# Attack speed (ASPD points; 100 = baseline).
ASPD_MIN = 20.0
ASPD_MAX = 600.0
BASE_ASPD = 100.0
# BAT percentage modifier is floored at -90% (BAT cannot shrink below 10%).
BAT_PCT_FLOOR = -0.9
BAT_PCT_ABS_FLOOR = 0.1

# Movement: tiles/second = moveSpeed * MOVE_SCALE.
MOVE_SCALE = 0.5

# Collider radii (tiles).
ALLY_COLLIDER_RADIUS = 0.25
ENEMY_COLLIDER_RADIUS = 0.1

# Contact block radii (ground uses the tile circumscribed circle).
BLOCK_RADIUS_GROUND_SQ = 0.49999037   # sqrt ~= 0.70709997
BLOCK_RADIUS_FLY_SQ = 0.79995137      # sqrt ~= 0.8944
BLOCK_RADIUS_DEVICE_SQ = 0.4472 * 0.4472

# Stealth re-engages this long after a block ends.
STEALTH_RESTORE_SECONDS = 3.0

# Default deployment-point rules (extension point; not driven in first cut).
DP_INIT = 10
DP_PER_SEC = 1
DP_MAX = 99
