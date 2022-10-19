from uniswapV3Python.src.libraries.Shared import *
from uniswapV3Python.src.libraries import FullMath, TickMath

### @notice Computes the price at a tick.
### @dev There are better ways to do this since getting the sqrtPrice and then squaring it
### won't give full precision and is computationally expensive. For example something similar
### to what is done in TickMath is better but it's irrelevant for this model.
### @param tick The current tick
### @return tick The price at the tick
def getPriceAtTick(tick):
    checkInt24(tick)
    sqrtPriceX96 = TickMath.getSqrtRatioAtTick(tick)
    # Writing explicit muldiv to show that this the multiplication will "overflow"
    priceX96 = FullMath.mulDiv(sqrtPriceX96, sqrtPriceX96, FixedPoint96_Q96)
    # sqrtPriceX96 is a uint160 with 96 decimals. For priceX96 we keep the 96 decimals
    # so we need extra bits => 160-96 = 64 bits. So we need 160+64 = 224 bits
    # We check for 256 here.
    checkUInt256(priceX96)

    return priceX96
