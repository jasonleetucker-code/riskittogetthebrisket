"""Server/client parity for the public Trade Advisor's fixed error copy.

The League Hub client never renders a server string: it holds the server's
fixed wording itself (``frontend/lib/trade-advisor-client.js``), keyed by the
contract's codes.  Two of those client tables are documented as VERBATIM
copies of ``src/trade/public_advisor.py::ERROR_MESSAGES``:

* ``INVALID_TRADE_COPY`` -- every ``("invalid_trade", reason)`` message;
* ``ADMISSION_COPY`` -- the two R2-5 admission-control refusals,
  ``("advisor_unavailable", "busy" | "timeout")``.

Until this test the admission copy was pinned only by a literal-string vitest
on the client, so the Python wording could change (or gain a third admission
reason) with nothing failing.  This test reads the JS source without
executing it and diffs both tables against the Python owner in both
directions, and pins that the reasons ``compute_admission`` can raise are
exactly the ones the client handles.

The other client messages (stale rosters, rate limited, disabled, offline,
unavailable) are deliberately client wording, not copies, and are not
compared here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from src.trade.public_advisor import ERROR_MESSAGES

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT_JS = REPO_ROOT / "frontend" / "lib" / "trade-advisor-client.js"
ADMISSION_PY = REPO_ROOT / "src" / "api" / "compute_admission.py"

_ENTRY = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*("(?:[^"\\]|\\.)*")\s*,?\s*$')


def _js_object(name: str) -> dict[str, str]:
    """Parse ``const NAME = {...}`` or ``Object.freeze({...})`` whose entries
    are one ``key: "string"`` per line.  Any other line shape fails loudly
    rather than being skipped, so a reformatted table cannot pass vacuously."""
    src = CLIENT_JS.read_text(encoding="utf-8")
    m = re.search(
        rf"(?:export\s+)?const\s+{name}\s*=\s*(?:Object\.freeze\(\s*)?\{{\n(.*?)\n\}}",
        src,
        re.S,
    )
    assert m, f"{name} not found in {CLIENT_JS.relative_to(REPO_ROOT)}"
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.strip().startswith("//"):
            continue
        em = _ENTRY.match(line)
        assert em, f"unparseable {name} line: {line!r}"
        key, literal = em.group(1), ast.literal_eval(em.group(2))
        assert key not in out, f"duplicate {name} key {key!r}"
        out[key] = literal
    assert out, f"{name} parsed empty"
    return out


def _python_messages(error: str) -> dict[str, str]:
    return {reason: msg for (err, reason), msg in ERROR_MESSAGES.items() if err == error and reason}


def test_invalid_trade_copy_matches_python_owner() -> None:
    assert _js_object("INVALID_TRADE_COPY") == _python_messages("invalid_trade")


def test_admission_copy_matches_python_owner() -> None:
    py = {
        r: m for r, m in _python_messages("advisor_unavailable").items() if r in ("busy", "timeout")
    }
    assert set(py) == {"busy", "timeout"}, "ERROR_MESSAGES lost an admission reason"
    assert _js_object("ADMISSION_COPY") == py


def test_client_handles_exactly_the_admission_reasons_python_raises() -> None:
    raised = set(
        re.findall(
            r'AdmissionRejected\(\s*self\.route\s*,\s*"([a-z_]+)"\s*\)', ADMISSION_PY.read_text()
        )
    )
    assert raised == {"busy", "timeout"}, raised
    assert set(_js_object("ADMISSION_COPY")) == raised
    src = CLIENT_JS.read_text(encoding="utf-8")
    branch = re.search(r'b\.error === "advisor_unavailable" && \(([^)]*)\)', src)
    assert branch, "errorFromResponse admission branch not found"
    assert set(re.findall(r'b\.reason === "([a-z_]+)"', branch.group(1))) == raised
