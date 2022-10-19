from uniswapV3Python.src.UniswapPool import *
from .libraries.SharedLimitOrder import *

from .libraries import (
    TickLimit,
    LimitOrderTickMath,
    PositionLimit,
    LimitOrderMath,
    LimitOrderSwapMath,
)

from dataclasses import dataclass


@dataclass
class ModifyLimitPositionParams:
    ## the address that owns the position
    owner: int
    ## the tick of the position
    tick: int
    ## any change in liquidity
    liquidityDelta: int


class ChainflipPool(UniswapPool):
    def __init__(self, token0, token1, fee, tickSpacing, ledger):
        checkInputTypes(string=(token0, token1), uint24=(fee), int24=(tickSpacing))

        # Setting default to rounding down as default since the majority of the math requires rounding down
        LimitOrderMath.setDecimalPrecRound(contextPrecision, "ROUND_DOWN")

        # For now both token0 and token1 limit orders on the same mapping. Maybe we will need to keep them
        # somehow else to be able to remove them after a tick is crossed.
        self.limitOrders = dict()

        # Creating two different dicts, one for each type of limit orders (token0 and token1)
        self.ticksLimitTokens0 = dict()
        self.ticksLimitTokens1 = dict()

        # Pass all paramaters to UniswapPool's constructor
        super().__init__(token0, token1, fee, tickSpacing, ledger)

    ### @dev Checks for valid limit tick inputs.
    def checkTick(tick):
        checkInputTypes(int24=(tick))
        # Check that priceTick > 0 to simplify edge cases (this happens because pricex96 can be zero
        # in some ticks while sqrtPricex96 will not).
        assert tick >= MIN_TICK_LO, "TLM"
        assert tick <= MAX_TICK_LO, "TUM"

    ## @notice Adds liquidity for the given recipient/tick/token position
    ## @dev The final amounts calculated are automatically transferred from the swapper
    ## to the pool and vice verse. The amount of liquidity minted should
    ## @param recipient The address for which the liquidity will be created
    ## @param tick The tick of the position in which to add liquidity
    ## @param token The token for which to add liquidity
    ## @param amount The amount of liquidity to mint, which should match exactly the amount of tokens
    ## that will be transferred from the user to the pool.
    ## @return amount The amount of token0 that was paid to mint the given amount of liquidity. The absolute
    ## value should match the function's call amount.
    def mintLimitOrder(self, token, recipient, tick, amount):
        checkInputTypes(
            string=token,
            accounts=(recipient),
            int24=(tick),
            uint128=(amount),
        )
        assert amount > 0
        assert (
            token == self.token0 or token == self.token1
        ), "Token not part of the pool"

        (
            position,
            liquidityLeftDelta,
            liquiditySwappedDelta,
        ) = self._modifyPositionLimitOrder(
            token, ModifyLimitPositionParams(recipient, tick, amount)
        )
        # Health check (these values are not very relevant in minting)
        assert liquidityLeftDelta == amount
        assert liquiditySwappedDelta == 0

        amountIn = toUint256(abs(amount))

        if token == self.token0:
            self.ledger.transferToken(recipient, self, self.token0, amountIn)
        elif token == self.token1:
            self.ledger.transferToken(recipient, self, self.token1, amountIn)

        return amountIn

    ## @dev Effect some changes to a position
    ## @param params the position details and the change to the position's liquidity to effect
    ## @param token The position's token
    ## @return position a storage pointer referencing the position with the given owner and tick range
    ## @return liquidityLeftDelta Change in liquidity's position left in token.
    ## @return liquiditySwappedDelta Change in liquidity's position already swapped in token pair.
    def _modifyPositionLimitOrder(self, token, params):
        checkInputTypes(
            string=token,
            accounts=(params.owner),
            int24=(params.tick),
            int128=(params.liquidityDelta),
        )

        ChainflipPool.checkTick(params.tick)

        (
            position,
            liquidityLeftDelta,
            liquiditySwappedDelta,
        ) = self._updatePositionLimitOrder(
            token,
            params.owner,
            params.tick,
            params.liquidityDelta,
        )

        return position, liquidityLeftDelta, liquiditySwappedDelta

    ### @dev Gets and updates a limit position with the given liquidity delta
    ## @param token The position's token
    ### @param owner the owner of the position
    ## @param tick The position's tick
    ## @param liquidityDelta The position's liquidity delta
    ### @return position A reference to the updated position
    ## @return liquidityLeftDelta Change in liquidity's position left in token.
    ## @return liquiditySwappedDelta Change in liquidity's position already swapped in token pair.
    def _updatePositionLimitOrder(self, token, owner, tick, liquidityDelta):
        checkInputTypes(
            string=token,
            accounts=(owner),
            int24=(tick),
            int128=(liquidityDelta),
        )
        # This will create a position if it doesn't exist
        position, created = PositionLimit.get(
            self.limitOrders, owner, tick, token == self.token0
        )
        # We could return a bool to assert if position has just been created
        if created:
            assert liquidityDelta > 0

        if token == self.token0:
            ticksLimitMap = self.ticksLimitTokens0
        else:
            ticksLimitMap = self.ticksLimitTokens1

        # Initialize values
        flipped = False

        ## if we need to update the ticks, do it.
        if liquidityDelta != 0:
            (flipped) = TickLimit.update(
                ticksLimitMap,
                tick,
                liquidityDelta,
                self.maxLiquidityPerTick,
                created,
                owner,
            )

        (liquidityLeftDelta, liquiditySwappedDelta,) = PositionLimit.update(
            position,
            liquidityDelta,
            ticksLimitMap[tick].oneMinusPercSwap,
            token == self.token0,
            LimitOrderTickMath.getPriceAtTick(tick),
            ticksLimitMap[tick].feeGrowthInsideX128,
            created,
        )

        if flipped:
            assert tick % self.tickSpacing == 0  ## ensure that the tick is spaced

        ## clear any tick data that is no longer needed
        if liquidityDelta < 0:
            if flipped:
                Tick.clear(ticksLimitMap, tick)
            # If position is burnt but not the tick, we need to remove the owner from tick.ownerPositions.
            # Position will be removed later after tokens have been collected.
            elif position.liquidity == 0:
                # Tick should contain the owner
                ticksLimitMap[tick].ownerPositions.remove(owner)
        return position, liquidityLeftDelta, liquiditySwappedDelta

    ## @notice Burn liquidity from the sender and account tokens owed for the liquidity to the position
    ## @dev This can only be run if the tick has only been partially crossed (or not used). If fully crossed,
    ## the position will have been burnt automatically.
    ## @dev Can be used to trigger a recalculation of fees owed to a position by calling with an amount of 0
    ## @dev If a position is fully burnt this way, it will be automatically collected and transferred
    ## to the owner (both tokens owed due to liquidity and/or fees)
    ## @param tick The position's tick
    ## @param recipient The position's owner.
    ## @param amount How much liquidity to burn
    ## @return amountBurnt0 The amount of token0 sent to the recipient due to the position's burn.
    ## @return amountBurnt1 The amount of token1 sent to the recipient due to the position's burn.
    ## @dev If position is fully burnt, all the tokens owed will be collected and added to the
    ## returned values amountBurnt0 and amountBurnt1.
    def burnLimitOrder(self, token, recipient, tick, amount):
        checkInputTypes(
            string=token,
            accounts=(recipient),
            int24=(tick),
            uint128=(amount),
        )

        # Add check if the position exists - when poking an uninitialized position it can be that
        # getFeeGrowthInside finds a non-initialized tick before Position.update reverts.
        Position.assertLimitPositionExists(
            self.limitOrders, recipient, tick, token == self.token0
        )

        # Added extra recipient input variable to mimic msg.sender
        (
            position,
            liquidityLeftDelta,
            liquiditySwappedDelta,
        ) = self._modifyPositionLimitOrder(
            token,
            ModifyLimitPositionParams(recipient, tick, -amount),
        )

        # Health check
        if amount == 0:
            assert liquidityLeftDelta == 0
            assert liquiditySwappedDelta == 0

        # Return amounts in the right order token0#token1
        (amountBurnt0, amountBurnt1) = (
            (abs(liquidityLeftDelta), abs(liquiditySwappedDelta))
            if token == self.token0
            else (abs(liquiditySwappedDelta), abs(liquidityLeftDelta))
        )

        # If position is fully burnt, automatically collect all the fees and transfer the full amount to the LP.
        # amountBurnt will be overwritten by collectLimitOrder if tick is fully burnt, and will also include fees
        # NOTE: This could return separate values instead of overwriting amountBurnt. Overwritting to have
        # the same return values as the original range order burn function.
        if position.liquidity == 0:
            (recipient, tick, amountBurnt0, amountBurnt1) = self.collectLimitOrder(
                recipient, token, tick, MAX_UINT128, MAX_UINT128
            )

        # As in uniswap we return the amount of tokens that were burned, that is without fees accrued.
        return (
            recipient,
            tick,
            amount,
            amountBurnt0,
            amountBurnt1,
        )

    ## Collect a limit Order. This can only be called for positions that have not been swapped or that have been
    ## partially swapped. If the position has been fully swapped, the position will have been burnt together with the tick.

    ## @notice Collects tokens owed to a position. This can only be called for positions that have not been swapped
    ## or that have been partially swapped. If the position has been fully swapped, the position will have been burnt
    ## together with the tick and collected.
    ## @dev Does not recompute fees earned, which must be done either via mint or burn of any amount of liquidity.
    ## Collect must be called by the position owner. To withdraw only token0 or only token1, amount0Requested or
    ## amount1Requested may be set to zero. To withdraw all tokens owed, caller may pass any value greater than the
    ## actual tokens owed, e.g. type(uint128).max. Tokens owed may be from accumulated swap fees or burned liquidity.
    ## @param recipient The address which should receive the fees collected
    ## @param tick The tick of the position for which to collect fees
    ## @param token The token of the position for which to collect fees
    ## @param amount0Requested How much token0 should be withdrawn from the fees owed
    ## @param amount1Requested How much token1 should be withdrawn from the fees owed
    ## @return amountPos0 The amount of fees collected in token0
    ## @return amountPos1 The amount of fees collected in token1
    def collectLimitOrder(
        self,
        recipient,
        token,
        tick,
        amount0Requested,
        amount1Requested,
    ):
        checkInputTypes(
            string=token,
            accounts=(recipient),
            int24=(tick),
            uint128=(amount0Requested, amount1Requested),
        )

        # Add this check to prevent creating a new position if the position doesn't exist or it's empty
        # even thought we would remove anyway at the end, but just for clarity.
        key = Position.assertLimitPositionExists(
            self.limitOrders, recipient, tick, token == self.token0
        )

        ## we don't need to checkTicks here, because invalid positions will never have non-zero tokensOwed{0,1}
        ## Hardcoded recipient == msg.sender.
        position, _ = PositionLimit.get(
            self.limitOrders, recipient, tick, token == self.token0
        )

        amountPos0 = (
            position.tokensOwed0
            if (amount0Requested > position.tokensOwed0)
            else amount0Requested
        )
        amountPos1 = (
            position.tokensOwed1
            if (amount1Requested > position.tokensOwed1)
            else amount1Requested
        )

        assert self.balances[self.token0] >= amountPos0
        assert self.balances[self.token1] >= amountPos1

        if amountPos0 > 0:
            position.tokensOwed0 -= amountPos0
            self.ledger.transferToken(self, recipient, self.token0, amountPos0)
        if amountPos1 > 0:
            position.tokensOwed1 -= amountPos1
            self.ledger.transferToken(self, recipient, self.token1, amountPos1)

        # Clear the position for bookkeeping purposes
        # NOTE: We could leave the position as UniSwap does. However, Solidity's memory/gas usage doesn't really depend
        # on clearing positions. In other languagues (Pyth/Rust) this matters so we would rather clear the positions.
        if position.liquidity == 0:
            # We should get the hash when getLimit is calculated before
            del self.limitOrders[key]

        # For debugging doing it like this, but we probably need to return both (or merge them)
        # return (recipient, tick, amount0, amount1, amountPos0, amountPos1)
        return (recipient, tick, amountPos0, amountPos1)

    ## @notice Swap token0 for token1, or token1 for token0
    ## @dev Overriding completely the UniswapPool's swap function to accomodate for Limit Orders during the swap flow.
    ## @dev Limit Orders have the ability to provide better prices than range orders. Therefore, the swap flow first
    ## checks for the existance of better priced limit orders and them moves onto range orders.
    ## @dev The tokens are automatically transferred at the end of the swapping function.
    ## @param recipient The address to receive the output of the swap
    ## @param zeroForOne The direction of the swap, true for token0 to token1, false for token1 to token0
    ## @param amountSpecified The amount of the swap, which implicitly configures the swap as exact input (positive), or exact output (negative)
    ## @param sqrtPriceLimitX96 The Q64.96 sqrt price limit. If zero for one, the price cannot be less than this
    ## value after the swap. If one for zero, the price cannot be greater than this value after the swap
    ## @return amount0 The delta of the balance of token0 of the pool, exact when negative, minimum when positive
    ## @return amount1 The delta of the balance of token1 of the pool, exact when negative, minimum when positive
    def swap(self, recipient, zeroForOne, amountSpecified, sqrtPriceLimitX96):
        checkInputTypes(
            accounts=(recipient),
            bool=(zeroForOne),
            int256=(amountSpecified),
            uint160=(sqrtPriceLimitX96),
        )
        assert amountSpecified != 0, "AS"

        slot0Start = self.slot0

        if zeroForOne:
            assert (
                sqrtPriceLimitX96 < slot0Start.sqrtPriceX96
                and sqrtPriceLimitX96 > TickMath.MIN_SQRT_RATIO
            ), "SPL"
        else:
            assert (
                sqrtPriceLimitX96 > slot0Start.sqrtPriceX96
                and sqrtPriceLimitX96 < TickMath.MAX_SQRT_RATIO
            ), "SPL"

        feeProtocol = (
            (slot0Start.feeProtocol % 16)
            if zeroForOne
            else (slot0Start.feeProtocol >> 4)
        )

        cache = SwapCache(feeProtocol, self.liquidity)

        if zeroForOne:
            ticksLimitMap = self.ticksLimitTokens1
        else:
            ticksLimitMap = self.ticksLimitTokens0

        exactInput = amountSpecified > 0

        state = SwapState(
            amountSpecified,
            0,
            slot0Start.sqrtPriceX96,
            slot0Start.tick,
            self.feeGrowthGlobal0X128 if zeroForOne else self.feeGrowthGlobal1X128,
            0,
            cache.liquidityStart,
            [],
        )

        while (
            state.amountSpecifiedRemaining != 0
            and state.sqrtPriceX96 != sqrtPriceLimitX96
        ):
            # First limit orders are checked since they can offer a better price for the user.

            ######################################################
            #################### LIMIT ORDERS ####################
            ######################################################

            # Probably we can do a simplified version of StepComputations
            stepLimit = StepComputations(0, None, False, 0, 0, 0, 0)
            stepLimit.sqrtPriceStartX96 = state.sqrtPriceX96

            # Find the next linear order tick. initialized == False if not found and returning the next best
            (stepLimit.tickNext, stepLimit.initialized) = nextLimitTick(
                ticksLimitMap, not zeroForOne, state.tick
            )
            # If !initialized then there are no more linear ticks with liquidityLeft > 0 that we can swap for now
            if stepLimit.initialized:

                tickLimitInfo = ticksLimitMap[stepLimit.tickNext]

                # Health check
                assert tickLimitInfo.oneMinusPercSwap > 0
                # Get price at that tick
                priceX96 = LimitOrderTickMath.getPriceAtTick(stepLimit.tickNext)
                (
                    stepLimit.amountIn,
                    stepLimit.amountOut,
                    stepLimit.feeAmount,
                    tickCrossed,
                    resultingOneMinusPercSwap,
                ) = LimitOrderSwapMath.computeSwapStep(
                    priceX96,
                    tickLimitInfo.liquidityGross,
                    state.amountSpecifiedRemaining,
                    self.fee,
                    zeroForOne,
                    tickLimitInfo.oneMinusPercSwap,
                )

                # Health check
                assert tickLimitInfo.oneMinusPercSwap <= Decimal("1")

                # Update oneMinusPercSwap with the value calculated
                tickLimitInfo.oneMinusPercSwap = resultingOneMinusPercSwap

                if exactInput:
                    state.amountSpecifiedRemaining -= (
                        stepLimit.amountIn + stepLimit.feeAmount
                    )
                    state.amountCalculated = SafeMath.subInts(
                        state.amountCalculated, stepLimit.amountOut
                    )
                else:
                    state.amountSpecifiedRemaining += stepLimit.amountOut
                    state.amountCalculated = SafeMath.addInts(
                        state.amountCalculated,
                        stepLimit.amountIn + stepLimit.feeAmount,
                    )

                # if the protocol fee is on, calculate how much is owed, decrement feeAmount, and increment protocolFee
                if cache.feeProtocol > 0:
                    delta = abs(stepLimit.feeAmount // cache.feeProtocol)
                    stepLimit.feeAmount -= delta
                    state.protocolFee += delta & (2**128 - 1)

                # Calculate linear fees can probably be done inside the Tick.computeLimitSwapStep function since it
                # will be stored within a tick (most likely). For now we keep it here to have the same structure.

                ## update global fee tracker. No need to check for liquidity, otherwise we would not have swapped a LO
                # if stateLimit.liquidity > 0:
                # feeAmount is in amountIn tokens => therefore feeGrowthInsideX128 is not in liquidityTokens
                tickLimitInfo.feeGrowthInsideX128 += FullMath.mulDiv(
                    stepLimit.feeAmount,
                    FixedPoint128_Q128,
                    tickLimitInfo.liquidityGross,
                )
                # Addition can overflow in Solidity - mimic it
                tickLimitInfo.feeGrowthInsideX128 = toUint256(
                    tickLimitInfo.feeGrowthInsideX128
                )

                if tickCrossed:
                    # Health check
                    assert tickLimitInfo.oneMinusPercSwap == 0
                    # The positions (and tick) cannot be burnt here since the income swap tokens should be received
                    # before sending tokens out to the LPs. Therefore, we just store an array of ticks crossed. The
                    # burning will be done at the end of the swap.
                    state.ticksCrossed.append(stepLimit.tickNext)
                    # There might be another Limit order that is better than range orders
                    if state.amountSpecifiedRemaining != 0:
                        continue
                    else:
                        # In case we cross the tick at the exact some time we complete the order
                        break
                else:
                    # Health check - swap should be completed
                    assert state.amountSpecifiedRemaining == 0
                    # Prevent from altering anything in the range order pool
                    break

            ######################################################
            #################### RANGE ORDERS ####################
            ######################################################

            step = StepComputations(0, 0, 0, 0, 0, 0, 0)
            step.sqrtPriceStartX96 = state.sqrtPriceX96

            (step.tickNext, step.initialized) = self.nextTick(state.tick, zeroForOne)

            ## get the price for the next tick
            step.sqrtPriceNextX96 = TickMath.getSqrtRatioAtTick(step.tickNext)

            # If there is a "next best" LO, use the TickMath.getSqrtRatioAtTick(stepLimit.tickNext) also as a limit price,
            # so if we reach there by swapping a RO, we stop, jump to the LO, and then come back to the RO if needed.
            # This is because we can't know the RO final price, and it could be a lot worse than the LO price. We could also
            # calculate the range order final price, compare it with the LO price, and then decide whether to swap the LO.
            # NOTE: A margin tick(s) could be added here before we jump into LO. Could potentially be used to tweak the
            # incentivization of RO's vs LO's. The details (and this mechanism for that matter) can be subject to change.
            if not stepLimit.initialized and stepLimit.tickNext != None:
                if zeroForOne:
                    # -1 so it takes that limit order
                    nextLOatTick = stepLimit.tickNext - 1

                else:
                    nextLOatTick = stepLimit.tickNext

                nextLOatPrice = TickMath.getSqrtRatioAtTick(nextLOatTick)
            else:
                nextLOatPrice = sqrtPriceLimitX96

            ## compute values to swap to the target tick, price limit, or point where input#output amount is exhausted.
            if zeroForOne:
                sqrtRatioTargetX96 = max(
                    sqrtPriceLimitX96, step.sqrtPriceNextX96, nextLOatPrice
                )
            else:
                sqrtRatioTargetX96 = min(
                    sqrtPriceLimitX96, step.sqrtPriceNextX96, nextLOatPrice
                )

            # Continue the range order swap as normal
            (
                state.sqrtPriceX96,
                step.amountIn,
                step.amountOut,
                step.feeAmount,
            ) = SwapMath.computeSwapStep(
                state.sqrtPriceX96,
                sqrtRatioTargetX96,
                state.liquidity,
                state.amountSpecifiedRemaining,
                self.fee,
            )

            if exactInput:
                state.amountSpecifiedRemaining -= step.amountIn + step.feeAmount
                state.amountCalculated = SafeMath.subInts(
                    state.amountCalculated, step.amountOut
                )
            else:
                state.amountSpecifiedRemaining += step.amountOut
                state.amountCalculated = SafeMath.addInts(
                    state.amountCalculated, step.amountIn + step.feeAmount
                )

            ## if the protocol fee is on, calculate how much is owed, decrement feeAmount, and increment protocolFee
            if cache.feeProtocol > 0:
                delta = abs(step.feeAmount // cache.feeProtocol)
                step.feeAmount -= delta
                state.protocolFee += delta & (2**128 - 1)

            ## update global fee tracker
            if state.liquidity > 0:
                state.feeGrowthGlobalX128 += FullMath.mulDiv(
                    step.feeAmount, FixedPoint128_Q128, state.liquidity
                )
                # Addition can overflow in Solidity - mimic it
                state.feeGrowthGlobalX128 = toUint256(state.feeGrowthGlobalX128)

            ## shift tick if we reached the next price
            if state.sqrtPriceX96 == step.sqrtPriceNextX96:
                ## if the tick is initialized, run the tick transition
                if step.initialized:
                    liquidityNet = Tick.cross(
                        self.ticks,
                        step.tickNext,
                        state.feeGrowthGlobalX128
                        if zeroForOne
                        else self.feeGrowthGlobal0X128,
                        self.feeGrowthGlobal1X128
                        if zeroForOne
                        else state.feeGrowthGlobalX128,
                    )
                    ## if we're moving leftward, we interpret liquidityNet as the opposite sign
                    ## safe because liquidityNet cannot be type(int128).min
                    if zeroForOne:
                        liquidityNet = -liquidityNet

                    state.liquidity = LiquidityMath.addDelta(
                        state.liquidity, liquidityNet
                    )

                state.tick = (step.tickNext - 1) if zeroForOne else step.tickNext
            elif state.sqrtPriceX96 != step.sqrtPriceStartX96:
                ## recompute unless we're on a lower tick boundary (i.e. already transitioned ticks), and haven't moved
                state.tick = TickMath.getTickAtSqrtRatio(state.sqrtPriceX96)

        ## End of swap loop
        # Set final tick as the range tick
        if state.tick != slot0Start.tick:
            self.slot0.sqrtPriceX96 = state.sqrtPriceX96
            self.slot0.tick = state.tick
        else:
            ## otherwise just update the price
            self.slot0.sqrtPriceX96 = state.sqrtPriceX96

        ## update liquidity if it changed
        if cache.liquidityStart != state.liquidity:
            self.liquidity = state.liquidity

        ## update fee growth global and, if necessary, protocol fees
        ## overflow is acceptable, protocol has to withdraw before it hits type(uint128).max fees
        if zeroForOne:
            self.feeGrowthGlobal0X128 = state.feeGrowthGlobalX128
            if state.protocolFee > 0:
                self.protocolFees.token0 += state.protocolFee
        else:
            self.feeGrowthGlobal1X128 = state.feeGrowthGlobalX128
            if state.protocolFee > 0:
                self.protocolFees.token1 += state.protocolFee

        (amount0, amount1) = (
            (amountSpecified - state.amountSpecifiedRemaining, state.amountCalculated)
            if (zeroForOne == exactInput)
            else (
                state.amountCalculated,
                amountSpecified - state.amountSpecifiedRemaining,
            )
        )

        ## do the transfers and collect payment
        if zeroForOne:
            if amount1 < 0:
                self.ledger.transferToken(self, recipient, self.token1, abs(amount1))
            balanceBefore = self.balances[self.token0]
            self.ledger.transferToken(recipient, self, self.token0, abs(amount0))
            assert balanceBefore + abs(amount0) == self.balances[self.token0], "IIA"
        else:
            if amount0 < 0:
                self.ledger.transferToken(self, recipient, self.token0, abs(amount0))

            balanceBefore = self.balances[self.token1]
            self.ledger.transferToken(recipient, self, self.token1, abs(amount1))
            assert balanceBefore + abs(amount1) == self.balances[self.token1], "IIA"

        # Burn all the ticks crossed together with their positions.
        for tick in state.ticksCrossed:
            self.burnCrossedTicksAndPositions(
                ticksLimitMap, tick, self.token1 if zeroForOne else self.token0
            )

        return (
            recipient,
            amount0,
            amount1,
            state.sqrtPriceX96,
            state.liquidity,
            state.tick,
        )

    ## @notice Burns a tick and all their underlying positions. This is called at the end of a swap
    ## to burn and collect all the crossed ticks and positions.
    ## @dev This could be done in a more efficient way by creating a function that burns
    ## all the positions without altering the tick and then burning the tick at the end. But here we are
    ## just reusing the burnLimitOrder for simplicity.
    ## @param Tick Rick to burn and collect
    ## @param tickLimitInfo Reference to the tick Info of the tick to burn and collect
    ## @param token Tick's token
    def burnCrossedTicksAndPositions(self, tickLimitInfo, tick, token):
        checkInputTypes(string=(token), int24=(tick))
        assert tickLimitInfo[tick].oneMinusPercSwap == 0
        for owner in tickLimitInfo[tick].ownerPositions:
            position, created = PositionLimit.get(
                self.limitOrders, owner, tick, token == self.token0
            )
            # Health check
            assert not created
            # Health check - shouldn't be needed since burntPositions have automatically been collected
            # and removed, but just checking to make sure behaviour is correct.
            assert position.liquidity > 0

            # NOTE: BurnLimitOrder will automatically call collectLimitOrder. That will clear the positions and tick.
            self.burnLimitOrder(token, owner, tick, position.liquidity)
            # Check that the position has been burnt
            Position.assertLimitPositionIsBurnt(
                self.limitOrders, owner, tick, token == self.token0
            )
        # Check that the tick has been cleared
        assert not tickLimitInfo.__contains__(tick)


## @notice Get the next limit tick containing limit orders with liquidity (oneMinusPercSwap > 0).
## @dev We are fetching for the next tick in every swap loop. Since the ticks don't get burnt until the end
## of the swap, we will find some LO ticks that have been previously swapped. Therefore we need to get only
## the LO ticks with oneMinusPercSwap > 0.
## @dev Returning a bool signaling whether it should be used or not (better price than the RO pool)
## @dev This might not be the most efficient flow but this is just for modeling.
## @param tickMapping Mapping of all the ticks that can potentially be used in the current swap.
## @param lte Whether to search for the next initialized tick to the left (less than or equal to the starting tick)
## @param currentTick Current tick of the pool's state.
def nextLimitTick(tickMapping, lte, currentTick):
    checkInputTypes(bool=(lte), int24=(currentTick))

    # Dictionary with ticks that have oneMinusPercSwap > 0
    dictTicksWithLiq = {
        k: v for k, v in tickMapping.items() if tickMapping[k].oneMinusPercSwap > 0
    }

    keysLimitTicks = sorted(list(dictTicksWithLiq.keys()))

    # Return an invalid tick if there are no ticks.
    if len(keysLimitTicks) == 0:
        return None, False

    if lte:
        # Start from the most left
        nextTick = keysLimitTicks[0]
        if nextTick <= currentTick:
            return nextTick, True
    else:
        # Start from the most right
        nextTick = keysLimitTicks[-1]
        if nextTick > currentTick:
            return nextTick, True

    # If no tick with LO is found, then we're done - no LO will be used. However, we return the next best tick so
    # the range orders know which is the next tick at which we should be using LOs.
    return nextTick, False
