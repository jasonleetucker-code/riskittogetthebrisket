"""One Python answer to "which board row is this draft pick?".

Draft picks are the only asset class on this platform with no stable
id: a pick's season, round and slot exist solely as substrings of a
display name, and every source spells that name differently.

    Sleeper roster        "2026 1.04 (own)"      / "2027 1st"
    Sleeper traded_picks  "2027 1st"             (no slot, no tier)
    canonical board       "2026 Pick 1.04"       (current year: SLOT rows)
                          "2027 Mid 1st"         (future years: TIER rows)

The frontend already had exactly one correct resolver for this —
``frontend/lib/trade-logic.js::resolvePickRow`` — and every JS consumer
routes through it.  Python had none, so the server-side engines that
resolve a roster (``src/trade/finder.py``, ``src/trade/suggestions.py``)
silently dropped every pick: they looked up the Sleeper label verbatim
in a board keyed by canonical name and got nothing.  Audit finding
W09-F003 measured the consequence — 25 picks in the finder's gated
asset pool and 0 picks in any of the 480 trades it returned, for any of
the 12 teams.

This module is the Python port of that resolver, kept deliberately
behaviour-identical:

* :func:`pick_lookup_candidates` mirrors ``buildPickLookupCandidates``
* :func:`resolve_pick_name` mirrors ``resolvePickRow``

Two rules from the JS version are load-bearing and preserved here:

1. **The alias map is applied to the INPUT label only**, never to
   synthesized candidates.  ``pickAliases`` redirects generic tier
   labels onto slot-specific rows ("2026 Mid 1st" -> "2026 Pick 1.06");
   applying it to the tier candidate a slot input like "2026 1.04"
   derives would systematically misroute every slot pick to the
   tier-centre slot.
2. **Suppressed generic-tier rows are skipped.**  The canonical
   pipeline keeps "2026 Mid 1st" on the board for name search but
   clears its ranking fields once "2026 Pick 1.06" exists
   (``pickGenericSuppressed``).  Resolving to one of those returns a
   row the board declined to price.

A miss returns ``None``.  It never falls back to a tier centre it did
not find, and callers must not substitute a number for it — a pick with
no board row has no value to show.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

__all__ = [
    "ROUND_WORD",
    "TIER_CENTRE_SLOT",
    "parse_pick_token",
    "pick_anchor_key",
    "pick_lookup_candidates",
    "resolve_pick_name",
    "normalize_pick_aliases",
]

# Round digit <-> ordinal word.  Rounds 1-6, matching
# ``ROUND_NUM`` / ``ROUND_LABELS`` in ``frontend/lib/trade-logic.js``,
# ``src/canonical/normalization_validator`` and the scraper's
# ``draft_rounds`` range.
ROUND_LABEL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th"}
ROUND_WORD = {word: num for num, word in ROUND_LABEL.items()}

# Tier-centre slot, matching ``TIER_CENTRE_SLOT`` in trade-logic.js and
# ``_suppress_generic_pick_tiers_when_slots_exist`` in
# ``src/api/data_contract.py``: Early=2, Mid=6, Late=10.
TIER_CENTRE_SLOT = {"early": 2, "mid": 6, "late": 10}

_ANNOTATION_RE = re.compile(r"\s*\([^)]*\)\s*$")
# ``pickAnchors`` is keyed WITHOUT the "Pick" token ("2026 1.01") while
# the canonical board row is named with it ("2026 Pick 1.01"); tier rows
# use the same string in both ("2026 Early 1st").
_ANCHOR_SLOT_RE = re.compile(r"^(20\d{2})\s+Pick\s+([1-6]\.\d{1,2})$", re.IGNORECASE)
_SLOT_RE = re.compile(r"^(\d{4})\s+(\d)\.(\d{2})")
_LABEL_RE = re.compile(
    r"^(\d{4})\s+(early|mid|late)?\s*(" + "|".join(ROUND_WORD) + r")",
    re.IGNORECASE,
)


def parse_pick_token(token: Any) -> dict[str, Any] | None:
    """Parse a pick token into ``{year, round, tier, slot}`` or ``None``.

    Handles "2026 1.06", "2026 early 1st", "2026 1st", "2026 mid 2nd".
    Port of ``parsePickToken``.
    """
    s = str(token or "").strip()

    m = _SLOT_RE.match(s)
    if m:
        slot = int(m.group(3))
        tier = "early" if slot <= 4 else "mid" if slot <= 8 else "late"
        return {
            "year": m.group(1),
            "round": ROUND_LABEL.get(int(m.group(2)), f"{m.group(2)}th"),
            "tier": tier,
            "slot": slot,
        }

    m = _LABEL_RE.match(s)
    if m:
        return {
            "year": m.group(1),
            "round": m.group(3).lower(),
            "tier": (m.group(2) or "").lower() or None,
            "slot": None,
        }

    return None


def pick_anchor_key(display_name: Any) -> str:
    """The ``pickAnchors`` key for a canonical pick row name.

    ``pickAnchors`` is the contract's published per-market pick board;
    it is the only evidence available for "did a retail market actually
    price this pick?".
    """
    m = _ANCHOR_SLOT_RE.match(str(display_name or "").strip())
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return str(display_name or "").strip()


def pick_lookup_candidates(raw_label: Any) -> list[str]:
    """Lowercased candidate board-row names for a raw pick label.

    Port of ``buildPickLookupCandidates``; the ordering matters and is
    preserved (raw, annotation-stripped, slot forms, tier forms,
    tier-centre slot forms, round-only fallback).
    """
    if not raw_label:
        return []
    raw = str(raw_label).strip()
    candidates: list[str] = []

    def push(value: Any) -> None:
        if not value:
            return
        key = str(value).strip().lower()
        if key and key not in candidates:
            candidates.append(key)

    # 1) Raw label exactly as provided.
    push(raw)

    # 2) Strip a trailing "(from Team X)" / "(own)" annotation.
    stripped = _ANNOTATION_RE.sub("", raw).strip()
    if stripped and stripped != raw:
        push(stripped)

    parsed = parse_pick_token(stripped or raw)
    if not parsed:
        return candidates

    year = parsed["year"]
    round_word = parsed["round"]
    tier = parsed["tier"]
    slot = parsed["slot"]
    round_digit = ROUND_WORD.get(round_word)

    # 3) Slot-specific canonical forms.
    if slot and round_digit:
        push(f"{year} Pick {round_digit}.{slot:02d}")
        push(f"{year} {round_digit}.{slot:02d}")

    # 4) Tier canonical form + its tier-centre slot sibling.
    if tier:
        push(f"{year} {tier.capitalize()} {round_word}")
        if round_digit:
            centre = TIER_CENTRE_SLOT.get(tier, 6)
            push(f"{year} Pick {round_digit}.{centre:02d}")
            push(f"{year} {round_digit}.{centre:02d}")

    # 5) Slot but no tier — derive the tier so tier-form rows resolve.
    if slot and not tier and round_digit:
        derived = "Early" if slot <= 4 else "Mid" if slot <= 8 else "Late"
        push(f"{year} {derived} {round_word}")

    # 6) Year + round only ("2027 1st") — Sleeper's /traded_picks shape.
    #    No slot is tracked there, so fall back to the tier centre the
    #    rest of the pipeline uses.
    if not slot and not tier and round_digit:
        push(f"{year} Mid {round_word}")
        push(f"{year} Pick {round_digit}.06")
        push(f"{year} {round_digit}.06")

    return candidates


def normalize_pick_aliases(pick_aliases: Any) -> dict[str, str]:
    """Lowercase a contract ``pickAliases`` map, dropping non-strings."""
    out: dict[str, str] = {}
    if isinstance(pick_aliases, Mapping):
        for key, value in pick_aliases.items():
            if isinstance(key, str) and isinstance(value, str):
                out[key.strip().lower()] = value.strip().lower()
    return out


def resolve_pick_name(
    raw_label: Any,
    known_names: Iterable[str] | Mapping[str, Any],
    pick_aliases: Any = None,
    *,
    suppressed: Iterable[str] | None = None,
) -> str | None:
    """Resolve a raw pick label to a known board-row name, or ``None``.

    Port of ``resolvePickRow``.  ``known_names`` may be any iterable or
    mapping of canonical row names (matched case-insensitively); the
    ORIGINAL casing is returned so callers can index their own maps.

    ``suppressed`` names the rows the contract flagged
    ``pickGenericSuppressed``; they are skipped exactly as the JS
    resolver skips them, so the walk continues to the slot-specific
    sibling even when ``pick_aliases`` is missing (stale contract).
    """
    if not raw_label:
        return None
    by_lower: dict[str, str] = {}
    for name in known_names:
        if isinstance(name, str) and name:
            by_lower.setdefault(name.strip().lower(), name)
    if not by_lower:
        return None
    skip = {str(n).strip().lower() for n in (suppressed or ()) if n}

    raw = str(raw_label).strip()
    stripped = _ANNOTATION_RE.sub("", raw).strip()

    # 1) Alias map, against the INPUT label only.
    aliases = normalize_pick_aliases(pick_aliases)
    if aliases:
        for form in (raw.lower(), stripped.lower()):
            target = aliases.get(form)
            if target is None:
                continue
            hit = by_lower.get(target)
            if hit is not None and target not in skip:
                return hit
            # Alias matched but its target is absent or suppressed —
            # fall through to the candidate walk rather than trying
            # another alias key.
            break

    # 2) Candidate walk, skipping suppressed generic-tier rows.
    for key in pick_lookup_candidates(raw):
        if key in skip:
            continue
        hit = by_lower.get(key)
        if hit is not None:
            return hit

    return None
