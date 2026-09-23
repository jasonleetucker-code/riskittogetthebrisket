#!/usr/bin/env python3
"""Record every source board's dataset state after a fetch.

Runs wherever a source CSV is (re)written — the end of ``Dynasty Scraper.py``
(GitHub scheduled refresh AND the production scrape loop), the IDP Show
production timer, and the scheduled-refresh workflow before
``git add -f data/scrape_state``.  Folds each current CSV into
``data/scrape_state/<key>_dataset.json`` via :mod:`src.sources.dataset_state`:
an unchanged board moves no data clock, a changed one records the change.

ONE WRITER PER FILE.  The GitHub refresh records the sources it fetches and
``--skip``s the ones production timers own (DLF, IDP Show), whose timers
record their own keys — two writers pushing the same state file would
conflict on rebase.

Exit codes: 0 success (including "nothing changed"), 1 a source could not be
recorded (its state is left untouched), 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.sources.dataset_state import (  # noqa: E402
    BroadChangePolicy,
    load_state,
    record_source_file,
    state_path,
)
from src.sources.freshness import (  # noqa: E402
    STYLE_SNAPSHOT,
    classify_style,
    default_config,
)
from src.sources.ktc_market import KTC_MARKET_KEY  # noqa: E402

DEFAULT_STATE_DIR = REPO_ROOT / "data" / "scrape_state"


def recorded_sources(repo_root: Path = REPO_ROOT) -> list[tuple[str, Path, str]]:
    """``(source_key, csv_path, signal)`` for every registered voter plus the
    KTC Market benchmark (its freshness qualifies every market comparison)."""
    from src.api.data_contract import _RANKING_SOURCES, _SOURCE_CSV_PATHS  # noqa: PLC0415

    keys = [str(s.get("key") or "") for s in _RANKING_SOURCES]
    keys.append(KTC_MARKET_KEY)
    out: list[tuple[str, Path, str]] = []
    for key in keys:
        cfg = _SOURCE_CSV_PATHS.get(key)
        if isinstance(cfg, str):
            rel, signal = cfg, "value"
        elif isinstance(cfg, dict):
            rel, signal = str(cfg.get("path") or ""), str(cfg.get("signal") or "value")
        else:
            continue
        if rel:
            out.append((key, repo_root / rel, signal))
    return out


def broad_policy() -> BroadChangePolicy:
    raw = default_config().raw.get("broadChange") or {}
    return BroadChangePolicy(
        min_rows=int(raw.get("minRows", 5)), min_fraction=float(raw.get("minFraction", 0.02))
    )


def _upstream_sidecar(state_dir: Path, key: str) -> tuple[str | None, str | None]:
    """A fetcher-written ``<key>_upstream.json`` (vendor-stated publication
    metadata, e.g. IDP Show's Datawrapper ``lastModifiedAt``)."""
    import json  # noqa: PLC0415

    try:
        meta = json.loads((Path(state_dir) / f"{key}_upstream.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(meta, dict):
        return None, None
    published = meta.get("lastModifiedAt") or meta.get("publishedAt")
    version = None
    if meta.get("chartId") and meta.get("version"):
        version = f"{meta['chartId']}/v{meta['version']}"
    return (str(published) if published else None), version


def _track_rows(prior: dict | None) -> bool:
    """Per-row clocks are kept unless the subset is a classified SNAPSHOT."""
    if not prior:
        return True
    history = ((prior.get("subsets") or {}).get("players") or {}).get("changeHistory") or []
    style, _ = classify_style(history, default_config())
    return style != STYLE_SNAPSHOT


def record_all(
    *,
    state_dir: Path,
    observed_at: datetime,
    only: set[str] | None = None,
    skip: set[str] | None = None,
    upstream: dict[str, tuple[str | None, str | None]] | None = None,
) -> tuple[list[str], list[str]]:
    written: list[str] = []
    failed: list[str] = []
    policy = broad_policy()
    for key, csv_path, signal in recorded_sources():
        if only and key not in only:
            continue
        if skip and key in skip:
            continue
        prior = load_state(state_path(state_dir, key))
        published, version = (upstream or {}).get(key, (None, None)) or (None, None)
        if published is None and version is None:
            published, version = _upstream_sidecar(state_dir, key)
        try:
            state, changed = record_source_file(
                source_key=key,
                csv_path=csv_path,
                signal=signal,
                state_dir=state_dir,
                observed_at=observed_at,
                upstream_published_at=published,
                dataset_version=version,
                policy=policy,
                track_rows=_track_rows(prior),
            )
        except Exception as exc:  # noqa: BLE001 — one source never blocks the rest
            print(f"  {key}: NOT recorded ({exc})", file=sys.stderr)
            failed.append(key)
            continue
        if changed:
            written.append(key)
        health = (state.get("health") or {}).get("state")
        if health and health != "HEALTHY":
            print(f"  {key}: health {health} — clocks unchanged", file=sys.stderr)
    return written, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--only", nargs="*", help="Record only these source keys")
    parser.add_argument(
        "--skip",
        nargs="*",
        help="Never record these keys (sources whose state another writer owns)",
    )
    parser.add_argument(
        "--observed-at", help="ISO timestamp of the observation (default: now, UTC)"
    )
    parser.add_argument(
        "--upstream",
        action="append",
        default=[],
        metavar="KEY=PUBLISHED_AT[,VERSION]",
        help="Vendor-stated publication time/version for one source",
    )
    args = parser.parse_args(argv)
    observed = datetime.now(timezone.utc)
    if args.observed_at:
        try:
            observed = datetime.fromisoformat(args.observed_at.replace("Z", "+00:00"))
        except ValueError:
            print(f"bad --observed-at {args.observed_at!r}", file=sys.stderr)
            return 2
    upstream: dict[str, tuple[str | None, str | None]] = {}
    for item in args.upstream:
        key, _, rest = item.partition("=")
        published, _, version = rest.partition(",")
        upstream[key] = (published or None, version or None)
    written, failed = record_all(
        state_dir=args.state_dir,
        observed_at=observed,
        only=set(args.only) if args.only else None,
        skip=set(args.skip) if args.skip else None,
        upstream=upstream,
    )
    print(f"source datasets recorded: {len(written)} changed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
