#!/usr/bin/env python3
"""Generate weekly fantasy matchup previews / recaps for a league.

Usage
-----
    # Wednesday morning — write previews for the current week.
    python scripts/generate_weekly_narratives.py --mode preview

    # Tuesday morning — write recaps for the just-completed week.
    python scripts/generate_weekly_narratives.py --mode recap

    # Backfill: explicit (season, week, mode), e.g. championship recap.
    python scripts/generate_weekly_narratives.py \\
        --mode recap --season 2025 --week 17

    # Single matchup only (useful for the on-demand admin endpoint).
    python scripts/generate_weekly_narratives.py \\
        --mode preview --season 2025 --week 17 --matchup-id 1

How it picks the week when ``--week`` is omitted
------------------------------------------------
The script trusts ``matchup_preview._detect_current_week`` to find the
"live" week — that's the same logic the public-league /league section
uses, so the cron's choice always matches what users see. For
``--mode preview`` the live week is the upcoming/in-progress week; for
``--mode recap`` we step back one to the most recent fully-scored week.

Network and API requirements
----------------------------
* ``ANTHROPIC_API_KEY`` env var must be set.
* The runner must reach ``api.sleeper.app`` (snapshot fetch is ~85
  GETs at first run, all parallelized).

Exit codes
----------
* 0 — every targeted article generated successfully (or already on
  disk and ``--force`` not passed).
* 1 — at least one generation failed; check stderr for the failure.
* 2 — bad invocation (no league configured, unknown mode, etc.).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# Allow running from repo root via ``python scripts/...`` without an
# install step.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _build_snapshot(league_id: str):
    from src.public_league.snapshot import build_public_snapshot

    return build_public_snapshot(league_id, include_nfl_players=True)


def _resolve_target_week(
    snapshot,
    *,
    mode: str,
    explicit_week: int | None,
) -> tuple[str, int]:
    """Return (season, week) for generation.

    With explicit ``--week``, use the current season's snapshot. With
    no week, derive it from the snapshot's matchup state.
    """
    from src.public_league import matchup_preview

    current = snapshot.current_season
    if current is None:
        raise RuntimeError("snapshot has no current season — Sleeper unreachable?")
    season = current.season

    if explicit_week is not None:
        return season, explicit_week

    # Use the matchup_preview detector — it knows the difference
    # between unscored and scored weeks.
    detected_week, detected_mode = matchup_preview._detect_current_week(current)  # noqa: SLF001
    if detected_week == 0:
        raise RuntimeError("no scored or unscored week found in current season")

    if mode == "preview":
        return season, detected_week
    # recap: if detector said "preview", the just-completed week is
    # one earlier; if it said "recap", that's our target.
    if detected_mode == "preview":
        return season, max(1, detected_week - 1)
    return season, detected_week


async def _generate_one(
    *,
    snapshot,
    season: str,
    week: int,
    matchup_id: int,
    mode: str,
    force: bool,
    client: Any,
) -> dict[str, Any] | None:
    """Generate (or skip) a single matchup article. Returns the article
    dict on success, or ``None`` if skipped because already on disk.
    """
    from src.public_league import matchup_narrative

    existing = matchup_narrative.load_article(season, week, matchup_id, mode)
    if existing is not None and not force:
        return None

    brief = matchup_narrative.build_brief(
        snapshot,
        season=season,
        week=week,
        matchup_id=matchup_id,
        mode=mode,
    )
    if brief is None:
        raise RuntimeError(
            f"could not build brief for {season} W{week} matchup {matchup_id}"
        )

    prior = matchup_narrative.collect_prior_articles(season, n=6)
    article = await matchup_narrative.generate_article(
        client=client, brief=brief, prior_articles=prior,
    )
    matchup_narrative.save_article(article)
    return article


async def _run(args: argparse.Namespace) -> int:
    from src.api import league_registry as _lr
    from src.public_league import matchup_narrative

    if args.league_key:
        cfg = _lr.get_league_by_key(args.league_key)
    else:
        cfg = _lr.get_default_league()
    if cfg is None:
        print("ERROR: no league configured", file=sys.stderr)
        return 2

    print(f"League: {cfg.key} ({cfg.display_name})")

    # Lazy-import anthropic so the script can be linted / tested
    # without the SDK installed on the host.
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic SDK not installed (pip install anthropic)", file=sys.stderr)
        return 2

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2
    client = anthropic.AsyncAnthropic(api_key=api_key)

    print(f"Building snapshot for league {cfg.sleeper_league_id}...")
    snapshot = _build_snapshot(cfg.sleeper_league_id)
    if not snapshot.seasons:
        print("ERROR: snapshot has no seasons (Sleeper chain empty?)", file=sys.stderr)
        return 2

    season, week = _resolve_target_week(
        snapshot, mode=args.mode, explicit_week=args.week,
    )
    print(f"Target: season={season} week={week} mode={args.mode}")

    if args.matchup_id is not None:
        targets = [int(args.matchup_id)]
    else:
        targets = matchup_narrative.enumerate_week_matchups(snapshot, season, week)
    if not targets:
        print(
            f"WARN: no matchups found for {season} W{week}; nothing to generate",
            file=sys.stderr,
        )
        return 0

    print(f"Generating {args.mode} for {len(targets)} matchup(s)...")

    failures = 0
    for mid in targets:
        try:
            result = await _generate_one(
                snapshot=snapshot,
                season=season,
                week=week,
                matchup_id=mid,
                mode=args.mode,
                force=args.force,
                client=client,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ matchup {mid}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failures += 1
            continue

        if result is None:
            print(f"  - matchup {mid}: already on disk, skipped (use --force to regen)")
        else:
            path = matchup_narrative.article_path(season, week, mid, args.mode)
            print(
                f"  ✓ matchup {mid}: '{result.get('title')}' "
                f"({result.get('wordCount')} words) → {path.relative_to(_REPO_ROOT)}"
            )
    return 1 if failures else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate weekly fantasy matchup previews/recaps via Claude.",
    )
    parser.add_argument(
        "--mode",
        choices=("preview", "recap"),
        required=True,
        help="preview = Wed run before games; recap = Tue run after games",
    )
    parser.add_argument(
        "--season",
        type=str,
        default=None,
        help="Season label (defaults to the snapshot's current season)",
    )
    parser.add_argument(
        "--week",
        type=int,
        default=None,
        help="Explicit week. If omitted, the detector picks the live week.",
    )
    parser.add_argument(
        "--matchup-id",
        type=int,
        default=None,
        help="Generate only this single matchup_id (default: every matchup that week).",
    )
    parser.add_argument(
        "--league-key",
        type=str,
        default=None,
        help="League key from registry. Defaults to the registry default.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate articles that already exist on disk.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
