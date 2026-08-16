"""Scraper-family name primitives, owned by the identity package (C1-ID-01).

These functions ARE ``Dynasty Scraper.py``'s matching primitives —
``clean_name``, ``normalize_lookup_name``, ``similarity`` / ``best_match``
and the ``_is_safe_name_merge`` guard family — moved verbatim so the
canonical identity owner (``src/identity/``) owns every player-equivalence
decision and the scraper imports them back as an adapter.  Extraction is
code motion, not redesign: byte-level behaviour is pinned by
``tests/identity/test_name_primitives_parity.py`` and any intentional
change to matching semantics belongs in ``src/identity/resolution.py``
policies, never here.

Vocabulary note (see the registry in ``src/utils/name_clean.py``): this is
name-key **family 4** — the scraper-clean pair — and it is deliberately NOT
``normalize_player_name`` (family 1).  The two disagree on accents, initial
collapsing scope, suffix anchoring and more; every cross-source join in the
contract pipeline uses family 1, while the scrape-time merge vocabulary is
this family.  Consolidating the two VOCABULARIES is a semantic change that
only a measured, owner-approved cutover may make; consolidating the
OWNERSHIP (this move) is what C1-ID-01 requires.

``pool_clean_name`` / ``pool_normalize_lookup`` in ``src/pool/builder.py``
remain deliberate mirrors of these transforms (their team-code set is
already shared and parity-tested); folding them onto this module is a
staged follow-up recorded in
``docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md``.
"""

from __future__ import annotations

import functools
import re
from difflib import SequenceMatcher
from typing import Callable

from src.utils.name_clean import NFL_TEAM_CODES

# The scraper historically carried its own ``_TEAM_CODES`` literal;
# ``tests/utils/test_team_codes_parity.py`` pins that literal equal to
# ``NFL_TEAM_CODES``, so importing the shared set here is behaviour-
# preserving by an existing test's authority.
_TEAM_CODES = NFL_TEAM_CODES


def clean_name(raw: object) -> str:
    """Strip position/team suffixes, generational suffixes, and inline team codes.
    Also normalizes unicode escapes and apostrophe variants.

    Moved verbatim from ``Dynasty Scraper.py::clean_name``.
    """
    if not raw:
        return ""
    name = str(raw).strip()
    # Decode literal unicode escapes like \\u0027 → '
    if "\\u" in name:
        try:
            name = name.encode("utf-8").decode("unicode_escape")
        except Exception:  # noqa: BLE001 — same tolerance as the scraper original
            name = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), name)
    # Trim ranking prefixes and misc scrape markers.
    name = re.sub(r"^\s*#?\d+\s*[\).:-]\s*", "", name)
    name = re.sub(r"\s*[\*†‡]+\s*$", "", name)
    # Strip trailing parenthetical notes: "X Player (IR)".
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    # Normalize various apostrophe/quote chars to standard apostrophe
    name = re.sub(r"[‘’`´'′]", "'", name)
    # Convert "Last, First" to "First Last" where applicable.
    if "," in name:
        m = re.match(r"^\s*([A-Za-z.'\- ]+),\s*([A-Za-z.'\- ]+)\s*$", name)
        if m:
            name = f"{m.group(2).strip()} {m.group(1).strip()}".strip()
    # Strip position/team tag after name (e.g. "Caleb Williams QB CHI")
    name = re.split(r"\s+(QB|RB|WR|TE|K|DEF|DST|OL|LB|DB|DL|DE|DT|CB|S|PK)\b", name)[0].strip()
    # Strip team code glued to end (e.g. "Caleb WilliamsCHI")
    m = re.match(r"^(.+?)([A-Z]{2,3})$", name)
    if m and m.group(2) in _TEAM_CODES and len(m.group(1).strip()) > 3:
        name = m.group(1).strip()
    # Strip generational suffixes: Jr., Sr., II, III, IV, V (with or without period/comma)
    name = re.sub(r"[,\s]+(Jr.?|Sr.?|I{2,3}|IV|V|VI)\s*$", "", name, flags=re.IGNORECASE).strip()
    # Normalize periods in initials: "T.J." → "T.J.", but also allow matching "TJ"
    # Don't strip periods here — handle in matching instead
    # Collapse any double spaces
    name = re.sub(r"\s{2,}", " ", name)
    return name


@functools.lru_cache(maxsize=8192)
def normalize_lookup_name(raw: object) -> str:
    """Name key for resilient matching across sources.

    Moved verbatim from ``Dynasty Scraper.py::normalize_lookup_name``.
    """
    s = clean_name(raw or "").lower()
    # Treat punctuation variants as the same player identity:
    # "T.J. Parker", "TJ Parker", and "T J Parker" -> "tj parker".
    s = s.replace("-", " ")
    s = s.replace(".", "")
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return s
    parts = s.split()
    # Collapse leading initial tokens: "t j parker" -> "tj parker".
    initial_run = []
    idx = 0
    while idx < len(parts) and len(parts[idx]) == 1:
        initial_run.append(parts[idx])
        idx += 1
    if len(initial_run) >= 2:
        merged = "".join(initial_run)
        s = " ".join([merged] + parts[idx:])
    return s


def _tokenize(name: str) -> list[str]:
    """Lowercase, normalize hyphens, split, sort tokens for order-independent comparison."""
    normalized = name.lower().replace("-", " ").replace(".", "")
    return sorted(normalized.split())


def similarity(a: str, b: str) -> float:
    """Fuzzy score between two names.  Moved verbatim from
    ``Dynasty Scraper.py::similarity`` — see that history for the
    first/last-name adjustment rationale."""
    a_low, b_low = a.lower().strip(), b.lower().strip()
    # Direct ratio
    direct = SequenceMatcher(None, a_low, b_low).ratio()
    # Token-sorted ratio (handles reordered tokens)
    a_sorted = " ".join(_tokenize(a_low))
    b_sorted = " ".join(_tokenize(b_low))
    token_sorted = SequenceMatcher(None, a_sorted, b_sorted).ratio()
    base = max(direct, token_sorted)

    # Adjust based on first/last name analysis
    a_parts, b_parts = a_low.split(), b_low.split()
    adjustment = 0.0
    if len(a_parts) >= 2 and len(b_parts) >= 2:
        last_a, last_b = a_parts[-1], b_parts[-1]
        first_a, first_b = a_parts[0].rstrip("."), b_parts[0].rstrip(".")

        if last_a == last_b and len(last_a) > 2:
            # Same last name — check first names carefully
            if first_a == first_b:
                adjustment = 0.02
            elif first_a[0] == first_b[0] and (len(first_a) <= 2 or len(first_b) <= 2):
                adjustment = 0.10
            else:
                # Prefix-subset penalty: one first name is a strict prefix
                # of the other with 2+ extra chars → distinct people.
                # e.g. "james"/"jameson", "chris"/"christian"
                shorter_f, longer_f = (
                    (first_a, first_b) if len(first_a) <= len(first_b) else (first_b, first_a)
                )
                if longer_f.startswith(shorter_f) and (len(longer_f) - len(shorter_f)) >= 2:
                    adjustment = -0.20
                else:
                    first_sim = SequenceMatcher(None, first_a, first_b).ratio()
                    if first_sim < 0.5:
                        adjustment = -0.15
                    else:
                        adjustment = -0.05
        elif last_a != last_b:
            if first_a == first_b and len(first_a) > 2:
                pass  # Same first name, different last — no special adjustment

    # [NEW] Length penalty — prevent very short names from inflating similarity
    min_len = min(len(a_low), len(b_low))
    if min_len <= 5:
        adjustment -= 0.08  # short names are unreliable matches

    return base + adjustment


def best_match(
    target: str,
    candidates,
    threshold: float = 0.78,
    match_guard: Callable[[str, str], bool] | None = None,
    *,
    debug: bool = False,
) -> str | None:
    """Find the best fuzzy match for target among candidates.

    match_guard: optional callable (target, candidate) -> bool
    used to reject structurally unsafe matches.

    Moved verbatim from ``Dynasty Scraper.py::best_match``; the module-
    global DEBUG print became the explicit ``debug`` parameter (the
    scraper adapter passes its own flag through).
    """
    best, best_score = None, 0
    for c in candidates:
        if match_guard and not match_guard(target, c):
            continue
        s = similarity(target, c)
        if s > best_score:
            best, best_score = c, s
    if debug and best and best_score >= threshold:
        print(f"    ✓ '{target}' → '{best}' ({best_score:.2f})")
    return best if best_score >= threshold else None


def name_tokens(name: str) -> list[str]:
    """Normalize a name into ordered alpha tokens for conservative merge checks.

    Moved verbatim from ``Dynasty Scraper.py::_name_tokens``.
    """
    cleaned = clean_name(name).lower().replace(".", "").replace("-", " ").replace("'", " ")
    return [t for t in cleaned.split() if t]


def first_name_compatible(a_first: str, b_first: str) -> bool:
    """Allow exact, initial, and near-typo first-name matches.

    Moved verbatim from ``Dynasty Scraper.py::_first_name_compatible``.
    """
    if not a_first or not b_first:
        return False
    if a_first == b_first:
        return True
    if len(a_first) == 1 and a_first == b_first[:1]:
        return True
    if len(b_first) == 1 and b_first == a_first[:1]:
        return True
    # Reject when one name is a strict prefix of the other with 2+ extra
    # chars — these are distinct names, not typos.
    # e.g. "james"/"jameson", "chris"/"christian", "mark"/"marquez"
    shorter, longer = (a_first, b_first) if len(a_first) <= len(b_first) else (b_first, a_first)
    if longer.startswith(shorter) and (len(longer) - len(shorter)) >= 2:
        return False
    return SequenceMatcher(None, a_first, b_first).ratio() >= 0.72


def is_safe_name_merge(
    src_name: str,
    dst_name: str,
    position_lookup: Callable[[str], str] | None = None,
) -> bool:
    """Guard fuzzy canonicalization so unrelated players are not merged.

    Moved verbatim from ``Dynasty Scraper.py::_is_safe_name_merge``, with
    the position gate's data dependency made explicit: the scraper read a
    module global (``SLEEPER_ROSTER_DATA``); callers now inject
    ``position_lookup`` (name → position family, "" when unknown).  A
    ``None`` lookup means "no position evidence available", which — like
    the original when the roster map was empty — cannot reject.
    """
    # Position gate: reject if both players have known incompatible positions
    if position_lookup is not None:
        pos_a = position_lookup(src_name)
        pos_b = position_lookup(dst_name)
        if pos_a and pos_b and pos_a != pos_b:
            return False

    src = name_tokens(src_name)
    dst = name_tokens(dst_name)
    if len(src) < 2 or len(dst) < 2:
        return False

    src_first, dst_first = src[0], dst[0]
    src_last, dst_last = src[-1], dst[-1]
    src_mid = src[1:-1]
    dst_mid = dst[1:-1]

    # Do not merge names that share first+last but differ on non-trivial middle tokens.
    # Example: "Josh Allen" vs "Josh Hines-Allen" must remain distinct.
    if src_first == dst_first and src_last == dst_last and src_mid != dst_mid:
        return False

    # Exact or near-exact last names must still have compatible first names.
    if src_last == dst_last:
        return first_name_compatible(src_first, dst_first)
    if SequenceMatcher(None, src_last, dst_last).ratio() >= 0.92:
        return first_name_compatible(src_first, dst_first)

    # Allow one trailing short token artifact (e.g., "Gervon Dexter Dr" -> "Gervon Dexter").
    if len(src) == len(dst) + 1 and len(src[-1]) <= 3 and src[:-1] == dst:
        return True
    if len(dst) == len(src) + 1 and len(dst[-1]) <= 3 and dst[:-1] == src:
        return True

    return False
