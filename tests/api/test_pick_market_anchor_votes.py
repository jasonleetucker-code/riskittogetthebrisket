"""KTC's pick board reaches the source that is allowed to vote.

Audit finding W05-F006.  On 2026-04-28 the plain ``ktc`` key was demoted
to a non-voting display key and ``ktcSfTep`` became the canonical retail
source — but the scraper's pick model writes KTC's pick values under
``ktc`` only, and nothing re-routed them.  Measured on the 2026-08-04
payload: all 72 current-year slot picks carried ``sourceCount == 1``
with ``anchorValue`` equal to IDPTradeCalc's number alone, while KTC's
number for the same asset sat one key away.

The re-key is safe because a draft pick carries no TE premium: on the
36 pick rows where the ``ktcSfTep`` CSV covers the asset, ``ktc`` and
``ktcSfTep`` agree on all 36 with zero mismatches.

The COVERAGE GUARD is the part that must not be simplified away.  KTC
publishes rounds 1-4 only; for rounds 5-6 the scraper stamps its own
modelled composite under ``ktc`` as a fallback, and mirroring that would
turn the pipeline's output into a source vote for itself.
"""

from __future__ import annotations

from src.api.data_contract import _mirror_ktc_pick_anchors


def _row(name: str, sites: dict) -> dict:
    return {
        "displayName": name,
        "canonicalName": name,
        "assetClass": "pick",
        "canonicalSiteValues": dict(sites),
    }


def _anchors() -> dict:
    # KTC's published board, interpolated onto slots by the scraper:
    # rounds 1-4 real, rounds 5-6 fabricated by ``_put_pick``'s fallback.
    return {
        "ktc": {
            "2026 Early 1st": 5605,
            "2026 1.01": 6726,
            "2026 5.01": 2003,
            "2027 Mid 1st": 5579,
        }
    }


class TestMirror:
    def test_a_covered_slot_pick_gains_the_voting_key(self):
        rows = [
            # Real ktcSfTep coverage for (2026, round 1) comes from the CSV.
            _row("2026 Early 1st", {"ktc": 5605, "ktcSfTep": 5605}),
            _row("2026 Pick 1.01", {"ktc": 6726, "idpTradeCalc": 8013}),
        ]
        assert _mirror_ktc_pick_anchors(rows, _anchors()) == 1
        assert rows[1]["canonicalSiteValues"]["ktcSfTep"] == 6726
        assert rows[1]["ktcSfTepFromPickAnchor"] is True

    def test_a_round_ktc_does_not_publish_is_left_alone(self):
        # Round 5's ``ktc`` value is the pipeline's own composite; using
        # it as a KTC vote would be a fabricated second opinion.
        rows = [
            _row("2026 Early 1st", {"ktc": 5605, "ktcSfTep": 5605}),
            _row("2026 Pick 5.01", {"ktc": 2003}),
        ]
        _mirror_ktc_pick_anchors(rows, _anchors())
        assert "ktcSfTep" not in rows[1]["canonicalSiteValues"]
        assert "ktcSfTepFromPickAnchor" not in rows[1]

    def test_a_year_with_no_anchor_is_left_alone(self):
        # 2029 has no KTC anchor at all.  A pick with no market price
        # has none to show, and inventing one is the failure this
        # codebase already had with a flat 7000/4000/2000/1200 table.
        rows = [
            _row("2026 Early 1st", {"ktc": 5605, "ktcSfTep": 5605}),
            _row("2029 Early 1st", {"ktc": 5144, "idpTradeCalc": 5034}),
        ]
        _mirror_ktc_pick_anchors(rows, _anchors())
        assert "ktcSfTep" not in rows[1]["canonicalSiteValues"]

    def test_a_real_ktcsftep_value_is_never_overwritten(self):
        rows = [_row("2026 Early 1st", {"ktc": 1, "ktcSfTep": 5605})]
        assert _mirror_ktc_pick_anchors(rows, _anchors()) == 0
        assert rows[0]["canonicalSiteValues"]["ktcSfTep"] == 5605

    def test_player_rows_are_untouched(self):
        row = {
            "displayName": "Bijan Robinson",
            "assetClass": "offense",
            "canonicalSiteValues": {"ktc": 8000},
        }
        rows = [_row("2026 Early 1st", {"ktc": 5605, "ktcSfTep": 5605}), row]
        _mirror_ktc_pick_anchors(rows, _anchors())
        assert "ktcSfTep" not in row["canonicalSiteValues"]

    def test_no_ktcsftep_coverage_at_all_mirrors_nothing(self):
        # Without a single CSV-loaded ktcSfTep pick row there is no
        # evidence of which years/rounds KTC covers, so the pass
        # abstains rather than guessing.
        rows = [_row("2026 Pick 1.01", {"ktc": 6726})]
        assert _mirror_ktc_pick_anchors(rows, _anchors()) == 0
        assert "ktcSfTep" not in rows[0]["canonicalSiteValues"]

    def test_missing_anchors_is_a_no_op(self):
        rows = [_row("2026 Pick 1.01", {"ktc": 6726})]
        assert _mirror_ktc_pick_anchors(rows, None) == 0
        assert _mirror_ktc_pick_anchors(rows, {}) == 0


class TestWiredIntoTheContract:
    """A unit-tested pass nothing calls is the failure class this audit
    is named after.  Assert the call site, not just the function."""

    def test_build_api_data_contract_routes_the_anchor(self):
        from src.api.data_contract import build_api_data_contract

        raw = {
            "players": {
                "2026 Early 1st": {
                    "ktc": 5605,
                    "ktcSfTep": 5605,
                    "_composite": 5605,
                    "_sites": 2,
                    "_rawComposite": 5605,
                    "_finalAdjusted": 5605,
                },
                "2026 Pick 1.01": {
                    "ktc": 6726,
                    "idpTradeCalc": 8013,
                    "_composite": 7587,
                    "_sites": 2,
                    "_rawComposite": 7587,
                    "_finalAdjusted": 7587,
                },
                "2026 Pick 5.01": {
                    "ktc": 2003,
                    "_composite": 2003,
                    "_sites": 1,
                    "_rawComposite": 2003,
                    "_finalAdjusted": 2003,
                },
            },
            "sites": [{"key": "ktc"}, {"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
            "pickAnchors": {
                "ktc": {"2026 Early 1st": 5605, "2026 1.01": 6726, "2026 5.01": 2003}
            },
            "sleeper": {},
        }
        rows = {
            r["displayName"]: r for r in build_api_data_contract(raw)["playersArray"]
        }
        assert rows["2026 Pick 1.01"]["canonicalSiteValues"]["ktcSfTep"] == 6726
        assert rows["2026 Pick 1.01"]["ktcSfTepFromPickAnchor"] is True
        # Round 5 is outside KTC's published board and stays unvoted.
        assert rows["2026 Pick 5.01"]["canonicalSiteValues"].get("ktcSfTep") is None
