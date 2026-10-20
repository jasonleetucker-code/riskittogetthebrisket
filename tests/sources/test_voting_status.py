"""Per-source voting status (owner directive 2026-10-19 §5 / §8).

``src/sources/voting_status.py`` decides nothing: every status is read from
the weighting the blend applied and the stamps the contract carries.  These
tests pin the plain-English status rules and that the payload carries no
player values (public-safe).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.sources import freshness as fr
from src.sources import voting_status as vs

NOW = datetime(2026, 10, 19, 6, 0, tzinfo=timezone.utc)
CFG = fr.load_config()
STEP = fr.load_step_schedule()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _state(
    days_ago: float | None, *, upstream: str | None = None, health="HEALTHY", baseline=False
):
    clock = NOW - timedelta(days=days_ago or 0)
    first = clock if baseline else clock - timedelta(days=200)
    return {
        "subsets": {
            "players": {
                "changeHistory": []
                if baseline
                else [{"at": _iso(clock), "broad": True, "rowsChanged": 9, "rowsTotal": 100}],
                "firstObservedAt": _iso(first),
                "firstObservationIsBaseline": True,
                "lastAnyMeaningfulChangeAt": _iso(clock),
                "lastBroadDatasetChangeAt": _iso(clock),
                "rowCount": 100,
                "rowCountHistory": [100],
                "rowChangedAt": {},
            }
        },
        "health": {
            "state": health,
            "errors": ["board carries no numeric rows"] if health == "FAILED" else [],
        },
        "upstream": {"publishedAt": upstream, "version": None},
    }


def _w(key, state):
    return fr.assess_source(key, state, as_of=NOW, cfg=CFG, schedule=fr.SCHEDULE_V2, step=STEP)


def _src(key, scope="overall_offense", **kw):
    return {"key": key, "display_name": key.upper(), "scope": scope, "weight": 1.0, **kw}


def _row(position, metas):
    return {
        "displayName": "SECRET NAME",
        "position": position,
        "rankDerivedValue": 4321,
        "sourceRankMeta": metas,
    }


def _voted(w=1.0):
    return {"appliedWeight": w, "valueContribution": 9999}


def _build(
    registry, weighting, rows, *, active=None, vote_states=None, seasonal=None, applied=True
):
    active = active if active is not None else [s["key"] for s in registry]
    contract = {
        "playersArray": rows,
        "sourceWeighting": {"applied": applied, "sources": {k: {} for k in active}},
        "privateSourceAvailability": vote_states or {},
        "sourceSeasonalState": {"inactive": seasonal or {}},
    }
    return vs.build_source_voting_status(contract, weighting, registry, as_of=NOW)


def _by_key(block):
    return {e["key"]: e for e in block["sources"]}


class TestStatuses:
    def test_active_steps_follow_the_schedule(self):
        reg = [_src("a"), _src("b"), _src("c"), _src("d")]
        weighting = {
            "a": _w("a", _state(2)),
            "b": _w("b", _state(9)),
            "c": _w("c", _state(16)),
            "d": _w("d", _state(23)),
        }
        rows = [_row("QB", {k: _voted() for k in "abcd"})]
        out = _by_key(_build(reg, weighting, rows))
        assert [out[k]["status"] for k in "abcd"] == [
            "active_100",
            "active_75",
            "active_50",
            "active_25",
        ]
        assert [out[k]["freshnessPct"] for k in "abcd"] == [100.0, 75.0, 50.0, 25.0]
        assert [out[k]["effectiveWeight"] for k in "abcd"] == [1.0, 0.75, 0.5, 0.25]
        assert out["a"]["restoreRequirement"] is None
        assert "100%" in out["b"]["restoreRequirement"]
        assert out["b"]["statusLabel"] == "Active — 75%"

    def test_older_than_thirty_days_is_stale_even_when_downloaded(self):
        reg = [_src("fp", "overall_idp")]
        weighting = {"fp": _w("fp", _state(10, upstream=_iso(NOW - timedelta(days=45))))}
        rows = [
            _row(
                "LB",
                {
                    "fp": {
                        "appliedWeight": 0.0,
                        "contributedToBlend": False,
                        "excludedReason": "freshness_or_health_zero_weight",
                    }
                },
            )
        ]
        e = _by_key(_build(reg, weighting, rows))["fp"]
        assert e["status"] == "stale"
        assert e["voting"] is False
        assert e["lastGenuineUpdateBasis"] == fr.CLOCK_BASIS_PUBLISHER
        assert e["daysSinceUpdate"] == 45
        assert e["effectiveWeight"] == 0.0
        assert e["notVotingRows"] == {"freshness_or_health_zero_weight": 1}
        assert "unchanged rankings do not count" in e["reason"]

    def test_unknown_update_time_is_a_data_issue_not_fresh(self):
        reg = [_src("new")]
        weighting = {"new": _w("new", _state(2, baseline=True))}
        e = _by_key(_build(reg, weighting, []))["new"]
        assert e["status"] == "data_issue"
        assert e["lastGenuineUpdate"] is None
        assert e["lastGenuineUpdateBasis"] == fr.CLOCK_BASIS_UNKNOWN
        assert e["effectiveWeight"] == 0.0

    def test_no_recorded_state_is_unmeasured_and_says_so(self):
        reg = [_src("nostate")]
        weighting = {"nostate": _w("nostate", None)}
        e = _by_key(_build(reg, weighting, [_row("QB", {"nostate": _voted()})]))["nostate"]
        assert e["status"] == "active_100"
        assert e["lastGenuineUpdateBasis"] == fr.CLOCK_BASIS_NOT_TRACKED
        assert e["freshnessPct"] is None
        assert "not measured" in e["reason"]
        idle = _by_key(_build(reg, weighting, []))["nostate"]
        assert idle["status"] == "data_issue"

    def test_seasonal_rookie_board_is_seasonal_not_stale(self):
        reg = [_src("rk", needs_rookie_translation=True)]
        weighting = {"rk": _w("rk", _state(43))}
        out = _build(reg, weighting, [], active=[], seasonal={"rk": {"classYear": 2026}})
        e = _by_key(out)["rk"]
        assert e["status"] == "seasonal"
        assert e["coverage"] == "rookie"
        assert "2026" in e["reason"]

    def test_shadow_source_is_testing(self):
        reg = [_src("sig", "position_idp")]
        vote = {
            "sig": {"state": "present", "voteState": "shadow", "heldFromVote": "x", "votes": False}
        }
        e = _by_key(_build(reg, {"sig": _w("sig", _state(1))}, [], active=[], vote_states=vote))[
            "sig"
        ]
        assert e["status"] == "testing"
        assert e["effectiveWeight"] == 0.0

    def test_owner_policy_hold_is_testing_with_the_decision_named(self):
        reg = [_src("dlfIdp", "overall_idp")]
        vote = {
            "dlfIdp": {
                "state": "present",
                "voteState": "held",
                "holdKind": "owner_policy",
                "holdDecision": "owner directive 2026-10-16: DLF vote is offense-only",
                "rollbackFlag": "dlf_offense_only_vote",
                "heldFromVote": "owner_policy_dlf_vote_offense_only",
                "private": False,
            }
        }
        e = _by_key(
            _build(reg, {"dlfIdp": _w("dlfIdp", _state(1))}, [], active=[], vote_states=vote)
        )["dlfIdp"]
        assert e["status"] == "testing"
        assert "2026-10-16" in e["reason"]
        assert e["voteHold"]["kind"] == "owner_policy"
        assert e["freshnessPct"] == 100.0  # fresh, held for policy reasons only

    def test_not_provisioned_private_source_is_a_data_issue(self):
        reg = [_src("signalsSf")]
        vote = {
            "signalsSf": {"state": "not_provisioned", "voteState": "unavailable", "votes": False}
        }
        e = _by_key(
            _build(reg, {"signalsSf": _w("signalsSf", None)}, [], active=[], vote_states=vote)
        )["signalsSf"]
        assert e["status"] == "data_issue"
        assert "production" in e["reason"]

    def test_failed_board_is_a_data_issue(self):
        reg = [_src("x")]
        e = _by_key(_build(reg, {"x": _w("x", _state(1, health="FAILED"))}, []))["x"]
        assert e["status"] == "data_issue"
        assert "not a usable rankings board" in e["reason"]

    def test_fresh_but_nothing_used_is_a_data_issue(self):
        reg = [_src("x")]
        e = _by_key(_build(reg, {"x": _w("x", _state(1))}, []))["x"]
        assert e["status"] == "data_issue"
        assert e["playersContributing"] == 0


class TestRowTallies:
    def test_counts_and_reasons_come_from_source_rank_meta(self):
        reg = [_src("a", "overall_idp", extra_scopes=["overall_offense"])]
        rows = [
            _row("QB", {"a": _voted(0.75)}),
            _row("LB", {"a": _voted(0.75)}),
            {"assetClass": "pick", "position": "PICK", "sourceRankMeta": {"a": _voted(0.75)}},
            _row("WR", {"a": {"appliedWeight": 0.75, "hampelDropped": True}}),
            _row(
                "TE",
                {"a": {"appliedWeight": 0.5, "contributedToBlend": False, "supersededBy": "b"}},
            ),
        ]
        e = _by_key(_build(reg, {"a": _w("a", _state(9))}, rows))["a"]
        assert e["coverage"] == "combined"
        assert e["contributingByUniverse"] == {"offense": 1, "idp": 1, "pick": 1}
        assert e["playersContributing"] == 2
        assert e["picksContributing"] == 1
        assert e["notVotingRows"] == {"outlier_filter": 1, "superseded_by_family": 1}
        assert e["meanAppliedWeight"] == 0.75


class TestPayload:
    def test_carries_no_player_names_or_values(self):
        reg = [_src("a")]
        out = _build(reg, {"a": _w("a", _state(1))}, [_row("QB", {"a": _voted()})])
        text = repr(out)
        assert "SECRET NAME" not in text
        assert "4321" not in text

    def test_every_registered_source_has_one_entry_in_order(self):
        reg = [_src(k) for k in ("z", "a", "m")]
        out = _build(reg, {k: _w(k, _state(1)) for k in "zam"}, [])
        assert [e["key"] for e in out["sources"]] == ["z", "a", "m"]
        assert out["registeredCount"] == 3
        assert set(out["statusLabels"]) == {
            "active_100",
            "active_75",
            "active_50",
            "active_25",
            "stale",
            "data_issue",
            "seasonal",
            "testing",
        }

    def test_coverage_mapping(self):
        assert vs.coverage_of({"scope": "overall_offense"}) == "offense"
        assert vs.coverage_of({"scope": "overall_idp"}) == "idp"
        assert vs.coverage_of({"scope": "position_idp"}) == "idp"
        assert (
            vs.coverage_of({"scope": "overall_idp", "extra_scopes": ["overall_offense"]})
            == "combined"
        )
        assert (
            vs.coverage_of({"scope": "overall_offense", "needs_rookie_translation": True})
            == "rookie"
        )

    def test_freshness_not_applied_votes_at_base(self):
        reg = [_src("a")]
        out = _build(reg, {"a": _w("a", _state(20))}, [_row("QB", {"a": _voted()})], applied=False)
        e = _by_key(out)["a"]
        assert e["status"] == "active_100"
        assert e["effectiveWeight"] == 1.0
        assert "switched off" in e["reason"]


class TestV1RuleInForceWithV2Shadow:
    """Owner decision 2026-10-20 on PR #1831 (Option B): the step schedule
    ships disabled.  The status then describes the v1 rule truthfully, and
    what v2 WOULD assign is a labelled, non-voting shadow."""

    @staticmethod
    def _v1(key, state):
        return fr.assess_source(key, state, as_of=NOW, cfg=CFG, schedule=fr.SCHEDULE_V1)

    def _out(self, state, *, shadow=True):
        reg = [_src("a")]
        contract = {
            "playersArray": [_row("QB", {"a": _voted()})],
            "sourceWeighting": {"applied": True, "sources": {"a": {}}},
            "privateSourceAvailability": {},
            "sourceSeasonalState": {"inactive": {}},
        }
        return vs.build_source_voting_status(
            contract,
            {"a": self._v1("a", state)},
            reg,
            as_of=NOW,
            shadow_weighting={"a": _w("a", state)} if shadow else None,
        )

    def test_status_reports_the_v1_rule(self):
        out = self._out(_state(10))
        assert out["freshnessSchedule"] == fr.SCHEDULE_V1
        e = _by_key(out)["a"]
        v1 = self._v1("a", _state(10)).subset_for(False).freshness
        assert e["weightFactors"]["freshness"] == round(v1, 4)

    def test_shadow_is_labelled_non_voting_and_shows_the_step(self):
        out = self._out(_state(10))
        assert out["shadow"]["votes"] is False
        assert out["shadow"]["freshnessSchedule"] == fr.SCHEDULE_V2
        shadow = _by_key(out)["a"]["shadowScheduleV2"]
        assert shadow["votes"] is False
        assert shadow["daysSinceUpdate"] == 10
        assert shadow["freshnessPct"] == 75.0
        assert shadow["effectiveWeightIfActivated"] == 0.75

    def test_shadow_changes_nothing_else(self):
        with_shadow = self._out(_state(10))
        without = self._out(_state(10), shadow=False)
        for e in with_shadow["sources"]:
            e.pop("shadowScheduleV2")
        with_shadow.pop("shadow")
        assert with_shadow == without

    def test_no_shadow_when_v2_is_the_rule_in_force(self):
        reg = [_src("a")]
        contract = {
            "playersArray": [_row("QB", {"a": _voted()})],
            "sourceWeighting": {"applied": True, "sources": {"a": {}}},
            "privateSourceAvailability": {},
            "sourceSeasonalState": {"inactive": {}},
        }
        out = vs.build_source_voting_status(
            contract,
            {"a": _w("a", _state(10))},
            reg,
            as_of=NOW,
            shadow_weighting={"a": _w("a", _state(10))},
        )
        assert "shadow" not in out
        assert "shadowScheduleV2" not in _by_key(out)["a"]
