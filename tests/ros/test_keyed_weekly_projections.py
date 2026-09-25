"""C5-PROJ-C — keyed WEEKLY projection sources: Fantasy Nerds + SportsDataIO.

Every fixture here is SYNTHETIC (see each file's ``_comment``): SportsDataIO
rows follow its published OpenAPI schema; Fantasy Nerds publishes no
response schema, so its fixture exercises the parser contract only. No
network anywhere: every fetch injects its transport, and the refusal tests
prove the transport is never called. No real key is used — the "secret"
below is a random test sentinel.
"""

from __future__ import annotations

import json
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.api import feature_flags
from src.league_intel.scorer import score_stat_line
from src.ros import fantasynerds_weekly_projections as fn
from src.ros import keyed_weekly_projections as kw
from src.ros import projection_source_census as census
from src.ros import sportsdataio_weekly_projections as sdio
from src.ros.projection_observations import ProjectionObservationError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "game_day" / "keyed_projections"
DYNASTY_MAIN_CARD = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "league_intel"
    / "sleeper_league_snapshot_2026-07-26.json"
)
OBSERVED_AT = "2026-09-24T18:00:00+00:00"
#: Test sentinel only — random, not a credential for any service.
SENTINEL_SECRET = "tEsT-sEnTiNeL-7f3a9c1e5b"
SMALL_CARD = {
    "pass_yd": 0.04,
    "pass_td": 4.0,
    "pass_int": -2.0,
    "pass_inc": -0.5,
    "rush_yd": 0.1,
    "rec": 1.0,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "bonus_rec_te": 0.5,
    "fum_lost": -2.0,
    "fgm": 3.0,
    "fgmiss": -1.0,
    "xpm": 1.0,
    "xpmiss": -1.0,
    "idp_tkl_solo": 1.0,
    "idp_tkl_ast": 0.5,
    "idp_sack": 4.0,
}

# Identity is the caller's (the identity owner's) job; these fixtures'
# fictitious provider ids map to fictitious Sleeper ids. 900006 is left
# unresolved on purpose.
SDIO_XWALK = {"900001": "s1", "900002": "s2", "900003": "s3", "900004": "s4", "900005": "s5"}
FN_XWALK = {"fn-101": "s1", "fn-102": "s2", "fn-103": "s4", "fn-104": "s-def"}


def _sdio_resolve(ref: kw.ProviderPlayerRef) -> str | None:
    return SDIO_XWALK.get(ref.provider_player_id)


def _fn_resolve(ref: kw.ProviderPlayerRef) -> str | None:
    return FN_XWALK.get(ref.provider_player_id)


def _load(name: str):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert "SYNTHETIC" in data["_comment"]
    return data["payload"]


def _main_card() -> dict:
    return json.loads(DYNASTY_MAIN_CARD.read_text(encoding="utf-8"))["scoring_settings"]


def _sdio_batch(card=SMALL_CARD, payload=None, **kw_args):
    return sdio.build_weekly_observations(
        _load("sportsdataio_w3_SYNTHETIC.json") if payload is None else payload,
        season=2026,
        week=3,
        observed_at=OBSERVED_AT,
        scoring_settings=card,
        resolve_player=_sdio_resolve,
        **kw_args,
    )


def _fn_batch(card=SMALL_CARD, payload=None):
    return fn.build_weekly_observations(
        _load("fantasynerds_w3_SYNTHETIC.json") if payload is None else payload,
        season=2026,
        week=3,
        observed_at=OBSERVED_AT,
        scoring_settings=card,
        resolve_player=_fn_resolve,
    )


@pytest.fixture(autouse=True)
def _reset_flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


class _Transport:
    def __init__(self, body=b"[]", headers=None, exc=None):
        self.body, self.headers, self.exc = body, headers or {}, exc
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers, timeout):
        self.calls.append((url, dict(headers)))
        if self.exc is not None:
            raise self.exc
        return kw.HttpResponse(body=self.body, headers=self.headers)


def _now():
    return datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)


# ── SportsDataIO: parsing, mapping, exact scoring ────────────────────


class TestSportsDataIoParsing:
    def test_rows_become_observations_and_refusals_are_counted(self):
        mb = _sdio_batch()
        ids = [o.sleeper_player_id for o in mb.batch.observations]
        assert ids == ["s1", "s2", "s3", "s4", "s5"]
        assert dict(mb.batch.refused) == {"unresolved_identity": 1, "week_mismatch": 1}
        assert [r.provider_player_id for r in mb.unresolved_players] == ["900006"]
        assert mb.stat_mapping_version == sdio.STAT_MAPPING_VERSION

    def test_stat_mapping_to_sleeper_keys(self):
        qb = _sdio_batch().batch.by_player_id()["s1"]
        line = dict(qb.stat_line)
        assert line["pass_yd"] == 255.0
        assert line["pass_cmp"] == 22.5 and line["pass_att"] == 34.0
        assert line["pass_int"] == 0.7 and line["pass_sack"] == 2.1
        assert line["rush_yd"] == 18.0 and line["fum_lost"] == 0.2
        # Linear identity of expectations, derived:
        assert line["pass_inc"] == pytest.approx(11.5)
        # Offensive rows never take IDP rules, even when the provider
        # publishes a tackle for them.
        assert not any(k.startswith("idp_") for k in line)
        assert qb.position == "QB" and qb.team == "AAA" and qb.opponent == "BBB"
        assert qb.model_company == "sportsdataio"
        assert qb.provider_family == "sportsDataIo"
        assert qb.native_points_ppr == 17.9

    def test_te_bonus_kicker_misses_and_idp_are_linear_derivations_or_direct(self):
        obs = _sdio_batch().batch.by_player_id()
        assert obs["s2"].stat_line["bonus_rec_te"] == 5.0
        k = obs["s3"].stat_line
        assert k["fgmiss"] == pytest.approx(0.3) and k["xpmiss"] == pytest.approx(0.1)
        assert k["fgm_50p"] == 0.3
        lb = obs["s4"].stat_line
        assert lb["idp_tkl_solo"] == 5.1 and lb["idp_tkl"] == 8.0
        assert lb["idp_tkl_loss"] == 0.6 and lb["idp_pass_def"] == 0.5
        assert obs["s4"].position == "LB"
        # DE row publishes no ``Tackles``: combined is derived solo + ast.
        assert obs["s5"].stat_line["idp_tkl"] == pytest.approx(3.6)
        assert obs["s5"].position == "DL"

    def test_scored_by_the_exact_scorer_under_the_callers_card(self):
        mb = _sdio_batch()
        for o in mb.batch.observations:
            assert (
                o.league_scored_points
                == score_stat_line(dict(o.stat_line), SMALL_CARD).total_points
            )
        qb = mb.batch.by_player_id()["s1"]
        # pass_yd + pass_td + pass_int + derived pass_inc + rush_yd + fum_lost
        expected = 255 * 0.04 + 1.8 * 4.0 + 0.7 * -2 + 11.5 * -0.5 + 18 * 0.1 + 0.2 * -2
        assert qb.league_scored_points == pytest.approx(expected)

    def test_null_stat_is_missing_not_zero(self):
        te = _sdio_batch(card=_main_card()).batch.by_player_id()["s2"]
        assert "fum_lost" not in te.stat_line  # FumblesLost: null
        assert "fum_lost" in te.uncovered_scoring_keys  # a gap, not a 0

    def test_unmapped_provider_stats_are_reported_not_scored(self):
        mb = _sdio_batch()
        assert "PassingSackYards" in mb.unmapped_provider_fields
        # Ratios / metadata / DFS are deliberately ignored, not "unmapped".
        for ignored in ("PassingRating", "DraftKingsSalary", "FantasyPointsPPR", "PlayerID"):
            assert ignored not in mb.unmapped_provider_fields

    def test_uncovered_league_keys_under_the_real_dynasty_main_card(self):
        obs = _sdio_batch(card=_main_card()).batch.by_player_id()
        qb = set(obs["s1"].uncovered_scoring_keys)
        # First downs, pick-six and length buckets are not in the feed.
        assert {"bonus_fd_qb", "pass_int_td"} <= qb
        assert "pass_yd" not in qb and "pass_inc" not in qb
        k = set(obs["s3"].uncovered_scoring_keys)
        assert {"fgm_yds", "fgmiss_40_49"} <= k
        lb = set(obs["s4"].uncovered_scoring_keys)
        assert "idp_tkl_solo" not in lb and "idp_sack" not in lb
        # Team-defense rules are not a player's gap.
        assert "pts_allow" not in qb and "yds_allow" not in lb


# ── Fantasy Nerds: aggregate, unverified schema, fail-loud parsing ───


class TestFantasyNerdsParsing:
    def test_envelope_rows_map_and_team_unit_is_refused(self):
        mb = _fn_batch()
        obs = mb.batch.by_player_id()
        assert sorted(obs) == ["s1", "s2", "s4"]
        assert mb.batch.refused["team_unit"] == 1
        qb = obs["s1"].stat_line
        assert qb["pass_yd"] == 240.0 and qb["pass_inc"] == pytest.approx(12.0)
        assert obs["s2"].stat_line["bonus_rec_te"] == 4.5
        assert obs["s1"].model_company == "fantasynerds_consensus"

    def test_ambiguous_categories_stay_unmapped_and_uncovered(self):
        mb = _fn_batch(card=_main_card())
        obs = mb.batch.by_player_id()
        # "fumbles" could be fumbles or fumbles LOST; "tackles" solo or combined.
        assert "fumbles" in mb.unmapped_provider_fields
        assert "tackles" in mb.unmapped_provider_fields
        assert "fum_lost" not in obs["s1"].stat_line
        assert "fum_lost" in obs["s1"].uncovered_scoring_keys
        assert "idp_tkl_solo" not in obs["s4"].stat_line
        assert "idp_tkl_solo" in obs["s4"].uncovered_scoring_keys
        assert obs["s4"].stat_line["idp_tkl_ast"] == 3.0

    def test_payload_that_does_not_state_its_week_is_refused(self):
        payload = dict(_load("fantasynerds_w3_SYNTHETIC.json"))
        payload.pop("week")
        mb = _fn_batch(payload=payload)
        assert mb.batch.observations == ()
        assert mb.batch.refused["week_unverifiable"] == 3

    def test_unrecognised_schema_fails_health_loudly(self):
        payload = {"season": 2026, "week": 3, "players": [
            {"playerId": "fn-101", "team": "AAA", "position": "QB", "pYdsX": 240.0},
        ]}  # fmt: skip
        mb = _fn_batch(payload=payload)
        assert mb.batch.refused["no_mapped_stats"] == 1
        assert "pYdsX" in mb.unmapped_provider_fields
        fetch = kw.KeyedFetchResult(
            status="ok", census_source_key=fn.CENSUS_SOURCE_KEY, feed="offense", season=2026,
            week=3, url="x", observed_at=OBSERVED_AT, credential_env_var=fn.CREDENTIAL_ENV_VAR,
        )  # fmt: skip
        health = kw.assess_fetch_health(fetch, mb)
        assert health.healthy is False and "schema_drift" in health.reason

    def test_unrecognised_envelope_raises(self):
        with pytest.raises(kw.WeeklyProjectionError):
            fn.parse_rows({"message": "nope"})

    def test_schema_is_declared_unverified(self):
        assert fn.SCHEMA_VERIFIED is False
        assert census.get_source(fn.CENSUS_SOURCE_KEY)["responseSchemaStatus"] == "UNVERIFIED"


# ── Credentials: missing is unavailable, never zero; never leaked ────


class TestCredentials:
    @pytest.mark.parametrize("mod", [sdio, fn])
    def test_flag_off_makes_no_call(self, mod, monkeypatch):
        monkeypatch.setenv(mod.CREDENTIAL_ENV_VAR, SENTINEL_SECRET)
        t = _Transport()
        r = mod.fetch_weekly_projection_rows(2026, 3, http_get=t, now=_now)
        assert r.status == "feature_disabled" and not r.ok and t.calls == []

    @pytest.mark.parametrize("mod", [sdio, fn])
    def test_missing_credential_is_an_explicit_refusal(self, mod, monkeypatch):
        monkeypatch.setenv(f"RISKIT_FEATURE_{mod.FEATURE_FLAG.upper()}", "1")
        feature_flags.reload()
        t = _Transport()
        r = mod.fetch_weekly_projection_rows(2026, 3, env={}, http_get=t, now=_now)
        assert r.status == "credential_missing"
        assert r.payload is None and r.observed_at is None
        assert mod.CREDENTIAL_ENV_VAR in r.reason and "not zero" in r.reason
        assert t.calls == []
        blank = mod.fetch_weekly_projection_rows(
            2026, 3, env={mod.CREDENTIAL_ENV_VAR: "   "}, http_get=t, now=_now
        )
        assert blank.status == "credential_missing" and t.calls == []

    def test_sportsdataio_key_travels_in_the_header_only(self, monkeypatch):
        monkeypatch.setenv("RISKIT_FEATURE_SPORTSDATAIO_WEEKLY_PROJECTIONS", "1")
        feature_flags.reload()
        t = _Transport(body=b"[]", headers={"last-modified": "Thu, 24 Sep 2026 17:45:00 GMT"})
        r = sdio.fetch_weekly_projection_rows(
            2026,
            3,
            feed="idp",
            env={sdio.CREDENTIAL_ENV_VAR: SENTINEL_SECRET},
            http_get=t,
            now=_now,
        )
        assert r.ok and r.payload == [] and r.observed_at == _now().isoformat()
        url, headers = t.calls[0]
        assert url == (
            "https://api.sportsdata.io/v3/nfl/projections/json/"
            "IdpPlayerGameProjectionStatsByWeek/2026REG/3"
        )
        assert SENTINEL_SECRET not in url
        assert headers == {"Ocp-Apim-Subscription-Key": SENTINEL_SECRET}
        assert r.payload_last_modified == "2026-09-24T17:45:00+00:00"
        assert SENTINEL_SECRET not in repr(r)

    def test_fantasynerds_key_never_appears_in_result_log_or_exception(self, monkeypatch, caplog):
        monkeypatch.setenv("RISKIT_FEATURE_FANTASYNERDS_WEEKLY_PROJECTIONS", "1")
        feature_flags.reload()
        env = {fn.CREDENTIAL_ENV_VAR: SENTINEL_SECRET}
        # A transport whose error message echoes the full keyed URL — the
        # worst case a real HTTP library can produce.
        seen: list[str] = []

        def leaky(url, headers, timeout):
            seen.append(url)
            logging.getLogger("test.transport").error("GET %s failed", url)
            raise ConnectionError(f"failed to fetch {url} (apikey={SENTINEL_SECRET})")

        with caplog.at_level(logging.DEBUG):
            r = fn.fetch_weekly_projection_rows(2026, 3, env=env, http_get=leaky, now=_now)
        assert SENTINEL_SECRET in seen[0]  # it really was on the wire URL
        assert r.status == "fetch_failed"
        rendered = [r.reason, r.url, repr(r), str(r)]
        assert all(SENTINEL_SECRET not in text for text in rendered)
        assert "<redacted>" in r.reason and "apikey=<redacted>" in r.url
        # Our module logged nothing containing it (the transport's own log
        # line is the only occurrence, and it is not ours).
        ours = [rec for rec in caplog.records if rec.name.startswith("src.")]
        assert all(SENTINEL_SECRET not in rec.getMessage() for rec in ours)

        ok = fn.fetch_weekly_projection_rows(
            2026, 3, env=env, http_get=_Transport(body=b'{"season":2026}'), now=_now
        )
        assert ok.ok and SENTINEL_SECRET not in repr(ok)
        bad = fn.fetch_weekly_projection_rows(
            2026, 3, env=env, http_get=_Transport(body=b"not json"), now=_now
        )
        assert bad.status == "bad_payload" and SENTINEL_SECRET not in repr(bad)

    def test_secret_wrapper_never_renders_or_serializes_its_value(self):
        cred = kw.read_credential("X_API_KEY", {"X_API_KEY": SENTINEL_SECRET})
        assert cred is not None and cred.reveal() == SENTINEL_SECRET
        assert SENTINEL_SECRET not in repr(cred) and SENTINEL_SECRET not in str(cred)
        assert SENTINEL_SECRET not in f"{cred}"
        with pytest.raises(TypeError):
            pickle.dumps(cred)

    def test_redact_scrubs_query_params_and_headers_by_name(self):
        text = "GET https://h/p?apikey=abc123&x=1 key=zzz Ocp-Apim-Subscription-Key: qqq9"
        out = kw.redact(text)
        assert "abc123" not in out and "qqq9" not in out and "x=1" in out

    def test_canonical_env_var_names_are_registered_empty_in_env_example(self):
        example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
        for mod in (sdio, fn):
            assert f"# {mod.CREDENTIAL_ENV_VAR}=\n" in example
            entry = census.get_source(mod.CENSUS_SOURCE_KEY)
            assert entry["credentialEnvVar"] == mod.CREDENTIAL_ENV_VAR


# ── Capability gate ──────────────────────────────────────────────────


class TestCapability:
    def _healthy(self, key):
        return kw.SourceHealth(key, True, OBSERVED_AT, "ok", 5)

    def test_available_only_with_flag_key_and_healthy_fetch(self, monkeypatch):
        env = {sdio.CREDENTIAL_ENV_VAR: SENTINEL_SECRET}
        off = sdio.source_available(self._healthy(sdio.CENSUS_SOURCE_KEY), env=env)
        assert off.available is False and "feature_disabled" in off.reasons[0]
        monkeypatch.setenv("RISKIT_FEATURE_SPORTSDATAIO_WEEKLY_PROJECTIONS", "1")
        feature_flags.reload()
        on = sdio.source_available(self._healthy(sdio.CENSUS_SOURCE_KEY), env=env)
        assert on.available is True and on.reasons == () and on.health_state == "healthy"
        no_key = sdio.source_available(self._healthy(sdio.CENSUS_SOURCE_KEY), env={})
        assert no_key.available is False
        assert no_key.reasons == ("credential_missing:SPORTSDATAIO_API_KEY",)
        unknown = sdio.source_available(None, env=env)
        assert unknown.available is False and unknown.health_state == "unknown"
        other = sdio.source_available(self._healthy(fn.CENSUS_SOURCE_KEY), env=env)
        assert other.available is False

    def test_one_missing_credential_does_not_touch_the_other_source(self, monkeypatch):
        monkeypatch.setenv("RISKIT_FEATURE_SPORTSDATAIO_WEEKLY_PROJECTIONS", "1")
        monkeypatch.setenv("RISKIT_FEATURE_FANTASYNERDS_WEEKLY_PROJECTIONS", "1")
        feature_flags.reload()
        env = {sdio.CREDENTIAL_ENV_VAR: SENTINEL_SECRET}  # Fantasy Nerds key absent
        assert sdio.source_available(self._healthy(sdio.CENSUS_SOURCE_KEY), env=env).available
        assert not fn.source_available(self._healthy(fn.CENSUS_SOURCE_KEY), env=env).available

    def test_health_from_a_real_parse(self):
        fetch = kw.KeyedFetchResult(
            status="ok", census_source_key=sdio.CENSUS_SOURCE_KEY, feed="offense", season=2026,
            week=3, url="x", observed_at=OBSERVED_AT, credential_env_var=sdio.CREDENTIAL_ENV_VAR,
        )  # fmt: skip
        assert kw.assess_fetch_health(fetch, _sdio_batch()).healthy is True
        missing = kw.KeyedFetchResult(
            status="credential_missing", census_source_key=sdio.CENSUS_SOURCE_KEY, feed="offense",
            season=2026, week=3, url="x", observed_at=None,
            credential_env_var=sdio.CREDENTIAL_ENV_VAR, reason="unset",
        )  # fmt: skip
        assert kw.assess_fetch_health(missing).healthy is False


# ── Baseline lock + ensemble adapter are REUSED, not duplicated ──────


class TestSharedMachinery:
    def test_kickoff_lock_is_the_shared_one_keyed_by_team_week(self):
        assert sdio.lock_baseline_at_kickoff is fn.lock_baseline_at_kickoff
        from src.ros import sleeper_weekly_projections as swp

        assert sdio.lock_baseline_at_kickoff is swp.lock_baseline_at_kickoff
        pre = _sdio_batch(payload=None).batch.observations
        post = sdio.build_weekly_observations(
            _load("sportsdataio_w3_SYNTHETIC.json"),
            season=2026,
            week=3,
            observed_at="2026-09-27T18:00:00+00:00",
            scoring_settings=SMALL_CARD,
            resolve_player=_sdio_resolve,
        ).batch.observations
        kick = "2026-09-27T17:00:00+00:00"
        kickoffs = {
            kw.team_week_game_id(2026, 3, "AAA"): kick,
            kw.team_week_game_id(2026, 3, "BBB"): kick,
        }
        lock = sdio.lock_baseline_at_kickoff([*pre, *post], kickoffs, now=kick)
        assert set(lock.baselines) == {"s1", "s2", "s3", "s4", "s5"}
        assert all(b.observation.observed_at == OBSERVED_AT for b in lock.baselines.values())
        assert lock.post_kickoff_observations_ignored == 5

    def test_ensemble_adapter_dates_by_provider_stamp_only(self):
        undated = _sdio_batch().batch.by_player_id()["s1"]
        with pytest.raises(ProjectionObservationError):
            sdio.to_projection_observation(undated)
        dated = _sdio_batch(payload_last_modified="2026-09-24T17:45:00+00:00").batch
        po = sdio.to_projection_observation(dated.by_player_id()["s1"])
        assert po.provider_family == "sportsDataIo" and po.horizon == "WEEKLY"
        assert po.access_posture == "KEYED_API_CREDENTIAL_REQUIRED"
        assert po.games == 1.0 and po.as_of == "2026-09-24T17:45:00+00:00"


# ── Census: family, ancestry, access, licensing ──────────────────────


class TestCensusEntries:
    def test_both_entries_are_weekly_seasonal_keyed_and_owner_attested(self):
        for key, flag, env in (
            (sdio.CENSUS_SOURCE_KEY, sdio.FEATURE_FLAG, sdio.CREDENTIAL_ENV_VAR),
            (fn.CENSUS_SOURCE_KEY, fn.FEATURE_FLAG, fn.CREDENTIAL_ENV_VAR),
        ):
            src = census.get_source(key)
            assert src["horizons"] == ["WEEKLY"] and src["gameType"] == "WEEKLY"
            assert src["valuationLane"] == "SEASONAL_INTELLIGENCE"
            assert src["accessPosture"] == "KEYED_API_CREDENTIAL_REQUIRED"
            assert src["licensingStatus"] == "OWNER_ATTESTED_AUTHORIZED"
            assert src["implementationStatus"] == "IMPLEMENTED_FLAG_OFF"
            assert src["featureFlag"] == flag and feature_flags._DEFAULTS[flag] is False
            assert src["credentialEnvVar"] == env
        assert census.validate_census() == []

    def test_sportsdataio_is_its_own_independent_family(self):
        src = census.get_source(sdio.CENSUS_SOURCE_KEY)
        assert src["providerFamily"] == "sportsDataIo"
        assert src["modelAncestry"]["isAggregate"] is False
        assert census.ancestry_families(sdio.CENSUS_SOURCE_KEY) == {"sportsDataIo"}

    def test_fantasynerds_is_an_aggregate_and_overlaps_rotowire(self):
        src = census.get_source(fn.CENSUS_SOURCE_KEY)
        assert src["modelAncestry"]["isAggregate"] is True
        assert "rotowire" in src["modelAncestry"]["constituentFamilies"]
        overlaps = census.ancestry_overlaps(
            [sdio.CENSUS_SOURCE_KEY, fn.CENSUS_SOURCE_KEY, "sleeperWeeklyProjections"]
        )
        assert overlaps == [
            (fn.CENSUS_SOURCE_KEY, "sleeperWeeklyProjections", frozenset({"rotowire"}))
        ]
        # Adding SportsDataIO expands the ensemble without a correlated pair.
        assert census.ancestry_overlaps([sdio.CENSUS_SOURCE_KEY, "sleeperWeeklyProjections"]) == []

    def test_validator_requires_aggregate_constituents_and_a_credential_name(self):
        base = {
            "key": "x",
            "evidenceClass": "PROJECTION_MODEL",
            "horizons": ["WEEKLY"],
            "implementationStatus": "GREENFIELD",
            "accessPosture": "KEYED_API_CREDENTIAL_REQUIRED",
            "licensingStatus": "OWNER_ATTESTED_AUTHORIZED",
            # Required for any OWNER_ATTESTED_AUTHORIZED entry (census rule).
            "accessAttestation": "docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md",
            "credentialEnvVar": "X_API_KEY",
            "providerFamily": "x",
            "targetPopulation": ["OFFENSE"],
            "acquisitionOwnerLane": "Claude 11",
        }
        lanes = [{"lane": "DFS_PROJECTION"}]
        assert census.validate_census({"sources": [base], "discoveryLanes": lanes}) == []
        agg = {**base, "modelAncestry": {"isAggregate": True, "constituentFamilies": []}}
        assert any(
            "constituentFamilies" in e
            for e in census.validate_census({"sources": [agg], "discoveryLanes": lanes})
        )
        for bad_name in (None, "x_api_key", "SOME_TOKEN", "abc123def"):
            bad = {**base, "credentialEnvVar": bad_name}
            assert census.validate_census({"sources": [bad], "discoveryLanes": lanes})

    def test_census_carries_names_never_values(self):
        raw = (census.CENSUS_PATH).read_text(encoding="utf-8")
        for key in (sdio.CENSUS_SOURCE_KEY, fn.CENSUS_SOURCE_KEY):
            src = census.get_source(key)
            assert not {"apiKey", "apikey", "key_value", "token", "secret"} & set(src)
        assert "apikey=<key>" in raw  # documented as a placeholder only
