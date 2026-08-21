"""Pure, dependency-free numerical algorithms shared across the public/private boundary.

This package exists for exactly one reason: some algorithms (today, KTC's Value
Adjustment) are needed on both sides of the public/private import boundary
enforced by ``tests/public_league/test_public_contract.py::ImportSurfaceTests``
(``src/public_league`` may never import ``src.trade``, ``src.canonical``,
``src.pool`` or ``src.api.data_contract``), but the algorithm itself has no
private business logic in it — it is closed-form math with no dependency on
canonical values, leagues, rosters or identity.

Modules here must depend on nothing but the standard library, so that neither
side of the boundary is compromised by importing them.  A module that needs
anything from ``src.trade`` or ``src.canonical`` does not belong here — it
belongs in the private package that owns that concept.
"""
