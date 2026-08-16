"""Canonical name + position normalization, alias resolution, and
position-aware canonical player keys.

This module is the *single* source of truth for:

* How a raw source name becomes a normalized lookup key
  (``normalize_player_name``).
* What aliases / nickname / first-name variants resolve to the same
  canonical form (``CANONICAL_NAME_ALIASES`` +
  ``resolve_canonical_name``).
* How a player gets a position-aware canonical key that keeps
  near-name collisions (Quay Walker vs Kenneth Walker, CJ Allen the LB
  vs C.J. Allen the WR) from collapsing into one entity
  (``canonical_player_key``).
* Which coarse position *family group* (``OFFENSE`` / ``IDP`` /
  ``PICK`` / ``OTHER``) a position belongs to for collision checking
  (``canonical_position_group``).

The contract layer (``src/api/data_contract.py``) and the identity
layer (``src/identity/matcher.py``) both import from here so the same
rules apply to every join, audit, and collision check in the pipeline.

Name-key families — the registry
--------------------------------
There is more than one name key in this repo, deliberately.  They are
NOT interchangeable: a ``set`` built with one is never hit by another,
and swapping one for another silently changes which rows collide.  This
list is the single Python-side statement of which key is which.  Its
JS counterpart is the header of ``frontend/lib/player-name-match.js``.

1. STRICT / canonical — :func:`normalize_player_name` (this module).
   ASCII fold, apostrophes dropped without a space, generational
   suffixes stripped, remaining punctuation → space, adjacent initials
   merged.  ``"T.J. Watt" → "tj watt"``, ``"Ja'Marr Chase" →
   "jamarr chase"``, ``"Kenneth Walker III" → "kenneth walker"``.
   Consumers: every cross-source join in the contract pipeline, the
   identity matcher, BDVM (injected as ``name_normalizer``), the
   scraper bridge adapter.
   Cross-language pair: ``player-name-match.js::normalizePlayerNameKey``
   is a byte-for-byte mirror, pinned by
   ``tests/utils/test_name_key_parity.py`` +
   ``frontend/__tests__/name-key-parity.test.js`` against the shared
   fixture ``tests/fixtures/name_key_cases.json``.  **Move both or
   neither.**
   Ladder on top of it: :func:`resolve_canonical_name` adds the
   :data:`CANONICAL_NAME_ALIASES` nickname table (a deliberate
   SUPERSET — not a drop-in swap in the collision-key direction), and
   :func:`canonical_player_key` adds the position group.

2. COMPACT — :func:`compact_name_key` (this module).  Lowercase, keep
   only alphanumerics, drop everything else including spaces.
   ``"D.J. Moore" → "djmoore"``.  Does NOT strip generational
   suffixes, so ``"Kenneth Walker III" → "kennethwalkeriii"``.
   Consumers: ``src/adapters/ktc_crowd_faab`` (crowd FAAB bid map),
   ``src/trade/faab_recommender::_ktc_crowd_blend`` (the lookup side of
   that same map), ``src/roster_intel/roster_source`` (value index +
   roster join).
   NOT a cross-language pair.  ``waiver-logic.js::normalizeNameCompact``
   looks identical but is not: Python's ``str.isalnum()`` is
   Unicode-aware and keeps ``é``, while the JS ``[^a-z0-9]`` strip
   removes it, so ``"Juanyéh Thomas"`` yields ``"juanyéhthomas"`` here
   and ``"juanyhthomas"`` there.  They join different populations and
   are never compared, so this is documented rather than "fixed":
   adding an ASCII fold here would change the roster_intel value join
   and the crowd FAAB map for every accented name.

3. LOOSE / trim — a bare ``str(x or "").strip().lower()``, defined
   locally at four unrelated sites: ``src/trade/waiver.py::
   _normalize_name`` (league roster-ownership set),
   ``src/api/source_history.py::_norm_name_key`` (rolling snapshot log
   keys, which additionally split ``"Name::assetClass"``),
   ``server.py`` FAAB-endpoint local ``_norm`` (resolving add/drop rows
   out of ``playersArray``), and ``waiver-logic.js::normalizeName``
   (client waiver pool).  These ARE byte-equivalent, but they key four
   domains that have no reason to know about each other, so they are
   deliberately NOT hoisted into a shared helper — the honest
   statement is this registry, not a false coupling.
   Swapping any of them for family 1 changes roster-ownership
   membership: ``"Marvin Harrison Jr."`` (Sleeper) would newly collide
   with ``"Marvin Harrison"`` (contract), and any future
   ``"Kenneth Walker"`` would collapse into ``"Kenneth Walker III"``.

4. PRIVATE one-offs, intentionally outside all of the above:
   ``src/trade/ktc_import.py::_norm_name`` (hyphen-preserving key over
   KTC's own name vocabulary; never escapes that module),
   ``scripts/_shared.py::_normalize_name`` (script-only, suffix strip
   runs first, no ASCII fold), and the scraper-clean pair
   ``clean_name`` / ``normalize_lookup_name`` — owned since C1-ID-01 by
   ``src/identity/name_primitives.py`` (moved verbatim out of
   ``Dynasty Scraper.py``, which now imports them back as an adapter) —
   mirrored as ``pool_clean_name`` / ``pool_normalize_lookup`` in
   ``src/pool/builder.py``.
"""

from __future__ import annotations

import re
import unicodedata

_SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v|dr)\b\.?", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Apostrophes (curly + straight) are removed *without* inserting a
# space so ``Ja'Marr`` and ``JaMarr`` collapse to the same token.  This
# rule runs before :data:`_NON_ALNUM_RE` so the remaining punctuation
# (hyphens, periods, etc.) can continue to split tokens.
_APOSTROPHE_RE = re.compile(r"[\u2018\u2019\u201B\u02BC']")


# ── NFL team codes (scraper-clean family) ───────────────────────────────
# Scraped tables sometimes glue the team abbreviation onto the end of the
# player name ("Caleb WilliamsJAC").  ``Dynasty Scraper.py::clean_name``
# and its extracted twin ``src/pool/builder.py::pool_clean_name`` both
# strip a trailing code in this set.
#
# The pool copy used to carry its own literal and had drifted 7 entries
# behind the scraper's (GBP, JAC, KCC, LVR, NEP, SFO, TBB), so the two
# "identical" cleaners disagreed.  The pool now imports this set, and
# ``tests/utils/test_team_codes_parity.py`` asserts it still equals the
# scraper's literal so the copies cannot drift again.
#
# Both long and short forms are present on purpose — different sources
# publish "GB" vs "GBP", "KC" vs "KCC", "JAX" vs "JAC".
NFL_TEAM_CODES: frozenset[str] = frozenset(
    {
        "ARI",
        "ATL",
        "BAL",
        "BUF",
        "CAR",
        "CHI",
        "CIN",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GB",
        "GBP",
        "HOU",
        "IND",
        "JAC",
        "JAX",
        "KC",
        "KCC",
        "LAC",
        "LAR",
        "LV",
        "LVR",
        "MIA",
        "MIN",
        "NE",
        "NEP",
        "NO",
        "NYG",
        "NYJ",
        "PHI",
        "PIT",
        "SEA",
        "SF",
        "SFO",
        "TB",
        "TBB",
        "TEN",
        "WAS",
        "FA",
    }
)


# ── Canonical position aliases ──────────────────────────────────────────
# Single source of truth for mapping raw position strings to league-standard
# position families. All modules should import from here, AND callers that
# need null-tolerant handling should use ``normalize_position()`` rather
# than wrapping ``POSITION_ALIASES.get(...)`` themselves.
POSITION_ALIASES: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "DL": "DL",
    "DE": "DL",
    "DT": "DL",
    "EDGE": "DL",
    "NT": "DL",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "MLB": "LB",
    "DB": "DB",
    "CB": "DB",
    "S": "DB",
    "SS": "DB",
    "FS": "DB",
    "K": "K",
    "P": "K",
    "PICK": "PICK",
}


def normalize_position(pos: object | None) -> str:
    """Normalize a raw position string to its canonical family.

    Null-tolerant wrapper around ``POSITION_ALIASES``: accepts None,
    non-string types, leading/trailing whitespace, and any case.
    Returns ``""`` for null/empty input.  Unknown positions pass
    through (uppercased) so callers can decide whether to treat them
    as filterable or accept them as-is.

    Use this instead of writing ``POSITION_ALIASES.get(p.upper(), p)``
    inline — every module that did had subtly different null-handling
    (some accepted ``None``, some required ``str``, some stripped,
    some didn't).
    """
    if pos is None:
        return ""
    p = str(pos).strip().upper()
    if not p:
        return ""
    return POSITION_ALIASES.get(p, p)


# ── Nickname map ────────────────────────────────────────────────────────
# Common nickname → formal first-name expansions for fuzzy matching.
# These are *token-level* substitutions applied before canonical-name
# resolution.  The mapping runs on the normalized token list, so the
# keys and values are both lowercase.
NICKNAME_MAP: dict[str, str] = {
    "cam": "cameron",
    "tj": "t j",
    "cj": "c j",
    "dj": "d j",
    "aj": "a j",
    "jt": "j t",
    "dk": "d k",
    "kj": "k j",
    "pj": "p j",
    "rj": "r j",
}


# ── Canonical name alias table ──────────────────────────────────────────
# Map of ``normalized_name → canonical_normalized_name`` used by
# ``resolve_canonical_name`` to collapse nickname / abbreviated first-
# name / known-variant spellings onto a single canonical form.
#
# Every entry here is a **deterministic** collapse — there is no fuzzy
# matching in this layer.  All keys are the output of
# ``normalize_player_name`` (no punctuation, lowercased, suffixes
# stripped, initials collapsed).  Values are the canonical form that
# downstream code uses for the join key.
#
# Adding an entry:
#   1. Normalize the variant spelling through ``normalize_player_name``
#      to derive the key.
#   2. Normalize the canonical spelling through ``normalize_player_name``
#      to derive the value.
#   3. Add the ``(key, value)`` pair here.
#
# Guidance for what belongs here:
#   * First-name nickname → formal (``pat mahomes`` → ``patrick mahomes``)
#   * Abbreviated middle initial drift (``marvin mitchell harrison`` →
#     ``marvin harrison``)
#   * Known source-specific variant spellings where one feed writes a
#     common short form and another feed writes the long form.
#
# What does NOT belong here:
#   * Two different players with confusable names — never alias across
#     distinct people.  Use ``canonical_player_key(name, position)``
#     with a position hint to keep them apart.
#   * Bulk suffix handling (Jr, Sr, II, III, IV, V) — these are
#     stripped deterministically by ``normalize_player_name`` already
#     and do not need to be re-asserted here.
CANONICAL_NAME_ALIASES: dict[str, str] = {
    # ── First-name nicknames / formal expansions ──
    "pat mahomes": "patrick mahomes",
    "mike evans": "michael evans",
    "mike gesicki": "mike gesicki",  # explicit identity — "michael gesicki"
    # is NOT used anywhere
    "kenny pickett": "kenny pickett",
    "chig okonkwo": "chigoziem okonkwo",
    "hollywood brown": "marquise brown",
    "bo nix": "bo nix",
    "nelly korda": "nelly korda",  # sanity placeholder — explicit
    "jaylen wright": "jaylen wright",  # explicit identity anchor
    # Abbreviated → full middle/first
    "pj walker": "pj walker",  # explicit anchor for the QB
    # ── Cross-source first-name drift ──────────────────────────────────
    # Verified by checking all three source CSVs (KTC, IDPTradeCalc,
    # DLF) and the dynasty_data player pool.
    "greg rousseau": "gregory rousseau",  # IDPTC "Greg" ↔ DLF "Gregory"
    "foye oluokun": "foyesade oluokun",  # DLF/IDPTC "Foye" ↔ dynasty_data "Foyesade"
    "josh metellus": "joshua metellus",  # DLF "Josh" ↔ dynasty_data "Joshua"
    "kam curl": "kamren curl",  # dynasty_data "Kam" ↔ DLF/IDPTC "Kamren"
    "kamren curl": "kamren curl",  # anchor the canonical form
    # ── 2026-07 identity sweep (scripts/audit_identity_matches.py) ─────
    # Each entry below was verified same-player via position + age +
    # team agreement between the source CSV row and the Sleeper-pool
    # row (see docs/identity-audit-2026-07.md for the evidence table).
    # Values are the pool's canonical spelling (normalize_player_name
    # output of the dynasty_data player name).
    "kenneth gainwell": "kenny gainwell",  # KTC/DLF/FP/DS/Flock/DN "Kenneth"
    # ↔ Sleeper "Kenny" (RB, TB, age 27; previously only recovered on
    # pfkDynasty via its sleeper_id column)
    "gabriel davis": "gabe davis",  # KTC/IDPTC "Gabriel" ↔ Sleeper "Gabe" (WR, 27)
    "alim mcneil": "alim mcneill",  # IDPTC single-l typo ↔ "McNeill" (DL, DET, 26)
    "andru phillips": "dru phillips",  # IDPTC/idpShow/DS "Andru" ↔ Sleeper
    # "Dru" (CB, NYG, 24)
    "camryn bynum": "cam bynum",  # IDPTC/idpShow/DS "Camryn" ↔ Sleeper "Cam" (S, IND, 28)
    "nickolas martin": "nick martin",  # IDPTC/idpShow "Nickolas" ↔ Sleeper
    # "Nick" (LB, SF, 23 — NOT the retired IND center, age rules him out)
    "josh palmer": "joshua palmer",  # DLF "Josh" ↔ Sleeper "Joshua" (WR, BUF, 26)
    "cameron skattebo": "cam skattebo",  # DS "Cameron" ↔ Sleeper "Cam" (RB, NYG, 24)
    "cameron ward": "cam ward",  # DS "Cameron" ↔ Sleeper "Cam" (QB, TEN, 24)
    "nathan landman": "nate landman",  # DS "Nathan" ↔ Sleeper "Nate" (LB, LAR, 27)
    "patrick surtain": "pat surtain",  # DS "Patrick Surtain II" ↔ Sleeper
    # "Pat Surtain" (CB, DEN, 26; suffix already stripped by normalize)
    "daxton hill": "dax hill",  # DS "Daxton" ↔ Sleeper "Dax" (S, CIN, 25)
    "donaven mcculley": "donoven mcculley",  # DS "Donaven" ↔ pool "Donoven"
    # (WR, MIA, 23 — vendor a/o vowel drift for the UDFA)
    "chauncey gardner johnson": "cj gardner johnson",  # DS legal first name
    # ↔ Sleeper "C.J. Gardner-Johnson" (S/DB, BUF, 28)
    "michael jackson": "mike jackson",  # DS "Michael" ↔ Sleeper "Mike"
    # (CB, CAR, 29 on both sides)
    "ahmad gardner": "sauce gardner",  # DS legal first name ↔ Sleeper
    # "Sauce" (CB, IND, 24)
    "justin madubuike": "nnamdi madubuike",  # DLF IDP still uses the
    # pre-2024 name; player renamed Justin → Nnamdi (DL, BAL, 28)
    "robert henry": "rob henry",  # DS/FP "Robert Henry Jr." ↔ pool
    # "Rob Henry" (RB, UTSA UDFA → WAS, age 24 on both sides)
}


# ── Position family groups ──────────────────────────────────────────────
# Coarser-than-position-family grouping used by collision detection and
# position-aware canonical keys.  Two players with different *groups*
# are always different canonical entities — we never merge an IDP LB
# with an offense WR just because they happen to share a normalized
# name.
POSITION_GROUP_OFFENSE = "OFFENSE"
POSITION_GROUP_IDP = "IDP"
POSITION_GROUP_PICK = "PICK"
POSITION_GROUP_KICKER = "KICKER"
POSITION_GROUP_OTHER = "OTHER"

_OFFENSE_FAMILIES = frozenset({"QB", "RB", "WR", "TE"})
_IDP_FAMILIES = frozenset({"DL", "LB", "DB"})
_KICKER_FAMILIES = frozenset({"K", "P"})


def _ascii_fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _collapse_initials(s: str) -> str:
    """Collapse adjacent single-letter words into a single token.

    'a j brown' → 'aj brown'
    't j hockenson' → 'tj hockenson'
    'd k metcalf' → 'dk metcalf'

    This ensures 'T.J. Hockenson' (→ 't j hockenson') matches
    'TJ Hockenson' (→ 'tj hockenson').
    """
    parts = s.split()
    result = []
    i = 0
    while i < len(parts):
        if len(parts[i]) == 1 and parts[i].isalpha():
            # Collect consecutive single-letter words
            initials = parts[i]
            while i + 1 < len(parts) and len(parts[i + 1]) == 1 and parts[i + 1].isalpha():
                i += 1
                initials += parts[i]
            result.append(initials)
        else:
            result.append(parts[i])
        i += 1
    return " ".join(result)


def normalize_player_name(name: str | None) -> str:
    """Collapse a display name to the deterministic join key.

    The transform is non-negotiable and applied to every name that
    participates in a cross-source join.  The steps are:

    1. ASCII fold (``é → e``, ``ñ → n``).
    2. Lowercase, strip leading/trailing whitespace.
    3. Replace ``&`` with ``and`` (handles "AJ and Friends" style).
    4. Strip generational suffixes (``jr|sr|ii|iii|iv|v|dr``) — the
       regex runs before punctuation stripping so "Jr." is handled.
    5. Replace non-alphanumerics (apostrophes, hyphens, periods) with
       spaces.
    6. Collapse repeated whitespace.
    7. Collapse adjacent single-letter tokens into one token
       (``t j watt`` → ``tj watt``).

    The output is a lowercase ASCII string with single-space tokens.
    ``normalize_player_name(None)`` and empty input return ``""``.
    """
    if not name:
        return ""
    s = _ascii_fold(name).lower().strip()
    s = s.replace("&", " and ")
    # Drop apostrophes without inserting whitespace so ``Ja'Marr`` and
    # ``JaMarr``, ``D'Andre`` and ``DAndre`` collide on the same key.
    s = _APOSTROPHE_RE.sub("", s)
    s = _SUFFIX_RE.sub("", s)
    s = _NON_ALNUM_RE.sub(" ", s).strip()
    s = re.sub(r"\s+", " ", s)
    s = _collapse_initials(s)
    return s


def strip_display_suffix(name: object) -> str:
    """Strip a generational suffix / trailing parenthetical, PRESERVING
    case and spacing.

    This is NOT a join key — it is a DISPLAY-name cleanup.  Every other
    helper in this module lowercases, which is wrong for anything that
    will be rendered or stored as a label.

    Why it exists (audit N3, 2026-07-29): the contract's player
    vocabulary comes from ``Dynasty Scraper.py::clean_name``, which
    strips generational suffixes — measured on the live payload, **0 of
    1076** contract keys carry ``Jr.`` / ``III`` / a parenthetical.
    Sleeper's raw ``full_name`` keeps them.  So any code that falls back
    to a raw Sleeper name emits a label in a foreign vocabulary, and
    every name-keyed consumer downstream (waiver ownership, angle,
    replacement, FAAB contention) then fails to join it.

    Deliberately narrow: it does not fold accents, drop apostrophes,
    collapse initials or lowercase, because the result is shown to a
    user.  It handles the two divergences actually observed between the
    Sleeper dump and the contract.

        >>> strip_display_suffix("Marvin Harrison Jr.")
        'Marvin Harrison'
        >>> strip_display_suffix("Kenneth Walker III")
        'Kenneth Walker'
        >>> strip_display_suffix("Michael Pittman (WR)")
        'Michael Pittman'
        >>> strip_display_suffix("Amon-Ra St. Brown")
        'Amon-Ra St. Brown'
    """
    if not name:
        return ""
    s = str(name).strip()
    if not s:
        return ""
    # Trailing parenthetical, e.g. "Name (WR)" / "Name (IR)".
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()
    # Generational suffix, only at the END and only as a whole token, so
    # "Vita Vea" keeps its "Vea" and a mid-name "V" is untouched.
    s = re.sub(r"[,\s]+(Jr\.?|Sr\.?|I{2,3}|IV|VI?)\s*$", "", s, flags=re.IGNORECASE).strip()
    return s


def compact_name_key(name: object) -> str:
    """Lowercase, alphanumerics-only join key (family 2 in the module
    registry above).

    ``"D.J. Moore"``, ``"DJ Moore"`` and ``"djmoore"`` all collapse to
    ``"djmoore"``.  Spaces are dropped along with every other
    non-alphanumeric character.

    This is NOT :func:`normalize_player_name` and is not a substitute
    for it.  It does not strip generational suffixes
    (``"Kenneth Walker III" → "kennethwalkeriii"``) and it does not
    ASCII-fold (``str.isalnum()`` is Unicode-aware, so
    ``"Juanyéh Thomas" → "juanyéhthomas"``).  Both properties are
    load-bearing for its current consumers, which build and query the
    key on the same side of the wire:

      * ``src/adapters/ktc_crowd_faab.build_crowd_bid_map`` keys the
        crowd FAAB bid map with it, and
        ``src/trade/faab_recommender._ktc_crowd_blend`` looks that map
        up with it.  These two MUST agree — they did not until
        2026-07-29, which silently disabled the crowd calibration
        factor for every name containing a space.
      * ``src/roster_intel/roster_source`` keys its value index and
        roster join with it.

    Do not "fix" the accent behaviour without measuring: an ASCII fold
    here changes the roster_intel join and the FAAB crowd map for every
    accented player name.
    """
    return "".join(c for c in str(name or "").lower() if c.isalnum())


def resolve_canonical_name(name: str | None) -> str:
    """Return the canonical normalized name for ``name``.

    Runs ``normalize_player_name`` then applies the
    :data:`CANONICAL_NAME_ALIASES` table to collapse nickname /
    abbreviated-first-name variants onto a single canonical key.

    The alias table is deliberately small and deterministic; no fuzzy
    matching happens here.  If no alias applies, the normalized name
    is returned unchanged, so this function is a safe drop-in
    replacement for ``normalize_player_name`` in any caller that wants
    alias-aware joins.
    """
    norm = normalize_player_name(name)
    if not norm:
        return ""
    return CANONICAL_NAME_ALIASES.get(norm, norm)


def canonical_position_group(position: str | None) -> str:
    """Return the coarse position group for a raw or normalized position.

    Mapping:

    * ``QB``, ``RB``, ``WR``, ``TE``  → ``OFFENSE``
    * ``DL``, ``LB``, ``DB`` (plus sub-families via
      ``normalize_position_family``) → ``IDP``
    * ``PICK`` → ``PICK``
    * ``K``, ``P``  → ``KICKER``
    * empty / unknown → ``OTHER``

    This is the grouping used by :func:`canonical_player_key` and the
    identity collision checks; it intentionally lumps DL/LB/DB into
    one ``IDP`` bucket because those families share a common IDP
    source pool and the same entity can drift between DL and LB
    depending on the source (e.g. Micah Parsons listed as LB in DLF
    and DL in Sleeper).
    """
    fam = normalize_position_family(position)
    if not fam:
        return POSITION_GROUP_OTHER
    if fam == "PICK":
        return POSITION_GROUP_PICK
    if fam in _OFFENSE_FAMILIES:
        return POSITION_GROUP_OFFENSE
    if fam in _IDP_FAMILIES:
        return POSITION_GROUP_IDP
    if fam in _KICKER_FAMILIES:
        return POSITION_GROUP_KICKER
    return POSITION_GROUP_OTHER


def canonical_player_key(
    name: str | None,
    position: str | None = None,
) -> str:
    """Return a position-aware canonical key for a player.

    The key has the form ``"<canonical_name>::<position_group>"``
    where ``canonical_name`` is the output of
    :func:`resolve_canonical_name` and ``position_group`` is the
    output of :func:`canonical_position_group`.  If ``position`` is
    omitted the group portion is ``"*"`` so callers can still compare
    unknown-position candidates against a known-position row as a
    last-resort match.

    The position group makes join keys **collision-safe**: Quay
    Walker (IDP LB) and Kenneth Walker (OFFENSE RB) get different
    keys (``walker::IDP`` vs ``walker::OFFENSE``) even though the
    normalized last name matches, which is essential to prevent the
    "near name, same surname, different player" collision class.

    Example:
        >>> canonical_player_key("Kenneth Walker III", "RB")
        'kenneth walker::OFFENSE'
        >>> canonical_player_key("Quay Walker", "LB")
        'quay walker::IDP'
        >>> canonical_player_key("Patrick Mahomes", "QB")
        'patrick mahomes::OFFENSE'
    """
    cname = resolve_canonical_name(name)
    if not cname:
        return ""
    group = canonical_position_group(position) if position else "*"
    return f"{cname}::{group}"


def normalize_team(team: str | None) -> str:
    if not team:
        return ""
    return _ascii_fold(team).upper().strip()


# IDP position priority, highest first. When Sleeper (or any other
# source) labels a player with multiple fantasy-eligible IDP positions
# we collapse them to a single canonical family using this ordering:
#
#   DL > DB > LB
#
# Concretely:
#   * DL + LB → DL
#   * DB + LB → DB
#   * DL + DB → DL   (per product decision; DL is the "heavier" role)
#   * LB is only emitted when the player is exclusively LB-eligible.
#
# Every site in the codebase that reads a raw Sleeper position —
# whether a single string, a slash-joined pair, or a
# ``fantasy_positions`` list — should either call
# :func:`resolve_idp_position` directly or go through
# :func:`normalize_position_family` which delegates to it.
IDP_PRIORITY: tuple[str, ...] = ("DL", "DB", "LB")


def resolve_idp_position(*candidates: str | list[str] | tuple[str, ...] | None) -> str:
    """Collapse a pile of raw Sleeper position candidates to one IDP family.

    ``candidates`` accepts any mix of single strings (``"DE"``),
    slash-joined pairs (``"DL/LB"``), and list/tuple values
    (Sleeper's ``fantasy_positions``). Every token is normalised via
    :data:`POSITION_ALIASES`; the first IDP family we see from
    :data:`IDP_PRIORITY` wins. If no IDP family is found an empty
    string is returned so callers can fall through to their existing
    offense handling.

    Examples
    --------
    >>> resolve_idp_position("DL", "LB")
    'DL'
    >>> resolve_idp_position("LB", "DB")
    'DB'
    >>> resolve_idp_position(["DE", "OLB"])    # DE maps to DL, OLB to LB → DL
    'DL'
    >>> resolve_idp_position("LB")              # exclusive LB-only
    'LB'
    >>> resolve_idp_position("CB")
    'DB'
    >>> resolve_idp_position("QB")              # non-IDP → empty
    ''
    """
    collected: set[str] = set()
    saw_non_idp = False

    def _accept(token: str) -> None:
        nonlocal saw_non_idp
        if not token:
            return
        tok = _ascii_fold(token).upper().strip()
        if not tok:
            return
        # Slash / comma / pipe / whitespace-joined multi-position
        # strings: split and recurse per piece. CSV exports of
        # ``fantasy_positions`` typically emit "DL,LB"; Sleeper's
        # own CSVs sometimes use "DL/LB"; DLF occasionally emits
        # "DL LB" space-delimited.
        if re.search(r"[/,|\s]", tok):
            for piece in re.split(r"[/,|\s]+", tok):
                _accept(piece)
            return
        # Strip trailing digits (e.g. "LB1" from DLF CSVs) and aliases.
        tok_base = re.sub(r"\d+$", "", tok) or tok
        canonical = POSITION_ALIASES.get(tok_base)
        if canonical in {"DL", "LB", "DB"}:
            collected.add(canonical)
        elif canonical:
            # Known non-IDP (QB/RB/WR/TE/K/PICK). Note its presence so
            # we can enforce LB exclusivity below; unknown tokens are
            # ignored to stay lenient on misformatted inputs.
            saw_non_idp = True

    for cand in candidates:
        if cand is None:
            continue
        if isinstance(cand, (list, tuple, set)):
            for item in cand:
                if isinstance(item, str):
                    _accept(item)
        elif isinstance(cand, str):
            _accept(cand)

    for family in IDP_PRIORITY:
        if family not in collected:
            continue
        if family == "LB" and saw_non_idp:
            # "LB only when the player is exclusively LB-eligible" —
            # if any non-IDP family also appeared, the player is not
            # a pure IDP and we refuse to emit LB. DL / DB already
            # matched above (they win over non-IDP context because
            # they are strong, unambiguous IDP signals).
            return ""
        return family
    return ""


def normalize_position_family(pos: str | None) -> str:
    if not pos:
        return ""
    p = _ascii_fold(pos).upper().strip()

    # Handle Sleeper-style dual positions (DL/LB, DB/LB, DL/DB) BEFORE
    # the tokenisation branches below. resolve_idp_position applies
    # the DL > DB > LB priority so a dual-eligible player always
    # collapses the same way no matter which source supplied them.
    # Match every separator the resolver accepts — "/" (Sleeper CSV),
    # "," (fantasy_positions column export), "|" (some third-party
    # dumps), and ASCII whitespace (DLF "DL LB"). Keeping the gate
    # symmetric with the resolver is what prevents "LB,CB" or
    # "LB CB" from falling through to first-token handling.
    _MULTI_SEP_RE = re.compile(r"[/,|\s]")
    if _MULTI_SEP_RE.search(p):
        idp_resolved = resolve_idp_position(p)
        if idp_resolved:
            return idp_resolved
        # Empty resolver result — either the pair has no IDP family
        # at all (e.g. "WR/KR") or it mixes LB with non-IDP
        # (e.g. "LB/QB", "LB,WR") and the exclusivity rule refused
        # to emit LB. In both cases fall through to the *first
        # non-IDP* part so the result is order-independent.
        parts = [piece.strip() for piece in _MULTI_SEP_RE.split(p) if piece.strip()]

        def _is_idp_part(piece: str) -> bool:
            base = re.sub(r"\d+$", "", piece) or piece
            return POSITION_ALIASES.get(base) in {"DL", "LB", "DB"}

        non_idp = next((x for x in parts if not _is_idp_part(x)), "")
        if non_idp:
            p = non_idp
        elif parts:
            # All-IDP multi-string that still resolved empty shouldn't
            # happen (LB/DL → DL; LB/CB → DB). Defensive fall-through.
            p = parts[0]

    p = p.replace("(", " ").replace(")", " ")
    p = re.sub(r"[^A-Z0-9]+", " ", p).strip()
    tokens = p.split()
    if not tokens:
        return ""
    t = tokens[0]
    # Strip trailing rank digits (e.g. "LB1" → "LB", "DL70" → "DL")
    # DLF IDP CSVs use formats like "LB1", "LB67" for positional rank.
    t_base = re.sub(r"\d+$", "", t) or t
    if t_base in POSITION_ALIASES:
        return POSITION_ALIASES[t_base]
    # startsWith fallback for compound tokens (e.g. "QBWR")
    for prefix in ("QB", "RB", "WR", "TE"):
        if t_base.startswith(prefix):
            return prefix
    return t


# ── First-name variant equivalence (W06-F001) ────────────────────────

#: Shortest first-name prefix that may stand in for a longer name.
#: Two characters would let "Ty Johnson" absorb "Tyler Johnson", who are
#: different people; single letters are an INITIAL and belong to the
#: initial-matching rung, which carries its own guards.
_MIN_VARIANT_PREFIX = 3


def is_first_name_variant(a: object, b: object) -> bool:
    """Are these two names the same human under first-name drift?

    The board's merge key is a canonical NAME. ``CANONICAL_NAME_ALIASES``
    carries hand-written pairs (Kenneth→Kenny, Chig→Chigoziem) and had
    none for Matt↔Matthew or Jam↔Jamarion, so one human occupied two
    board rows — a resolved row and an unresolved ghost holding stranded
    vendor votes (W06-F001). Enumerating more pairs would fix those two
    players and nothing else; this states the RULE instead.

    True only when every one of these holds:

    * both names have at least two parts;
    * everything after the first name matches exactly (surname AND any
      middle parts — "Chris Del Rio" is not "Christian Rio");
    * the first names differ, and the shorter is a strict prefix of the
      longer;
    * the shorter first name is at least :data:`_MIN_VARIANT_PREFIX`
      characters.

    **This is deliberately not sufficient on its own to merge two rows.**
    "Chris Smith" and "Christian Smith" satisfy it and may well be two
    people. The caller must additionally establish that only one of them
    carries an identity — merging a resolved row with an *unidentified*
    one cannot silently fuse two known players, because two known
    players both carry ids. A confident wrong merge is worse than the
    ghost it would have removed, so the rule is the cheap half of the
    test and the identity gate is the load-bearing half.
    """
    a_parts = str(a or "").strip().lower().split()
    b_parts = str(b or "").strip().lower().split()
    if len(a_parts) < 2 or len(b_parts) < 2:
        return False
    if a_parts[1:] != b_parts[1:]:
        return False
    first_a, first_b = a_parts[0], b_parts[0]
    if first_a == first_b:
        return False
    shorter, longer = sorted((first_a, first_b), key=len)
    if len(shorter) < _MIN_VARIANT_PREFIX:
        return False
    return longer.startswith(shorter)
