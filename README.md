## Chainflip JIT AMM - Python model
This repository contains a python model of the Chainflip JIT AMM. It is build based on the [Pythonized Uniswap V3](https://github.com/chainflip-io/chainflip-uniswapV3-python) AMM.

This logic aims to provide an initial model for the Chainflip JIT AMM that will be implemented in the Chainflip Protocol. It inherits the range order logic from the Uniswap V3 AMM and adds an additional type of orders - limit orders. 

Limit orders allow liquidity providers to place single-sided positions on any tick (not range). All the limit order positions are bundled into ticks following the same approach as the range orders. One way to think about this is as if there was a layer of limit order ticks on top of the range order pool.
Limit orders will be executed at the tick price and will be used iff they provide a better swap price for the user than the range orders. A single swap can be completed using a combination of range and limit orders.
Once limit order positions are consumed (fully swapped), the swapped position plus the accumulated fees will be collected automatically and transferred to the liquidity provider's balance. LP fees in limit order positions are accrued in the same way as for range orders. 

## Dependencies

- Python >=3.7.3, <3.10
For Ubuntu `sudo apt-get install python3 python-dev python3-dev build-essential`
- [Poetry (Python dependency manager)](https://python-poetry.org/docs/)


## Setup

First, ensure you have [Poetry](https://python-poetry.org) installed

```bash
git clone git@github.com:chainflip-io/python-uniswap-v3.git
cd python-jit-amm
poetry shell
poetry install
```

### Running Tests

Pytest is used to run the tests.

```bash
pytest
pytest <testfile-name>::<test-name>
```
