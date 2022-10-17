import math
from . import LimitOrderMath
from uniswapV3Python.src.libraries import FullMath
from uniswapV3Python.src.libraries.Shared import *


def computeSwapStep(
    priceX96, liquidityGross, amountRemaining, feePips, zeroForOne, oneMinusPercSwap
):
    checkInputTypes(
        uint256=priceX96,
        uint128=liquidityGross,
        int256=amountRemaining,
        uint24=feePips,
        bool=zeroForOne,
        decimal=oneMinusPercSwap,
    )
    # Calculate liquidityLeft (available) from liquidityGross and oneMinusPercSwap
    liquidity = math.floor(liquidityGross * oneMinusPercSwap)
    checkUInt128(liquidity)

    tickCrossed = False

    # exactIn < 0 means exactOut = True
    exactIn = amountRemaining >= 0

    if exactIn:
        amountRemainingLessFee = FullMath.mulDiv(
            amountRemaining, ONE_IN_PIPS - feePips, ONE_IN_PIPS
        )
        if zeroForOne:
            amountOut = LimitOrderMath.calculateAmount1LO(
                amountRemainingLessFee, priceX96, False
            )
        else:
            amountOut = LimitOrderMath.calculateAmount0LO(
                amountRemainingLessFee, priceX96, False
            )

        if amountOut >= liquidity:
            # Tick crossed
            if zeroForOne:
                amountIn = LimitOrderMath.calculateAmount0LO(liquidity, priceX96, True)
            else:
                amountIn = LimitOrderMath.calculateAmount1LO(liquidity, priceX96, True)
            assert amountIn <= amountRemainingLessFee
            resultingOneMinusPercSwap = Decimal("0")
            amountOut = liquidity

        else:
            # Tick not crossed
            amountIn, amountOut, resultingOneMinusPercSwap = calculateAmounts(
                amountOut, liquidity, oneMinusPercSwap, priceX96, zeroForOne
            )

            assert amountIn <= amountRemainingLessFee

            # Health check
            assert amountOut < liquidity

    else:
        # exactOut
        if abs(amountRemaining) >= liquidity:
            # Tick crossed
            resultingOneMinusPercSwap = Decimal("0")
            amountOut = liquidity
            if zeroForOne:
                amountIn = LimitOrderMath.calculateAmount0LO(amountOut, priceX96, True)
            else:
                amountIn = LimitOrderMath.calculateAmount1LO(amountOut, priceX96, True)
        else:
            # Tick not crossed
            amountIn, amountOut, resultingOneMinusPercSwap = calculateAmounts(
                abs(amountRemaining), liquidity, oneMinusPercSwap, priceX96, zeroForOne
            )

            # Health check
            assert amountOut < liquidity

    tickCrossed = amountOut == liquidity
    # Health check
    assert tickCrossed == (resultingOneMinusPercSwap == Decimal("0"))

    ## cap the output amount to not exceed the remaining output amount
    if (not exactIn) and (amountOut > abs(amountRemaining)):
        assert False, "We should not get here with the JIT AMM pool"
        checkUInt256(-amountRemaining)
        amountOut = abs(amountRemaining)

    if exactIn and not tickCrossed:
        ## we didn't reach the target, so take the remainder of the maximum input as fee
        checkUInt256(amountRemaining)
        feeAmount = abs(amountRemaining) - amountIn
    else:
        feeAmount = FullMath.mulDivRoundingUp(amountIn, feePips, ONE_IN_PIPS - feePips)
    return (amountIn, amountOut, feeAmount, tickCrossed, resultingOneMinusPercSwap)


def calculateAmounts(amountOut, liquidity, oneMinusPercSwap, priceX96, zeroForOne):
    checkInputTypes(
        uint256=priceX96,
        uint128=liquidity,
        int256=amountOut,
        bool=zeroForOne,
        decimal=oneMinusPercSwap,
    )

    # All decimal operations here are rounded down (truncated)

    # Calculate percSwapDecrease rounding down in favour of the pool (less amount out). This could maybe be rounded
    # up if end up recalculating amountIn afterwards.

    # currentPercSwapped = amountSwapped / liquidityLeft
    # tick.percSwap = tick.percSwap + (1-tick.percSwap) * currentPercSwapped128_Q128
    # tick.oneMinusPercSwap = tick.oneMinusPercSwap - tick.oneMinusPercSwap * currentPercSwapped128_Q128

    # Doing the operation in two steps because otherwise Decimal gets rounded wrongly.
    # percSwapDecrease = oneMinusPercSwap * amountOut / liquidity
    division = Decimal(amountOut) / Decimal(liquidity)
    # By default rounded down - truncated
    percSwapDecrease = oneMinusPercSwap * division

    auxPercSwapDecrease = percSwapDecrease

    # NOTE: Here is where precision can be lost because oneMinusPercSwap can be 0.XYZ while percSwapDecrease can be 0.00000ZYX.
    # The precision that oneMinusPercSwap can store will depend on how close to zero it is (floating point precision).
    # We have to use the oneMinusPercSwap - initial to calculate amountIn and Out instead of percSwapDecrease because
    # precision is lost in the operation as explained above.

    # We round up the calculation to round down the percSwapDecrease
    resultingOneMinusPercSwap = LimitOrderMath.subtractDecimalRoundingUp(
        oneMinusPercSwap, percSwapDecrease
    )

    # Health check
    assert resultingOneMinusPercSwap > Decimal("0")
    assert resultingOneMinusPercSwap <= Decimal("1")
    # Could be equal if the amountOut/LiqLeft is many orders of magnitude smaller than oneMinusPercSwap or if it's
    # equal to zero (extreme prices)
    assert (
        resultingOneMinusPercSwap <= oneMinusPercSwap
    ), "oneMinusPercSwap should decrease or stay the same"

    # This will calculate the real percSwapDecrease that will be stored in the position. Then we use that to backcalculate
    # amount In and amount Out
    percSwapDecrease = oneMinusPercSwap - resultingOneMinusPercSwap

    # Health check
    assert abs(auxPercSwapDecrease) >= percSwapDecrease
    # To ensure amountOut it will match the burn calculation
    amountOut = LimitOrderMath.getAmountSwappedFromTickPercentatge(
        percSwapDecrease, oneMinusPercSwap, liquidity
    )

    # Should recalculate amountIn to then take abs(amountRemaining) - amountIn as fees.
    # NOTE: There are some special behaviours in extreme prices (where amountOut=0), where if recalculated then amountIn = Zero,
    # which then causes all amountIn to be taken as fee but no swap has happened. If it weren't recalculated, it would stay as
    # amountIn, which would be money inside the pool. But since the position hasn't been affected I believe it's correct
    # to take it as fees.

    # NOTE: The issue here is that amountOut being rounded down causes amountIn to not get rounded up properly. That impacts the burn
    # calculation and potentially (when no fees at least) in some case the LP gets 1 token more than the pool has.
    # This pops up in the test_precision_zeroForOne and test_precision_oneForZero tests.
    # Might not be an issue with fees and this might be unnecessary. As a workaround for now we use the amountOut rounded up for the
    # calculation of amountIn. Same thing implemented in Position.
    amountOutRoundedUp = LimitOrderMath.getAmountSwappedFromTickPercentatgeRoundUp(
        percSwapDecrease, oneMinusPercSwap, liquidity
    )
    # Health check
    assert amountOutRoundedUp >= amountOut
    assert abs(amountOutRoundedUp - amountOut) <= 1

    # Changing for amountOutOrig solves the problem but unclear if this is good
    if zeroForOne:
        amountIn = LimitOrderMath.calculateAmount0LO(amountOutRoundedUp, priceX96, True)
    else:
        amountIn = LimitOrderMath.calculateAmount1LO(amountOutRoundedUp, priceX96, True)

    return amountIn, amountOut, resultingOneMinusPercSwap
