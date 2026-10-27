"""The League Hub client's deadlines outlast the server's own bounds (E4-2).

``frontend/lib/trade-advisor-client.js::CLIENT_DEADLINE_MS`` exists only so a
request the server never answers (a dropped connection, a stalled proxy)
cannot leave the page waiting forever.  When the server DOES answer, its own
fixed copy must win: the analyze route bounds one caller's wait at
``config/trade/analyze_admission.json`` ``public_advisor_analyze.timeoutSeconds``
and then answers a fixed 503 ``timeout``, held to the response floor
(``config/trade/public_advisor.json`` ``responseFloorMs``).  So the client's
analyze deadline must exceed ``server timeout + floor + network margin``,
whatever those sizes become when the owner confirms them.

This reads the JS source without executing it (same posture as
``test_public_advisor_client_copy_parity.py``) and fails when a config change
on either side would let the client give up before the server answers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.api import compute_admission

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT_JS = REPO_ROOT / "frontend" / "lib" / "trade-advisor-client.js"
ADVISOR_CONFIG = REPO_ROOT / "config" / "trade" / "public_advisor.json"

#: Allowance for the gate, limiter, body read, serialisation and the network
#: between the server deciding and the browser receiving.  A DECLARED PRIOR.
NETWORK_MARGIN_MS = 2000
#: The floor allowance while ``responseFloorMs`` is unset (the launch gate is
#: closed then, so this only keeps the test meaningful before launch).
UNSET_FLOOR_ALLOWANCE_MS = 1000


def _client_deadlines() -> dict[str, int]:
    src = CLIENT_JS.read_text(encoding="utf-8")
    m = re.search(r"export const CLIENT_DEADLINE_MS = Object\.freeze\(\{\n(.*?)\n\}\);", src, re.S)
    assert m, "CLIENT_DEADLINE_MS not found in the advisor client"
    out: dict[str, int] = {}
    for line in m.group(1).splitlines():
        em = re.fullmatch(r"\s*([a-z]+):\s*(\d+),?\s*", line)
        assert em, f"unparseable CLIENT_DEADLINE_MS line: {line!r}"
        out[em.group(1)] = int(em.group(2))
    return out


def _max_floor_ms() -> int:
    raw = json.loads(ADVISOR_CONFIG.read_text(encoding="utf-8")).get("responseFloorMs")
    if isinstance(raw, dict):
        return max(int(v) for v in raw.values())
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    return UNSET_FLOOR_ALLOWANCE_MS


def test_client_deadline_table_is_exactly_analyze_and_list():
    assert set(_client_deadlines()) == {"analyze", "list"}


def test_client_analyze_deadline_outlasts_the_server_answer():
    deadlines = _client_deadlines()
    server_seconds = compute_admission.spec_for(
        compute_admission.ROUTE_PUBLIC_ADVISOR
    ).timeout_seconds
    bound = server_seconds * 1000 + _max_floor_ms() + NETWORK_MARGIN_MS
    assert deadlines["analyze"] > bound, (
        f"the client would give up at {deadlines['analyze']} ms, before the server's own "
        f"fixed answer (bounded at {bound:.0f} ms)"
    )


def test_client_list_deadline_outlasts_the_floor_and_margin():
    # The GET lists take no admission slot and no floor; they still must not
    # undercut a slow-but-answering server by the margin.
    assert _client_deadlines()["list"] > NETWORK_MARGIN_MS + UNSET_FLOOR_ALLOWANCE_MS


def test_the_client_maps_its_own_timeout_onto_the_server_timeout_copy():
    src = CLIENT_JS.read_text(encoding="utf-8")
    assert re.search(
        r'CLIENT_TIMEOUT_ERROR = Object\.freeze\(\{\s*kind: "timeout",\s*retryable: true,\s*'
        r"message: ADMISSION_COPY\.timeout,",
        src,
    ), "a client timeout must reuse the server's fixed `timeout` copy and kind"
