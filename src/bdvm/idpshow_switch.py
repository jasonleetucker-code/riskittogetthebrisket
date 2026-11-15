"""The one switch that decides whether IDP Show projections enter BDVM snapshots.

OWNER-RESERVED, DEFAULT OFF.  Real IDP Show projection records that land in a
``data/bdvm/projections/<season>/`` snapshot change the fundamental values
``GET /api/bdvm/values`` serves (they supersede reconstructed-baseline proxies
per player and become a second real source in the consensus beside Clay).
Whether that happens is an owner decision, not an engineering side effect of a
parser repair, so the merge is opt-in:

* environment: ``BDVM_IDPSHOW_MERGE_INTO_SNAPSHOT=1`` (the ``dynasty-bdvm-refresh``
  unit already reads ``EnvironmentFile=-<app>/.env``, so activating it needs no
  unit change), or
* command line: ``--merge-into-snapshot`` on ``scripts/fetch_idpshow_projections.py``
  (``--merge-idpshow`` on ``scripts/refresh_bdvm_projections.py``, which passes it
  through).

With the switch off the fetcher still parses and writes the records to a SHADOW
file under ``data/bdvm/shadow/`` that no BDVM reader opens, so the owner can
inspect exactly what activation would bring in.

This module is deliberately stdlib-only and import-free: the refresh launcher
(``scripts/refresh_bdvm_projections.py``) must evaluate the same switch as the
fetcher it spawns, and its exit-code contract must not depend on importing the
BDVM engine to do so.  One definition, two callers.
"""

from __future__ import annotations

import os
from typing import Mapping

#: Environment variable that activates the merge.  Anything but a truthy value is OFF.
MERGE_ENV_VAR = "BDVM_IDPSHOW_MERGE_INTO_SNAPSHOT"

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def merge_into_snapshot_enabled(
    cli_flag: bool = False, environ: Mapping[str, str] | None = None
) -> bool:
    """True only when the owner has explicitly switched the merge on.

    ``cli_flag`` is the command-line opt-in; the environment variable is the
    standing opt-in.  Unset, empty, ``0``, ``false`` and anything unrecognised
    are OFF - an ambiguous value must never activate an owner-reserved change.
    """
    if cli_flag:
        return True
    env = os.environ if environ is None else environ
    return str(env.get(MERGE_ENV_VAR, "")).strip().lower() in _TRUTHY
