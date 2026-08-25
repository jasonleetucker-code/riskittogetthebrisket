"""Draft Sharks ROS adapter.

Reads the REAL rest-of-season boards that
``scripts/fetch_draftsharks_ros.py`` acquires from
``/ros-rankings/superflex`` and ``/ros-rankings/idp`` behind the
authenticated Playwright session.  ``source_mode`` reports ``"ros"``
when it served those.

The dynasty Superflex + IDP CSVs remain a season-long PROXY fallback,
used only when the real SF board is absent (fresh checkout, ROS page
outage, an acquisition the fetcher refused).  ``source_mode`` reports
``"dynasty_proxy"`` then, so "we served ROS" and "we served a
stand-in" are distinguishable downstream rather than both reading as a
DraftSharks ROS opinion.

The staged "PR 1 proxy / PR 2 swap" plan this docstring used to
describe is COMPLETE; the swap landed and ``_load_existing_csvs`` is
gone.  Registry weight and aggregator behaviour are unchanged by that
history and are not this module's business.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.ros.scrape import ScrapeResult


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


def _read_ros_csv(path: Path) -> list[dict[str, Any]]:
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
                    }
                )
    except OSError as exc:
        LOG.warning("[ros] DS ROS read failed for %s: %s", path, exc)
        return []
    n = len(rows)
    for r in rows:
        r["total_ranked"] = n
    return rows


def _read_dynasty_proxy_csv(path: Path) -> list[dict[str, Any]]:
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
                    }
                )
    except OSError as exc:
        LOG.warning("[ros] DS dynasty-proxy read failed for %s: %s", path, exc)
        return []
    n = len(rows)
    for r in rows:
        r["total_ranked"] = n
    return rows


def _union_primary_first(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Merge two boards under ONE source key without double-counting.

    The primary board wins outright; a secondary row is merged only when
    its name is ABSENT from the primary.  That is the whole invariant:
    ``src/ros/aggregate.py`` adds the source's full weight per ROW with no
    ``(source_key, player)`` guard, so one vendor listing a player on two
    of its own boards counts that vendor's opinion twice.

    Merging only unseen names is also what makes the two boards' separate
    rank scales safe.  Each row carries its own ``total_ranked`` and
    ``rank_to_score`` normalizes against it, which is correct for
    genuinely disjoint boards (the dynasty proxies: 453 offense-only rows
    and 411 IDP-only, one name in common) and would be wrong only for
    overlapping ones — which is exactly the case this excludes.

    Returns ``(rows, merged_from_secondary)``.
    """
    seen = {(r.get("sourceName") or "").strip().lower() for r in primary}
    rows = list(primary)
    merged = 0
    for row in secondary:
        name = (row.get("sourceName") or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        rows.append(row)
        merged += 1
    return rows, merged


def scrape(src_meta: dict[str, Any]) -> ScrapeResult:
    """Read DraftSharks ROS data.

    Prefers the real ROS-page output (``draftSharksRosSf.csv`` /
    ``draftSharksRosIdp.csv``) when present — those carry the actual
    rest-of-season expert ranks scraped from
    ``draftsharks.com/ros-rankings/...`` via the authenticated
    Playwright fetcher.

    Falls back to the dynasty Superflex + IDP CSVs as a season-long
    proxy when the ROS fetcher hasn't run yet (fresh checkout, ROS
    page outage, etc.).

    The two files are UNIONED name-first, not concatenated.

    WHY the union (audit 2026-07-30, still valid): concatenating the two
    boards handed DraftSharks 67.4% of the blend instead of 50.8%,
    inflated ``sourceCount`` / ``confidence`` on 939 of 1084 players, and
    systematically suppressed QB/LB in a superflex IDP league.  Any
    player listed on both pages must count once.

    WHAT THE UNION CONTRIBUTES IS NOT FIXED, and this docstring used to
    say it was.  The 2026-07-30 measurement found the two pages covering
    an identical universe, so the union added nothing, and that
    observation was written down as though it were a property.  It is
    not: re-measured 2026-08-25 (V1-89) the vendor had reshaped both
    pages — the idp page was genuinely IDP-restricted, the SF board was
    a few hundred rows, and the union added several hundred IDP players
    the SF page did not list.

    The invariants that hold regardless:

    * each file carries its OWN ``total_ranked``, and ``rank_to_score``
      normalises against that per row.  Two boards of different sizes
      therefore union safely with no renormalisation;
    * the SF board is primary — it is the one this source key claims to
      be (``is_superflex``) — and the idp page can only ADD names, never
      displace an SF rank;
    * the overlap between the pages, and hence the size of the
      contribution, is measured when it matters and never assumed.
    """
    started = datetime.now(timezone.utc).isoformat()
    key = str(src_meta.get("key") or "draftSharksRosSf")

    # Prefer real ROS data when the SF board is populated.
    #
    # The SF board is the one this source key claims to be
    # (``is_superflex: True``, +10% format-match bonus in
    # ``src/ros/aggregate.py``).  When it is missing we do NOT promote
    # the idp file in its place — that file is a 1QB board, and serving
    # it under a superflex key would pay a format-match bonus for a
    # format mismatch.  Fall through to the dynasty proxies instead,
    # which are genuinely superflex + genuinely disjoint (453
    # offense-only rows vs 411 IDP-only, one name in common).
    sf_rows = _read_ros_csv(DS_ROS_SF_CSV)
    idp_rows = _read_ros_csv(DS_ROS_IDP_CSV)
    source_mode = "ros"
    if not sf_rows:
        if idp_rows:
            LOG.warning(
                "[ros] DraftSharks: SF ROS board empty but IDP board has "
                "%d rows — declining to serve a 1QB board under a "
                "superflex key; falling back to the dynasty proxies.",
                len(idp_rows),
            )
        sf_rows = _read_dynasty_proxy_csv(DS_DYNASTY_SF_CSV)
        idp_rows = _read_dynasty_proxy_csv(DS_DYNASTY_IDP_CSV)
        source_mode = "dynasty_proxy"

    rows, merged = _union_primary_first(sf_rows, idp_rows)
    LOG.info(
        "[ros] DraftSharks: %d rows (sf=%d, idp=%d -> merged=%d new, mode=%s)",
        len(rows),
        len(sf_rows),
        len(idp_rows),
        merged,
        source_mode,
    )

    completed = datetime.now(timezone.utc).isoformat()
    if not rows:
        return ScrapeResult(
            source_key=key,
            status="failed",
            error=(
                "DraftSharks proxy CSVs missing or empty — "
                "scripts/fetch_draftsharks.py must run first.  "
                "Source will fall back to last-known-good if available."
            ),
            started_at=started,
            completed_at=completed,
        )

    return ScrapeResult(
        source_key=key,
        status="ok",
        rows=rows,
        started_at=started,
        completed_at=completed,
        player_count=len(rows),
    )
