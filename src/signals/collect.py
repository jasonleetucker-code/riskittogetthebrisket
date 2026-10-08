"""Read the live Buy/Sell emitters THROUGH THEIR OWNERS (C6-SIG-01).

Each collector calls the emitter's canonical owner, reads the verdict the
owner published, and files it as a :class:`~src.signals.reconciler.Observation`.
None of them re-derives an emitter's rules, thresholds or scores — when an
owner cannot answer (feature flag off, no projection snapshot, ledger
absent, an exception) the emitter is reported ``unobserved`` with that
reason and contributes nothing.  It is never read as neutral.

Player identity: every emitter row is placed on the canonical contract's
asset key (:func:`src.history.keys.asset_key_for_contract_row`) by platform
id first, then by exact display name, then by the identity family's
canonical name (:func:`src.utils.name_clean.resolve_canonical_name`).  A
name that maps to more than one row and cannot be split by position group
is AMBIGUOUS; one that maps to none is UNRESOLVED.  Both are reported in
``unresolved`` — never fuzzy-matched onto a best guess.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

from src.history.keys import asset_key_for_contract_row
from src.signals import reconciler as rec
from src.utils.name_clean import canonical_position_group, resolve_canonical_name

_LOGGER = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ── Identity ─────────────────────────────────────────────────────────────


@dataclass
class IdentityIndex:
    """Contract-row asset keys, reachable by id and by name."""

    by_id: dict[str, str] = field(default_factory=dict)
    by_display_name: dict[str, set[str]] = field(default_factory=dict)
    by_exact_name: dict[str, set[str]] = field(default_factory=dict)
    by_canonical_name: dict[str, set[str]] = field(default_factory=dict)
    group_by_key: dict[str, str] = field(default_factory=dict)
    id_by_key: dict[str, str] = field(default_factory=dict)
    display_by_key: dict[str, str] = field(default_factory=dict)
    quarantined: dict[str, str] = field(default_factory=dict)

    def resolve(
        self,
        *,
        player_id: Any = None,
        name: Any = None,
        position: Any = None,
        emitter_key: Any = None,
    ) -> tuple[str | None, str | None]:
        """``(asset_key, None)`` or ``(None, failure)``."""
        found = self.resolve_detailed(
            player_id=player_id, name=name, position=position, emitter_key=emitter_key
        )
        return found.key, found.failure

    def resolve_with_basis(
        self,
        *,
        player_id: Any = None,
        name: Any = None,
        position: Any = None,
        emitter_key: Any = None,
    ) -> tuple[str | None, str | None, str | None]:
        """``(asset_key, failure, basis)`` — basis says HOW it was placed."""
        found = self.resolve_detailed(
            player_id=player_id, name=name, position=position, emitter_key=emitter_key
        )
        return found.key, found.failure, found.basis

    def resolve_detailed(
        self,
        *,
        player_id: Any = None,
        name: Any = None,
        position: Any = None,
        emitter_key: Any = None,
    ) -> "Resolution":
        """Place one emitter row, refusing rather than guessing.

        Order: the platform id; the emitter's own join key when that key IS
        the contract's exact ``displayName`` (Consensus Edge ``playerKey``);
        then name.  Name matching is evidence of identity only when nothing
        contradicts it:

        * an emitter that supplied an id the board does not carry is a
          DIFFERENT person from any name candidate that has its own id — that
          candidate is refused (``id_not_on_board``).  Only an id-less
          candidate can be reached, labelled ``name_fallback:id_not_on_board``,
          and only with a supplied position whose group agrees;
        * a supplied position whose group differs from the candidate's is a
          ``position_conflict``, even for a single candidate.

        Refused or ambiguous resolutions return their name ``candidates`` so
        the caller can mark those players ``unplaced`` for the emitter rather
        than ``silent``.
        """
        pid = str(player_id or "").strip()
        if pid and pid in self.by_id:
            return Resolution(self.by_id[pid], None, "player_id")
        id_off_board = bool(pid)
        ekey = str(emitter_key or "").strip()
        prefix = ""
        if ekey:
            candidates = self.by_display_name.get(ekey)
            if candidates and len(candidates) == 1:
                return Resolution(next(iter(candidates)), None, "emitter_key")
            prefix = "name_fallback:"
        if id_off_board:
            prefix = "name_fallback:id_not_on_board:"
        raw = str(name or "").strip()
        if not raw:
            return Resolution(None, "id_not_on_board" if id_off_board else "unresolved")
        group = canonical_position_group(str(position)) if position else None
        for basis, found in (
            ("exact_name", self.by_exact_name.get(raw.casefold())),
            ("canonical_name", self.by_canonical_name.get(resolve_canonical_name(raw))),
        ):
            if not found:
                continue
            candidates = frozenset(found)
            if id_off_board:
                # A candidate carrying its own id is somebody else.
                pool = {key for key in candidates if not self.id_by_key.get(key)}
                if not pool:
                    return Resolution(None, "id_not_on_board", candidates=candidates)
                if not group:
                    return Resolution(None, "id_not_on_board", candidates=candidates)
            else:
                pool = set(candidates)
            if group:
                agreeing = {key for key in pool if self.group_by_key.get(key) in (group, "")}
                if not agreeing:
                    return Resolution(None, "position_conflict", candidates=candidates)
                pool = agreeing
            if len(pool) == 1:
                suffix = "+position" if group and len(candidates) > 1 else ""
                return Resolution(next(iter(pool)), None, f"{prefix}{basis}{suffix}")
            return Resolution(None, "ambiguous", candidates=candidates)
        return Resolution(None, "id_not_on_board" if id_off_board else "unresolved")


@dataclass(frozen=True)
class Resolution:
    key: str | None
    failure: str | None
    basis: str | None = None
    candidates: frozenset[str] = frozenset()


def _contract_rows(contract: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = contract.get("playersArray")
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def build_identity_index(contract: Mapping[str, Any]) -> IdentityIndex:
    index = IdentityIndex()
    for row in _contract_rows(contract):
        keyed = asset_key_for_contract_row(dict(row))
        if keyed is None:
            continue
        key = keyed[0]
        display = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        index.display_by_key.setdefault(key, display)
        index.group_by_key.setdefault(
            key, canonical_position_group(str(row.get("position") or "")) or ""
        )
        for pid in (row.get("playerId"), row.get("sleeperId"), row.get("_sleeperId")):
            pid_s = str(pid or "").strip()
            if pid_s:
                index.by_id.setdefault(pid_s, key)
                index.id_by_key.setdefault(key, pid_s)
        if str(row.get("displayName") or "").strip():
            index.by_display_name.setdefault(str(row.get("displayName")).strip(), set()).add(key)
        for name in {row.get("displayName"), row.get("canonicalName")}:
            name_s = str(name or "").strip()
            if not name_s:
                continue
            index.by_exact_name.setdefault(name_s.casefold(), set()).add(key)
            canonical = resolve_canonical_name(name_s)
            if canonical:
                index.by_canonical_name.setdefault(canonical, set()).add(key)
        if row.get("quarantined"):
            flags = row.get("anomalyFlags")
            reason = ",".join(str(f) for f in flags) if isinstance(flags, list) and flags else ""
            index.quarantined[key] = reason or "quarantined"
    return index


@dataclass
class _Placement:
    observations: list[rec.Observation] = field(default_factory=list)
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    #: name candidates of rows the join refused -> why (so those players
    #: read ``unplaced`` for this emitter, never ``silent``).
    unplaced: dict[str, str] = field(default_factory=dict)

    def refuse(self, found: "Resolution", record: dict[str, Any]) -> None:
        self.unresolved.append({**record, "candidates": sorted(found.candidates)})
        for key in found.candidates:
            self.unplaced.setdefault(key, str(found.failure))

    def place(
        self,
        index: IdentityIndex,
        *,
        emitter_id: str,
        player_id: Any,
        name: Any,
        position: Any,
        native_label: str | None,
        reason: str | None,
        evidence: Mapping[str, Any],
        emitter_key: Any = None,
    ) -> None:
        found = index.resolve_detailed(
            player_id=player_id, name=name, position=position, emitter_key=emitter_key
        )
        key, basis = found.key, found.basis
        if key is None:
            self.refuse(
                found,
                {
                    "emitter": emitter_id,
                    "name": name,
                    "playerId": player_id,
                    "nativeLabel": native_label,
                    "reason": found.failure,
                },
            )
            return
        self.observations.append(
            rec.Observation(
                emitter_id=emitter_id,
                player_key=key,
                native_label=native_label,
                display_name=index.display_by_key.get(key) or (str(name) if name else None),
                reason=reason,
                placement=basis,
                evidence=dict(evidence),
            )
        )


# ── Freshness ────────────────────────────────────────────────────────────


def contract_market_freshness(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Age of the market data behind board-derived signals.

    Reuses the two existing owners rather than inventing a rule: the
    oldest market-anchor age (``consensus_edge.service.resolve_hours_stale``,
    read off the contract's own ``dataFreshness`` block) against the repo's
    scrape-cadence staleness budget
    (``league_registry.SCORING_SNAPSHOT_MAX_AGE_HOURS``).  No usable
    freshness data is ``unknown`` — never assumed fresh.
    """
    from src.api.league_registry import SCORING_SNAPSHOT_MAX_AGE_HOURS  # noqa: PLC0415
    from src.consensus_edge.service import resolve_hours_stale  # noqa: PLC0415

    hours = resolve_hours_stale(dict(contract))
    if hours is None:
        state = "unknown"
    elif hours <= SCORING_SNAPSHOT_MAX_AGE_HOURS:
        state = "fresh"
    else:
        state = "stale"
    return {
        "state": state,
        "hoursStale": hours,
        "budgetHours": SCORING_SNAPSHOT_MAX_AGE_HOURS,
        "basis": "oldest_market_anchor_age",
    }


def _contract_as_of(contract: Mapping[str, Any]) -> str | None:
    value = contract.get("scrapeTimestamp") or contract.get("generatedAt")
    return str(value) if value else None


def _iso_from_ms(value: Any) -> str | None:
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return (_EPOCH + timedelta(milliseconds=ms)).isoformat()


def _guarded(emitter_id: str, fn: Callable[[], tuple[rec.EmitterRun, list[dict[str, Any]]]]):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — one emitter failing must not hide the others
        _LOGGER.warning("signal reconciler: %s collection failed: %s", emitter_id, exc)
        return rec.unobserved(emitter_id, f"error:{type(exc).__name__}"), []


# ── Collectors ───────────────────────────────────────────────────────────


def collect_terminal(
    contract: Mapping[str, Any],
    index: IdentityIndex,
    *,
    resolved_team: Mapping[str, Any] | None,
    news_items: list[dict[str, Any]] | None,
    league_key: str | None,
    freshness: Mapping[str, Any],
) -> tuple[rec.EmitterRun, list[dict[str, Any]]]:
    """The terminal rule engine's verdicts for the selected roster."""
    emitter = "terminal_signal"
    if not resolved_team:
        return rec.unobserved(emitter, "no_team_resolved"), []

    def _run():
        from src.api import terminal as _terminal  # noqa: PLC0415

        notes: list[str] = []
        if news_items is None:
            notes.append("news_unavailable: news-driven rules could not fire for this run")
        payload = _terminal.build_terminal_payload(
            dict(contract),
            resolved_team=dict(resolved_team),
            news_items=news_items if news_items is not None else [],
            user_state=None,
            league_key=league_key,
        )
        placement = _Placement()
        for signal in payload.get("signals") or []:
            if not isinstance(signal, Mapping):
                continue
            placement.place(
                index,
                emitter_id=emitter,
                player_id=signal.get("sleeperId"),
                name=signal.get("name"),
                position=signal.get("pos"),
                native_label=signal.get("signal"),
                reason=signal.get("reason"),
                evidence={
                    "tag": signal.get("tag"),
                    "firedTags": [
                        f.get("tag") for f in signal.get("fired") or [] if isinstance(f, Mapping)
                    ],
                    "trend7": signal.get("trend7"),
                    "trend30": signal.get("trend30"),
                    "rankChange": signal.get("rankChange"),
                    "newsCount": signal.get("newsCount"),
                },
            )
        # Roster-scoped: a player off this roster was never evaluated, so he
        # is out_of_scope for this emitter, not silent.
        covered, _missed, _basis = roster_keys(index, resolved_team)
        run = rec.EmitterRun(
            emitter_id=emitter,
            state=rec.OBSERVED,
            as_of=_contract_as_of(contract),
            freshness=dict(freshness),
            observations=tuple(placement.observations),
            unplaced=dict(placement.unplaced),
            notes=tuple(notes),
            covered_keys=frozenset(covered),
        )
        return run, placement.unresolved

    return _guarded(emitter, _run)


def collect_bdvm(
    contract: Mapping[str, Any],
    index: IdentityIndex,
    *,
    league_key: str,
    freshness: Mapping[str, Any],
) -> tuple[rec.EmitterRun, list[dict[str, Any]]]:
    """BDVM's fundamental-vs-market verdict, read off its value board."""
    emitter = "bdvm_market_signal"
    from src.api import feature_flags  # noqa: PLC0415

    if not feature_flags.is_enabled("bdvm_engine"):
        return rec.unobserved(emitter, "feature_disabled:bdvm_engine"), []

    def _run():
        from src.api import bdvm_api  # noqa: PLC0415

        payload = bdvm_api.get_bdvm_values(contract, league_key)
        status = payload.get("status") if isinstance(payload, Mapping) else None
        if status != "ok":
            return rec.unobserved(emitter, f"status:{status}"), []
        placement = _Placement()
        saw_unsignalled = False
        for player in payload.get("players") or []:
            if not isinstance(player, Mapping):
                continue
            signal = player.get("signal")
            if not isinstance(signal, Mapping):
                saw_unsignalled = True
                continue
            market = player.get("market") if isinstance(player.get("market"), Mapping) else {}
            placement.place(
                index,
                emitter_id=emitter,
                player_id=player.get("playerId"),
                name=player.get("name"),
                position=player.get("position"),
                native_label=signal.get("signal"),
                reason=signal.get("reason"),
                evidence={"gap": market.get("gap"), "marketValue": market.get("marketValue")},
            )
        # BDVM's own per-player refusals (no_projection, missing_age, ...):
        # carried with the owner's reason, never left to read as silence.
        declined: dict[str, str] = {}
        for row in payload.get("unpriced") or []:
            if not isinstance(row, Mapping):
                continue
            found = index.resolve_detailed(name=row.get("name"), position=row.get("position"))
            if found.key is None:
                placement.refuse(
                    found,
                    {
                        "emitter": emitter,
                        "name": row.get("name"),
                        "playerId": None,
                        "nativeLabel": None,
                        "reason": found.failure,
                        "emitterUnpricedReason": row.get("reason"),
                    },
                )
                continue
            declined.setdefault(found.key, str(row.get("reason") or "unpriced"))
        # BDVM skips quarantined canonical rows before pricing and publishes
        # no unpriced entry for them (src/bdvm/service.py); say so.
        placed = {obs.player_key for obs in placement.observations}
        for key in index.quarantined:
            if key not in placed:
                declined.setdefault(key, "quarantined")
        meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else {}
        # The verdict compares a projection-driven value against the market.
        # The market leg's age is measurable; the projection snapshot has no
        # declared staleness budget, so the best this can honestly say is
        # "stale" (when the market leg is) or "unknown" — never "fresh".
        bdvm_freshness = {
            "state": "stale" if freshness.get("state") == "stale" else "unknown",
            "marketLeg": dict(freshness),
            "projectionLeg": "no_declared_budget",
            "basis": "worst_of_market_and_projection_legs",
        }
        notes = []
        if saw_unsignalled:
            notes.append("some BDVM rows carried no signal block and were not filed")
        run = rec.EmitterRun(
            emitter_id=emitter,
            state=rec.OBSERVED,
            as_of=str(meta.get("asOf")) if meta.get("asOf") else None,
            freshness=bdvm_freshness,
            observations=tuple(placement.observations),
            unplaced=dict(placement.unplaced),
            notes=tuple(notes),
            declined=declined,
        )
        return run, placement.unresolved

    return _guarded(emitter, _run)


def collect_consensus_edge(
    contract: Mapping[str, Any],
    index: IdentityIndex,
    *,
    freshness: Mapping[str, Any],
) -> tuple[rec.EmitterRun, list[dict[str, Any]]]:
    """Consensus Edge verdicts, including ``Withheld``.

    Gated on Consensus Edge's own flag: the feature's ship gate kept it
    off, and reading its board here while it is off would publish a
    verdict its owner refuses to serve.
    """
    emitter = "consensus_edge"
    from src.api import feature_flags  # noqa: PLC0415

    if not feature_flags.is_enabled("consensus_edge"):
        return rec.unobserved(emitter, "feature_disabled:consensus_edge"), []

    def _run():
        from src.consensus_edge import api as ce_api  # noqa: PLC0415

        board = ce_api.board_for_contract(dict(contract))
        if not isinstance(board, Mapping) or board.get("status") != "ok":
            status = board.get("status") if isinstance(board, Mapping) else None
            return rec.unobserved(emitter, f"status:{status}"), []
        placement = _Placement()
        for row in board.get("players") or []:
            if not isinstance(row, Mapping):
                continue
            placement.place(
                index,
                emitter_id=emitter,
                player_id=None,
                # CE's playerKey IS the contract's exact displayName
                # (fair_value._row_key); name matching is a labelled fallback.
                emitter_key=row.get("playerKey"),
                name=row.get("displayName"),
                position=row.get("position"),
                native_label=row.get("label"),
                reason=row.get("labelReason"),
                evidence={
                    "consensusEdgePlayerKey": row.get("playerKey"),
                    "score": row.get("score"),
                    "confidence": row.get("confidence"),
                    "quarantined": row.get("quarantined"),
                },
            )
        notes = ["experimental: Consensus Edge stamps every payload experimental"]
        sell_side = board.get("sellSideValidation")
        if isinstance(sell_side, Mapping) and not sell_side.get("validated"):
            notes.append("sell_side_unvalidated: see consensus_edge SELL_SIDE_VALIDATION")
        run = rec.EmitterRun(
            emitter_id=emitter,
            state=rec.OBSERVED,
            as_of=str(board.get("contractScrapedAt")) if board.get("contractScrapedAt") else None,
            freshness=dict(freshness),
            observations=tuple(placement.observations),
            unplaced=dict(placement.unplaced),
            notes=tuple(notes),
        )
        return run, placement.unresolved

    return _guarded(emitter, _run)


#: ``market_payload``'s own maximum ``limit``.
_SHARP_ASSET_LIMIT = 500


def collect_sharp(index: IdentityIndex) -> tuple[rec.EmitterRun, list[dict[str, Any]]]:
    """Sharp-cohort movement evidence.  The owner publishes no verdict."""
    emitter = "sharp_market"

    def _run():
        from src.sharp import market as sharp_market  # noqa: PLC0415

        payload = sharp_market.market_payload(asset_type="player", limit=_SHARP_ASSET_LIMIT)
        if payload.get("status") != "ok":
            return rec.unobserved(emitter, f"status:{payload.get('status')}"), []
        placement = _Placement()
        window = (payload.get("query") or {}).get("window")
        for row in payload.get("assets") or []:
            if not isinstance(row, Mapping):
                continue
            placement.place(
                index,
                emitter_id=emitter,
                player_id=row.get("assetId"),
                name=row.get("displayName"),
                position=row.get("position"),
                native_label=None,
                reason=None,
                evidence={
                    "window": window,
                    "buys": row.get("buys"),
                    "sells": row.get("sells"),
                    "net": row.get("net"),
                    "signalStrength": row.get("signalStrength"),
                    "confidence": row.get("confidence"),
                    "uniqueManagers": row.get("uniqueManagers"),
                    "lastMovementAt": _iso_from_ms(row.get("lastTs")),
                },
            )
        assets = [row for row in payload.get("assets") or [] if isinstance(row, Mapping)]
        # Below the limit the board listed every asset with movement, so an
        # absent player genuinely had none (silent).  AT the limit it was
        # truncated: anyone not listed was never evaluated (out_of_scope).
        truncated = len(assets) >= _SHARP_ASSET_LIMIT
        covered = frozenset(obs.player_key for obs in placement.observations) if truncated else None
        platforms = ((payload.get("coverage") or {}).get("platforms")) or {}
        updated = sorted(
            str(meta.get("lastUpdatedAt"))
            for meta in platforms.values()
            if isinstance(meta, Mapping) and meta.get("lastUpdatedAt")
        )
        run = rec.EmitterRun(
            emitter_id=emitter,
            state=rec.OBSERVED,
            as_of=updated[-1] if updated else None,
            freshness={"state": "unknown", "basis": "no_declared_budget_for_sharp_crawl"},
            observations=tuple(placement.observations),
            unplaced=dict(placement.unplaced),
            notes=(
                "owner default window and strength sort; at most "
                f"{_SHARP_ASSET_LIMIT} assets (truncated={truncated})",
            ),
            covered_keys=covered,
        )
        return run, placement.unresolved

    return _guarded(emitter, _run)


# ── Assembly ─────────────────────────────────────────────────────────────


def roster_keys(
    index: IdentityIndex, resolved_team: Mapping[str, Any]
) -> tuple[list[str], list[dict[str, Any]], str]:
    """The roster's asset keys, by roster PLAYER ID whenever the team has them.

    Both team producers (scraper and Sleeper overlay) publish ``playerIds``;
    display names are a labelled fallback for a team that carries none.  A
    rostered id the canonical board does not carry is reported, not dropped.
    """
    keys: list[str] = []
    unresolved: list[dict[str, Any]] = []
    ids = resolved_team.get("playerIds")
    if isinstance(ids, list) and ids:
        for pid in ids:
            key, failure = index.resolve(player_id=pid)
            if key is None:
                unresolved.append(
                    {
                        "emitter": None,
                        "playerId": str(pid),
                        "name": None,
                        "reason": "not_on_canonical_board",
                        "scope": "roster",
                    }
                )
            else:
                keys.append(key)
        return list(dict.fromkeys(keys)), unresolved, "player_id"
    for name in resolved_team.get("players") or []:
        key, failure = index.resolve(name=name)
        if key is None:
            unresolved.append({"emitter": None, "name": name, "reason": failure, "scope": "roster"})
        else:
            keys.append(key)
    return list(dict.fromkeys(keys)), unresolved, "name_fallback"


def build_reconciled_signals(
    contract: Mapping[str, Any],
    *,
    league_key: str,
    resolved_team: Mapping[str, Any] | None,
    news_items: list[dict[str, Any]] | None,
    scope: str = "auto",
    player: str | None = None,
    collectors: Sequence[str] | None = None,
    team_request: Mapping[str, Any] | None = None,
    team_source: str | None = None,
) -> dict[str, Any]:
    """Collect every live emitter through its owner and reconcile.

    ``scope``: ``roster`` (the resolved team's players), ``league`` (every
    player any emitter spoke about), or ``auto`` (roster when a team
    resolved, else league).  ``player`` narrows the result to one player,
    resolved through the same identity index.  ``collectors`` restricts
    which emitters are asked (tests); an emitter not asked is reported
    ``unobserved`` / ``not_run`` like any other missing emitter.
    """
    index = build_identity_index(contract)
    freshness = contract_market_freshness(contract)
    wanted = set(collectors) if collectors is not None else None

    def _want(emitter_id: str) -> bool:
        return wanted is None or emitter_id in wanted

    runs: list[rec.EmitterRun] = []
    unresolved: list[dict[str, Any]] = []
    plans = (
        (
            "terminal_signal",
            lambda: collect_terminal(
                contract,
                index,
                resolved_team=resolved_team,
                news_items=news_items,
                league_key=league_key,
                freshness=freshness,
            ),
        ),
        (
            "bdvm_market_signal",
            lambda: collect_bdvm(contract, index, league_key=league_key, freshness=freshness),
        ),
        (
            "consensus_edge",
            lambda: collect_consensus_edge(contract, index, freshness=freshness),
        ),
        ("sharp_market", lambda: collect_sharp(index)),
    )
    for emitter_id, plan in plans:
        if not _want(emitter_id):
            continue
        run, missed = plan()
        runs.append(run)
        unresolved.extend(missed)

    effective_scope = scope
    if scope == "auto":
        effective_scope = "roster" if resolved_team else "league"
    universe: list[str] | None = None
    roster_basis: str | None = None
    if effective_scope == "roster":
        if resolved_team:
            universe, roster_missed, roster_basis = roster_keys(index, resolved_team)
            unresolved.extend(roster_missed)
        else:
            universe = []

    player_filter: dict[str, Any] | None = None
    if player:
        # A Sleeper id is all digits; anything else is a NAME.  Passing the
        # query as both would make every name look like an off-board id.
        query = player.strip()
        if query.isdigit():
            key, failure = index.resolve(player_id=query)
        else:
            key, failure = index.resolve(name=query)
        player_filter = {"query": player, "playerKey": key, "reason": failure}
        if key is None:
            universe = []
        elif universe is None or key in universe:
            universe = [key]
        else:
            universe = []

    payload = rec.reconcile(
        runs,
        player_keys=universe,
        quarantined=index.quarantined,
        display_names=index.display_by_key,
        unresolved=unresolved,
    )
    payload.update(
        {
            "leagueKey": league_key,
            "scope": effective_scope,
            "team": (
                {
                    "ownerId": str(resolved_team.get("ownerId") or "") or None,
                    "name": resolved_team.get("name"),
                }
                if resolved_team
                else None
            ),
            "playerFilter": player_filter,
            # An explicit team that did not resolve is stated, never silently
            # turned into a league-wide answer.
            "teamResolution": {
                "requested": dict(team_request) if team_request else None,
                "resolved": bool(resolved_team),
                "source": team_source if resolved_team else None,
                "reason": "team_not_found" if team_request and not resolved_team else None,
            },
            "rosterPlacement": roster_basis,
            "contract": {
                "scrapeTimestamp": contract.get("scrapeTimestamp"),
                "generatedAt": contract.get("generatedAt"),
                "marketFreshness": freshness,
            },
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )
    return payload
