import math
from Shared import *

# ------------------ Constants ------------------ #

### The minimum tick that may be passed to #getPriceAtTick so the price obtained is > 0. This happens because pricex96 can be zero
# in some ticks while sqrtPricex96 will not).
MIN_TICK_LO = -665455
### The maximum tick that may be passed to #getPriceAtTick - symetric to MIN_TICK_LO
MAX_TICK_LO = -MIN_TICK_LO


# ------------------ Shared dataclasses ------------------ #


@dataclass
class TickInfoLimit:
    ## the total position liquidity that references this tick
    liquidityGross: int

    # accomulated percentatge of the pool swapped - relative meaning. Storing 1 minus the value
    # Possibly using floating point number with 256 in both the mantissa and the exponent.
    # For now, in python using Decimal to get more precision than a simple float and to be able
    # to achieve better rounding. Initial value should be one.
    oneMinusPercSwap: Decimal

    ## fee growth per unit of liquidity on the _other_ side of this tick (relative to the current tick)
    ## only has relative meaning, not absolute — the value depends on when the tick is initialized.
    ## In the token opposite to the liquidity token.
    feeGrowthInsideX128: int

    # list of owners of positions contained in this tick. We can't just store the hash because then we can't
    # know who is the owner. So we need to recalculate the hash when we burn the position. We only require the
    # owner since we figure out the isToken0 and the tick.
    # NOTE: We could also store the hash(which is the key to the dict) to not keep straight reference to the LPs
    # and to skip recomputing the has when burning the position.
    ownerPositions: list


# ------------------ Shared utility functions ------------------ #


def insertUninitializedLimitTickstoMapping(mapping, keys):
    for key in keys:
        insertTickInMapping(mapping, key, TickInfoLimit(0, Decimal(1), 0, []))


def getMinTickLO(tickSpacing):
    return math.ceil(MIN_TICK_LO / tickSpacing) * tickSpacing


def getMaxTickLO(tickSpacing):
    return math.floor(MAX_TICK_LO / tickSpacing) * tickSpacing
