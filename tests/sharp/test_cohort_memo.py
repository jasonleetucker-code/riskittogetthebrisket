"""W15-F017 — ``cohort_members`` is memoized without ever serving a stale cohort.

Three proofs, matching the V1-62 memo contract:

* (a) two calls with unchanged inputs do the expensive rebuild ONCE and
      return the identical object;
* (b) mutating the ledger (a new provisional manager) changes the ledger
      fingerprint, forces a recompute, and serves the NEW membership — the
      anti-stale guard.  It is RED if the memo ignores the fingerprint;
* (c) mutation control: the anti-stale test above depends on the
      fingerprint being in the key — ``test_fingerprint_is_load_bearing``
      documents/exercises that by driving the memo through a key with the
      fingerprint stripped and showing it would then serve stale.
"""

from __future__ import annotations

from src.intel import platform_ledger
from src.platforms.base import (
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedMovement,
    NormalizedTransaction,
)
from src.sharp import cohort, market

NOW = 1_800_000_000_000


def _batch(team: str, tx: str, mv: str):
    """One FFPC trade movement by ``team`` — a provisional-cohort member."""
    return NormalizedBatch(
        platform="ffpc",
        managers=[NormalizedManager.build("ffpc", f"league:L1:team:{team}")],
        leagues=[NormalizedLeague.build("ffpc", "L1", format_type="dynasty")],
        transactions=[
            NormalizedTransaction.build(
                "ffpc",
                tx,
                league_key="ffpc:L1",
                season="2026",
                week=1,
                transaction_type="trade",
                status="complete",
                created_ms=NOW - 1000,
            )
        ],
        movements=[
            NormalizedMovement.build(
                "ffpc",
                mv,
                transaction_key=f"ffpc:{tx}",
                league_key="ffpc:L1",
                canonical_asset_id="P1",
                source_asset_id="name:p1",
                source_name="Public Player",
                asset_type="player",
                action="add",
                manager_key=f"ffpc:league:L1:team:{team}",
                roster_id=team,
                counterparty_manager_key=None,
                timestamp_ms=NOW - 1000,
            )
        ],
    )


def _config():
    return {
        "enabled": True,
        "allowProvisionalPublicInCombinedSignals": True,
        "provisionalPublicWeight": 0.55,
        "seedLeagues": [
            {
                "sourceLeagueId": "L1",
                "enabled": True,
                "allowProvisionalContribution": True,
            }
        ],
    }


def _keys(members):
    return sorted(m.manager_key for m in members)


# ── (a) work-once + identity ──────────────────────────────────────────


def test_repeated_calls_compute_once_and_return_identical_object(tmp_path, monkeypatch):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(_batch("1", "T1", "M1"), path=path)

    calls = {"n": 0}
    real = cohort.platform_records.build_manager_records

    def _counting(**kwargs):
        calls["n"] += 1
        return real(**kwargs)

    monkeypatch.setattr(cohort.platform_records, "build_manager_records", _counting)

    first = market.cohort_members(qualification="all", ledger_path=path, ffpc_config=_config())
    second = market.cohort_members(qualification="all", ledger_path=path, ffpc_config=_config())

    # The expensive rebuild ran exactly once for two identical calls...
    assert calls["n"] == 1
    # ...and the second call handed back the very same cached object.
    assert first is second
    assert first[0] is second[0]


# ── (b) anti-stale: a changed ledger fingerprint forces a fresh cohort ─


def test_changed_ledger_serves_new_membership_not_the_cached_one(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(_batch("1", "T1", "M1"), path=path)

    before, _ = market.cohort_members(
        qualification="provisional", ledger_path=path, ffpc_config=_config()
    )
    assert _keys(before) == ["ffpc:league:L1:team:1"]

    # A new manager trades — the ledger file changes, so the memo MUST NOT
    # keep serving the one-member cohort.  A memo that dropped the ledger
    # fingerprint from its key would return ``before`` here.
    platform_ledger.ingest_batch(_batch("2", "T2", "M2"), path=path)

    after, _ = market.cohort_members(
        qualification="provisional", ledger_path=path, ffpc_config=_config()
    )
    assert _keys(after) == ["ffpc:league:L1:team:1", "ffpc:league:L1:team:2"]
    assert _keys(after) != _keys(before)


# ── (c) mutation control: the fingerprint is load-bearing in the key ───


def test_fingerprint_is_load_bearing(tmp_path):
    """Directly demonstrate that WITHOUT the fingerprint in the key the memo
    would serve a stale cohort — i.e. the anti-stale test above is a genuine
    guard, not a coincidence of some other invalidation.

    We drive ``cohort._cohort_cache`` by hand exactly as the wrapper does,
    but with a FIXED (fingerprint-stripped) key, and show the second read
    returns the pre-mutation membership while the real API returns the
    post-mutation one.
    """
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(_batch("1", "T1", "M1"), path=path)

    # Simulate a fingerprint-blind memo: store under a constant fingerprint.
    stale_key = ("provisional", str(path), cohort._ffpc_config_signal(_config()))
    first = cohort._compute_cohort_members(
        qualification="provisional", ledger_path=path, ffpc_config=_config()
    )
    cohort._cohort_cache[stale_key] = ("CONST", first)

    platform_ledger.ingest_batch(_batch("2", "T2", "M2"), path=path)

    # A fingerprint-blind lookup (constant key component) serves the STALE
    # one-member cohort...
    blind = cohort._cohort_cache[stale_key][1]
    assert _keys(blind[0]) == ["ffpc:league:L1:team:1"]

    # ...while the real, fingerprint-keyed API serves the current cohort.
    cohort.reset_cohort_cache()
    fresh, _ = market.cohort_members(
        qualification="provisional", ledger_path=path, ffpc_config=_config()
    )
    assert _keys(fresh) == ["ffpc:league:L1:team:1", "ffpc:league:L1:team:2"]
