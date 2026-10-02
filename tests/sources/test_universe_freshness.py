"""#1555 V2-1: one board, two asset universes, one clock each.

IDP Trade Calculator prices offense and IDP players on one board. An IDP-only
update large enough to count as a broad change for the whole board used to
refresh the freshness clock of offense rows that did not move (row age =
``max(row clock, board broad clock)``). Measured in the tracked state on
2026-09-30: 442 rows (the offense board, Jalen Coker among them) last changed
2026-08-28, while the broad events of 09-15 and 09-23 touched IDP rows only.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from src.api import feature_flags as ff
from src.sources.freshness import SourceWeighting, SubsetFreshness

AS_OF = datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)
OLD = "2026-08-28T01:13:39Z"  # the offense universe's last broad change
NEW = "2026-09-23T21:54:29Z"  # an IDP-only broad change


def _subset(style="BATCH", *, offense=40, idp=30, idp_new=20, clock=NEW):
    rows = {f"off{i}": OLD for i in range(offense)}
    rows.update({f"idp{i}": OLD for i in range(idp - idp_new)})
    rows.update({f"idpnew{i}": NEW for i in range(idp_new)})
    return SubsetFreshness(
        source_key="idpTradeCalc",
        subset="players",
        style=style,
        style_evidence={},
        expected_hours=135.8,
        cadence_source="learned",
        observed_cadence_hours=None,
        clock="lastBroadDatasetChangeAt",
        clock_at=datetime.fromisoformat(clock.replace("Z", "+00:00")),
        last_any_change_at=None,
        last_broad_change_at=None,
        as_of=AS_OF,
        age_hours=None,
        freshness=1.0,
        state="ON_SCHEDULE",
        row_changed_at=rows,
    ), {k: ("idp" if k.startswith("idp") else "offense") for k in rows}


def _weighting(sub):
    return SourceWeighting("idpTradeCalc", True, {"players": sub}, "HEALTHY", 1.0, 1.0, 1.0, 0, 0.0)


def test_idp_only_publication_no_longer_refreshes_offense_rows():
    sub, universes = _subset()
    sw = _weighting(sub)
    # Before: the offense row is credited with the IDP-only change of 09-23.
    _f_old, age_old = sw.factor_for_row(is_pick=False, row_key="off0")
    assert round(age_old) == 159
    # After: it ages from its own universe's last broad change, 08-28.
    f_new, age_new = sw.factor_for_row(
        is_pick=False, row_key="off0", universe="offense", key_universe=universes
    )
    assert round(age_new) == 804
    assert f_new < _f_old


def test_idp_rows_keep_the_board_clock():
    sub, universes = _subset()
    sw = _weighting(sub)
    plain = sw.factor_for_row(is_pick=False, row_key="idpnew0")
    aware = sw.factor_for_row(
        is_pick=False, row_key="idpnew0", universe="idp", key_universe=universes
    )
    assert plain == aware


def test_a_universe_clock_can_only_make_evidence_older():
    # An offense-only change newer than the board clock is NOT credited here:
    # the universe clock caps the source clock, it never replaces it upward.
    sub, universes = _subset(clock=OLD)
    for key in list(sub.row_changed_at)[:20]:
        sub.row_changed_at[key] = "2026-09-29T00:00:00Z"
    sw = _weighting(sub)
    _f, age = sw.factor_for_row(
        is_pick=False, row_key="off25", universe="offense", key_universe=universes
    )
    assert round(age) >= 803


@pytest.mark.parametrize(
    "case",
    ["single_universe", "explicit_style", "no_row_clocks", "thin_second_universe"],
)
def test_no_universe_clock_where_the_board_does_not_span_universes(case):
    if case == "single_universe":
        sub, universes = _subset(idp=0, idp_new=0)
    elif case == "explicit_style":
        sub, universes = _subset(style="EXPLICIT_UPSTREAM_TIMESTAMP")
    elif case == "no_row_clocks":
        sub, universes = _subset()
        sub.row_changed_at = {}
    else:
        sub, universes = _subset(idp=4, idp_new=4)
    assert sub.universe_clock("offense", universes) is None


def test_pipeline_applies_it_only_to_offense_rows_of_mixed_boards():
    from src.api.data_contract import build_api_data_contract
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _ = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")

    def build(on):
        os.environ["RISKIT_FEATURE_SOURCE_UNIVERSE_FRESHNESS"] = "1" if on else "0"
        ff.reload()
        try:
            return build_api_data_contract(json.loads(json.dumps(payload)))
        finally:
            os.environ.pop("RISKIT_FEATURE_SOURCE_UNIVERSE_FRESHNESS", None)
            ff.reload()

    off, on = build(False), build(True)
    after = {r["displayName"]: r for r in on["playersArray"]}
    for row in off["playersArray"]:
        other = after.get(row["displayName"])
        if other is None:
            continue
        for key, meta in (row.get("sourceRankMeta") or {}).items():
            f_off = meta.get("freshness", 1.0)
            f_on = ((other.get("sourceRankMeta") or {}).get(key) or {}).get("freshness", 1.0)
            if row.get("assetClass") in ("idp", "pick"):
                assert f_on == f_off, (row["displayName"], key)
            else:
                assert f_on <= f_off + 1e-9, (row["displayName"], key)


def test_universe_clocks_are_computed_once_per_map_and_refresh_for_a_new_map():
    sub, universes = _subset()
    first = sub.universe_clock("offense", universes)
    sub.row_changed_at["off0"] = "2026-09-29T00:00:00Z"  # ignored: same map, cached
    assert sub.universe_clock("offense", universes) == first
    fresh_map = dict(universes)  # a new build's map recomputes
    assert sub.universe_clock("offense", fresh_map) == first  # one row cannot reach threshold
