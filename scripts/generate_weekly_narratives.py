#!/usr/bin/env python3
"""Generate weekly fantasy matchup previews / recaps for a league.

Three actions, one canonical pipeline (owner decision 2026-08-14,
docs/WEEKLY_REPORT_STUDIO_MANUAL_AI_ARCHITECTURE_2026-08-14.md — Manual
External AI is the DEFAULT mode; site-side API generation is an explicit,
optional convenience, never a requirement):

    --action export    (DEFAULT) Build the canonical brief + a provider-
                        neutral prompt package for every targeted matchup.
                        ZERO API calls, no ANTHROPIC_API_KEY needed. Prints
                        the package and writes it under
                        data/narrative_packages/ for the owner to paste
                        into any chat LLM.

    --action import     Read a manually-produced article (or a directory
                        of them, one per matchup) and validate + publish
                        each through the same storage/schema every other
                        path uses. See --import-path.

    --action generate   The original on-demand/automatic API path: calls
                        Anthropic directly. Requires ANTHROPIC_API_KEY.
                        Optional convenience only — never required for
                        the canonical weekly workflow, never scheduled by
                        default.

Usage
-----
    # Wednesday morning — export the previews package for the current week.
    python scripts/generate_weekly_narratives.py --action export --mode preview

    # Paste the package's systemPrompt/userPrompt into an external LLM,
    # save its six JSON responses under one directory, then:
    python scripts/generate_weekly_narratives.py --action import \\
        --mode preview --import-path /path/to/six-responses/

    # Tuesday morning — same for recaps.
    python scripts/generate_weekly_narratives.py --action export --mode recap

    # Optional: on-demand site-side API generation (needs the key).
    python scripts/generate_weekly_narratives.py --action generate --mode preview

    # Backfill: explicit (season, week, mode), e.g. championship recap.
    python scripts/generate_weekly_narratives.py \\
        --action export --mode recap --season 2025 --week 17

    # Single matchup only (useful for the on-demand admin endpoint).
    python scripts/generate_weekly_narratives.py \\
        --action generate --mode preview --season 2025 --week 17 --matchup-id 1

How it picks the week when ``--week`` is omitted
------------------------------------------------
The script trusts ``matchup_preview._detect_current_week`` to find the
"live" week — that's the same logic the public-league /league section
uses, so the cron's choice always matches what users see. For
``--mode preview`` the live week is the upcoming/in-progress week; for
``--mode recap`` we step back one to the most recent fully-scored week.

Network and API requirements
-----------------------------
* ``--action export`` / ``--action import``: only ``api.sleeper.app``
  (snapshot fetch) — no LLM API key required at all.
* ``--action generate``: additionally requires ``ANTHROPIC_API_KEY``.

Exit codes
----------
* 0 — every targeted matchup succeeded (generated / exported / imported),
  or already on disk and ``--force`` not passed.
* 1 — at least one target failed; check stderr for the failure.
* 2 — bad invocation (no league configured, unknown mode, missing
  ``--import-path``, etc.).
"""

from __future__ import annotations

import argparse
import asyncio
import json
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
    explicit_season: str | None,
) -> tuple[str, int]:
    """Return (season, week) for generation.

    Resolution rules:
      * ``--season`` overrides the snapshot's "current" season for
        backfills (e.g. ``--season 2024 --week 17``).  When the season
        isn't on the snapshot's chain, we fail loudly rather than
        falling back to current — silently writing to the wrong
        season's directory is the bug class this argument exists to
        prevent.
      * ``--week`` overrides the detector.  Any season+week combo is
        valid as long as the snapshot has data for it.
      * With neither argument, the detector picks the live week off
        the current season.
    """
    from src.public_league import matchup_preview

    if explicit_season:
        target = snapshot.season_by_year(explicit_season)
        if target is None:
            available = ", ".join(s.season for s in snapshot.seasons) or "(none)"
            raise RuntimeError(
                f"--season {explicit_season!r} not found on snapshot. "
                f"Available seasons: {available}"
            )
    else:
        target = snapshot.current_season
        if target is None:
            raise RuntimeError("snapshot has no current season — Sleeper unreachable?")
    season = target.season

    if explicit_week is not None:
        return season, explicit_week

    # Use the matchup_preview detector — it knows the difference
    # between unscored and scored weeks.  The detector runs against
    # the chosen season, so backfills against a completed prior season
    # land on its most-recently-scored week (typically Week 17).
    detected_week, detected_mode = matchup_preview._detect_current_week(target)  # noqa: SLF001
    if detected_week == 0:
        raise RuntimeError(f"no scored or unscored week found in season {season}")

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
        raise RuntimeError(f"could not build brief for {season} W{week} matchup {matchup_id}")

    prior = matchup_narrative.collect_prior_articles(season, n=6)
    article = await matchup_narrative.generate_article(
        client=client,
        brief=brief,
        prior_articles=prior,
    )
    matchup_narrative.save_article(article)
    return article


def _packages_dir() -> Path:
    """Scratch location for exported prompt packages.

    Deliberately NOT under ``exports/narratives/`` (the committed,
    published-article store) — a prompt package is ephemeral working
    material, not a publication. ``data/`` is gitignored by default here
    (only ``data/ros/`` is force-re-included by the scheduled-refresh
    workflow), so this never gets swept into a scheduled commit.
    """
    override = (os.getenv("LEAGUE_NARRATIVE_PACKAGES_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _REPO_ROOT / "data" / "narrative_packages"


def _package_path(season: str, week: int, matchup_id: int, mode: str) -> Path:
    return (
        _packages_dir() / str(season) / f"week-{int(week):02d}" / f"{mode}-{int(matchup_id)}.json"
    )


async def _export_one(
    *,
    snapshot,
    season: str,
    week: int,
    matchup_id: int,
    mode: str,
) -> dict[str, Any]:
    from src.public_league import matchup_narrative

    brief = matchup_narrative.build_brief(
        snapshot,
        season=season,
        week=week,
        matchup_id=matchup_id,
        mode=mode,
    )
    if brief is None:
        raise RuntimeError(f"could not build brief for {season} W{week} matchup {matchup_id}")
    prior = matchup_narrative.collect_prior_articles(season, n=6)
    return matchup_narrative.build_manual_package(brief, prior_articles=prior)


async def _run_export(
    args: argparse.Namespace, snapshot, season: str, week: int, targets: list[int]
) -> int:
    print(f"Exporting {args.mode} packages for {len(targets)} matchup(s) (zero API calls)...")
    failures = 0
    for mid in targets:
        try:
            package = await _export_one(
                snapshot=snapshot, season=season, week=week, matchup_id=mid, mode=args.mode
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ matchup {mid}: {type(exc).__name__}: {exc}", file=sys.stderr)
            failures += 1
            continue
        path = _package_path(season, week, mid, args.mode)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(package, indent=2, sort_keys=True), encoding="utf-8")
        print(f"  ✓ matchup {mid}: package → {path}")
    if not failures:
        print(
            f"\n{len(targets)} package(s) written under {_package_path(season, week, targets[0], args.mode).parent}\n"
            "Paste each package's systemPrompt/userPrompt into a chat LLM, save the six "
            "JSON responses, then run --action import --import-path <dir>."
        )
    return 1 if failures else 0


def _load_import_candidates(import_path: Path) -> list[dict[str, Any]]:
    if import_path.is_dir():
        files = sorted(p for p in import_path.iterdir() if p.suffix == ".json")
    else:
        files = [import_path]
    out: list[dict[str, Any]] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            out.extend(data)
        else:
            out.append(data)
    return out


async def _run_import(args: argparse.Namespace, snapshot, season: str, week: int) -> int:
    from src.public_league import matchup_narrative

    if not args.import_path:
        print("ERROR: --action import requires --import-path", file=sys.stderr)
        return 2
    import_path = Path(args.import_path).expanduser().resolve()
    if not import_path.exists():
        print(f"ERROR: --import-path {import_path} does not exist", file=sys.stderr)
        return 2

    candidates = _load_import_candidates(import_path)
    if not candidates:
        print(f"WARN: no candidate articles found under {import_path}", file=sys.stderr)
        return 0

    prior = matchup_narrative.collect_prior_articles(season, n=6)
    failures = 0
    for candidate in candidates:
        mid = candidate.get("matchupId")
        if mid is None:
            print("  ✗ candidate missing matchupId, skipped", file=sys.stderr)
            failures += 1
            continue
        mid = int(mid)
        cand_season = str(candidate.get("season") or season)
        cand_week = int(candidate.get("week") or week)
        cand_mode = candidate.get("mode") or args.mode

        brief = matchup_narrative.build_brief(
            snapshot, season=cand_season, week=cand_week, matchup_id=mid, mode=cand_mode
        )
        if brief is None:
            print(
                f"  ✗ matchup {mid}: could not build brief for {cand_season} W{cand_week} "
                f"({cand_mode}) — is this the wrong week/season?",
                file=sys.stderr,
            )
            failures += 1
            continue

        existing = matchup_narrative.load_article(cand_season, cand_week, mid, cand_mode)
        if existing is not None and not args.force:
            print(f"  - matchup {mid}: already on disk, skipped (use --force to reimport)")
            continue

        article, validation = matchup_narrative.import_manual_article(
            candidate,
            brief=brief,
            prior_articles=prior,
            batch=candidates,
            provider=candidate.get("provider"),
            model=candidate.get("model"),
            force=args.force,
        )
        for w in validation.warnings:
            print(f"    ! matchup {mid} warning: {w}")
        if article is None:
            print(f"  ✗ matchup {mid}: validation failed:", file=sys.stderr)
            for e in validation.errors:
                print(f"      - {e}", file=sys.stderr)
            failures += 1
            continue
        path = matchup_narrative.article_path(cand_season, cand_week, mid, cand_mode)
        print(
            f"  ✓ matchup {mid}: '{article.get('title')}' imported → {path.relative_to(_REPO_ROOT)}"
        )
    return 1 if failures else 0


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

    client = None
    if args.action == "generate":
        # Lazy-import anthropic so export/import never need the SDK or a
        # key installed on the host — the canonical weekly path does not
        # depend on either (docs/WEEKLY_REPORT_STUDIO_MANUAL_AI_ARCHITECTURE_
        # 2026-08-14.md — Manual External AI is the default, this is the
        # optional On-Demand API convenience only).
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

    try:
        season, week = _resolve_target_week(
            snapshot,
            mode=args.mode,
            explicit_week=args.week,
            explicit_season=args.season,
        )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"Target: season={season} week={week} mode={args.mode} action={args.action}")

    if args.action == "import":
        return await _run_import(args, snapshot, season, week)

    if args.matchup_id is not None:
        targets = [int(args.matchup_id)]
    else:
        targets = matchup_narrative.enumerate_week_matchups(snapshot, season, week)
    if not targets:
        print(
            f"WARN: no matchups found for {season} W{week}; nothing to {args.action}",
            file=sys.stderr,
        )
        return 0

    if args.action == "export":
        return await _run_export(args, snapshot, season, week, targets)

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
        "--action",
        choices=("export", "import", "generate"),
        default="export",
        help=(
            "export (default, zero API calls) = build the manual prompt package; "
            "import = validate + publish a manually-produced article; "
            "generate = optional on-demand site-side API call (needs ANTHROPIC_API_KEY)"
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("preview", "recap"),
        required=True,
        help="preview = Wed run before games; recap = Tue run after games",
    )
    parser.add_argument(
        "--import-path",
        type=str,
        default=None,
        help="--action import only: a JSON file or a directory of JSON files to import.",
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
