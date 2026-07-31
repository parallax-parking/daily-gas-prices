"""The threshold grid, shared by the writer and the scorer.

Kept in its own module rather than in forecast.py because `forecast` is both a
module name and the package directory name, and `import forecast` resolving to
the wrong one depending on how the script was invoked is exactly the kind of
bug that silently changes which columns get scored.
"""

from __future__ import annotations

# P(change > c) is stored for these thresholds, in cents, always **relative to
# the level at forecast time** — DESIGN.md §6.4. Absolute thresholds would make
# each day a structurally different bet, some of them already resolved before
# being asked, and pooling those into a reliability curve is meaningless.
THRESHOLDS_C = [-2.0, -1.0, 0.0, 1.0, 2.0]

# The only genuinely hard threshold. In smoke testing ±2c scored a Brier of
# 0.0002 against a 100% base rate — resolved before it was asked. Report all
# five; judge the system on this one, secondarily ±1c.
HEADLINE_THRESHOLD_C = 0.0


def threshold_key(threshold_c: float) -> str:
    """-2.0 -> 'm2c', 0.0 -> '0c', 1.0 -> 'p1c'."""
    if threshold_c == 0:
        return "0c"
    sign = "m" if threshold_c < 0 else "p"
    magnitude = abs(threshold_c)
    text = str(int(magnitude)) if magnitude == int(magnitude) else str(magnitude)
    return f"{sign}{text}c"


PROB_COLUMNS = [f"p_gt_{threshold_key(c)}" for c in THRESHOLDS_C]
