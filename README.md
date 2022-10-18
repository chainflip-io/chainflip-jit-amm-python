## Chainflip JIT AMM - Python model
This repository contains a python model of the Chainflip JIT AMM. It is build based on the [Pythonized Uniswap V3](https://github.com/chainflip-io/python-uniswap-v3) AMM.

This logic aims to provide an initial model for the Chainflip JIT AMM that will be implemented in the Chainflip protocol. It inherits the range order logic from the Uniswap V3 AMM and adds an additional type of orders - limit lrders. 

Limit orders allow liquidity providers to place single-sided positions on any tick (not range). These orders will be executed at the tick price and will be used iff they provide a better swap price for the user than the range orders. Once the positions are consumed, the swapped position plus the accumulated fees will be collected automatically and transferred to the liquidity provider's balance. All the limit order positions are bundled into ticks following the same approach as the range orders.

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
pytest <test-name>
```
