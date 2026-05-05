"""Research / sandbox modules.

Sandbox-only analyses live here.  Modules in this package are
explicitly forbidden from mutating the live contract or any of the
``latest_*`` globals in ``server.py``.  Their job is to read the live
contract + raw source CSVs and produce read-only "what-if" projections.
"""
