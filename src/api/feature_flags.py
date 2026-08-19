"""Feature flag registry for phased rollout of the 2026-04 upgrade.

Every new capability added in Phases 1–10 of the major upgrade is
gated here so production can stay on the proven path while new code
proves itself.

**Defaults are PER-FLAG, and several of the interesting ones ship
enabled.**  This docstring, ``README.md`` and ``docs/ARCHITECTURE.md``
all used to assert a blanket disabled-by-default rule, and
ARCHITECTURE built a stronger claim on top of it about production
behaviour being frozen until a flag was flipped.  Both were false: 8 of
the 16 entries in ``_DEFAULTS`` below are ``True`` — ``bdvm_engine``,
``te_basis_conversion`` (which reprices every tight end on the live
board), ``monte_carlo_trade``, ``idp_scoring_fit``,
``reception_scoring_fit``, ``nfl_data_ingest``, ``realized_points_api``
and ``perfect_draft`` — several with comments recording that the
enabled default is deliberate.

**One live gate is deliberately NOT in this registry**, and it is the
sharpest illustration of why the paragraph above matters:
``RISKIT_FEATURE_LEDGER_RANK_CHANGE`` is read directly in
``data_contract._stamp_rank_changes``, defaults ON, and therefore appears
in no operator surface at all.  Audit **F-24** proposed registering it;
that is blocked, not abandoned, and the reason is recorded at the read
site.

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
    "unified_id_mapper": False,
    # #804 per-source RANK capture into the canonical temporal ledger
    # (src/history/source_rank.py).  CAPTURE ONLY — it writes a new
    # ``source_rank`` lane and nothing reads it; no weighting, no
    # correlation scoring, no canonical value or ranking movement.
    #
    # DEFAULT OFF, and the reason is storage rather than risk.  Measured
    # on a real board: 7,245 observations per build across 21 sources at
    # ~446 B/row (index overhead on the shared observations table, not
    # payload — stripping every denormalized string saves only 4-7%).
    # At the 2-hourly scrape that is ~38.8 MB/day and ~14.2 GB/year, which
    # is a production disk commitment an owner has to make deliberately.
    # Enable with RISKIT_FEATURE_SOURCE_RANK_CAPTURE=1 once a cadence and
    # a retention posture are chosen; see
    # docs/history/SOURCE_RANK_CAPTURE.md for the per-cadence table.
    "source_rank_capture": False,
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
    # Phase 7 — ESPN injury feed.  UNREACHABLE, so OFF.
    #
    # The gate in ``src/nfl_data/injury_feed.py`` is real and correct.
    # The module has no production importer, so the gate never runs and
    # the old "Safe to activate" was true only in the sense that
    # activating it did nothing.
    "espn_injury_feed": False,
    # Phase 8 — Depth chart cross-check.  SCRIPT_ONLY, so OFF.
    #
    # ``src/nfl_data/depth_charts.py`` is gated and imported — by
    # ``scripts/refresh_depth_charts.py`` alone.  The old comment's
    # "Requires injury feed ON to cross-check" made it depend on a flag
    # whose own module never runs, so neither half could ever fire.
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
    # source_rank_capture gates a WRITE, not a response: on, the
    # fresh-scrape path records per-source ranks into the temporal
    # ledger; off, it records nothing.  No response body changes either
    # way, which is the point of a capture-only unit.
    "source_rank_capture": LIVE,
    # ── Reachable from server.py; toggling changes a response ──
    "nfl_data_ingest": LIVE,
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
    # consensus_edge gates the /api/consensus-edge/* router mounted in
    # server.py: off → 503 feature_disabled, on → the board.
    "consensus_edge": LIVE,
    # ── Gate exists, module is stranded ──
    #
    # ``src/nfl_data/injury_feed.py`` and ``src/news/usage_signals.py``
    # both check their flag properly.  Nothing imports either module, so
    # the check never executes.
    "espn_injury_feed": UNREACHABLE,
    "usage_signals": UNREACHABLE,
    # ``src/nfl_data/depth_charts.py`` is gated and is imported — by
    # ``scripts/refresh_depth_charts.py`` only.  Note this is a DIFFERENT
    # module from ``src/playerctx/normalize.py::parse_depth_charts``,
    # which is live and ungated; conflating the two reads as "depth
    # charts work, so the flag must be live".
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
