"""The threshold grids and probability maths, shared by writer and scorer.

Kept in its own module rather than in forecast.py because `forecast` is both a
module name and the package directory name, and `import forecast` resolving to
the wrong one depending on how the script was invoked is exactly the kind of
bug that silently changes which columns get scored.

Two grids live here and they are emphatically not the same thing:

  - **THRESHOLDS_C** — what gets *stored*, in cents relative to the level at
    forecast time. Load-bearing; see DESIGN.md §6.4. Never make these absolute.
  - **DISPLAY_STEP** — what gets *shown*: absolute prices rounded to a readable
    increment. Purely cosmetic, recomputed from mu and sigma at render time,
    and touching nothing on disk.
"""

from __future__ import annotations

import math

# P(change > c) is stored for these thresholds, in cents, always **relative to
# the level at forecast time** — DESIGN.md §6.4. Absolute thresholds would make
# each day a structurally different bet, some of them already resolved before
# being asked, and pooling those into a reliability curve is meaningless.
THRESHOLDS_C = [-2.0, -1.0, 0.0, 1.0, 2.0]

# The only genuinely hard threshold. In smoke testing ±2c scored a Brier of
# 0.0002 against a 100% base rate — resolved before it was asked. Report all
# five; judge the system on this one, secondarily ±1c.
HEADLINE_THRESHOLD_C = 0.0

# Display increment for absolute prices: half a cent. "Is it above $3.995?" is
# a question a person can hold in their head; "is it above $3.9921?" is not.
# This affects presentation only — see the module docstring.
DISPLAY_STEP = 0.005

# How far either side of the centre the displayed ladder reaches. 2.5 sigma
# covers ~99% of the predictive distribution, so the ends are near-certainties
# that usefully bracket the interesting middle.
DISPLAY_SPAN_SIGMAS = 2.5


def threshold_key(threshold_c: float) -> str:
    """-2.0 -> 'm2c', 0.0 -> '0c', 1.0 -> 'p1c'."""
    if threshold_c == 0:
        return "0c"
    sign = "m" if threshold_c < 0 else "p"
    magnitude = abs(threshold_c)
    text = str(int(magnitude)) if magnitude == int(magnitude) else str(magnitude)
    return f"{sign}{text}c"


PROB_COLUMNS = [f"p_gt_{threshold_key(c)}" for c in THRESHOLDS_C]


def prob_greater_than(threshold_c: float, mu_c: float, sigma_c: float) -> float:
    """P(change > threshold) under the Gaussian predictive distribution.

    math.erfc rather than scipy.stats.norm.sf — it keeps scipy out of the
    dependency set for one function, and is exact to double precision.
    """
    if sigma_c <= 0:
        return 1.0 if mu_c > threshold_c else 0.0
    return 0.5 * math.erfc((threshold_c - mu_c) / (sigma_c * math.sqrt(2.0)))


def prob_above_price(
    price: float, level: float, mu_c: float, sigma_c: float
) -> float:
    """P(tomorrow's price > `price`), for any absolute price in dollars.

    This is the §5.2 property in action: storing mu and sigma rather than only
    the five threshold probabilities means any absolute price is recoverable
    afterwards, including ones nobody thought to ask about at forecast time.
    """
    return prob_greater_than((price - level) * 100.0, mu_c, sigma_c)


def snap(value: float, step: float = DISPLAY_STEP, mode: str = "nearest") -> float:
    """Round `value` onto the display grid.

    `mode` matters for interval endpoints. Rounding an 80% interval inward
    would state a range narrower than the one actually claimed — a small lie in
    the direction of overconfidence, which is the failure this project spends
    most of its effort avoiding. Endpoints therefore snap outward ('down' for
    the low end, 'up' for the high), making the displayed range contain *at
    least* the stated probability.
    """
    scaled = value / step
    if mode == "down":
        scaled = math.floor(scaled)
    elif mode == "up":
        scaled = math.ceil(scaled)
    else:
        scaled = math.floor(scaled + 0.5)
    # Re-round the product: 0.005 has no exact binary representation, so the
    # multiply can land on 3.9949999999999997 and print as $3.9950 anyway, but
    # comparisons against it would be off.
    return round(scaled * step, 10)


def price_ladder(
    level: float,
    mu_c: float,
    sigma_c: float,
    step: float = DISPLAY_STEP,
    span_sigmas: float = DISPLAY_SPAN_SIGMAS,
) -> list[tuple[float, float]]:
    """[(price, P(tomorrow > price)), ...] on the display grid, ascending.

    Spans `span_sigmas` either side of the predictive centre, so the ladder
    adapts to how uncertain the forecast is rather than being a fixed width.
    """
    centre = level + mu_c / 100.0
    reach = max(span_sigmas * sigma_c / 100.0, step)
    low = snap(centre - reach, step, "up")
    high = snap(centre + reach, step, "down")

    rungs: list[tuple[float, float]] = []
    steps = int(round((high - low) / step)) if high >= low else -1
    for i in range(steps + 1):
        price = round(low + i * step, 10)
        rungs.append((price, prob_above_price(price, level, mu_c, sigma_c)))
    return rungs
