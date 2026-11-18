"""Run a script under the fake clock:

    python tests/fake_clock_run.py 2027-01-01T00:30:00Z scripts/validate_api_contract.py --repo . --lane structural

Used by the year-boundary harness for the blocking-gate SCRIPTS that are not
pytest tests (e.g. the API data contract check).  Same shim as ``--fake-now``;
read-only advisory tooling.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests import fake_clock  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: fake_clock_run.py <ISO-8601 instant> <script.py> [args...]", file=sys.stderr)
        return 2
    fake_clock.install(argv[1])
    script = argv[2]
    sys.argv = [script, *argv[3:]]
    sys.path.insert(0, str(Path(script).resolve().parent))
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
