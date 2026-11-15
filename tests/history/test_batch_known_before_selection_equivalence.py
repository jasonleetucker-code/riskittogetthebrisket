"""``batch_known_before`` sorts each asset's candidates ONCE and answers
every instant with the first admissible row (bisect + short scan).

It used to re-filter the whole history and re-run ``_select_best``'s four
stable sorts for every ``(asset, instant)`` request — the dominant cost of
grading the public activity feed (one player recurs across many trades).

The rewrite is only acceptable if it selects EXACTLY the same row for every
request.  This pins that property against a verbatim copy of the retired
per-request selection, over randomized ledgers built to hit every tie
branch: same-day rows with and without a proven instant, date-only and
zone-qualified stamps (including negative offsets that defeat a text
compare), equal ``observed_at`` text across origins, unlisted / ``:zip=``
origins, colliding content hashes, superseded rows (corrections), the
history floor, and request instants landing exactly on an observation.
"""

from __future__ import annotations

import random
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.history import asof, store


def _reference_select_best(rows):
    """The retired ``_select_best`` body, verbatim."""
    if not rows:
        return None
    ordered = sorted(rows, key=lambda r: str(r["content_hash"]))
    ordered = sorted(ordered, key=lambda r: store.origin_rank(str(r["origin"])))
    ordered = sorted(
        ordered,
        key=lambda r: (1, str(r["observed_at"])) if r["observed_at"] else (0, ""),
        reverse=True,
    )
    ordered = sorted(ordered, key=lambda r: str(r["observed_date"]), reverse=True)
    return ordered[0]


def _reference_batch(requests, path):
    """The retired per-request selection: the same candidate fetch, then
    filter + full re-sort for EVERY request.  Returns the selected row id
    (or the unavailable reason) per request, positionally."""
    conn = asof._connect_readonly(path)
    out = []
    try:
        for asset_key, instant in requests:
            utc = instant.astimezone(timezone.utc)
            requested = utc.date().isoformat()
            if requested < store.HISTORY_FLOOR:
                out.append(("unavailable", asof.REASON_BEFORE_BOUNDARY))
                continue
            max_date = max(
                i.astimezone(timezone.utc).date().isoformat()
                for k, i in requests
                if k == asset_key
                and i.astimezone(timezone.utc).date().isoformat() >= store.HISTORY_FLOOR
            )
            rows = asof._fetch_candidates(
                conn, asset_key, store.LANE_CANONICAL, "", date_max=max_date
            )
            filtered = [
                r
                for r in rows
                if str(r["observed_date"]) < requested
                or (
                    str(r["observed_date"]) == requested
                    and asof._instant_at_or_before(r["observed_at"], utc)
                )
            ]
            best = _reference_select_best(filtered)
            if best is None:
                out.append(("unavailable", asof.REASON_NO_PRIOR))
            else:
                out.append(("value", best["value"], best["observed_date"], best["observed_at"]))
    finally:
        conn.close()
    return out


_ORIGINS = (
    "live:server",
    "migration:board_history",
    "migration:rank_history",
    "backfill:archive",
    "backfill:archive:zip=2026-08-01",
    "zz:unlisted",
    "aa:unlisted",
)
_DAYS = ("2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-08-02")


def _stamp(rng: random.Random, day: str):
    choice = rng.randrange(8)
    hh = rng.choice((0, 3, 12, 12, 23))
    mm = rng.choice((0, 0, 30))
    if choice == 0:
        return None
    if choice == 1:
        return day  # date-only: an UNKNOWN instant, never admissible same-day
    if choice == 2:
        return f"{day}T{hh:02d}:{mm:02d}:00"  # naive (legacy) — read as UTC
    if choice == 3:
        return f"{day}T{hh:02d}:{mm:02d}:00+00:00"
    if choice == 4:
        return f"{day}T{hh:02d}:{mm:02d}:00-05:00"  # defeats a text compare
    if choice == 5:
        return f"{day}T{hh:02d}:{mm:02d}:00+02:00"
    if choice == 6:
        return f"{day} {hh:02d}:{mm:02d}:00"  # space separator
    return "not-a-stamp"


def _build_ledger(path: Path, rng: random.Random, keys: list[str]) -> None:
    conn = store.connect(path)
    try:
        ids = []
        for key in keys:
            for _ in range(rng.randrange(0, 18)):
                day = rng.choice(_DAYS)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO observations (asset_key, asset_class, lane, "
                    "source_key, observed_date, observed_at, value, origin, recorded_at, "
                    "content_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        key,
                        "offense",
                        store.LANE_CANONICAL,
                        "",
                        day,
                        _stamp(rng, day),
                        float(rng.randrange(1, 9999)),
                        rng.choice(_ORIGINS),
                        "2026-08-03T00:00:00+00:00",
                        rng.choice(("h1", "h2", "h3", f"h{rng.random()}")),
                    ),
                )
                if cur.rowcount == 1:
                    ids.append(cur.lastrowid)
        # Corrections: superseded rows must vanish from both selections.
        rng.shuffle(ids)
        for superseded, superseding in zip(ids[0::5], ids[1::5]):
            conn.execute(
                "INSERT OR IGNORE INTO corrections VALUES (?,?,?,?)",
                (superseded, superseding, "test", "2026-08-03T00:00:00+00:00"),
            )
        conn.commit()
    finally:
        conn.close()


def _instants(rng: random.Random, path: Path, key: str, n: int):
    """Random request instants, a third of them landing EXACTLY on a
    recorded stamp (the at-or-before boundary)."""
    conn = sqlite3.connect(path)
    try:
        stamps = [
            s
            for (s,) in conn.execute(
                "SELECT observed_at FROM observations WHERE asset_key=?", (key,)
            )
            if s and store.has_time_component(s)
        ]
    finally:
        conn.close()
    out = []
    for _ in range(n):
        if stamps and rng.random() < 0.34:
            parsed = datetime.fromisoformat(rng.choice(stamps))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            out.append(parsed)
            continue
        base = datetime.fromisoformat(rng.choice(_DAYS + ("2026-08-03",))).replace(
            tzinfo=timezone.utc
        )
        tz = timezone(timedelta(hours=rng.choice((0, -7, 5))))
        out.append((base + timedelta(minutes=rng.randrange(0, 24 * 60))).astimezone(tz))
    return out


class BatchSelectionEquivalenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        store._reset_setup_cache_for_tests()

    def test_sorted_once_selection_matches_the_per_request_selection(self) -> None:
        checked = 0
        selected = 0
        for seed in range(60):
            rng = random.Random(seed)
            path = Path(self._td.name) / f"ledger_{seed}.sqlite"
            keys = [f"player:{i}" for i in range(4)]
            _build_ledger(path, rng, keys)
            requests = []
            for key in keys:
                requests.extend((key, inst) for inst in _instants(rng, path, key, 12))
            rng.shuffle(requests)

            got = asof.batch_known_before(requests, path=path)["results"]
            expected = _reference_batch(requests, path)
            for result, want in zip(got, expected, strict=True):
                if want[0] == "unavailable":
                    self.assertIsNone(result["value"], (seed, result))
                    self.assertEqual(result["missingReason"], want[1], (seed, result))
                else:
                    selected += 1
                    self.assertEqual(
                        (result["value"], result["observedDate"], result["observedAt"]),
                        want[1:],
                        seed,
                    )
                checked += 1
        # Guard against a vacuous pass: both outcomes must be exercised.
        self.assertGreater(checked, 2000)
        self.assertGreater(selected, checked // 4)
        self.assertLess(selected, checked)

    def test_selection_order_restricted_to_a_subset_is_the_subsets_own_order(self) -> None:
        # The lemma the rewrite rests on, stated directly — over plain
        # rows rather than a ledger, so ties the unique index forbids
        # (same date + instant + origin, equal content hashes, fully equal
        # sort keys resolved only by input order) are exercised too.
        rng = random.Random(7)
        rows = [
            {
                "id": i,
                "observed_date": rng.choice(_DAYS[:2]),
                "observed_at": rng.choice((None, "", "2026-07-15T12:00:00+00:00")),
                "origin": rng.choice(_ORIGINS[:2]),
                "content_hash": rng.choice(("h1", "h2")),
            }
            for i in range(60)
        ]
        full = asof._selection_order(rows)
        for _ in range(300):
            subset = [r for r in rows if rng.random() < 0.5]
            ids = {r["id"] for r in subset}
            self.assertEqual(
                [r["id"] for r in full if r["id"] in ids],
                [r["id"] for r in asof._selection_order(subset)],
            )
            best = _reference_select_best(subset)
            self.assertEqual(
                best["id"] if best is not None else None,
                next((r["id"] for r in full if r["id"] in ids), None),
            )


if __name__ == "__main__":
    unittest.main()
