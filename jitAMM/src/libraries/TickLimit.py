from uniswapV3Python.src.libraries import LiquidityMath
from .SharedLimitOrder import *

### @notice Updates a limit order tick and returns true if the tick was flipped from initialized to uninitialized, or vice versa
### @param self The mapping containing all tick information for initialized ticks
### @param tick The tick that will be updated
### @param liquidityDelta A new amount of liquidity to be added (subtracted)
### @param maxLiquidity The maximum liquidity allocation for a single tick
### @param created Whether the position modifying this tick has just been created
### @param owner Account that modified a position contained in this tick
### @return flipped Whether the tick was flipped from initialized to uninitialized, or vice versa
def update(
    self,
    tick,
    liquidityDelta,
    maxLiquidity,
    created,
    owner,
):
    checkInputTypes(
        dict=self,
        int24=(tick),
        int128=(liquidityDelta),
        bool=(created),
        uint128=maxLiquidity,
    )

    # Tick might not exist - create it. Make sure tick is not created unless it is then initialized with liquidityDelta > 0
    if not self.__contains__(tick):
        assert liquidityDelta > 0, "Avoid creating empty tick"
        insertUninitializedLimitTickstoMapping(self, [tick])

    info = self[tick]

    # Health check - if tick is swapped it should have been burnt.
    if liquidityDelta > 0:
        assert info.oneMinusPercSwap > 0

    liquidityGrossBefore = info.liquidityGross
    liquidityGrossAfter = LiquidityMath.addDelta(liquidityGrossBefore, liquidityDelta)

    assert liquidityGrossAfter <= maxLiquidity, "LO"

    flipped = (liquidityGrossAfter == 0) != (liquidityGrossBefore == 0)

    info.liquidityGross = liquidityGrossAfter

    # Add owner to ownerPosition list if not already there. Doing a hashlist has the problem that
    # when burning we don't know who is the owner of the position. We store the address instead of a reference
    # to the account because
    if liquidityDelta > 0 and created:
        # Health check for development purposes
        assert owner not in info.ownerPositions, "Position already in hashPositions"
        info.ownerPositions.append(owner)
    else:
        # If we are burning or the position had already been initialized, the position should
        # already be in the info.ownerPositions list.
        # Health check only for development purposes.
        assert owner in info.ownerPositions, "Position not in ownerPositions"

    # No longer require flip to signal if it has been initialized but it is needed for when it is cleared
    return flipped
