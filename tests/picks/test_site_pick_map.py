"""C1-U6-D1 — a source that did not publish a year contributes MISSING.

RED-authored 2026-08-17.  Every test in the ``TestUnpublishedYearIsMissing``
class below was **proven to fail** against the verbatim extraction
(commit "extract the scraper pick-map builder"), before any behaviour
changed.  The four failures were exactly the four forcing paths:

    lookup_tier   nearest year, same tier                      (path 1)
    lookup_tier   nearest year, slots inside the tier range    (path 2)
    lookup_slot   nearest year, same slot                      (path 3)
    both          the ``(year, None)`` un-yeared bucket        (path 4)

Path 4 is the one #877's diagnosis missed, and it survives any repair
that only deletes ``_nearest_year``: a row the label parser resolved
WITHOUT a year ("1ST EARLY") counted as evidence for every requested
year, three of which had not happened yet.

The invariant is the sibling of the one this codebase already enforces:

    MISSING != 0
    MISSING != NEAREST_YEAR'S_VALUE
    MISSING != PREVIOUS_YEAR'S_VALUE

Deriving an unpublished future year is legitimate and already built —
``_inject_far_future_pick_sources`` mints those rows from the measured
vendor year step and ``_complete_future_pick_values`` stamps them
``derived_year_step``.  What this module must not do is hand that owner
a fabricated observation, because a derivation that fires only when the
year is absent can never fire if the year is never absent.
"""

from __future__ import annotations

import csv
import glob
import io
import os
import zipfile

import pytest

from src.picks.site_pick_map import (
    build_site_pick_map,
    fmt_pick_value,
    parse_pick_label,
    pick_suffix,
    pick_value,
    slot_tier_ranges,
    slot_to_tier,
)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rows(*specs):
    """``("2028", "early", 1, 5188)`` / ``("2028", None, 1, 5188, 3)`` →
    parsed rows in the shape the builder consumes."""
    out = []
    for spec in specs:
        year, tier, rnd, value, *rest = spec
        if rest:
            out.append(
                {
                    "kind": "slot",
                    "year": year,
                    "round": rnd,
                    "slot": rest[0],
                    "value": float(value),
                }
            )
        else:
            out.append(
                {
                    "kind": "tier",
                    "year": year,
                    "round": rnd,
                    "tier": tier,
                    "value": float(value),
                }
            )
    return out


def tier_key(year, tier, rnd):
    return f"{year} {tier.capitalize()} {rnd}{pick_suffix(rnd)}"


def slot_key(year, rnd, slot):
    return f"{year} {rnd}.{slot:02d}"


class TestUnpublishedYearIsMissing:
    """The four forcing paths.  Each of these failed before the repair."""

    def test_path1_nearest_year_same_tier_does_not_fill_an_unpublished_year(self):
        """Path 1 — ``lookup_tier``'s nearest-year-same-tier fallback.

        The exact shape of the live defect: KTC publishes 2026-2028 and
        nothing for 2029, and 2029 came back carrying 2028's number
        byte-for-byte under a key that names 2029.
        """
        published = rows(
            (2026, "early", 1, 5602.0),
            (2027, "early", 1, 6972.0),
            (2028, "early", 1, 5188.0),
        )
        built = build_site_pick_map(published, [2026, 2027, 2028, 2029])

        assert built.values[tier_key(2028, "early", 1)] == 5188
        assert tier_key(2029, "early", 1) not in built.values, (
            "2029 was never published; the emitted value is 2028's, "
            f"got {built.values.get(tier_key(2029, 'early', 1))!r}"
        )

    def test_path2_nearest_year_slot_range_does_not_fill_an_unpublished_year(self):
        """Path 2 — the tier lookup's second nearest-year fallback,
        which averages published SLOTS inside the tier's slot range.

        Reachable independently of path 1: a source that publishes slot
        rows but no tier rows takes this branch and not the other, so
        deleting only the first leaves the fabrication intact.
        """
        published = rows(*[(2028, None, 1, 6000.0 - 100 * s, s) for s in range(1, 5)])
        built = build_site_pick_map(published, [2028, 2029])

        assert built.values[tier_key(2028, "early", 1)] is not None
        assert tier_key(2029, "early", 1) not in built.values

    def test_path3_nearest_year_same_slot_does_not_fill_an_unpublished_year(self):
        """Path 3 — ``lookup_slot``'s own nearest-year fallback."""
        published = rows((2028, None, 1, 6225.6, 1))
        built = build_site_pick_map(published, [2028, 2029])

        assert built.values[slot_key(2028, 1, 1)] == 6225.6
        assert slot_key(2029, 1, 1) not in built.values

    def test_path4_the_unyeared_bucket_is_not_evidence_for_every_year(self):
        """Path 4 — ``for y in (year, None)``.

        A label the parser resolved without a year is evidence about ONE
        draft, not about four.  It cannot be evidence about a year that
        has not happened: nothing published in 2026 is an observation of
        the 2029 rookie class.

        Measured before choosing this rule: across 13 archives spanning
        2026-07-14 to 2026-08-17 and every pick-bearing source, the
        un-yeared grammars matched **zero** rows.  So this branch is
        latent rather than live — which is precisely why it had to be
        closed by rule and not by noticing it in the output.
        """
        published = rows(
            (None, "early", 1, 5000.0),  # a bare "EARLY 1ST" row
            (None, None, 1, 5100.0, 1),  # a bare "1.01" row
        )
        built = build_site_pick_map(published, [2026, 2027, 2028, 2029])

        emitted_years = sorted({int(k[:4]) for k in built.values})
        assert emitted_years == [2026], (
            "an un-yeared label is evidence for the nearest requested draft only; "
            f"it was credited to {emitted_years}"
        )

    def test_the_slot_estimate_cannot_launder_a_fabricated_tier(self):
        """``_estimate_slot_from_tier`` re-enters ``lookup_tier``.

        So repairing the tier lookup alone is not enough to repair the
        slot lookup, and repairing the slot lookup alone is not enough
        either — the estimate would re-import the fabrication through
        the back door and emit twelve slot rows for a year with no
        evidence at all.
        """
        published = rows((2028, "early", 1, 5188.0))
        built = build_site_pick_map(published, [2028, 2029])

        assert slot_key(2028, 1, 1) in built.values, "the same-year estimate must still work"
        fabricated = [k for k in built.values if k.startswith("2029")]
        assert (
            fabricated == []
        ), f"2029 rows derived from a 2029 tier that does not exist: {fabricated}"

    def test_a_year_gap_in_the_middle_is_also_missing(self):
        """Not a "future years" rule — an EVIDENCE rule.

        A source publishing 2026 and 2028 but not 2027 leaves 2027
        missing, in both directions.  A rule that special-cased "later
        than the last published year" would pass the 2029 case and still
        fabricate here.
        """
        published = rows((2026, "early", 1, 5602.0), (2028, "early", 1, 5188.0))
        built = build_site_pick_map(published, [2026, 2027, 2028])

        assert sorted({int(k[:4]) for k in built.values}) == [2026, 2028]


class TestPublishedEvidenceStillResolves:
    """The repair removes fabrication, not function.  Everything a
    source DID publish must still emit, or this is a regression dressed
    as a fix."""

    def test_exact_tier_rows_emit(self):
        built = build_site_pick_map(rows((2027, "mid", 2, 3057.0)), [2027])
        assert built.values[tier_key(2027, "mid", 2)] == 3057

    def test_exact_slot_rows_emit(self):
        built = build_site_pick_map(rows((2026, None, 1, 6225.6, 6)), [2026])
        assert built.values[slot_key(2026, 1, 6)] == 6225.6

    def test_same_year_slots_still_answer_a_tier(self):
        """Within-year aggregation is not substitution: these ARE the
        source's own observations for the year being asked about."""
        built = build_site_pick_map(
            rows(*[(2026, None, 1, 4000.0, s) for s in range(1, 5)]),
            [2026],
        )
        assert built.values[tier_key(2026, "early", 1)] == 4000

    def test_same_year_tier_still_spreads_into_a_slot_curve(self):
        built = build_site_pick_map(rows((2026, "early", 1, 5000.0)), [2026])
        early = [built.values[slot_key(2026, 1, s)] for s in range(1, 5)]
        assert early[0] > early[-1], "the slot curve must still descend inside the tier"
        assert abs(sum(early) / len(early) - 5000) < 1.0, "and still average near the tier value"

    def test_multiple_rows_for_one_key_average(self):
        built = build_site_pick_map(
            rows((2026, "early", 1, 4000.0), (2026, "early", 1, 6000.0)), [2026]
        )
        assert built.values[tier_key(2026, "early", 1)] == 5000


class TestProvenanceTravelsWithTheNumber:
    """§8 of the repair directive: a derived value may not masquerade as
    a direct source observation."""

    def test_every_emitted_key_carries_an_evidence_class(self):
        built = build_site_pick_map(
            rows((2026, "early", 1, 5000.0), (2026, None, 2, 3000.0, 5)), [2026]
        )
        assert set(built.provenance) == set(built.values)
        assert all(v for v in built.provenance.values())

    def test_a_published_tier_and_a_derived_slot_are_not_the_same_class(self):
        built = build_site_pick_map(rows((2026, "early", 1, 5000.0)), [2026])
        assert built.provenance[tier_key(2026, "early", 1)] == "published_tier"
        assert built.provenance[slot_key(2026, 1, 1)] != "published_tier", (
            "a slot value spread out of a tier row is a derivation, and calling it "
            "the same thing as a published slot is how derived evidence gets counted "
            "as observed"
        )

    def test_a_published_slot_is_marked_published(self):
        built = build_site_pick_map(rows((2026, None, 1, 6225.6, 1)), [2026])
        assert built.provenance[slot_key(2026, 1, 1)] == "published_slot"

    def test_missing_keys_carry_no_provenance_either(self):
        built = build_site_pick_map(rows((2028, "early", 1, 5188.0)), [2028, 2029])
        assert not [k for k in built.provenance if k.startswith("2029")]


class TestPrimitives:
    """The helpers moved with the builder; they were untested too."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026 Early 1st", {"kind": "tier", "year": 2026, "tier": "early", "round": 1}),
            ("2026 Pick 1.06", {"kind": "slot", "year": 2026, "round": 1, "slot": 6}),
            ("2026 1.06", {"kind": "slot", "year": 2026, "round": 1, "slot": 6}),
            ("EARLY 1ST", {"kind": "tier", "year": None, "tier": "early", "round": 1}),
            ("1.06", {"kind": "slot", "year": None, "round": 1, "slot": 6}),
            ("2026 2", {"kind": "tier", "year": 2026, "tier": "mid", "round": 2}),
            ("Josh Allen", None),
            ("", None),
            (None, None),
            (2026, None),
        ],
    )
    def test_label_grammar(self, raw, expected):
        assert parse_pick_label(raw) == expected

    def test_year_absent_is_none_not_a_default(self):
        """The whole repair rests on this distinction surviving the
        parser: ``None`` means the label did not say, and that is not
        the same fact as any particular year."""
        assert parse_pick_label("EARLY 1ST")["year"] is None

    @pytest.mark.parametrize("bad", [None, 0, -1, 0.0, "5000", True is False])
    def test_pick_value_refuses_non_values(self, bad):
        assert pick_value(bad) is None

    def test_pick_value_accepts_positives(self):
        assert pick_value(5188) == 5188.0

    def test_fmt_collapses_integral_floats(self):
        assert fmt_pick_value(5188.0) == 5188
        assert isinstance(fmt_pick_value(5188.0), int)
        assert fmt_pick_value(6225.6) == 6225.6
        assert fmt_pick_value(None) is None

    def test_suffixes(self):
        assert [pick_suffix(n) for n in range(1, 7)] == ["st", "nd", "rd", "th", "th", "th"]

    def test_tier_ranges_partition_the_league(self):
        ranges = slot_tier_ranges(12)
        assert ranges == {"early": (1, 4), "mid": (5, 8), "late": (9, 12)}
        covered = [s for lo, hi in ranges.values() for s in range(lo, hi + 1)]
        assert sorted(covered) == list(range(1, 13))
        assert [slot_to_tier(s) for s in (1, 4, 5, 8, 9, 12)] == [
            "early",
            "early",
            "mid",
            "mid",
            "late",
            "late",
        ]

    def test_tier_ranges_scale_with_league_size(self):
        assert slot_tier_ranges(10) == {"early": (1, 3), "mid": (4, 6), "late": (7, 10)}

    def test_empty_input_is_empty_output_not_an_error(self):
        assert build_site_pick_map([], [2026]).values == {}
        assert not build_site_pick_map([], [2026])

    def test_rows_with_no_usable_round_emit_nothing(self):
        assert (
            build_site_pick_map([{"kind": "tier", "year": 2026, "round": None}], [2026]).values
            == {}
        )


class TestAgainstRealVendorBoards:
    """The unit tests above are synthetic by design — they isolate one
    path each.  This one asserts the same property over the actual rows
    the live sources publish, because a rule that only holds on
    hand-built input is a rule about the input."""

    @staticmethod
    def _parsed(text):
        out = []
        for row in csv.DictReader(io.StringIO(text)):
            try:
                val = float(row.get("value") or 0)
            except (TypeError, ValueError):
                continue
            pval = pick_value(val)
            if pval is None:
                continue
            parsed = parse_pick_label(row.get("name") or "")
            if not parsed:
                continue
            parsed["value"] = pval
            out.append(parsed)
        return out

    def _boards(self):
        """Live raw first; fall back to the newest archive that has
        ``site_raw/``.  Yields ``(label, parsed_rows)``."""
        found = False
        for path in sorted(glob.glob(os.path.join(REPO, "exports/latest/site_raw/*.csv"))):
            with open(path, encoding="utf-8") as fh:
                parsed = self._parsed(fh.read())
            if parsed:
                found = True
                yield os.path.basename(path), parsed
        if found:
            return
        for arc in sorted(glob.glob(os.path.join(REPO, "exports/archive/*.zip")), reverse=True):
            with zipfile.ZipFile(arc) as z:
                names = [n for n in z.namelist() if "site_raw" in n and n.endswith(".csv")]
                if not names:
                    continue
                for n in names:
                    parsed = self._parsed(z.read(n).decode("utf-8", "replace"))
                    if parsed:
                        yield f"{os.path.basename(arc)}:{os.path.basename(n)}", parsed
                return

    def test_no_source_emits_a_year_it_did_not_publish(self):
        boards = list(self._boards())
        if not boards:
            pytest.skip("no site_raw snapshots available in this checkout")
        for label, parsed in boards:
            published = sorted({r["year"] for r in parsed if r.get("year") is not None})
            assert published, f"{label}: no yeared rows to reason about"
            horizon = list(range(min(published), max(published) + 4))
            built = build_site_pick_map(parsed, horizon)
            emitted = sorted({int(k[:4]) for k in built.values})
            assert emitted == published, (
                f"{label}: published {published} but emitted {emitted} — "
                f"the extra years carry no observation behind them"
            )
