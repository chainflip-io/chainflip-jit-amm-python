import math

from uniswapV3Python.src.libraries import FullMath
from uniswapV3Python.src.libraries.Shared import *

from decimal import *

### @notice Calculates the amount1 from an amountInToken0 and a tick priceX96
### @dev Calculates amountInToken0 * price
### @param amountInToken0 Amount In in token 0
### @param priceX96 Price at the limit order tick
### @param roundUp Bool to signal if it needs to be rounded up or down
### @return amount1 Amount of token1 obtained by swapping amountInToken0
def calculateAmount1LO(amountInToken0, priceX96, roundUp):
    checkInputTypes(uint256=(priceX96), int256=amountInToken0)

    # NOTE: Not using FullMath mulDiv and mulDivRoundingUp because of the potential overflow, mainly when rounding down
    # called by LimitcomputeSwapStep. We let it overflow and cap it afterwards. If done in other languages (Pyth/Rust)
    # we need to accomodate for that or do it in a slightly different way (e.g. mulDiv handling larger uint)
    if roundUp:
        return unsafeMulDivRoundingUp(amountInToken0, priceX96, FixedPoint96_Q96)
    else:
        return unsafeMulDiv(amountInToken0, priceX96, FixedPoint96_Q96)


def calculateAmount0LO(amountInToken1, priceX96, roundUp):
    checkInputTypes(uint256=(priceX96), int256=amountInToken1)

    # NOTE: Not using FullMath mulDiv and mulDivRoundingUp because of the potential overflow, mainly when rounding down
    # called by LimitcomputeSwapStep. We let it overflow and cap it afterwards. If done in other languages (Pyth/Rust)
    # we need to accomodate for that or do it in a slightly different way (e.g. mulDiv handling larger uint)
    if roundUp:
        # Should never be divided by zero because it is not allowed to mint positions at price 0.
        return unsafeMulDivRoundingUp(amountInToken1, FixedPoint96_Q96, priceX96)
    else:
        return unsafeMulDiv(amountInToken1, FixedPoint96_Q96, priceX96)


def getAmountSwappedFromTickPercentatge(
    percSwapChange, oneMinusPercSwap, liquidityGross
):
    checkInputTypes(decimal=(percSwapChange, oneMinusPercSwap), uint128=liquidityGross)
    # By default this will be rounded down - truncated. These are Decimal types.
    perc = percSwapChange / oneMinusPercSwap
    # Conversion to integer and rounded down.
    amountSwappedPrev = math.floor(liquidityGross * perc)
    return amountSwappedPrev


def getAmountSwappedFromTickPercentatgeRoundUp(
    percSwapChange, oneMinusPercSwap, liquidityGross
):
    checkInputTypes(decimal=(percSwapChange, oneMinusPercSwap), uint128=liquidityGross)
    setDecimalPrecRound(getcontext().prec, "ROUND_UP")
    # By default this will be rounded down - truncated. These are Decimal types.
    perc = percSwapChange / oneMinusPercSwap
    setDecimalPrecRound(getcontext().prec, "ROUND_DOWN")
    # Conversion to integer and rounded down.
    amountSwappedPrev = math.ceil(liquidityGross * perc)

    return amountSwappedPrev


def setDecimalPrecRound(precision, rounding):
    checkInputTypes(int=(precision))
    assert rounding in ["ROUND_DOWN", "ROUND_UP"]

    # Set decimal precision and rounding
    # Set all new contexts to the same default contexts
    DefaultContext.prec = precision
    DefaultContext.Emin = -999999999999999999
    DefaultContext.Emax = 999999999999999999
    DefaultContext.rounding = rounding
    setcontext(DefaultContext)


# Used only to substract percSwapDecrease from OneMinusPercSwapped. The result should never be negative.
def subtractDecimalRoundingUp(a, b):
    checkInputTypes(decimal=(a, b))
    setDecimalPrecRound(getcontext().prec, "ROUND_UP")
    result = a - b
    # Assert overflow
    assert result >= Decimal("0")
    setDecimalPrecRound(getcontext().prec, "ROUND_DOWN")
    return result


## @notice Calculates ceil(a×b÷denominator) with full precision.
## @param a The multiplicand
## @param b The multiplier
## @param denominator The divisor
## @return result The 256-bit result
def unsafeMulDivRoundingUp(a, b, c):
    return unsafeDivRoundingUp(a * b, c)


## @notice Calculates ceil(a÷denominator) with full precision rounding up.
## @param a The multiplicand
## @param b The divisor
## @return result The 256-bit result
def unsafeDivRoundingUp(a, b):
    result = a // b
    if a % b > 0:
        result += 1
    return result


## @notice Calculates floor(a×b÷denominator) with full precision.
## @param a The multiplicand
## @param b The multiplier
## @param denominator The divisor
## @return result The 256-bit result
def unsafeMulDiv(a, b, c):
    result = (a * b) // c
    return result
