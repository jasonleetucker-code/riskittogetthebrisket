"""Trade-engine package initialization.

The arbitrage finder is patched at package import so every caller—API,
CLI, tests, and audit scripts—uses the same KTC package Value Adjustment
as the frontend trade calculator.
"""

from . import finder as _finder
from .finder_value_adjustment import install as _install_value_adjustment

_install_value_adjustment(_finder)

del _finder, _install_value_adjustment
