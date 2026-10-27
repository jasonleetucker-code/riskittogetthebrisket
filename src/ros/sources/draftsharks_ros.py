"""Draft Sharks ROS adapters — one board per source key.

Reads the REAL rest-of-season boards that
``scripts/fetch_draftsharks_ros.py`` acquires from
``/ros-rankings/superflex`` and ``/ros-rankings/idp`` behind the
authenticated Playwright session, and serves them as TWO source keys:

* ``draftSharksRosSf``  — :func:`scrape` — the superflex board, alone;
* ``draftSharksRosIdp`` — :func:`scrape_idp` (registered through
  ``src/ros/sources/draftsharks_ros_idp.py``) — the IDP-group rows of the
  idp board, minus any IDP player the superflex board already ranks.

ONE KEY, ONE RANK BASIS (2026-10-27).  The two boards used to be unioned
name-first under ``draftSharksRosSf``.  A rank only means something
relative to the population it was ranked within (``rank_to_score``
normalises by the row's own ``total_ranked``), and the two pages rank
different populations: the superflex page ranks every position it lists
together, the idp page ranks IDP players among themselves.  The union
therefore published two rank bases under one key:

* until 2026-09-16 the superflex board carried ~63 IDP players and the
  idp board supplied the other ~376 — the IDP group SPLIT across two
  bases inside one source, so six deeper IDPs out-scored the best IDP the
  superflex board ranked (measured on ``907dfee4d~1``);
* from ``907dfee4d`` (automated refresh, 2026-09-16T21:49Z) the vendor's
  superflex board lists no IDP players, so the whole IDP group moved,
  silently, onto the idp board's basis under the same superflex key.  The
  top LB's DraftSharks score went 30.3 -> 100.0 with no code change.

Serving the idp board under its own declared key is the existing pattern
for an IDP-only board in this aggregate (``fantasyProsRosIdp``), so
nothing is invented: no crosswalk, no renormalisation, no translated
rank.  Every row carries ``rankBasis`` (its board id) so
``src/ros/rank_basis.py`` can detect a mixed or shifting basis on any
source.

One vendor, one vote still holds ACROSS the two keys: the superflex board
is primary, and an IDP player it ranks is withheld from the idp key with
reason ``rank_basis_mismatch`` (counted in the scrape diagnostics) rather
than voting twice on two bases.

The dynasty Superflex + IDP CSVs remain a season-long PROXY fallback,
used per key only when that key's real ROS board is absent
(``sourceMode: "dynasty_proxy"`` in the diagnostics).  The superflex key
never promotes the idp file in its place — that would pay a superflex
format bonus for a different board.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ros.rank_basis import RANK_BASIS_MISMATCH
from src.ros.scrape import ScrapeResult
from src.utils.name_clean import POSITION_GROUP_IDP, canonical_position_group


REPO_ROOT = Path(__file__).resolve().parents[3]

# Real DraftSharks ROS data (written by scripts/fetch_draftsharks_ros.py
# via authenticated Playwright on /ros-rankings/superflex + /idp).
# When these CSVs exist they take precedence over the dynasty-page
# proxies registered below — this is the actual ROS-specific signal
# the adapter was designed for.
DS_ROS_SF_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksRosSf.csv"
DS_ROS_IDP_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksRosIdp.csv"

# Dynasty-page CSVs maintained by scripts/fetch_draftsharks.py — used
# as a fallback when the real ROS pages haven't been fetched yet
# (e.g. fresh checkout, ROS fetcher temporarily down).  These pages
# carry deeper coverage but mix in season-long valuation context.
DS_DYNASTY_SF_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksSf.csv"
DS_DYNASTY_IDP_CSV = REPO_ROOT / "CSVs" / "site_raw" / "draftSharksIdp.csv"

LOG = logging.getLogger("ros.adapter.draftsharks")

#: Board ids stamped on every row as ``rankBasis`` — one per acquisition,
#: because each acquisition ranks its own population.
BASIS_ROS_SF = "draftsharks:ros-superflex"
BASIS_ROS_IDP = "draftsharks:ros-idp"
BASIS_DYNASTY_SF_PROXY = "draftsharks:dynasty-superflex-proxy"
BASIS_DYNASTY_IDP_PROXY = "draftsharks:dynasty-idp-proxy"

#: Withheld-row reason: an idp-board IDP whose name the superflex board
#: lists in ANOTHER position group (see :func:`scrape_idp`).
NAME_COLLISION_WITH_SUPERFLEX = "name_collision_with_superflex_board"


def _read_ros_csv(path: Path, basis: str) -> list[dict[str, Any]]:
    """Read the real ROS-page CSV (written by fetch_draftsharks_ros.py).

    Schema is the orchestrator's standard format:
    ``canonicalName,sourceName,position,team,rank,total_ranked,projection``.
    """
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                name = (raw.get("sourceName") or "").strip()
                if not name:
                    continue
                position = (raw.get("position") or "").strip().upper().split("/")[0]
                team = (raw.get("team") or "").strip()
                try:
                    rank = int(raw.get("rank") or 0)
                except (TypeError, ValueError):
                    rank = 0
                if rank <= 0:
                    continue
                rows.append(
                    {
                        "sourceName": name,
                        "canonicalName": "",
                        "position": position,
                        "team": team,
                        "rank": rank,
                        "total_ranked": 0,  # patched below
                        "projection": (raw.get("projection") or "").strip(),
                        "rankBasis": basis,
                    }
                )
    except OSError as exc:
        LOG.warning("[ros] DS ROS read failed for %s: %s", path, exc)
        return []
    n = len(rows)
    for r in rows:
        r["total_ranked"] = n
    return rows


def _read_dynasty_proxy_csv(path: Path, basis: str) -> list[dict[str, Any]]:
    """Fallback reader: dynasty Superflex / IDP CSV used as a ROS proxy.

    Schema is the dynasty-page schema written by
    ``scripts/fetch_draftsharks.py`` (Player, Fantasy Position, etc.).
    """
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for i, raw in enumerate(reader, start=1):
                name = (raw.get("Player") or raw.get("name") or "").strip()
                if not name:
                    continue
                position = (
                    (raw.get("Fantasy Position") or raw.get("position") or "").strip().upper()
                )
                position = position.split("/")[0]
                team = (raw.get("Team") or raw.get("team") or "").strip()
                rank_field = raw.get("Rank") or raw.get("rank")
                try:
                    rank = int(rank_field) if rank_field else i
                except (TypeError, ValueError):
                    rank = i
                projection: str = ""
                proj_field = raw.get("3D Value +") or raw.get("projection")
                if proj_field:
                    try:
                        f_val = float(proj_field)
                        if f_val > 0:
                            projection = str(f_val)
                    except (TypeError, ValueError):
                        pass
                rows.append(
                    {
                        "sourceName": name,
                        "canonicalName": "",
                        "position": position,
                        "team": team,
                        "rank": rank,
                        "total_ranked": 0,
                        "projection": projection,
                        "rankBasis": basis,
                    }
                )
    except OSError as exc:
        LOG.warning("[ros] DS dynasty-proxy read failed for %s: %s", path, exc)
        return []
    n = len(rows)
    for r in rows:
        r["total_ranked"] = n
    return rows


def _name_key(row: dict[str, Any]) -> str:
    return (row.get("sourceName") or "").strip().lower()


def _superflex_board() -> tuple[list[dict[str, Any]], str]:
    """The board ``draftSharksRosSf`` serves, and its mode.

    The real ROS superflex board when it has rows, else the dynasty
    superflex proxy.  Shared by both keys so the idp key withholds against
    exactly the board the superflex key published.
    """
    rows = _read_ros_csv(DS_ROS_SF_CSV, BASIS_ROS_SF)
    if rows:
        return rows, "ros"
    return _read_dynasty_proxy_csv(DS_DYNASTY_SF_CSV, BASIS_DYNASTY_SF_PROXY), "dynasty_proxy"


def _failed(key: str, started: str, error: str, diagnostics: dict[str, Any]) -> ScrapeResult:
    return ScrapeResult(
        source_key=key,
        status="failed",
        error=error,
        started_at=started,
        completed_at=datetime.now(timezone.utc).isoformat(),
        diagnostics=diagnostics,
    )


def scrape(src_meta: dict[str, Any]) -> ScrapeResult:
    """``draftSharksRosSf`` — the superflex ROS board, and nothing else.

    Prefers the real ROS page output (``draftSharksRosSf.csv``) and falls
    back to the dynasty superflex proxy when it is absent.  The idp file is
    never merged in or promoted in its place: it is a different board with
    its own population, served under its own key by :func:`scrape_idp`.
    """
    started = datetime.now(timezone.utc).isoformat()
    key = str(src_meta.get("key") or "draftSharksRosSf")
    rows, source_mode = _superflex_board()
    if source_mode != "ros":
        LOG.warning(
            "[ros] DraftSharks: SF ROS board empty — serving the dynasty "
            "superflex proxy under %s; the idp board stays on its own key.",
            key,
        )
    LOG.info("[ros] DraftSharks SF: %d rows (mode=%s)", len(rows), source_mode)
    diagnostics: dict[str, Any] = {"sourceMode": source_mode}
    if not rows:
        return _failed(
            key,
            started,
            "DraftSharks superflex ROS board and dynasty proxy both missing or "
            "empty — scripts/fetch_draftsharks_ros.py / fetch_draftsharks.py "
            "must run first.  Source falls back to last-known-good if available.",
            diagnostics,
        )
    return ScrapeResult(
        source_key=key,
        status="ok",
        rows=rows,
        started_at=started,
        completed_at=datetime.now(timezone.utc).isoformat(),
        player_count=len(rows),
        diagnostics=diagnostics,
    )


def scrape_idp(src_meta: dict[str, Any]) -> ScrapeResult:
    """``draftSharksRosIdp`` — the idp board's IDP-group rows.

    * The real ROS idp board when present, else the dynasty IDP proxy.
    * Only rows whose position resolves to the IDP group are emitted
      (``canonical_position_group``).  They keep the board's own rank and
      ``total_ranked`` — nothing is renumbered, so the basis is the page's
      population exactly as published.  This matters when the vendor
      serves the idp URL as a full board (it has, as a 1QB board): its
      offense rows would otherwise give DraftSharks a second offense vote.
    * An IDP player the superflex board already ranks is withheld
      (``rank_basis_mismatch``): the superflex key carries DraftSharks'
      vote for him on its own basis, and a second vote on another basis
      would be both a double count and a basis mix.
    * An IDP whose NAME the superflex board lists in another group is
      withheld too (``name_collision_with_superflex_board``) — the
      aggregate keys players by canonical name alone.
    """
    started = datetime.now(timezone.utc).isoformat()
    key = str(src_meta.get("key") or "draftSharksRosIdp")
    board = _read_ros_csv(DS_ROS_IDP_CSV, BASIS_ROS_IDP)
    source_mode = "ros"
    if not board:
        board = _read_dynasty_proxy_csv(DS_DYNASTY_IDP_CSV, BASIS_DYNASTY_IDP_PROXY)
        source_mode = "dynasty_proxy"

    sf_rows, _sf_mode = _superflex_board()
    sf_groups: dict[str, set[str]] = {}
    for r in sf_rows:
        sf_groups.setdefault(_name_key(r), set()).add(canonical_position_group(r.get("position")))
    rows: list[dict[str, Any]] = []
    not_idp = 0
    withheld = 0
    collisions = 0
    for row in board:
        if canonical_position_group(row.get("position")) != POSITION_GROUP_IDP:
            not_idp += 1
            continue
        groups_on_sf = sf_groups.get(_name_key(row))
        if groups_on_sf:
            # Same name on the superflex board.  As an IDP there it is the
            # same player ranked on the other basis (rank_basis_mismatch).
            # In another group (the WR and the LB both named Justin
            # Jefferson) it is a name collision: the aggregate keys players
            # by canonical name alone, so emitting it would fold this IDP's
            # vote into the other player's row.  Withheld either way — the
            # behaviour of the retired name-first union, kept on purpose.
            if POSITION_GROUP_IDP in groups_on_sf:
                withheld += 1
            else:
                collisions += 1
            continue
        rows.append(row)
    if withheld:
        LOG.warning(
            "[ros] DraftSharks IDP: withheld %d IDP players the superflex board "
            "already ranks (%s) — one vendor vote per player, one rank basis "
            "per key.",
            withheld,
            RANK_BASIS_MISMATCH,
        )
    LOG.info(
        "[ros] DraftSharks IDP: %d rows (board=%d, non-IDP skipped=%d, withheld=%d, mode=%s)",
        len(rows),
        len(board),
        not_idp,
        withheld,
        source_mode,
    )
    diagnostics: dict[str, Any] = {
        "sourceMode": source_mode,
        "withheld": {
            RANK_BASIS_MISMATCH: withheld,
            NAME_COLLISION_WITH_SUPERFLEX: collisions,
            "not_idp_group": not_idp,
        },
    }
    if not rows:
        return _failed(
            key,
            started,
            "DraftSharks idp ROS board and dynasty IDP proxy yielded no IDP rows "
            "this key may serve.  Source falls back to last-known-good if available.",
            diagnostics,
        )
    return ScrapeResult(
        source_key=key,
        status="ok",
        rows=rows,
        started_at=started,
        completed_at=datetime.now(timezone.utc).isoformat(),
        player_count=len(rows),
        diagnostics=diagnostics,
    )
