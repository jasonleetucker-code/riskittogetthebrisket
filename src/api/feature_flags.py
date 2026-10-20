"""Feature flag registry for phased rollout of the 2026-04 upgrade.

Every new capability added in Phases 1–10 of the major upgrade is
gated here so production can stay on the proven path while new code
proves itself.

**Defaults are PER-FLAG, and several of the interesting ones ship
enabled.**  This docstring, ``README.md`` and ``docs/ARCHITECTURE.md``
all used to assert a blanket disabled-by-default rule, and
ARCHITECTURE built a stronger claim on top of it about production
behaviour being frozen until a flag was flipped.  Both were false:
24 of the 63 entries in ``_DEFAULTS`` below are ``True`` —
``bdvm_engine``, ``te_basis_conversion`` (which reprices every tight
end on the live board), ``monte_carlo_trade``, ``idp_scoring_fit``,
``reception_scoring_fit``, ``nfl_data_ingest``, ``realized_points_api``,
``perfect_draft``, ``ledger_rank_change``, ``waiver_live_opportunity``,
``source_freshness_weighting``, ``source_family_cap``, ``source_universe_freshness``,
``signals_active_source``, ``dlf_offense_only_vote``,
``two_way_alt_evidence_rules``,
``fantasypros_idp_upstream_clock``,
``game_day_live_game_state``, ``sleeper_weekly_projections``,
``rookie_auction``, ``dfs_workspace``, ``dfs_auto_slates``,
``trade_screenshot_import`` and ``manager_intelligence`` — several with comments
recording that the enabled default is deliberate.

**No live gate sits outside this registry any more.**  The last one —
``RISKIT_FEATURE_LEDGER_RANK_CHANGE``, read directly in
``data_contract._stamp_rank_changes`` and therefore visible in no
operator surface at all — was registered as ``ledger_rank_change`` on
2026-08-25, closing audit **F-24** (V1-87).  The read site now routes
through ``is_enabled``; the measured blast radius that unblocked the
registration is recorded at its ``_DEFAULTS`` entry.

For a flag that ships enabled, the env var is a ROLLBACK lever, not an
opt-in.  Read ``_DEFAULTS`` for the flag you care about rather than
assuming dormancy; a reader who trusted the old sentence would have
concluded a live repricing path was inert.

Pattern
-------
    from src.api.feature_flags import is_enabled

    if is_enabled("monte_carlo_trade"):
        # new probabilistic path
    else:
        # existing deterministic path

Env-var override
----------------
Set ``RISKIT_FEATURE_<UPPERCASED_NAME>=1`` (or ``true``/``yes``/``on``)
to flip a flag on at deploy time without a config edit.  Set to
``0``/``false``/``no``/``off`` to explicitly disable.

Reads are cached per-process; call ``reload()`` in tests to pick up
env changes mid-run.
"""

from __future__ import annotations

import os
import threading
from typing import Final

# ── Flag registry ─────────────────────────────────────────────────
#
# Keys MUST be snake_case.  The dict is the ONLY place to declare a
# flag — unknown keys raise on read so typos don't silently evaluate
# as "off".

_DEFAULTS: Final[dict[str, bool]] = {
    # Phase 1 — Unified ID mapper
    # NO_GATE — the mapper is unconditional and this flag has never
    # gated it.  OFF so the registry stops reporting a switch that does
    # not exist; the mapper itself is unaffected either way.
    # Lane 7 — MULTI-BRIDGE cross-position ladder.  OFF, deliberately.
    #
    # The vote-withholding repair beside it is UNCONDITIONAL: with no usable
    # bridge an IDP-only source now casts no vote instead of asserting that
    # its #1 is asset #1.  That path fires on 0 rows of the healthy board, so
    # it moves nothing and needs no flag.
    #
    # THIS flag governs whether a SECOND qualified bridge joins the ladder,
    # and that is a methodology change with measured consequences: enabling it
    # admits Draft Sharks alongside IDP Trade Calculator and moves 337 of
    # 1,111 values (294 IDP, 42 picks via the rookie tether, 1 offense; 327
    # down / 10 up; IDP median 20, p95 544, max 1,623), with top-50 membership
    # churn 0 and top-100 churn 4.  Those are two markets genuinely disagreeing
    # about how fast IDP value decays, not a defect — but which of them the
    # board should publish is an owner decision, so it ships off and is flipped
    # with RISKIT_FEATURE_MULTI_BRIDGE_LADDER=1.
    #
    # OFF is not "single point of failure restored": the ladder still comes
    # from the bridge owner's MEASURED capability rather than the is_backbone
    # label, and with the flag off it uses the first usable bridge, which
    # reproduces the incumbent ladder integer for integer.
    "multi_bridge_ladder": False,
    # Freshness-aware source weighting (owner directive 2026-09-23;
    # docs/sources/SOURCE_FRESHNESS_WEIGHTING.md).  ON: each blend vote is
    # base × freshness × health × coverage from src/sources/freshness.py.
    # OFF (RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING=0 + restart): the
    # dynamic factors are still computed and stamped on every row, so
    # observability survives rollback, but only the base weight is applied.
    "source_freshness_weighting": True,
    # The owner's universal freshness SCHEDULE -- HELD, DEFAULT OFF (owner
    # decision 2026-10-20 on PR #1831, Option B;
    # docs/owner/PR1831_OPTION_B_DECISION_2026-10-20.md).  The implementation
    # and the freshness percentages are APPROVED (owner directive 2026-10-19,
    # "Universal Source Voting and Freshness Policy" §2;
    # docs/sources/UNIVERSAL_FRESHNESS_SCHEDULE_2026-10-19.md): every dynasty
    # ranking source's freshness factor is a step function of whole days since
    # its last GENUINE publisher update -- 0-7 days 1.00, 8-14 0.75, 15-21
    # 0.50, 22-30 0.25, >30 0 (config/sources/freshness_schedule_v2.json) --
    # on the vendor-stated publication time where one is recorded, else the
    # last observed content change; an update time that cannot be established
    # votes at 0.  ACTIVATION IS HELD for the owner: turned on it moved 918
    # values (LaJohntay Wester +42.9%), and the INCUMBENT outlier filter can
    # remove legitimate source votes when the voting population changes --
    # the defect outlier-integrity-v2 exists to fix.  Setting this default
    # True (or RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2 true-y in any
    # deploy/config/env surface) IS the owner's freshness activation decision
    # and may only be made with the owner's explicit approval --
    # ``tests/api/test_freshness_v2_hold_locked.py`` fails otherwise, and
    # deploy/verify-deploy.sh fails a production deploy whose effective flag
    # is ON.  OFF: the v1 cadence-relative curve, byte for byte (the board is
    # identical to main); the per-source voting status reports the v1 rule.
    # ``source_freshness_weighting`` still decides whether ANY freshness
    # factor is applied.  Activation, once approved: flip this default.
    "source_freshness_schedule_v2": False,
    # Family-capped source voting (owner directive 2026-09-24;
    # docs/sources/SOURCE_FRESHNESS_WEIGHTING.md).  ON: every member of a
    # correlation family votes with its own effective weight and the
    # family's total is capped at one provider's authority
    # (data_contract.cap_family_weights).  OFF
    # (RISKIT_FEATURE_SOURCE_FAMILY_CAP=0 + restart): the retired
    # family-head selection — the registry-first member votes, the rest
    # are stamped supersededBy.
    "source_family_cap": True,
    # Universe-aware source freshness (#1555 V2-1, 2026-09-30).  ON: a source
    # whose one board prices offense AND IDP players (IDP Trade Calculator) ages
    # each row from its own universe's broad-change clock, capped at the source
    # clock -- an IDP-only publication no longer refreshes unchanged offense rows
    # (src/sources/freshness.py::SubsetFreshness.universe_clock).  It can only
    # make evidence OLDER, never fresher.  OFF (RISKIT_FEATURE_SOURCE_UNIVERSE_
    # FRESHNESS=0 + restart): one clock per subset, the prior behaviour.
    "source_universe_freshness": True,
    # Signals Fantasy as an ACTIVE canonical source (owner addendum
    # 2026-10-03; docs/sources/SIGNALS_FANTASY_INTEGRATION.md §9).  ON: the
    # authenticated native-value boards vote (``signalsSf``; the IDP family
    # boards ``signalsIdp{Dl,Lb,Db}`` are collected and run in SHADOW until
    # ``signals_idp_shared_market`` — ``data_contract.PRIVATE_SOURCE_VOTE_HOLDS``)
    # as value-ordered rank signals inside the FantasyCalc B10 family
    # wherever the box-local private store is present.  OFF
    # (RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE=0 + restart): both keys leave the
    # active source set exactly as a disabled source does — no vote, not
    # expected — while their native values stay visible; the contract stamps
    # ``privateSourceAvailability[*].rolledBack``.
    "signals_active_source": True,
    # Signals IDP MASTER switch (2026-10-04; meaning narrowed 2026-10-19, owner
    # directive SIGNALS_IDP_VOTING_2026-10-19).  OFF: the three Signals IDP
    # boards (signalsIdpDl/Lb/Db) run in SHADOW — their within-family rank is
    # translated onto the shared market (the bridge owner's family ladder)
    # and published per row as ``sourceShadowMeta``, with no vote.
    # ALONE IT NO LONGER ACTIVATES ANYTHING: a family votes only when this,
    # its own family flag (``signals_idp_{dl,lb,db}_vote``) AND
    # ``signals_idp_xwalk_v2`` are all ON (AND semantics,
    # ``data_contract.PRIVATE_SOURCE_HOLD_RELEASE_FLAGS``).  With this ON and
    # every other release flag OFF the board is byte-identical to the default.
    # Rollback of ALL Signals IDP: RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET=0
    # + restart.
    "signals_idp_shared_market": False,
    # Signals IDP FAMILY-scoped quarantine (owner directive 2026-10-19,
    # PR-H).  OFF (incumbent): one IDP family failing its own floor /
    # collapse check withholds the whole IDP release — every family keeps
    # its last good board.  ON: only the failing family is withheld (its
    # CSV, clock and ``_last_success`` untouched); the passing families
    # publish with their own clocks.  Any internal error in the
    # family-scoped path falls back to release-level quarantine.  The gate
    # runs in the ``dynasty-signals-values`` collector
    # (``src/sources/signals.py::collect_value_dataset``), whose unit has no
    # EnvironmentFile, so the registry default governs it; it moves no
    # served value by itself (a family board votes only through its own vote
    # state).  Rollback: revert the default (or set the env var in the unit).
    "signals_idp_family_quarantine": False,
    # Per-family Signals IDP release switches (owner directive 2026-10-19).
    # Each lifts ONE family's hold, and only together with the master
    # (``signals_idp_shared_market``) and ``signals_idp_xwalk_v2``.  Default
    # OFF; flipped per family only after that family's preregistered gates,
    # independent review and the applicable owner decisions.  Rollback of one
    # family: RISKIT_FEATURE_SIGNALS_IDP_<FAM>_VOTE=0 + restart.
    "signals_idp_dl_vote": False,
    "signals_idp_lb_vote": False,
    "signals_idp_db_vote": False,
    # Candidate F, the coverage-aligned within-family crosswalk
    # (``src/bridges/family_crosswalk.py``; docs/sources/
    # SIGNALS_FANTASY_INTEGRATION.md).  ON: the Signals IDP shadow stamps (and
    # any released family's vote) use F — votes are a permutation of the
    # matched players' bridge coordinates; Signals-only and rookie rows are
    # withheld with a reason — plus the Signals-scoped Sleeper-id
    # contradiction guard.  OFF: the shadow keeps Candidate A, which can never
    # vote: master + family ON with this OFF is ``held:
    # no_qualified_translation``.  Rollback of the method:
    # RISKIT_FEATURE_SIGNALS_IDP_XWALK_V2=0 + restart (held, never A).
    "signals_idp_xwalk_v2": False,
    # DLF IDP HOLD -- TEMPORARY, AND LOCKED BY THE OWNER (Option 3,
    # 2026-10-20).  This flag is NOT an exclusion of DLF's IDP opinion: the
    # universal source-voting directive of 2026-10-19 approves restoring
    # ``dlfIdp`` / ``dlfRookieIdp`` inside DLF's one provider-family cap, and
    # the restore is implemented (this flag OFF).  It stays ON because
    # restoring DLF IDP under the INCUMBENT outlier filter
    # (``_hampel_filter_per_player``) drops valid Draft Sharks IDP /
    # FantasyPros IDP / IDP Trade Calculator votes -- 34-54% moves on rows
    # such as Trevin Wallace, none from DLF's own vote.  On 2026-10-20 the
    # owner chose Option 3: do NOT accept those moves, do NOT activate the
    # candidate replacement filter (it failed 3 of its 6 mandatory
    # adversarial tests), and keep DLF IDP voting disabled until a
    # PREREGISTERED outlier-filter Version 2 passes EVERY mandatory gate.
    # Lifting this hold (default False, or RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE
    # set false-y in any deploy/config/env surface) IS the owner's DLF IDP
    # activation decision and may only be made with the owner's explicit
    # approval -- ``tests/api/test_dlf_idp_hold_locked.py`` fails otherwise.
    # ON: the DLF IDP boards stay ingested and displayed but are held from
    # the vote through ``data_contract.POLICY_SOURCE_VOTE_HOLDS`` (the same
    # active-source gate seasonal inactivity and private holds use);
    # ``dlfSf`` / ``dlfRookieSf`` / ``dlfValuesSfTep`` vote unchanged.
    "dlf_offense_only_vote": True,
    # DLF VALUES RANK -> HILL VOTE -- HELD, DEFAULT OFF (owner decision
    # 2026-10-20, "Hold D4 for V2").  HELD pending outlier-integrity-v2 +
    # explicit owner approval.  The implementation (owner closeout 2026-10-18
    # Decision 4, kept by the source-voting directive of 2026-10-19) is
    # intact: ``dlfValuesSfTep`` is registered as an offense-only member of
    # the existing ``dlf`` family (its native value ORDER -> percentile ->
    # Hill; raw/max rejected) and SPLITS DLF's one provider cap with DLF
    # Rank.  It is held because under the INCUMBENT outlier filter
    # (``_hampel_filter_per_player``) turning it on newly drops OTHER
    # sources' valid votes on 12-13 offense rows (6 Draft Sharks, plus IDPTC,
    # Yahoo/Boone, KTC Crowd, FantasyPros; e.g. Theo Johnson -7.4%) -- the
    # same mechanism class the owner rejected for DLF IDP.  The owner's
    # outlier-integrity-v2 directive
    # (docs/owner/OUTLIER_INTEGRITY_V2_DIRECTIVE_2026-10-20.md, addendum)
    # makes D4 a second restoration target.  Setting this default True (or
    # RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE true-y in any deploy/config/
    # env surface) IS the owner's D4 activation decision and may only be made
    # with the owner's explicit approval after V2 passes --
    # ``tests/api/test_dlf_values_hold_locked.py`` fails otherwise, and
    # deploy/verify-deploy.sh fails a production deploy whose effective flag
    # is ON.  OFF: collected and displayed, held from the vote by the
    # owner-policy vote-hold gate (``data_contract.POLICY_SOURCE_VOTE_HOLDS``);
    # decision fields identical to main.  Activation, once approved:
    # flip this default (the only step).
    "dlf_values_rank_hill_vote": False,
    # Two-way boost alt-family evidence (PR #1817 review + owner source-voting
    # directive 2026-10-19).  ON: ``data_contract._apply_two_way_player_boost``
    # prices a two-way player's alt-family value as a REAL member of that
    # family with the same observations would be priced: only sources that
    # VOTE there on this build (the blend loop's own per-(row, source) weight
    # owner, after holds, freshness and user overrides), the incumbent blend,
    # and the single-source retention applied once when the alt evidence rests
    # on one B10 family.  A correctness fix: a quarantined, held or disabled
    # source no longer prices a player through the side door.  OFF
    # (RISKIT_FEATURE_TWO_WAY_ALT_EVIDENCE_RULES=0 + restart): the prior boost,
    # byte for byte.
    "two_way_alt_evidence_rules": True,
    # FantasyPros IDP on its actual upstream clock (owner closeout 2026-10-18
    # Decision 5, kept by the 2026-10-19 directive).  ON: the ``style:
    # EXPLICIT_UPSTREAM_TIMESTAMP`` that ``config/sources/freshness_v1.json``
    # declares for ``fantasyProsIdp`` (``styleFlag``) is in force, so the
    # voting clock is the vendor's stated expert-update time and re-scraping an
    # old ranking can never refresh its age.  Today it moves confidence
    # labels/axes only; once a second non-anchor IDP voter exists the lower
    # weight reaches values.  OFF
    # (RISKIT_FEATURE_FANTASYPROS_IDP_UPSTREAM_CLOCK=0 + restart): the style is
    # dropped and the prior broad-change clock applies.
    "fantasypros_idp_upstream_clock": True,
    # Joint outlier + sparse-evidence CHALLENGER (#1555 Batch 2 Unit C,
    # owner decision B 2026-10-01) -- two separately promotable halves, both
    # OFF until the owner approves that specific candidate (valuation
    # methodology).  Measured: docs/valuation/evidence/joint-challenger-2026-10-01/.
    # FILTER half: the per-player outlier filter weighs family-capped evidence
    # (src/api/joint_robust_filter.py -- weak evidence cannot remove dominant
    # evidence; never manufactures a single-family row).  Needs
    # source_family_cap; with the cap off it stands down to the incumbent.
    "joint_outlier_sparse_challenger": False,
    # Rank-space Hampel challenger (owner master package 2026-10-17, audit F1;
    # docs/valuation/evidence/rank-space-hampel-2026-10-17/PREREGISTRATION.md):
    # the same per-player outlier filter computed in the Hill curve's
    # percentile coordinates instead of values.  Shadow evaluation only;
    # promotion is an owner decision after the preregistered rule passes.
    "rank_space_hampel_challenger": False,
    # Per-vote rank-space Hampel challenger (owner follow-up 2026-10-17;
    # docs/valuation/evidence/rank-space-hampel-per-vote-2026-10-17/
    # PREREGISTRATION.md): the same filter with each vote inverted through the
    # forward map (curve + TE transform) that produced it.  A separate
    # experiment from rank_space_hampel_challenger, whose NOT BETTER result
    # stands.  Shadow evaluation only; promotion is an owner decision.
    "rank_space_hampel_per_vote_challenger": False,
    # IDP three-voter Hampel challenger ``idp-hampel-n3-v1`` (owner closeout
    # 2026-10-18, Decision 1; docs/valuation/evidence/idp-outlier-n3-2026-10-18/
    # PREREGISTRATION.md): the served per-player outlier filter, unchanged,
    # with min n = 3 on ``assetClass == "idp"`` rows only.  Offense and pick
    # rows take the incumbent path byte for byte, and every other filter
    # challenger takes precedence.  Shadow evaluation only; the DLF IDP vote
    # hold is independent of it.  Promotion is an owner decision.
    "idp_hampel_n3_challenger": False,
    # IDP deep-tail native-value challenger ``idp-deep-tail-native-v1`` (owner
    # closeout 2026-10-18, Decision 6; docs/valuation/evidence/
    # idp-deep-tail-native-2026-10-18/PREREGISTRATION.md): an IDP row's
    # shared-market rank vote at effective rank 500 < r <= 904 is priced at the
    # IDP Trade Calculator's own native value for that rank
    # (src/canonical/deep_tail_native.py) instead of the Hill/tail
    # extrapolation.  No Hill constant, reference N, tail saturation rank or
    # coordinate changes.  Shadow evaluation only; promotion is an owner decision.
    "idp_deep_tail_native_challenger": False,
    # Disagreement-preserving outlier policy ``outlier-corroborated-v1`` (owner
    # directive 2026-10-19 "Universal source voting and freshness", §6;
    # src/api/outlier_policy.py; preregistered in docs/valuation/evidence/
    # outlier-disagreement-2026-10-19/PREREGISTRATION.md before it was run).
    # ON: the per-player filter rejects only a gross, uncorroborated vote (more
    # than 4x off the other families in implied rank AND 1,000 points off, with
    # no other family within 2x) or the votes of a board the scale screen finds
    # mis-scaled; valid disagreement keeps its vote.  OFF: the incumbent Hampel
    # filter, byte for byte.  Every other filter challenger takes precedence.
    # Stays OFF until independent validation and an owner decision.  Rollback if
    # ever switched on: RISKIT_FEATURE_OUTLIER_DISAGREEMENT_POLICY=0 + restart.
    "outlier_disagreement_policy": False,
    # Outlier integrity v2 (owner directive 2026-10-20 "Fix the outlier filter
    # and restore DLF IDP voting" + 10:20 UTC addendum; preregistered in
    # docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md before it was built;
    # src/api/source_integrity.py).  MASTER switch of the layered validation
    # challenger: Layer A (identity evidence) and Layer B (format, structural
    # normalization, feed provenance, segment integrity, continuity holds) run
    # only while this is ON, each named change also behind its own flag below.
    # OFF: every board pass byte for byte the incumbent.  Mutually exclusive with
    # ``outlier_disagreement_policy`` (V1): both ON raises at build time.  Stays
    # OFF until the preregistered verdict, independent review and an explicit
    # owner decision.  Rollback if ever switched on:
    # RISKIT_FEATURE_OUTLIER_INTEGRITY_V2=0 + restart.
    "outlier_integrity_v2": False,
    # V2 Layer A (identity owner): each CSV join is graded with the source's own
    # published position / team / age / ids inside src/identity/resolution.py;
    # CONTRADICTED and UNRESOLVED observations are refused (absent, never zero)
    # and an in-source duplicate votes only when disambiguated.  Effective only
    # with ``outlier_integrity_v2``.  Owner-reserved activation.
    "identity_evidence_v2": False,
    # V2 B2 (ingestion): a scraper-payload value proven inconsistent with the
    # vendor's own same-run CSV (board proof across >= 2 position groups, or a
    # single row > 2x off) is absent and the CSV value votes; no CSV, withheld.
    # Effective only with ``outlier_integrity_v2``.  Owner-reserved activation.
    "payload_provenance_guard": False,
    # V2 B1 (normalization owner): a rookie-board vote the ladder did not
    # translate is withheld (``normalization_untranslated``) instead of voting a
    # within-class rank as an overall rank.  Effective only with
    # ``outlier_integrity_v2``.  Owner-reserved activation.
    "rookie_ladder_fail_closed": False,
    # V2 U4 (history owner), RECORD-ONLY: each fresh scrape folds its board into
    # the source_rank lane (src/history/source_rank.py) that B3 / B4 baselines
    # read.  Moves no value by itself (reading the lane needs
    # ``outlier_integrity_v2``).  Owner-reserved activation.
    "source_rank_history_record": False,
    # V2 D-1 (confidence change, evaluated separately as V2+D1): a vote held by
    # B4 becomes a B11 lost-evidence seat, so a hold can never raise confidence.
    # Effective only with ``outlier_integrity_v2``.  Owner-reserved activation.
    "integrity_holds_as_withheld": False,
    # Outlier integrity V2.1 (successor preregistration
    # docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md, committed before
    # any V2.1 code; owner O-1 decision 2026-10-20).  Applies the registered
    # repairs R1-R14 and persistence rules P-1..P-4 to the V2 layers (B0
    # tolerance, B3a / B3b minimums, A3 position families, age intervals,
    # ordinal-slot preservation, explainer coverage, cold-start team rule,
    # content-distinct persistence, cap release is not confirmation).
    # Effective only with ``outlier_integrity_v2``; OFF = V2 exactly, and with
    # the master OFF the board is byte for byte the incumbent.  Evaluated in
    # replay only; activation is owner-reserved.  Rollback if ever switched
    # on: RISKIT_FEATURE_OUTLIER_INTEGRITY_V21=0 + restart.
    "outlier_integrity_v21": False,
    # SPARSE half: one voting family is stamped ``limitedEvidence`` and the
    # 0.30 single-source retention is not applied.
    "joint_sparse_limited_evidence": False,
    # Sparse-evidence ESTIMATOR (Batch 3 Unit E, 2026-10-01) -- a CHALLENGER,
    # OFF until a preregistered gate passes and is independently reviewed
    # (valuation methodology).  ON: the rows the 0.30 single-source retention
    # would hit keep their one family's observation as central evidence,
    # bounded above by healthy eligible families that did NOT list the player
    # (censor-aware, counted by family; src/api/sparse_evidence.py), and carry
    # an additive ``sparseEvidence`` block.  OFF: the incumbent haircut, byte
    # for byte.  Evidence: docs/valuation/evidence/sparse-evidence-2026-10-01/.
    # Rollback if ever switched on: RISKIT_FEATURE_SPARSE_EVIDENCE_ESTIMATOR=0
    # and restart (flag reads are cached per process).
    "sparse_evidence_estimator": False,
    # C1-U4 — ledger-derived rankChange on the canonical contract.  ON
    # derives each ranked row's rankChange from the temporal ledger's
    # previous recorded board; OFF stamps None on every row (deliberately
    # not the retired self-referential cache).  Registered 2026-08-25,
    # closing audit F-24 (V1-87): the flag was read directly from the
    # environment in data_contract and was invisible to this inventory,
    # snapshot(), /api/status and the reachability test.  Blast radius
    # MEASURED on the production box (Lane 4 run 32843495391, deployed
    # 8537aa4c2, ledger present with 37 recorded board dates): ON derives
    # a non-null rankChange for 743 of 749 ranked rows on the 2026-08-25
    # board (comparator 2026-08-24, 1342 ranked assets); OFF is
    # structurally all-None, so the blast radius is exactly those 743
    # rankChange stamps — no VALUE, rank, or tier moves under either
    # setting.  Rollback: RISKIT_FEATURE_LEDGER_RANK_CHANGE=0 (and
    # restart — registry reads are cached per process).
    "ledger_rank_change": True,
    "unified_id_mapper": False,
    # Phase 2 — nfl_data_py pipeline
    # Activated with the 2026-04-25 deploy that adds nfl_data_py to
    # requirements.txt.  Safe: every fetch is guarded so an import
    # failure in prod degrades to [].  Upstream cost: one-time ~150MB
    # pip install.  Flip to False via RISKIT_FEATURE_NFL_DATA_INGEST=0
    # if pandas install ever breaks prod.
    "nfl_data_ingest": True,
    # Phase 3 — Realized fantasy points — endpoint-only, inert until
    # a client calls it.  Activated with nfl_data_ingest.
    "realized_points_api": True,
    # Phase 4 — Confidence intervals.  NO_GATE, so OFF.
    #
    # The old comment here claimed "Frontend ValueBandBadge renders when
    # field is present".  Nothing renders it: the badge is exported from
    # the ui barrel and imported by no page, ``stamp_bands_on_players``
    # has no caller, and ``rank_history_band`` has no caller either.
    # There is also no ``is_enabled("value_confidence_intervals")``
    # anywhere — only docstrings describing one.
    "value_confidence_intervals": False,
    # Phase 5 — Positional tiering.  NO_GATE, so OFF.
    #
    # The old comment claimed "Frontend TierDivider renders when tierId
    # set".  ``TierDivider`` renders only on /draft, and off a locally
    # computed ``p.tier`` — the backend never stamps ``tierId`` at all,
    # because ``stamp_tiers_on_players`` is called only from
    # ``scripts/refit_tier_thresholds.py``.  Two identifiers for two
    # different things, which is why the claim read as true.
    "positional_tiers": False,
    # Phase 6 — Usage-based signals — BUILT BUT NOT WIRED, and OFF.
    #
    # This comment used to read "fires via unified_signal_engine when
    # nfl_data_ingest supplies stats".  It did not fire, because nothing
    # in the tree calls ``detect_usage_transitions`` or
    # ``unified_signal_engine`` at all — the flag reported True for a
    # capability with no live path (gap analysis §4.2).
    #
    # It stays OFF now for a second, independent reason, measured
    # 2026-07-27 against the persisted 2025 season by
    # ``scripts/audit/measure_usage_signal_rate.py``: the detector fires
    # on a mean **17.8% of active players every week**, stable across
    # weeks 6-18.  Threshold tuning does not fix it — flooring the
    # standard deviation makes it worse (19% -> 32%), and a plain
    # 30-percentage-point absolute-move rule still hits 21%.  A
    # four-observation z-score on a bounded 0-1 share does not
    # discriminate, because real NFL snap share genuinely moves that
    # much week to week.
    #
    # Turning this on today would only enable a flag with no consumer.
    # Whoever wires the consumer must re-run the audit first.
    "usage_signals": False,
    # Phase 7 — ESPN injury feed.  Gate is SCRIPT_ONLY (see
    # ``_GATE_STATUS`` below), so the DEFAULT stays False —
    # ``test_only_a_live_flag_may_default_on`` correctly forbids a
    # non-LIVE gate from defaulting True, because toggling it alone
    # cannot change any request/response.
    #
    # ``scripts/refresh_injury_feed.py`` (Live Waiver Opportunity layer,
    # docs/faab-live-opportunity-model.md) is now the module's
    # importer: it diffs consecutive fetches and turns a transition
    # into a BDVM structured event (INJURY / ACTIVATED_RETURN) that
    # ``src/trade/faab_opportunity.py`` reads.  Its systemd timer sets
    # ``RISKIT_FEATURE_ESPN_INJURY_FEED=1`` in that ONE process's
    # environment (the documented rollback-lever pattern above) —
    # deliberately not flipped here, which would turn every OTHER
    # process on too for a gate that changes nothing for them.
    "espn_injury_feed": False,
    # Phase 8 — Depth chart cross-check.  Same reasoning as
    # ``espn_injury_feed`` immediately above: gate is SCRIPT_ONLY, so
    # the default stays False.  ``scripts/refresh_depth_charts.py``
    # now ALSO turns a detected slot change into a
    # DEPTH_CHART_PROMOTION/DEMOTION BDVM event, and its systemd timer
    # sets ``RISKIT_FEATURE_DEPTH_CHART_VALIDATION=1`` for that process
    # only.  The old comment's "Requires injury feed ON to cross-check"
    # was already moot before this — the two flags never depended on
    # each other in code, only in a stale sentence.
    "depth_chart_validation": False,
    # Phase 9 — Monte Carlo trade simulator — new endpoint
    # /api/trade/simulate-mc.  Old /api/trade/simulate is unchanged.
    # Enabling reveals the "Simulate" button in the trade-calc UI.
    "monte_carlo_trade": True,
    # Phase 10 — Backtesting + dynamic weights — held OFF until 2-3
    # months of historical snapshots accumulate.  Flipping this on
    # without a populated dynamic_source_weights.json is a no-op
    # (falls back to static weights).  Promoted deliberately, not
    # automatically.
    "dynamic_source_weights": False,
    # Collaborative audit, finding F — TE basis conversion at blend time.
    #
    # Replaces the flat ``_TE_BLANKET_NON_NATIVE_MULTIPLIER`` (1.15) on
    # non-TEP sources' TE contributions with KTC's own MEASURED base →
    # TE++ uplift curve (``src/league_intel/te_premium.py``).  The blend
    # is already anchored on ``ktcSfTep``, which IS the TE++ board, so
    # this corrects the magnitude of an alignment that was happening
    # anyway — it does not add a second one.  1.15 sits below the entire
    # observed range (KTC's smallest actual uplift is 1.209), so every
    # tight end was being lifted too little.
    #
    # ON by default and deliberately so.  A flag defaulting OFF here
    # would repeat ORCHESTRATION.md 6.14/6.15's named mistake: the
    # previous TE module was left unimported so "toggle off" would be
    # byte-identical, which also meant the double-count guard could
    # never fire on it.  Both paths are exercised by
    # ``tests/api/test_te_basis_conversion.py``.
    #
    # This moves live consensus values for TEs, so it has a rollback:
    # RISKIT_FEATURE_TE_BASIS_CONVERSION=0 restores the flat 1.15.  An
    # explicit operator TE-premium slider value also wins over the
    # curve regardless of this flag.
    "te_basis_conversion": True,
    # IDP positional scoring fit (Tier 2).  This league pays coverage
    # and disruption and discounts finishing plays, so relative to DB it
    # values DL about +7% and LB about +3% versus the generic rate card
    # every ranking source prices on.  Measured, stable across pool
    # depth, and re-allocates between IDP positions rather than
    # inflating IDP as a whole — see src/league_intel/scoring_fit.py.
    #
    # ON by default as of 2026-07-27, on the operator's explicit
    # direction and after re-measuring the blast radius the
    # ``value_moving_on`` gate requires.  Rollback:
    # RISKIT_FEATURE_IDP_SCORING_FIT=0.
    #
    # THE DIRECTION IN THE ORIGINAL MEASUREMENT WAS BACKWARDS.  #592
    # recorded "relative to DB, pays DL about +7% and LB about +3%".
    # Re-run through the module's own entry point on raw nflverse rows,
    # with both leagues' scoring_settings verified byte-identical to
    # what #592 recorded (zero drift on all 8 IDP keys), it measures
    # DB 1.0366 / DL 1.0001 / LB 0.9633 — DB highest, LB lowest.
    #
    # The rate card settles which is right: idp_pass_def is 2.52x UP
    # (a DB stat, and the biggest move on the board) while idp_sack is
    # 0.64x DOWN (the signature DL stat) and idp_tkl_solo 0.92x DOWN
    # (the LB volume stat).  A league that pays coverage and discounts
    # sacks cannot be tilting toward DL.  See scoring_fit's docstring.
    #
    # Scope: this axis reaches only ``build_board_adjustments`` — the
    # OPT-IN league-adjusted lens.  The default market board is
    # untouched, which is why enabling it is a smaller step than the
    # blast radius below makes it sound.
    "idp_scoring_fit": True,
    # Per-player reception-depth tilt (Tier 2).  Separate from
    # idp_scoring_fit above rather than sharing it: that flag is named
    # for IDP, and using it to gate an offence feature would make the
    # name a lie — an operator disabling "idp_scoring_fit" would
    # silently also disable every receiver adjustment.
    #
    # ON since 2026-07-28.  Reception-distance banding is the largest
    # scoring divergence on this card and the market cannot see it: the
    # per-catch spread is 8x (0.25 to 2.00) while every ranking source
    # prices a flat rate.
    #
    # Magnitude, measured — quote THIS, not the 8x.  Receptions are only
    # 17-33% of a skill player's points, so the composed VALUE tilt over
    # 199 receivers with 20+ catches (2025) is:
    #
    #   median 1.000  p10 0.942  p90 1.042  min 0.765  max 1.098
    #   0 of 199 at the clamp; dispersion drift 0.0226 (bound 0.12)
    #
    # Coherent at the extremes rather than random: checkdown backs and
    # short-area tight ends down (Jerome Ford 0.765), deep threats up
    # (Alec Pierce 1.098).  Year-over-year r=0.72-0.77, so the band shape
    # is a real player trait rather than noise.
    #
    # The multipliers carry TILT ONLY.  The shared level (0.9543) is
    # held out and reported separately, because it depends on the
    # baseline league being what the market prices — an assumption that
    # swings the level 2x and flips its sign across plausible rates.
    # Mean-normalised, so this cannot inflate receivers as a class.
    #
    # Reaches the OPT-IN league-adjusted lens only, never the default
    # market board.
    #
    # AUDIT F-26 (2026-08-18): this line used to name `/api/gameplan` as the
    # endpoint it reaches.  Measured, that is wrong in a way worth stating
    # rather than silently editing — the gate in `src/api/gameplan.py` is
    # called only from `get_league_adjusted_values`, which backs
    # **`/api/valuation/league-adjusted`**.  The flag is genuinely live; the
    # module it lives in is not the endpoint it serves.  `/api/gameplan`
    # itself has zero frontend consumers (Scope Manifest `C2-GP-01`,
    # DISCONNECTED), so the old wording pointed a reader at a route no user
    # can reach and implied this flag was inert.
    # Rollback: RISKIT_FEATURE_RECEPTION_SCORING_FIT=0.
    "reception_scoring_fit": True,
    # BDVM — projection-driven fundamental dynasty valuation engine
    # (src/bdvm/, endpoints /api/bdvm/values|roster|trades).  ON as of
    # 2026-07-28: the condition it was held OFF for is satisfied.
    # ``scripts/bdvm_build_baseline.py`` now writes a real snapshot
    # (2,815 records for 2026) and the engine answers status="ok" —
    # 726 players priced, 222 honestly unpriced — instead of the
    # placeholder "no_projection_snapshot" payload.
    #
    # Blast radius is small by construction:
    #   * it never touches rankDerivedValue or any existing route;
    #   * /rankings' "Fund gap" column gates on status == "ok", so it
    #     self-suppresses wherever a snapshot is missing rather than
    #     rendering blanks;
    #   * the signal-alert leg seeds a silent baseline per (user,
    #     league) on its first sweep, so flag-on day cannot flood.
    #
    # Rollback: RISKIT_FEATURE_BDVM_ENGINE=0 and restart (flag reads
    # are cached per process).  A box with no snapshot on disk degrades
    # to the same honest empty payload it served before.
    # See docs/research/bdvm-v1/IMPLEMENTATION_REPORT.md.
    "bdvm_engine": True,
    # Perfect Draft — budget-constrained rookie-auction optimizer
    # (src/draft/, endpoint /api/draft/roster-context, client solver in
    # frontend/lib/perfect-draft.js).  ON at introduction because it is
    # purely additive: it writes no value, mutates no contract, and
    # touches no existing route.  The /draft panel silently vanishes on
    # any non-ok response, so a box that cannot serve it renders the
    # board exactly as it did before.
    #
    # It answers a question nothing else in the app answers — which
    # COMBINATION of rookies a budget should buy — using the canonical
    # rankDerivedValue board and the same lineup solver the ROS engine
    # uses.  It never re-prices a player.
    #
    # Note the flag does NOT gate the slot-logic removal from
    # frontend/lib/draft-logic.js; that is an unconditional correction
    # to a wrong model, not a feature.
    #
    # Rollback: RISKIT_FEATURE_PERFECT_DRAFT=0 and restart (flag reads
    # are cached per process).
    "perfect_draft": True,
    # Rookie auction room (``src/auction/``, owner directive 2026-09-29).
    # Default ON for MOCK rooms: the router refuses to create an official
    # room at all until the owner separately approves launch.  Off → every
    # /api/auction/* route 503s feature_disabled and the runtime loop does
    # not start.  Rollback: RISKIT_FEATURE_ROOKIE_AUCTION=0 and restart.
    "rookie_auction": True,
    # DFS workspace (``src/dfs/``, owner directive 2026-09-30).  Private
    # /api/dfs/* router: slate import, projection-baseline lineup builds and
    # upload-CSV export.  Additive — it reads and writes only data/dfs/ and
    # never touches the dynasty board.  Off → every /api/dfs/* route 503s
    # FEATURE_DISABLED.  Rollback: RISKIT_FEATURE_DFS_WORKSPACE=0 + restart.
    "dfs_workspace": True,
    # DFS licensed slate feed (``src/dfs/providers.py``, owner addendum
    # 2026-09-30): SportsDataIO DfsSlatesByDate → canonical slate.  DEFAULT
    # OFF: the feed is paid, no SPORTSDATAIO_API_KEY is provisioned, and its
    # DraftKings/FanDuel coverage is documented but not verified.  Off → the
    # provider endpoints answer PROVIDER_UNAVAILABLE and the official platform
    # CSV remains the path.  Enable only after owner approval of the plan:
    # RISKIT_FEATURE_DFS_SPORTSDATAIO_SLATES=1 + the key + restart.
    "dfs_sportsdataio_slates": False,
    # DFS automatic slates (``src/dfs/auto/``, permanent owner requirement
    # 2026-09-30: zero manual CSV imports).  NFL DraftKings + FanDuel slates
    # derived from the schedule, priced from the owner-authorised Daily
    # Fantasy Fuel pages, projected from independent families.  Additive: it
    # writes only data/dfs/ (system:auto snapshots) and never touches the
    # dynasty board.  Off → /api/dfs/auto/slates answers FEATURE_DISABLED,
    # queues no refresh, and the timer tick exits 2; the manual file path is
    # unaffected.  Rollback: RISKIT_FEATURE_DFS_AUTO_SLATES=0 + restart.
    "dfs_auto_slates": True,
    # Import Trade from Screenshot (C3-IMPORT-IMAGE): ``POST
    # /api/trade/import-screenshot`` reads an uploaded screenshot with the
    # LOCAL tesseract binary and returns asset identities + sides only
    # (never values).  Additive: it writes nothing, retains nothing, and the
    # calculator still prices every asset from the canonical board.  A box
    # without the ``tesseract-ocr`` package answers 503 ``ocr_unavailable``
    # rather than failing.  Off → the route answers 404 feature_disabled and
    # the status endpoint reports ``enabled: false``.
    # Rollback: RISKIT_FEATURE_TRADE_SCREENSHOT_IMPORT=0 + restart.
    "trade_screenshot_import": True,
    # Manager Intelligence (owner directive 2026-10-16): ``GET
    # /api/manager-intel/profile`` resolves any Sleeper username and
    # aggregates that manager's league rosters into one player portfolio,
    # priced by the canonical board.  Private (signed-in users only),
    # rate-limited, read-only, writes nothing.  Default ON: the owner
    # confirmed 2026-10-17 the site is non-commercial, so Sleeper's free
    # public API terms apply.  Off → 503 feature_disabled and the nav item
    # disappears.  Rollback: RISKIT_FEATURE_MANAGER_INTELLIGENCE=0 + restart.
    "manager_intelligence": True,
    # Consensus Edge — the unified buy/sell board.  DEFAULT **OFF**.
    #
    # It was flipped ON on 2026-08-04 on the strength of a top-20 study
    # (+3.59% median cohort-excess at 14d, beating a random-20 draw in 6
    # of 7 folds) and flipped back OFF the same day, on the same bar,
    # after an independent audit found the board those numbers were
    # measured on.  Every IDP fair value came from a leave-one-out board
    # that had excluded the only registered ``is_backbone`` source, so
    # the crosswalk that turns a within-DL/LB/DB rank into a
    # combined-pool rank was gone and the numbers were not on any scale
    # (220 rows, median 1.224x the default board, up to 3.48x).
    #
    # With those rows refused (ADR-021) and every measurement re-run
    # against the repaired board, the pre-registered ship gate returns
    # **do not ship**:
    #
    #   * top-20 buys: median **-1.01%** at 14d over 6 folds, beating a
    #     random-20 draw in **0 of 6**; **-0.55%** at 7d over 12 folds,
    #     **0 of 12**.
    #   * mispricing rho: **+0.031** at 14d (was +0.126) and **+0.040**
    #     at 7d (was +0.089) — "no effect detected" at both, and the
    #     market-value benchmark now beats it in 5 of 6 and 9 of 12.
    #
    # So the edge that justified shipping was carried by rows priced in
    # units that do not exist.  Nothing here is broken — the endpoints,
    # the page and the refusal states all work — but a buy/sell call
    # with no measured edge is not something to put in front of a user
    # by default.
    #
    # Turn it on with ``RISKIT_FEATURE_CONSENSUS_EDGE=1`` (plus a
    # restart; flag reads are process-cached) to keep evaluating it.
    # Flipping this default back to True requires the gate in
    # ``scripts/validate_consensus_edge_board.py`` to pass on a re-run,
    # not a judgement call.  See ADR-023.
    "consensus_edge": False,
    # Host-native realized scoring — score the LEAGUE HOST's own weekly
    # stat line directly instead of round-tripping it through nflverse
    # column names.  DEFAULT **OFF**, and off is a validation gate, not a
    # verdict (#802).
    #
    # The champion path normalizes a provider row into Sleeper's stat
    # vocabulary and scores that.  For nflverse rows that is right.  For
    # rows that CAME from Sleeper it is a lossy round-trip:
    # ``league_comparison.sleeper_stats._FIELD_MAP`` translates the host's
    # short keys INTO nflverse long keys, and
    # ``realized_points.sleeper_stat_line_from_row`` translates them BACK.
    # A category with no nflverse column is destroyed in the middle hop
    # even though the source and destination vocabularies both carry it —
    # 50 of the 85 rules dynasty_main pays, including every player
    # special-teams category, the whole kicker family, the rec_* distance
    # bands and the first-down bonuses.
    #
    # Measured on the host's own 2025 wk14 dump, player entries only:
    # ~451 points in one week, ~7,676 across a 17-week regular season,
    # currently reported as impossible to know.
    #
    # OFF by default because flipping it MOVES HISTORICAL NUMBERS that
    # BDVM's reconstructed baseline, league-comparison and the backtests
    # all consume.  Evaluation is not activation.  Promotion is a
    # separate, measured PR that flips the canonical owner and migrates
    # those consumers together — this flag is a temporary
    # champion/challenger gate and must NOT become a permanently
    # supported second scoring system.
    #
    # Enable with ``RISKIT_FEATURE_HOST_NATIVE_SCORING=1`` **and a
    # restart** (flag reads are process-cached).  Evidence:
    # docs/scoring/HOST_NATIVE_SCORING_VALIDATION.md.
    "host_native_scoring": False,
    # Live Waiver Opportunity layer (docs/faab-live-opportunity-model.md,
    # 2026-09-01).  SHADOW ONLY: gated in server.py's
    # /api/waiver/faab-recommend handler, which computes
    # ``src.trade.faab_opportunity.opportunity_value`` alongside the
    # canonical-only value and logs both to
    # ``data/faab/shadow_comparisons_<leagueKey>.json`` — the LIVE
    # response still uses the canonical-only value regardless of this
    # flag.  Same champion/challenger posture as ``host_native_scoring``
    # above: evaluation is not activation.  Promotion to the live bid is
    # a separate, later, human-reviewed step once the shadow log gives
    # outcome evidence — never automatic.
    #
    # Stage 1 activation (owner-directed): default ON only to accumulate
    # shadow comparisons automatically. The response path remains pinned
    # to the canonical-only value; this flag does not promote the
    # challenger into a live recommendation. Roll back with
    # RISKIT_FEATURE_WAIVER_LIVE_OPPORTUNITY=0 + restart.
    "waiver_live_opportunity": True,
    # Game Day live game state — ``src/nfl_data/live_game_state.py`` reads
    # ESPN's public scoreboard (observed quarter / clock / status).
    # Consumed by ``src/api/matchup_intel.py`` (observed-clock remaining
    # production).  Access is owner-attested
    # (docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md).  Default ON
    # since Game Day U5 (2026-09-25): the shared live collector
    # (``src/ros/game_day_live.py`` + the ``dynasty-game-day-live`` timer)
    # polls it on a bounded cadence and persists every observation, so the
    # request path no longer depends on it.  Rollback:
    # ``RISKIT_FEATURE_GAME_DAY_LIVE_GAME_STATE=0`` + restart the backend
    # (the collector is a fresh process per tick and reads it next tick).
    # Off, ``fetch_live_game_state`` returns an explicit ``enabled=False``
    # observation (no network call) and Game Day keeps the schedule-only
    # evidence, where a passed kickoff stays ``unknown``.
    "game_day_live_game_state": True,
    # C5-PROJ-C, first WEEKLY-horizon projection source (2026-09-24):
    # Sleeper's weekly projections endpoint (RotoWire stat lines served by
    # Sleeper), in ``src/ros/sleeper_weekly_projections.py``.  SEASONAL
    # intelligence lane only — never dynasty value.  Access is
    # owner-attested (census entry ``sleeperWeeklyProjections``,
    # OWNER_ATTESTED_AUTHORIZED; record
    # docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md).  Consumed by
    # ``src/api/matchup_intel.py`` (kickoff-locked weekly baselines).
    # Default ON since Game Day U5 (2026-09-25): the shared live collector
    # fetches it at most every 10 min near a kickoff (3 h otherwise, never
    # once every game has kicked off) and persists every fetch append-only,
    # so a restart after kickoff keeps each game's pre-kickoff baseline.
    # Rollback: ``RISKIT_FEATURE_SLEEPER_WEEKLY_PROJECTIONS=0`` + restart the
    # backend (the collector reads it next tick).  Off,
    # ``fetch_weekly_projection_rows`` refuses with ``feature_disabled`` and
    # makes no network call, and Game Day uses the preseason per-game
    # FALLBACK, labelled as not a current-week forecast.
    "sleeper_weekly_projections": True,
    # Game Day live game state from SportsDataIO (2026-09-25) —
    # ``src/nfl_data/sportsdataio_live_game_state.py``, a PROVIDER behind
    # the one live-state owner ``src/nfl_data/live_game_state.py``
    # (``fetch_live_game_state(provider="sportsdataio")``).  Owner-named for
    # live game state (docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md);
    # the collector (``src/ros/game_day_live.py``) uses it only when ESPN
    # fails (HTTP 403 / backoff), one provider per tick with the reason
    # recorded.  Default OFF: it needs the owner-installed
    # ``SPORTSDATAIO_API_KEY`` and a live-scores subscription, and a keyed
    # feed costs quota.  Capability = this flag ON + the Game Day master
    # flag ON + key present + last fetch healthy.  Off, or with no key,
    # the fetcher refuses (``flag_disabled`` / ``credential_missing``)
    # without a request.  Enable: RISKIT_FEATURE_SPORTSDATAIO_LIVE_GAME_STATE=1
    # + restart (the collector reads it next tick).
    "sportsdataio_live_game_state": False,
    # Game Day live game state from BALLDONTLIE (owner-approved candidate,
    # 2026-09-27) — ``src/nfl_data/balldontlie_live_game_state.py``, a
    # PROVIDER behind ``src/nfl_data/live_game_state.py``.  SHADOW ONLY: the
    # collector records each observation and compares it with the provider
    # it actually selected (``game_day_live.collect_shadow_live_state``); it
    # is never selected and never reaches a forecast.  A PARTIAL provider on
    # the free tier (lifecycle + score, no period/clock).  Default OFF: it
    # needs the owner-installed ``BALLDONTLIE_API_KEY``.  Enable shadow:
    # RISKIT_FEATURE_BALLDONTLIE_LIVE_GAME_STATE=1 + key (the collector reads
    # both next tick).  Evaluation: docs/game-day/BALLDONTLIE_LIVE_STATE_EVALUATION.md.
    "balldontlie_live_game_state": False,
    # C5-PROJ-C keyed WEEKLY projection sources (2026-09-25): Fantasy Nerds
    # (``src/ros/fantasynerds_weekly_projections.py``, key
    # FANTASYNERDS_API_KEY) and SportsDataIO
    # (``src/ros/sportsdataio_weekly_projections.py``, key
    # SPORTSDATAIO_API_KEY).  SEASONAL intelligence lane only.  Licensing is
    # OWNER_ATTESTED_AUTHORIZED; OFF because no production credential is
    # installed yet.  Off, or no key → the fetch refuses (feature_disabled /
    # credential_missing) with no network call; that source is unavailable
    # and nothing else is affected.  Activate: install the key in the
    # service environment, set RISKIT_FEATURE_<NAME>=1, restart; the source
    # becomes usable only once ``source_available()`` also sees a healthy
    # fetch.
    "fantasynerds_weekly_projections": False,
    "sportsdataio_weekly_projections": False,
    # Owner Decision 11 (2026-10-18) — playoff / title odds count a team's ROS
    # evidence ONCE.  ``src/ros/playoff_sim._compose_team_distribution``: on a
    # best-ball pre-sim basis (itself drawn from each player's rosValue) the
    # incumbent re-applies the ROS z-score mean multiplier and the
    # roster-depth variance lift, both summaries of the same rosValues.  ON
    # serves the corrected equation; OFF serves the incumbent byte for byte.
    # Start/sit leagues (empirical basis) are identical either way.  OFF
    # (shadow only) because the preregistered comparison failed gate G4
    # (docs/research/PLAYOFF_ROS_DOUBLE_COUNT_D11.md): it improved weekly
    # log loss 1.133 -> 0.661 but its score distribution was worse
    # calibrated (mean PIT 0.95 vs 0.83).  Turning it on is a disposition
    # change that needs a re-run that passes every gate, not an opt-in.
    # Rollback if ever switched on: RISKIT_FEATURE_PLAYOFF_ROS_COUNTED_ONCE=0
    # + restart.
    "playoff_ros_counted_once": False,
}

_ENV_PREFIX: Final[str] = "RISKIT_FEATURE_"
_cache: dict[str, bool] = {}
_lock = threading.Lock()


def _env_read(name: str) -> bool | None:
    """Return the env-var override for ``name`` or None if absent.

    Accepted truthy: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
    Accepted falsy:  ``0``, ``false``, ``no``, ``off`` (case-insensitive).
    Anything else → None (treated as absent; default wins).
    """
    raw = os.getenv(f"{_ENV_PREFIX}{name.upper()}", "")
    if not raw:
        return None
    low = raw.strip().lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    return None


def is_enabled(name: str) -> bool:
    """Return the effective value for ``name``.

    Raises KeyError if the flag isn't registered in ``_DEFAULTS``.
    """
    if name not in _DEFAULTS:
        raise KeyError(
            f"unknown feature flag: {name!r}.  Register it in "
            f"src.api.feature_flags._DEFAULTS first."
        )
    with _lock:
        if name in _cache:
            return _cache[name]
        env = _env_read(name)
        effective = _DEFAULTS[name] if env is None else env
        _cache[name] = effective
        return effective


def reload() -> None:
    """Clear the process-local cache so the next ``is_enabled`` call
    re-reads env vars.  Tests that set env mid-run should call this.
    """
    with _lock:
        _cache.clear()


def snapshot() -> dict[str, bool]:
    """Return the current effective flag values for every registered
    flag.  Cheap — used by ``/api/status`` to expose what's on."""
    return {name: is_enabled(name) for name in _DEFAULTS}


def registered_flags() -> list[str]:
    """Return the registered flag names in declaration order."""
    return list(_DEFAULTS.keys())


# ── Gate status ───────────────────────────────────────────────────
#
# WHY THIS IS DATA AND NOT A COMMENT
#
# Every flag below used to carry a prose comment describing what it
# did.  Measured 2026-07-27 by walking imports transitively from
# ``server.py``, **7 of 13 could not affect a request at all** — and
# four of those defaulted True while their comments asserted live
# behaviour ("fires via unified_signal_engine", "Frontend TierDivider
# renders when tierId set", "Safe to activate").
#
# That is ORCHESTRATION.md §6.15 in registry form: the stated purpose
# and the actual predicate differ and nothing forces them to agree.  A
# comment cannot be checked, so the classification moves here where
# ``tests/api/test_feature_flag_reachability.py`` re-measures it against
# the real import graph on every run.  Add a flag without classifying
# it and that test fails.
#
# The four statuses:
#
#   LIVE          a gate exists in a module reachable from server.py.
#                 Toggling changes what a request does.
#   SCRIPT_ONLY   a gate exists, but only in ``scripts/``.  Toggling
#                 changes an operator tool, never a response.
#   UNREACHABLE   a gate exists in a module NOTHING imports.  Toggling
#                 is a no-op today; the gate is real but stranded.
#   NO_GATE       no ``is_enabled`` call anywhere.  The flag is inert:
#                 the capability it names is either unconditional or
#                 absent, and the flag's value means nothing either way.
#
# Only LIVE flags may default True — anything else advertising itself
# as on is the lie this table exists to prevent.

LIVE: Final[str] = "LIVE"
SCRIPT_ONLY: Final[str] = "SCRIPT_ONLY"
UNREACHABLE: Final[str] = "UNREACHABLE"
NO_GATE: Final[str] = "NO_GATE"

_GATE_STATUS: Final[dict[str, str]] = {
    # ── Reachable from server.py; toggling changes a response ──
    "nfl_data_ingest": LIVE,
    # ledger_rank_change gates the temporal-ledger rankChange derivation in
    # ``data_contract._stamp_rank_changes``, which reaches a request through
    # ``/api/data``: on → each ranked row's rankChange derives from the
    # ledger's previous recorded board (743 of 749 rows non-null on the
    # measured production board), off → None on every row.
    "ledger_rank_change": LIVE,
    "realized_points_api": LIVE,
    "monte_carlo_trade": LIVE,
    "te_basis_conversion": LIVE,
    "idp_scoring_fit": LIVE,
    "reception_scoring_fit": LIVE,
    # bdvm_engine gates three routes inline in server.py
    # (/api/bdvm/values, /api/bdvm/roster, /api/bdvm/trades): off →
    # 503 feature_disabled, on → the BDVM payloads.
    "bdvm_engine": LIVE,
    # perfect_draft gates /api/draft/roster-context inline in server.py:
    # off → 503 feature_disabled (and the /draft panel vanishes), on →
    # the roster context the client optimizer runs against.
    "perfect_draft": LIVE,
    # rookie_auction gates the /api/auction/* router mounted in server.py
    # and the auction runtime loop started in lifespan.
    "rookie_auction": LIVE,
    # dfs_workspace gates the /api/dfs/* router mounted in server.py.
    "dfs_workspace": LIVE,
    # dfs_sportsdataio_slates gates src/dfs/providers.py, reached through the
    # /api/dfs/provider-slates* routes mounted in server.py.
    "dfs_sportsdataio_slates": LIVE,
    # dfs_auto_slates gates src/dfs/auto (the /api/dfs/auto/* routes mounted
    # in server.py, and scripts/refresh_dfs_auto_slates.py on its timer).
    "dfs_auto_slates": LIVE,
    # trade_screenshot_import gates /api/trade/import-screenshot inline in
    # server.py: off → 404 feature_disabled, on → the extraction payload.
    "trade_screenshot_import": LIVE,
    # manager_intelligence gates the /api/manager-intel router mounted in
    # server.py: off → 503 feature_disabled, on → the profile.
    "manager_intelligence": LIVE,
    # consensus_edge gates the /api/consensus-edge/* router mounted in
    # server.py: off → 503 feature_disabled, on → the board.
    "consensus_edge": LIVE,
    # multi_bridge_ladder gates how many QUALIFIED cross-position bridges
    # seed the shared-market ladder in
    # ``data_contract._compute_unified_rankings`` (Phase 0), which reaches a
    # request through ``/api/data`` and every engine that reads the board:
    # off → the first usable bridge only, reproducing the incumbent ladder
    # integer for integer, on → all of them combined.  Measured on the
    # 2026-08-20 board, flipping it moves 337 of 1,111 values.
    "multi_bridge_ladder": LIVE,
    # source_freshness_weighting gates whether the dynamic freshness ×
    # health × coverage factor is APPLIED in
    # ``data_contract._compute_unified_rankings`` (Phase 2-3), which reaches
    # a request through ``/api/data`` and every engine that reads the board;
    # off → base weights only, factors still stamped.
    "source_freshness_weighting": LIVE,
    # source_freshness_schedule_v2 selects the freshness RULE (owner step
    # schedule vs the v1 cadence curve) in
    # ``data_contract._source_weighting_resolution``, read on every board
    # build, which reaches a request through ``/api/data`` and every engine
    # that reads the board.
    "source_freshness_schedule_v2": LIVE,
    # source_family_cap gates whether correlated family members all vote
    # under a family cap or the family head alone votes, in
    # ``data_contract._compute_unified_rankings``, which reaches a request
    # through ``/api/data`` and every engine that reads the board.
    "source_family_cap": LIVE,
    # dlf_offense_only_vote gates the vote hold on the DLF IDP boards in
    # ``data_contract._policy_source_vote_holds`` -- a TEMPORARY hold
    # re-applied 2026-10-19 (default ON): the owner rescinded the 2026-10-16
    # policy hold, but restoring DLF IDP under the incumbent outlier filter
    # drops valid Draft Sharks / FantasyPros / IDPTC IDP votes (30 rows, up to
    # 54%), so the restore is held.  LOCKED by the owner's Option 3 decision
    # of 2026-10-20: it lifts only with explicit owner approval after a
    # preregistered outlier-filter Version 2 passes every mandatory gate
    # (tests/api/test_dlf_idp_hold_locked.py).  Mechanism of a lift:
    # RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0 + restart.  Read by
    # ``build_api_data_contract`` on every board build, which reaches a
    # request through ``/api/data`` and every engine that reads the board.
    "dlf_offense_only_vote": LIVE,
    # dlf_values_rank_hill_vote releases the DLF Values hold inside
    # ``data_contract._policy_source_vote_holds``; two_way_alt_evidence_rules
    # gates ``data_contract._apply_two_way_player_boost``'s evidence rules;
    # fantasypros_idp_upstream_clock gates the configured freshness style in
    # ``src/sources/freshness.load_config``.  All read on every board build,
    # which reaches a request through ``/api/data``.
    "dlf_values_rank_hill_vote": LIVE,
    "two_way_alt_evidence_rules": LIVE,
    "fantasypros_idp_upstream_clock": LIVE,
    # source_universe_freshness caps each row's freshness clock at its own asset
    # universe's broad-change clock on mixed offense+IDP boards (#1555 V2-1).
    "source_universe_freshness": LIVE,
    # signals_active_source gates the Signals voters in
    # ``data_contract._private_source_vote_state``, reached through
    # ``build_api_data_contract`` on every /api/data build.
    "signals_active_source": LIVE,
    # signals_idp_shared_market (the Signals IDP master) and the three
    # per-family release flags gate the Signals IDP vote hold in
    # ``data_contract._private_source_vote_state`` (AND semantics), reached
    # through ``build_api_data_contract`` on every /api/data build.
    "signals_idp_shared_market": LIVE,
    # signals_idp_family_quarantine gates the IDP family-scoped quarantine in
    # ``src/sources/signals.py`` (imported by server.py, so it measures LIVE);
    # the gate itself runs in the dynasty-signals-values collector process.
    "signals_idp_family_quarantine": LIVE,
    "signals_idp_dl_vote": LIVE,
    "signals_idp_lb_vote": LIVE,
    "signals_idp_db_vote": LIVE,
    # signals_idp_xwalk_v2 selects the Signals IDP crosswalk (Candidate F) in
    # ``data_contract._compute_unified_rankings`` and the Signals-scoped
    # identity guard in ``_enrich_from_source_csvs``, both on every board build.
    "signals_idp_xwalk_v2": LIVE,
    # joint_outlier_sparse_challenger swaps the per-player outlier filter and
    # the single-source haircut in ``data_contract._compute_unified_rankings``,
    # which reaches a request through ``/api/data``; ships OFF (challenger).
    "joint_outlier_sparse_challenger": LIVE,
    # rank_space_hampel_challenger swaps the per-player outlier filter's
    # coordinate system in data_contract._compute_unified_rankings (reaches a
    # request through /api/data); ships OFF (challenger).
    "rank_space_hampel_challenger": LIVE,
    # rank_space_hampel_per_vote_challenger swaps the same filter for its
    # per-vote coordinate form in the same function (reaches a request through
    # /api/data); ships OFF (challenger).
    "rank_space_hampel_per_vote_challenger": LIVE,
    # idp_hampel_n3_challenger lowers the per-player outlier filter's minimum
    # voter count to 3 on IDP rows in the same function (reaches a request
    # through /api/data); ships OFF (challenger).
    "idp_hampel_n3_challenger": LIVE,
    # idp_deep_tail_native_challenger reprices deep IDP shared-market rank votes
    # in the same function's blend loop (reaches a request through /api/data);
    # ships OFF (challenger).
    "idp_deep_tail_native_challenger": LIVE,
    # outlier_disagreement_policy replaces the per-player outlier filter's
    # decision in the same function and screens each board between two ranking
    # passes in build_api_data_contract (reaches a request through /api/data);
    # ships OFF (challenger).
    "outlier_disagreement_policy": LIVE,
    # The outlier-integrity-v2 flags gate src/api/source_integrity.py, called
    # from data_contract's enrichment and ranking passes on every board build
    # (reaches a request through /api/data); all ship OFF (challenger).
    "outlier_integrity_v2": LIVE,
    "identity_evidence_v2": LIVE,
    "payload_provenance_guard": LIVE,
    "rookie_ladder_fail_closed": LIVE,
    "integrity_holds_as_withheld": LIVE,
    "outlier_integrity_v21": LIVE,
    # source_rank_history_record gates the record-only history lane write at
    # server.py's fresh-scrape recording site; ships OFF.
    "source_rank_history_record": LIVE,
    # joint_sparse_limited_evidence replaces the single-source haircut with a
    # limitedEvidence stamp in the same function; ships OFF (challenger).
    "joint_sparse_limited_evidence": LIVE,
    # sparse_evidence_estimator replaces the single-source haircut with a
    # censor-aware central estimate in the same function, which reaches a
    # request through ``/api/data``; ships OFF (challenger).
    "sparse_evidence_estimator": LIVE,
    # host_native_scoring gates the stat vocabulary
    # ``league_comparison.sleeper_stats.fetch_sleeper_weekly_stats``
    # emits, which reaches a request through ``historical_stats`` →
    # ``scoring_engine`` → ``/api/league-comparison``: off → the host's
    # keys are translated into nflverse column names (and 50 of the 85
    # rules dynasty_main pays are lost in the round trip), on → the
    # host's own vocabulary is scored directly.  See
    # docs/scoring/HOST_NATIVE_SCORING_VALIDATION.md.
    "host_native_scoring": LIVE,
    # waiver_live_opportunity gates a computation inside server.py's
    # /api/waiver/faab-recommend handler (reachable from server.py by
    # construction — it IS server.py), so the import-graph measurement
    # below is genuinely LIVE.  This does NOT mean toggling it changes
    # the response: it is a SHADOW gate by design (see its _DEFAULTS
    # comment) — reachable-and-wired is a different claim from
    # response-changing, which is exactly why it defaults False rather
    # than True despite measuring LIVE.
    "waiver_live_opportunity": LIVE,
    # ``src/nfl_data/injury_feed.py`` is reachable since 2026-09-01 via
    # ``scripts/refresh_injury_feed.py``, a script-only entry point (no
    # server.py route reads it directly) that writes into the BDVM
    # events ledger, which server.py DOES read through
    # ``src/trade/faab_opportunity.py``.  Not plain LIVE (no request
    # changes response by toggling this flag alone — the effect only
    # shows up after the script has run and written events) and not
    # UNREACHABLE either — SCRIPT_ONLY captures it correctly.
    "espn_injury_feed": SCRIPT_ONLY,
    # ``src/news/usage_signals.py`` — still genuinely stranded.  Nothing
    # imports it.  Reviving it was evaluated for the Live Waiver
    # Opportunity layer (docs/faab-live-opportunity-model.md) and scoped
    # OUT of this pass: ``src/nfl_data/usage_windows.py`` needs a weekly
    # nflverse pull this layer does not otherwise require, and the
    # depth-chart + injury-feed events alone already cover the
    # directive's named cases.  ``depth_charts.usage_confirms_slot_change``
    # exists and is a real, tested cross-check primitive, but nothing
    # calls it yet — a genuine follow-up, not fabricated here.
    "usage_signals": UNREACHABLE,
    # ``src/nfl_data/live_game_state.py`` — reached through
    # ``src/api/matchup_intel.py::_observe_live_state`` on the matchup
    # endpoint and by the Game Day live collector
    # (``src/ros/game_day_live.py``): on, observed quarter/clock drive
    # remaining production; off, schedule-only evidence.  Defaults True
    # since Game Day U5.
    "game_day_live_game_state": LIVE,
    # ``src/ros/sleeper_weekly_projections.py`` — the C5-PROJ-C weekly
    # source, reached through ``src/api/matchup_intel.py::
    # _weekly_projection_fetches`` on the matchup endpoint and by the Game
    # Day live collector: on, kickoff-locked weekly baselines; off, the
    # labelled preseason fallback.  Defaults True since Game Day U5.
    "sleeper_weekly_projections": LIVE,
    # ``src/nfl_data/sportsdataio_live_game_state.py`` — reached through
    # ``live_game_state.fetch_live_game_state(provider="sportsdataio")`` by
    # the Game Day live collector's ESPN-failure fallback.  Defaults False.
    "sportsdataio_live_game_state": LIVE,
    # ``src/nfl_data/balldontlie_live_game_state.py`` — reached through
    # ``live_game_state.fetch_live_game_state(provider="balldontlie")`` by the
    # Game Day live collector's SHADOW capture.  Defaults False.
    "balldontlie_live_game_state": LIVE,
    # The two keyed weekly sources: built and tested, not yet consumed by
    # any route/script/engine (the Game Day consumer wires them). Default
    # False, and they also need their credential env var.
    "fantasynerds_weekly_projections": UNREACHABLE,
    "sportsdataio_weekly_projections": UNREACHABLE,
    # ``src/ros/playoff_sim.ros_counted_once_enabled`` — read by
    # ``_build_team_distributions`` on every canonical forecast, reached
    # through ``/api/public/league/rosPlayoffOdds`` / ``playoffOdds`` /
    # ``rosChampionship``: on, the corrected ROS-once equation; off, the
    # incumbent (Owner Decision 11).
    "playoff_ros_counted_once": LIVE,
    # ``src/nfl_data/depth_charts.py`` is gated and imported by
    # ``scripts/refresh_depth_charts.py``, which since 2026-09-01 also
    # writes DEPTH_CHART_PROMOTION/DEMOTION events into the BDVM ledger
    # — same SCRIPT_ONLY reasoning as ``espn_injury_feed`` above.  Note
    # this is a DIFFERENT module from
    # ``src/playerctx/normalize.py::parse_depth_charts``, which is live
    # and ungated; conflating the two reads as "depth charts work, so
    # the flag must be live".
    "depth_chart_validation": SCRIPT_ONLY,
    # ── No gate anywhere: the flag is decoration ──
    #
    # Each of these is named in a docstring that describes a gate, and
    # in no ``is_enabled`` call.  Prose is the only place the gating
    # exists.
    #
    # value_confidence_intervals: ``stamp_bands_on_players`` has no
    #   caller, ``rank_history_band`` has no caller, and ValueBandBadge
    #   is exported from the ui barrel and mounted on no page.  Dead at
    #   all three layers.
    # positional_tiers: ``stamp_tiers_on_players`` is called only from
    #   ``scripts/refit_tier_thresholds.py``.  ``TierDivider`` renders
    #   only on /draft, off a locally computed ``p.tier`` — not the
    #   backend ``tierId`` the flag's old comment named.
    # unified_id_mapper: the mapper is unconditional.  The flag has
    #   never gated it.
    # dynamic_source_weights: ``src/backtesting/harness.py`` calls
    #   itself "flag-gated ... implicitly", which is an accurate
    #   description of not being flag-gated.
    "value_confidence_intervals": NO_GATE,
    "positional_tiers": NO_GATE,
    "unified_id_mapper": NO_GATE,
    "dynamic_source_weights": NO_GATE,
}


def gate_status(name: str) -> str:
    """Return whether ``name``'s gate can actually run.

    Raises KeyError for an unregistered flag, same as :func:`is_enabled`.
    """
    if name not in _DEFAULTS:
        raise KeyError(f"unknown feature flag: {name!r}")
    return _GATE_STATUS[name]


def effective_flags() -> dict[str, dict[str, object]]:
    """Flag values alongside whether they can do anything.

    ``/api/status`` reports :func:`snapshot`, which answers "is it on?".
    That question is misleading on its own for the seven flags whose
    gates cannot run — this answers "is it on, and would it matter?".
    """
    return {
        name: {"enabled": is_enabled(name), "gateStatus": _GATE_STATUS[name]} for name in _DEFAULTS
    }
