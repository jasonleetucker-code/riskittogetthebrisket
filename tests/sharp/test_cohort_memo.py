"""W15-F017 — ``cohort_members`` is memoized without ever serving a stale cohort.

Four groups of proofs, matching the V1-62 memo contract:

* (a) two calls with unchanged inputs do the expensive rebuild ONCE and
      return the identical object;
* (b) mutating the ledger (a new provisional manager) changes the ledger
      fingerprint, forces a recompute, and serves the NEW membership — the
      anti-stale guard.  It is RED if the memo ignores the fingerprint;
* (c) mutation control: the anti-stale test above depends on the
      fingerprint being in the key — ``test_fingerprint_is_load_bearing``
      documents/exercises that by driving the memo through a key with the
      fingerprint stripped and showing it would then serve stale.
* (d) V1-62 — ``curated.ensure_schema`` must not WRITE to the ledger on a
      call where nothing needs to change.  Before its fix, the version
      stamp there was an unconditional ``INSERT OR REPLACE`` + commit on
      EVERY call, and that write landed in the exact ledger file whose
      ``(mtime_ns, size)`` is the memo's only freshness signal — so every
      cohort build silently invalidated its own cache before the next
      caller could ever see a hit.  Group (a) above does not catch this:
      its ``tmp_path`` fixture happens to hit ``curated_cohort_members``'s
      broad ``except Exception: return []`` (a lock contention artifact
      of calling it immediately after ``build_manager_records`` opens its
      own connection on the same fresh file), so the write never fires in
      that specific setup.  Group (d) forces the schema to be fully
      migrated FIRST (``curated.ensure_schema`` called directly, matching
      ``curated_cohort_members``'s own call shape) so the write path is
      exercised for real, the way a warm production ledger exercises it.
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
from src.sharp import cohort, curated as curated_model, market

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


# ── (d) V1-62: the curated version stamp must not self-poison the memo ──


def _ledger_fingerprint(path):
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def test_ensure_schema_does_not_touch_ledger_once_version_is_current(tmp_path):
    """A steady-state call to ``curated.ensure_schema`` must be a pure read.

    The FIRST call is allowed to migrate (creating the curated tables and
    writing the version stamp for the first time changes the file — that
    is real, necessary work). Every call AFTER that, against an unchanged
    ledger, must leave the file byte-for-byte and mtime-for-mtime alone.
    Before the fix, the unconditional ``INSERT OR REPLACE`` + ``commit()``
    touched the file on every single call.
    """
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(_batch("1", "T1", "M1"), path=path)

    conn = curated_model.ensure_schema(path)
    conn.close()
    fingerprint_after_migration = _ledger_fingerprint(path)

    for _ in range(3):
        conn = curated_model.ensure_schema(path)
        conn.close()
        assert _ledger_fingerprint(path) == fingerprint_after_migration


def test_curated_industry_lookup_does_not_poison_the_cohort_memo(tmp_path, monkeypatch):
    """End-to-end: once the curated schema is warm, repeated
    ``cohort_members`` calls through the REAL ``curated_industry_members``
    path share one rebuild, and the ledger fingerprint never moves between
    them.

    ``curated_industry_members`` (unlike the rest of ``_compute_cohort_members``)
    does not accept or forward a ``ledger_path`` — it always resolves through
    ``src.intel.ledger.default_path()``. That is a separate, narrower
    pre-existing characteristic, not something this test works around
    silently: ``ledger.default_path`` is monkeypatched to point at this
    test's isolated ledger so the write path is exercised against a
    hermetic fixture rather than the real default ledger file. This is
    also why scenario group (a)'s ``tmp_path`` fixture does not reach the
    bug (see module docstring): it never redirects the default path, so
    the curated write there lands on the real default ledger instead of
    the fixture, self-swallowed by ``curated_industry_members``'s broad
    ``except Exception: return []`` on whatever state that file happens
    to be in.
    """
    from src.intel import ledger as ledger_module

    path = tmp_path / "ledger.sqlite3"
    monkeypatch.setattr(ledger_module, "default_path", lambda: path)
    platform_ledger.ingest_batch(_batch("1", "T1", "M1"), path=path)
    curated_model.ensure_schema(path).close()

    calls = {"n": 0}
    real_compute = cohort._compute_cohort_members

    def _counting(**kwargs):
        calls["n"] += 1
        return real_compute(**kwargs)

    monkeypatch.setattr(cohort, "_compute_cohort_members", _counting)

    fingerprint_before = _ledger_fingerprint(path)
    first, _ = cohort.cohort_members(qualification="all", ledger_path=path)
    fingerprint_after_first = _ledger_fingerprint(path)
    second, _ = cohort.cohort_members(qualification="all", ledger_path=path)
    fingerprint_after_second = _ledger_fingerprint(path)

    assert calls["n"] == 1
    assert first is second
    assert fingerprint_before == fingerprint_after_first == fingerprint_after_second


def test_mutation_control_unconditional_write_reintroduces_self_poisoning(tmp_path):
    """Mutation control for (d): reproduce the RETIRED unconditional write
    directly (not by editing source) and show it defeats the memo — i.e.
    the two tests above are genuine guards against a real failure mode,
    not a coincidence of this fixture.
    """
    path = tmp_path / "ledger.sqlite3"
    platform_ledger.ingest_batch(_batch("1", "T1", "M1"), path=path)
    curated_model.ensure_schema(path).close()

    fingerprint_before = _ledger_fingerprint(path)
    conn = curated_model.platform_ledger.ensure_platform_schema(path)
    try:
        # The exact statement removed from curated.ensure_schema: an
        # unconditional version-stamp write, run with no version change.
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            ("curated_sharp_schema_version", str(curated_model.SCHEMA_VERSION)),
        )
        conn.commit()
    finally:
        conn.close()
    fingerprint_after = _ledger_fingerprint(path)

    assert fingerprint_before != fingerprint_after
