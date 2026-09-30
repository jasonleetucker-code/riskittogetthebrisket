"""Platform lineup-upload CSVs.

The export is rebuilt from the stored build and RE-VALIDATED against the rule
set at export time — a build is never exported on the strength of having been
valid when it was made.  Platform player IDs are emitted verbatim as strings.

An export is a file for the owner to upload.  Generating it submits nothing,
and the build is not marked submitted by it.  While the rule set's export
format is ``unverified`` the response says so; the header row is the rule
set's slot order, and IDs are validated to ``[0-9A-Za-z-]`` so no cell can be
read as a spreadsheet formula.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

from src.dfs.imports import SlateAthlete
from src.dfs.optimizer import validate_lineup
from src.dfs.rules import RuleSet

# First character alphanumeric: a leading "-" or "=" is read as a formula by spreadsheets.
_SAFE_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z\-]{0,39}$")


class ExportError(ValueError):
    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def build_upload_csv(
    ruleset: RuleSet, lineups: list[dict[str, Any]], athletes: list[SlateAthlete]
) -> str:
    by_id = {a.player_id: a for a in athletes}
    header = list(ruleset.export.get("header") or [s.name for s in ruleset.slots])
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(header)
    for lu in lineups:
        assignment = [(p["slot"], p["playerId"]) for p in lu["players"]]
        errors = validate_lineup(assignment, ruleset, by_id)
        if errors:
            raise ExportError(
                "LINEUP_INVALID_AT_EXPORT",
                f"Lineup {lu.get('index')} is no longer valid.",
                {"errors": errors},
            )
        ids = [pid for _, pid in assignment]
        if not all(_SAFE_ID.match(pid) for pid in ids):
            raise ExportError(
                "UNSAFE_PLAYER_ID",
                "A player ID contains characters that cannot be exported safely.",
            )
        w.writerow(ids)
    return out.getvalue()
