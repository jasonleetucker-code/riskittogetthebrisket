"""Where draft-class lifecycle EVIDENCE comes from, and which leagues a
board-scoped verdict must consult (#1414).

The RULE lives in :mod:`src.identity.pick_lifecycle` and nowhere else.  This
module is plumbing only: it fetches Sleeper state OFF the request path,
persists it, reads it back, and enumerates the leagues a scoring-scoped
board may be served to.  It decides nothing itself.

Evidence sources, in the order a consumer sees them
===================================================

1. **The scrape's own sleeper block** — ``sleeper.draftClassEvidence``,
   written by ``Dynasty Scraper.py`` from the drafts / picks / rosters it
   already fetches for its league.  It travels inside the raw payload, so a
   board rebuilt from the export archive re-derives the same verdict.
2. **Per-league snapshots** — ``data/leagues/draft_classes_<sleeperLeagueId>.json``
   (same directory and override env as the scoring cards), written by the
   post-scrape warm pass for every active league
   (:func:`refresh_draft_class_snapshot`).  This is how a league the scrape
   did not run for contributes evidence, and how per-league consumers (the
   Sleeper overlay's pick ownership, the draft-capital fallback) read their
   league's verdict without a request-time fetch.

Nothing here fetches inside a request.  Absent evidence is ``unknown`` in the
owner, which keeps a class active.

Which leagues a board verdict consults
======================================

The board is scoring-scoped; a league may be served it only when its scoring
is PROVEN identical (W18-F001).  For retirement the question is inverted and
answered fail-closed: every active league is consulted UNLESS its stored
scoring card proves a DIFFERENT fingerprint from the board's own.  A league
with no card, or a card of any age that matches, is consulted — so a league
whose evidence is missing keeps the class active rather than being quietly
left out of the vote.  Card age is deliberately ignored here: a stale card
can only widen the consulted set, never shrink it below the truth.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from src.identity.pick_lifecycle import (
    ClassLifecycle,
    LeagueDraftEvidence,
    board_class_lifecycle,
    evidence_from_sleeper,
    league_class_lifecycles,
    retired_seasons,
)

log = logging.getLogger(__name__)

SLEEPER_API = "https://api.sleeper.app/v1"
SNAPSHOT_PREFIX = "draft_classes_"
#: The contract key the scraper writes into its ``sleeper`` block.
SLEEPER_BLOCK_FIELD = "draftClassEvidence"

Fetch = Callable[[str], Any]


def _default_fetch(url: str) -> Any:
    from src.api.sleeper_overlay import _http_get_json  # noqa: PLC0415

    return _http_get_json(url)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Collection (off the request path) ─────────────────────────────────


def collect_league_draft_evidence(
    sleeper_league_id: str,
    *,
    league_key: str | None,
    fetch: Fetch | None = None,
    rosters: list[Any] | None = None,
    league_info: Mapping[str, Any] | None = None,
) -> LeagueDraftEvidence | None:
    """Fetch one league's draft state and assemble it through the owner.

    Reads the league's ``/drafts`` plus ONE hop of ``previous_league_id``
    (Sleeper chains a dynasty league year to year under new ids, so last
    season's rookie draft lives on the previous league), the picks of every
    COMPLETE draft, and the league's current rosters.  ``rosters`` /
    ``league_info`` may be passed by a caller that already holds them.

    Returns ``None`` only when the league's own ``/drafts`` list cannot be
    read — then nothing can be proven.  Every partial failure after that is
    recorded as UNOBSERVED inside the evidence, never as zero.
    """
    lid = str(sleeper_league_id or "").strip()
    if not lid:
        return None
    get = fetch or _default_fetch
    drafts = get(f"{SLEEPER_API}/league/{lid}/drafts")
    if not isinstance(drafts, list):
        return None
    all_drafts: list[Any] = list(drafts)
    lists_observed = [lid]

    info = league_info if isinstance(league_info, Mapping) else get(f"{SLEEPER_API}/league/{lid}")
    prev = (
        str((info or {}).get("previous_league_id") or "").strip()
        if isinstance(info, Mapping)
        else ""
    )
    if prev and prev != "0" and prev != lid:
        prev_drafts = get(f"{SLEEPER_API}/league/{prev}/drafts")
        if isinstance(prev_drafts, list):
            all_drafts.extend(prev_drafts)
            lists_observed.append(prev)

    picks_by_draft: dict[str, Any] = {}
    for d in all_drafts:
        if not isinstance(d, Mapping):
            continue
        draft_id = str(d.get("draft_id") or "").strip()
        if not draft_id or str(d.get("status") or "").strip().lower() != "complete":
            continue
        picks = get(f"{SLEEPER_API}/draft/{draft_id}/picks")
        picks_by_draft[draft_id] = picks if isinstance(picks, list) else None

    roster_rows = (
        rosters if isinstance(rosters, list) else get(f"{SLEEPER_API}/league/{lid}/rosters")
    )
    rostered: list[str] | None = None
    if isinstance(roster_rows, list):
        rostered = []
        for r in roster_rows:
            if isinstance(r, Mapping):
                # ``players`` already includes taxi and reserve on Sleeper.
                rostered.extend(str(p) for p in (r.get("players") or []) if p)

    return evidence_from_sleeper(
        league_key=league_key,
        sleeper_league_id=lid,
        drafts=all_drafts,
        picks_by_draft_id=picks_by_draft,
        rostered_player_ids=rostered,
        observed_at=_now_iso(),
        draft_lists_observed=lists_observed,
    )


# ── Snapshot persistence ──────────────────────────────────────────────


def snapshot_path(sleeper_league_id: str) -> Path:
    from src.api.league_registry import scoring_snapshot_dir  # noqa: PLC0415

    return scoring_snapshot_dir() / f"{SNAPSHOT_PREFIX}{str(sleeper_league_id).strip()}.json"


def write_snapshot(evidence: LeagueDraftEvidence) -> Path | None:
    if not evidence.sleeper_league_id:
        return None
    path = snapshot_path(evidence.sleeper_league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(evidence.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def read_snapshot(sleeper_league_id: str | None) -> LeagueDraftEvidence | None:
    """The stored evidence, or ``None``.  Never raises, never fetches."""
    lid = str(sleeper_league_id or "").strip()
    if not lid:
        return None
    try:
        raw = json.loads(snapshot_path(lid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ev = LeagueDraftEvidence.from_dict(raw)
    if ev is None or ev.sleeper_league_id != lid:
        return None
    return ev


def refresh_draft_class_snapshot(cfg: Any, fetch: Fetch | None = None) -> bool:
    """Warm-pass entry point.  A failure leaves the previous snapshot alone."""
    lid = str(getattr(cfg, "sleeper_league_id", "") or "").strip()
    if not lid:
        return False
    try:
        ev = collect_league_draft_evidence(lid, league_key=getattr(cfg, "key", None), fetch=fetch)
        if ev is None:
            return False
        write_snapshot(ev)
        return True
    except Exception as exc:  # noqa: BLE001 — never break the warm pass
        log.warning(
            "draft_class_evidence: refresh failed for %s: %s", getattr(cfg, "key", lid), exc
        )
        return False


# ── Consumers ─────────────────────────────────────────────────────────


def league_lifecycles_for_sleeper_id(
    sleeper_league_id: str | None, seasons: Iterable[int]
) -> dict[int, ClassLifecycle]:
    """A league-scoped surface's verdicts, from that league's snapshot."""
    return league_class_lifecycles(seasons, read_snapshot(sleeper_league_id))


def active_seasons_for_league(sleeper_league_id: str | None, seasons: Iterable[int]) -> list[int]:
    """``seasons`` minus the ones THIS league has retired, order kept."""
    seasons = [int(s) for s in seasons]
    retired = retired_seasons(league_lifecycles_for_sleeper_id(sleeper_league_id, seasons))
    return [s for s in seasons if s not in retired]


def served_league_evidence(
    sleeper_block: Mapping[str, Any] | None,
) -> dict[str, LeagueDraftEvidence | None]:
    """Every league a board built from ``sleeper_block`` may be served to,
    with its evidence (``None`` = none).  See the module docstring.
    """
    block = sleeper_block if isinstance(sleeper_block, Mapping) else {}
    board_lid = str(block.get("leagueId") or "").strip()
    try:
        from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

        scoring = block.get("scoringSettings")
        board_fp = scoring_fingerprint(scoring if isinstance(scoring, dict) else None)
    except Exception:  # noqa: BLE001 — unprovable scoring widens the vote
        board_fp = None

    out: dict[str, LeagueDraftEvidence | None] = {}
    try:
        from src.api import league_registry  # noqa: PLC0415

        if board_lid:
            key = league_registry.league_key_for_sleeper_id(board_lid) or f"sleeper:{board_lid}"
            payload_ev = LeagueDraftEvidence.from_dict(block.get(SLEEPER_BLOCK_FIELD))
            if payload_ev is not None and payload_ev.sleeper_league_id == board_lid:
                out[key] = payload_ev
            else:
                out[key] = read_snapshot(board_lid)
        for cfg in league_registry.active_leagues():
            lid = str(cfg.sleeper_league_id or "").strip()
            if not lid or lid == board_lid:
                continue
            if board_fp:
                card = league_registry.scoring_settings_for_league(cfg)
                fp = scoring_fingerprint(card) if card else None
                if fp and fp != board_fp:
                    continue  # PROVEN to score differently — never served this board
            out[cfg.key] = read_snapshot(lid)
    except Exception as exc:  # noqa: BLE001 — cannot enumerate ⇒ cannot retire
        log.warning("draft_class_evidence: served-league enumeration failed: %s", exc)
        out["registry:unavailable"] = None
    return out


def board_pick_class_lifecycle(
    sleeper_block: Mapping[str, Any] | None, seasons: Iterable[int]
) -> tuple[dict[int, ClassLifecycle], dict[str, dict[int, ClassLifecycle]]]:
    """``(board verdict per season, per-league verdicts)`` for a board."""
    seasons = sorted({int(s) for s in seasons})
    per_league = {
        key: league_class_lifecycles(seasons, ev)
        for key, ev in served_league_evidence(sleeper_block).items()
    }
    board = {
        s: board_class_lifecycle(s, {k: lcs.get(s) for k, lcs in per_league.items()})
        for s in seasons
    }
    return board, per_league
