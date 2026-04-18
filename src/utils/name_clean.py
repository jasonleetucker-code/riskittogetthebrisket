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


# ── Canonical position aliases ──────────────────────────────────────────
# Single source of truth for mapping raw position strings to league-standard
# position families. All modules should import from here.
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
    "greg rousseau": "gregory rousseau",      # IDPTC "Greg" ↔ DLF "Gregory"
    "foye oluokun": "foyesade oluokun",       # DLF/IDPTC "Foye" ↔ dynasty_data "Foyesade"
    "josh metellus": "joshua metellus",       # DLF "Josh" ↔ dynasty_data "Joshua"
    "kam curl": "kamren curl",                # dynasty_data "Kam" ↔ DLF/IDPTC "Kamren"
    "kamren curl": "kamren curl",             # anchor the canonical form
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
