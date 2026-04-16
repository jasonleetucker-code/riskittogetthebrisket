#!/usr/bin/env python3
"""Fetch FantasyPros Dynasty IDP rankings and write a source CSV.

FantasyPros publishes its dynasty rankings inline in the page HTML as a
JavaScript constant::

    var ecrData = { ..., "players": [...], ... };

No JS execution, no auth, and no paywall bypass are needed — a plain
``requests.get`` with a browser UA returns the full payload in the
static HTML.  This script extracts the ``players`` array from four
separate FantasyPros dynasty pages:

    * https://www.fantasypros.com/nfl/rankings/dynasty-idp.php  (combined)
    * https://www.fantasypros.com/nfl/rankings/dynasty-dl.php   (DL family)
    * https://www.fantasypros.com/nfl/rankings/dynasty-lb.php   (LB family)
    * https://www.fantasypros.com/nfl/rankings/dynasty-db.php   (DB family)

Core model
----------

**Combined IDP page is authoritative for cross-position overall ordering.**
**Individual DL/LB/DB pages are used only as depth extension** — to
reach players who don't appear on the combined page.

For every FantasyPros-known IDP, we derive an *effective overall rank*
via this algorithm:

1. **Direct authority.** If the player appears on the combined board,
   ``effective_rank = combined_rank`` unconditionally.  The individual
   page never overrides.
2. **Depth extension.** If the player is NOT on the combined board but
   IS on an individual board, ``effective_rank = g_pos(ind_rank)``
   where ``g_pos`` is a monotone piecewise-linear interpolation
   mapping per-page rank -> combined overall rank, fit from the
   overlap between the combined board and that individual page.
3. **Extrapolation.** Past the last anchor, ``g_pos`` extrapolates
   using the median slope of the last 3-5 anchor segments, capped at
   a sane maximum (600) and enforced strictly monotone.
4. **Canonical family.** Family is ``DL``/``LB``/``DB`` from the
   combined board when present, else from the individual board.

After computing the effective rank, we convert it to an internal value
via the exact Hill curve every other source uses::

    value = round(1 + 9998 / (1 + ((eff_rank - 1) / 45) ** 1.10))

This is the SAME formula used in
:mod:`src.canonical.player_valuation`; do not introduce a new scale.

Output CSV
----------

Written to ``CSVs/site_raw/fantasyProsIdp.csv`` with columns:

    name, originalRank, effectiveRank, derivationMethod, family,
    normalizedValue, matchedSourceName, position, team

Read by ``_enrich_from_source_csvs`` in ``src/api/data_contract.py``
as a rank-signal source; ``effectiveRank`` drives the downstream blend.

Run::

    python3 scripts/fetch_fantasypros_idp.py [--mirror-data-dir] [--dry-run]

Exit codes:
    0  - success, CSV written
    1  - soft failure (fetch / parse error, or zero rows extracted)
    2  - schema / shape regression:
         * ecrData missing the ``players`` key, or
         * combined-board row count below :data:`_FP_COMBINED_ROW_FLOOR`, or
         * any individual board row count below
           :data:`_FP_INDIVIDUAL_ROW_FLOOR`
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    print("[fetch_fantasypros_idp] requests is not installed", file=sys.stderr)
    sys.exit(1)


FP_URLS = {
    "combined": "https://www.fantasypros.com/nfl/rankings/dynasty-idp.php",
    "DL": "https://www.fantasypros.com/nfl/rankings/dynasty-dl.php",
    "LB": "https://www.fantasypros.com/nfl/rankings/dynasty-lb.php",
    "DB": "https://www.fantasypros.com/nfl/rankings/dynasty-db.php",
}
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = REPO_ROOT / "CSVs" / "site_raw" / "fantasyProsIdp.csv"
DATA_DIR_DST = REPO_ROOT / "data" / "exports" / "latest" / "site_raw" / "fantasyProsIdp.csv"

# Minimum row counts.  The dynasty IDP boards are small — combined
# currently carries ~70 players (38 LB, 22 S, 8 DE, 2 CB) and the
# individual DL/LB/DB boards each carry 30-45.  Floors set at ~70% of
# live baseline so a scrape regression trips exit 2 rather than
# silently publishing a degraded CSV.
_FP_COMBINED_ROW_FLOOR: int = 50
_FP_INDIVIDUAL_ROW_FLOOR: int = 25

# Safety cap for extrapolation past the last anchor — never emit an
# effective rank deeper than this, regardless of the individual page
# depth.  Keeps runaway curves from poisoning the downstream blend.
_EXTRAPOLATION_CAP: int = 600

# Number of trailing anchor segments to average for extrapolation
# slope.  Small values track the tail more tightly; larger values
# smooth out a noisy curve.  5 matches the idp_backbone ladder tail.
_EXTRAPOLATION_SEGMENT_WINDOW: int = 5


class FantasyProsSchemaError(RuntimeError):
    """Raised when ecrData is missing the expected structure."""


# ── Family mapping ──────────────────────────────────────────────────────
# FantasyPros pages use per-position families but the combined IDP board
# uses ``player_position_id`` in {DE, DT, LB, S, CB}.  We collapse these
# to the three families the internal pipeline uses: DL / LB / DB.
_FP_POS_TO_FAMILY: dict[str, str] = {
    "DE": "DL",
    "DT": "DL",
    "DL": "DL",
    "EDGE": "DL",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "S": "DB",
    "SS": "DB",
    "FS": "DB",
    "CB": "DB",
    "DB": "DB",
}


def _fp_pos_to_family(pos_id: str) -> str:
    return _FP_POS_TO_FAMILY.get((pos_id or "").strip().upper(), "")


# ── Hill curve value formula ────────────────────────────────────────────
def _hill_curve_value(rank: float) -> int:
    """Return the 1-9999 Hill curve value for an effective overall rank.

    Uses the SAME formula every other source in the pipeline uses.  Do
    not introduce a new scale — the blend weights are calibrated to
    this exact shape (midpoint 45, slope 1.10).
    """
    if rank <= 0:
        return 9999
    value = round(1 + 9998 / (1 + ((rank - 1) / 45.0) ** 1.10))
    return max(1, min(9999, int(value)))


# ── HTML fetch / ecrData extraction ─────────────────────────────────────
def _fetch_html(url: str, *, timeout: int = 30) -> str:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _extract_ecr_data(html: str) -> dict[str, Any]:
    """Walk ``ecrData = {...}`` out of FantasyPros page HTML.

    Uses a balanced-brace walk because the payload is a multi-KB JS
    object literal with nested ``players`` array; a lazy regex can't
    find the closing brace reliably.
    """
    marker = re.search(r"ecrData\s*=\s*(\{)", html)
    if not marker:
        raise FantasyProsSchemaError("ecrData marker not found in page HTML")
    start = marker.start(1)
    depth = 0
    end = None
    for i in range(start, len(html)):
        ch = html[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise FantasyProsSchemaError("ecrData payload had unbalanced braces")
    payload = html[start:end]
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise FantasyProsSchemaError(
            f"ecrData expected dict, got {type(parsed).__name__}"
        )
    if "players" not in parsed or not isinstance(parsed["players"], list):
        raise FantasyProsSchemaError(
            "ecrData shape changed: missing 'players' list "
            f"(available keys: {sorted(parsed.keys())[:10]})"
        )
    return parsed


def _parse_players(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract (rank, name, pos_id, team) from an ecrData payload."""
    out: list[dict[str, Any]] = []
    for entry in data["players"]:
        name = str(entry.get("player_name") or "").strip()
        if not name:
            continue
        rank = entry.get("rank_ecr")
        if rank is None:
            continue
        try:
            rank_int = int(rank)
        except (TypeError, ValueError):
            continue
        pos_id = str(entry.get("player_position_id") or "").strip().upper()
        pos_rank = str(entry.get("pos_rank") or "").strip()
        team = str(entry.get("player_team_id") or "").strip()
        out.append(
            {
                "rank": rank_int,
                "name": name,
                "pos_id": pos_id,
                "pos_rank": pos_rank,
                "team": team,
            }
        )
    # Defensive sort; FP returns sorted but don't rely on it.
    out.sort(key=lambda r: r["rank"])
    return out


# ── Anchor curve construction ───────────────────────────────────────────
def _build_anchor_curve(
    individual_rows: list[dict[str, Any]],
    combined_by_name: dict[str, dict[str, Any]],
) -> list[tuple[int, int]]:
    """Fit a monotone anchor curve from page-rank -> combined-rank.

    Iterates the individual page rows in page-rank order.  For each
    player who also appears on the combined board, emits an anchor
    ``(individual_rank, combined_rank)``.  Enforces strict
    monotonicity by dropping any later anchor whose combined rank is
    <= the last accepted anchor's combined rank — the combined
    ordering is authoritative, so a non-monotone anchor means the
    individual page ordering disagrees with the combined page and we
    side with combined.
    """
    anchors: list[tuple[int, int]] = []
    for row in individual_rows:
        combined = combined_by_name.get(row["name"])
        if not combined:
            continue
        ind_rank = int(row["rank"])
        comb_rank = int(combined["rank"])
        if anchors and comb_rank <= anchors[-1][1]:
            # Non-monotone — skip.  The earlier anchor has lower
            # individual rank AND lower-or-equal combined rank, so
            # this one would invert the curve.
            continue
        if anchors and ind_rank <= anchors[-1][0]:
            # Also drop duplicates / non-monotone on the x-axis.
            continue
        anchors.append((ind_rank, comb_rank))
    return anchors


def _interpolate(r: float, anchors: list[tuple[int, int]]) -> float:
    """Monotone piecewise-linear interpolation.

    Given a strictly increasing list of ``(x, y)`` anchors and a
    query ``r`` on the x-axis, return the interpolated ``y`` using::

        g(r) = y_i + (r - x_i) * ((y_{i+1} - y_i) / (x_{i+1} - x_i))

    When ``r`` is deeper than the last anchor, extrapolate using the
    median slope of the last ``_EXTRAPOLATION_SEGMENT_WINDOW``
    anchor segments, enforce strict monotonicity, and cap at
    ``_EXTRAPOLATION_CAP``.
    """
    if not anchors:
        # Degenerate fallback — no overlap observed.  Return r as-is
        # so the caller still gets a monotone, positive output.
        return float(r)
    first_x, first_y = anchors[0]
    if r <= first_x:
        # Below the first anchor — pin to first anchor's y.  The
        # individual page and combined page agree on rank ordering
        # before the first overlap point, so the first anchor's y is
        # the safest floor.
        return float(first_y)
    # Walk anchors until we find the segment containing r
    for i in range(len(anchors) - 1):
        x_i, y_i = anchors[i]
        x_j, y_j = anchors[i + 1]
        if x_i <= r <= x_j:
            if x_j == x_i:
                return float(y_j)
            return y_i + (r - x_i) * ((y_j - y_i) / (x_j - x_i))
    # Past the last anchor — extrapolate.
    last_x, last_y = anchors[-1]
    if len(anchors) >= 2:
        # Compute every segment slope, take the median of the last
        # ``_EXTRAPOLATION_SEGMENT_WINDOW`` (or fewer if we don't
        # have that many segments yet).
        all_slopes = [
            (anchors[k + 1][1] - anchors[k][1])
            / max(1, (anchors[k + 1][0] - anchors[k][0]))
            for k in range(len(anchors) - 1)
        ]
        tail = all_slopes[-_EXTRAPOLATION_SEGMENT_WINDOW:]
        tail_sorted = sorted(tail)
        median_slope = tail_sorted[len(tail_sorted) // 2]
    else:
        median_slope = 1.0
    # Enforce minimum slope of 1.0 so extrapolated ranks never
    # stagnate — each additional individual rank must push the
    # overall rank forward at least one step.
    if median_slope < 1.0:
        median_slope = 1.0
    extrap = last_y + (r - last_x) * median_slope
    # Cap.
    if extrap > _EXTRAPOLATION_CAP:
        extrap = float(_EXTRAPOLATION_CAP)
    # Strict monotonicity vs last anchor.
    if extrap <= last_y:
        extrap = float(last_y + 1)
    return extrap


# ── Build final rows ────────────────────────────────────────────────────
def _build_rows(
    combined_rows: list[dict[str, Any]],
    family_rows: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, list[tuple[int, int]]]]:
    """Assemble the final CSV rows + diagnostic anchor curves.

    Returns ``(rows, anchors_by_family)``.  Rows are sorted by
    ``effectiveRank`` ascending.
    """
    combined_by_name = {r["name"]: r for r in combined_rows}

    # Anchor curves per family.
    anchors_by_family: dict[str, list[tuple[int, int]]] = {}
    for fam, rows in family_rows.items():
        anchors_by_family[fam] = _build_anchor_curve(rows, combined_by_name)

    out: list[dict[str, Any]] = []

    # 1. Direct combined rows.
    for row in combined_rows:
        family = _fp_pos_to_family(row["pos_id"])
        eff = int(row["rank"])
        out.append(
            {
                "name": row["name"],
                "originalRank": int(row["rank"]),
                "effectiveRank": eff,
                "derivationMethod": "direct_combined",
                "family": family,
                "normalizedValue": _hill_curve_value(eff),
                "matchedSourceName": row["name"],
                "position": row["pos_id"],
                "team": row["team"],
            }
        )

    # 2. Depth-extension rows from individual pages.
    for fam, rows in family_rows.items():
        anchors = anchors_by_family.get(fam) or []
        for row in rows:
            if row["name"] in combined_by_name:
                # Already emitted via combined — combined wins for
                # BOTH rank and family.  Do not overwrite.
                continue
            eff_float = _interpolate(float(row["rank"]), anchors)
            eff = int(round(eff_float))
            if eff < 1:
                eff = 1
            if eff > _EXTRAPOLATION_CAP:
                eff = _EXTRAPOLATION_CAP
            out.append(
                {
                    "name": row["name"],
                    "originalRank": int(row["rank"]),
                    "effectiveRank": eff,
                    "derivationMethod": "anchored_from_individual",
                    "family": fam,
                    "normalizedValue": _hill_curve_value(eff),
                    "matchedSourceName": row["name"],
                    "position": row["pos_id"],
                    "team": row["team"],
                }
            )

    out.sort(key=lambda r: (r["effectiveRank"], r["name"]))
    return out, anchors_by_family


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "name",
        "originalRank",
        "effectiveRank",
        "derivationMethod",
        "family",
        "normalizedValue",
        "matchedSourceName",
        "position",
        "team",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ── CLI entry ───────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DST,
        help="CSV path to write (default: CSVs/site_raw/fantasyProsIdp.csv).",
    )
    parser.add_argument(
        "--mirror-data-dir",
        action="store_true",
        help="Also mirror to data/exports/latest/site_raw/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print row counts and a sample without writing the CSV.",
    )
    parser.add_argument(
        "--from-dir",
        type=Path,
        default=None,
        help=(
            "Read HTML from a directory containing combined.html / dl.html / "
            "lb.html / db.html (for dev / tests)."
        ),
    )
    args = parser.parse_args(argv)

    # Fetch + parse all 4 pages.
    html_by_key: dict[str, str] = {}
    for key, url in FP_URLS.items():
        try:
            if args.from_dir is not None:
                fname_key = "combined" if key == "combined" else key.lower()
                html_path = args.from_dir / f"{fname_key}.html"
                html_by_key[key] = html_path.read_text(encoding="utf-8")
            else:
                html_by_key[key] = _fetch_html(url)
        except Exception as exc:
            print(
                f"[fetch_fantasypros_idp] fetch failed ({key}): {exc}",
                file=sys.stderr,
            )
            return 1

    try:
        combined_data = _extract_ecr_data(html_by_key["combined"])
        dl_data = _extract_ecr_data(html_by_key["DL"])
        lb_data = _extract_ecr_data(html_by_key["LB"])
        db_data = _extract_ecr_data(html_by_key["DB"])
    except FantasyProsSchemaError as exc:
        print(f"[fetch_fantasypros_idp] schema regression: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[fetch_fantasypros_idp] parse failed: {exc}", file=sys.stderr)
        return 1

    combined_rows = _parse_players(combined_data)
    family_rows = {
        "DL": _parse_players(dl_data),
        "LB": _parse_players(lb_data),
        "DB": _parse_players(db_data),
    }

    # Schema probes.
    if len(combined_rows) < _FP_COMBINED_ROW_FLOOR:
        print(
            "[fetch_fantasypros_idp] combined row count below floor: "
            f"{len(combined_rows)} < {_FP_COMBINED_ROW_FLOOR}",
            file=sys.stderr,
        )
        return 2
    for fam, rows in family_rows.items():
        if len(rows) < _FP_INDIVIDUAL_ROW_FLOOR:
            print(
                f"[fetch_fantasypros_idp] {fam} row count below floor: "
                f"{len(rows)} < {_FP_INDIVIDUAL_ROW_FLOOR}",
                file=sys.stderr,
            )
            return 2

    # Build final rows + diagnostic anchors.
    rows, anchors_by_family = _build_rows(combined_rows, family_rows)
    if not rows:
        print("[fetch_fantasypros_idp] no rows extracted", file=sys.stderr)
        return 1

    # Per-family diagnostics.
    print(
        f"[fetch_fantasypros_idp] combined={len(combined_rows)} "
        f"DL={len(family_rows['DL'])} LB={len(family_rows['LB'])} "
        f"DB={len(family_rows['DB'])} -> total={len(rows)}"
    )
    for fam in ("DL", "LB", "DB"):
        a = anchors_by_family.get(fam) or []
        ext_count = sum(
            1
            for r in rows
            if r["derivationMethod"] == "anchored_from_individual"
            and r["family"] == fam
        )
        print(
            f"[fetch_fantasypros_idp]   {fam}: anchors={len(a)} extension_rows={ext_count}"
        )

    if args.dry_run:
        print("[fetch_fantasypros_idp] --dry-run; not writing CSV")
        for r in rows[:5]:
            print("  ", r)
        return 0

    _write_csv(args.dest, rows)
    print(f"[fetch_fantasypros_idp] wrote {len(rows)} rows -> {args.dest}")

    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, rows)
            print(f"[fetch_fantasypros_idp] mirrored -> {DATA_DIR_DST}")
        except Exception as exc:
            print(
                f"[fetch_fantasypros_idp] mirror failed: {exc}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
