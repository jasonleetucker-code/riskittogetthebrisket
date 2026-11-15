"""TC-A — "Simulate impact" names its equity basis honestly.

``team_impact``'s equity is the RAW canonical sum (receiving - sending), with
no package Value Adjustment.  Its rationale called it "Net KTC equity" -- a
vendor's name on a quantity that is neither KTC's nor the active package
model's adjusted gap (UX audit P1-6, engine audit §3.2 V7).  The panel itself
is kept (owner decision pending on retiring its accept/decline); only the
label is corrected.
"""

from __future__ import annotations

from src.trade.team_impact import _rationale


def test_the_equity_bullet_says_raw_before_value_adjustment() -> None:
    bullets = _rationale(
        starter_value_delta={},
        starter_delta={},
        overflow_delta={},
        redundancy=[],
        window_fit=0.0,
        posture="HOLD",
        equity=1000,
        fit_score=0.0,
    )
    assert bullets == ["Net raw equity +1000 (before Value Adjustment)"]
    assert not any("KTC" in b for b in bullets)
