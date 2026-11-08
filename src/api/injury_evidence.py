"""Injury evidence: classify and attribute a news item BEFORE it may reach the
injury discount (W21-F001, owner master directive 2026-11-08 section 19 priority 14).

Only a confirmed or credibly reported CURRENT injury, attributed to the right
player, becomes an injury assessment.  Everything else (contract, transaction,
suspension, coaching, rumor, recovery, return to play, negated or historical
language, unrelated mentions) is labelled and kept out of the severity ->
multiplier table in ``injury_impact``.  This module decides NOTHING about how
large a discount is; it only decides whether an item is injury evidence for a
specific player.  Unknown is never "injury": every unprovable condition fails
closed with a named reason.
"""

from __future__ import annotations

import re
from typing import Any

from src.identity.name_primitives import normalize_lookup_name
from src.identity.resolution import pos_family

CONFIRMED_INJURY = "confirmed_injury"
SPECULATION = "speculation"
RECOVERY_UPDATE = "recovery_update"
RETURN_TO_PLAY = "return_to_play"
CONTRACT = "contract_extension"
TRANSACTION = "transaction"
SUSPENSION = "suspension"
COACHING = "coaching_change"
HISTORICAL = "historical_injury_reference"
NEGATED = "negated_injury"
AMBIGUOUS = "ambiguous"
UNRELATED = "unrelated_mention"

# Classes that RESOLVE or contradict a current injury claim for the same player.
RESOLVING = frozenset({NEGATED, RETURN_TO_PLAY})


def _rx(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


# GENUINE resolution only.  Negation/return words are scoped to the injury CLAIM: "not cleared",
# "will not return", "questionable to return" CONFIRM an injury and are rewritten (below) before
# the resolution patterns run.
_NEGATED = _rx(
    (
        r"no injur\w*",
        r"not injured",
        r"isn'?t injured",
        r"wasn'?t injured",
        r"injury[- ]free",
        r"free of injury",
        r"cleared",
        r"avoided (?:a |any )?(?:serious |major )?injury",
        r"no structural damage",
        r"dodged (?:a |an )?injury",
        r"injury (?:fears|concerns|scare) (?:eased|allayed|unfounded)",
    )
)
# "not cleared", "hasn't been cleared", "not yet cleared" -> the player is NOT cleared: an injury.
_NOT_CLEARED = re.compile(
    r"\b(?:not|never|n't|yet|without)(?:\W+\w+){0,2}?\W+cleared\b", re.IGNORECASE
)
# Negated / hedged RETURN is an availability loss, i.e. injury-confirming.
_NEG_RETURN = re.compile(
    r"\b(?:(?:will|would|could)\s+not|won'?t|wouldn'?t|not\s+(?:expected|likely)\s+to|"
    r"unlikely\s+to|unable\s+to|did\s+not|didn'?t|doesn'?t|does\s+not|questionable\s+to|"
    r"doubtful\s+to|not\s+able\s+to|no\s+timetable\s+(?:for|to)|"
    r"(?:expected|projected|potential|target\w*)(?:\s+a)?)"
    r"\s+(?:\w+\s+)?return\w*|\breturn\w*\s+(?:in|by|around|after\s+\d|no\s+earlier)\b",
    re.IGNORECASE,
)
_RETURN = _rx(
    (
        r"returns?",
        r"returned",
        r"returning",
        r"back (?:at|in|to) practice",
        r"full participant",
        r"full practice",
        r"activated",
        r"expected to play",
        r"will play",
        r"set to play",
        r"good to go",
        r"removed from the injury report",
        r"off the injury report",
    )
)
_RECOVERY = _rx(
    (
        r"recover\w*",
        r"rehab\w*",
        r"progress\w*",
        r"on track",
        r"ahead of schedule",
        r"healing",
        r"making strides",
    )
)
_HISTORICAL = _rx(
    (
        r"last (?:season|year)",
        r"previous\w*",
        r"in 20\d\d",
        r"injury[- ]prone",
        r"injury history",
        r"after missing",
        r"missed (?:\d+|several|multiple|most|much)",
        r"coming off",
        r"returned from",
        r"former injur\w*",
    )
)
# Hedges on whether an injury EXISTS.  A hedged duration/availability ("could miss the rest of
# the season", "may not play Sunday") hedges the consequence of a stated injury, not its existence.
_SPECULATION = _rx(
    (
        r"rumou?rs?",
        r"speculat\w*",
        r"unconfirmed",
        r"(?:could|might|may)\s+(?:possibly\s+)?(?:be|have)\s+(?:been\s+)?"
        r"(?:dealing|suffering|nursing|hurt|injured|aggravat\w*|re-?injur\w*|suffer\w*|tweak\w*|battling)",
        r"fears?",
        r"unclear",
        r"unknown",
        r"possible",
        r"potential\w*",
        r"concerns?",
        r"worr\w*",
        r"if he",
        r"would be",
        r"monitoring",
        r"wait(?:ing)? (?:on|for)",
    )
)
_INJURY = _rx(
    (
        r"injur\w*",
        r"hurt",
        r"torn",
        r"tear",
        r"acl",
        r"mcl",
        r"pcl",
        r"achilles",
        r"fractur\w*",
        r"broken",
        r"surgery",
        r"strain\w*",
        r"sprain\w*",
        r"concussion",
        r"hamstring",
        r"high[- ]ankle",
        r"ankle",
        r"knee",
        r"shoulder",
        r"groin",
        r"calf",
        r"quad",
        r"foot",
        r"wrist",
        r"placed on (?:ir|injured reserve)",
        r"injured reserve",
        r"on the ir",
        r"to ir",
        r"ruled out",
        r"out for (?:the )?(?:season|year|\d+|several|multiple)",
        r"season[- ]ending",
        r"questionable",
        r"doubtful",
        r"day[- ]to[- ]day",
        r"carted off",
        r"left the game",
        # availability loss without a body part
        r"\b(?:will|to|expected to|likely to)\s+miss\s+(?:the\s+)?(?:next|rest|remainder|\d|several|multiple|extended)",
        r"out\s+indefinitely",
        r"sidelined",
        r"week[- ]to[- ]week",
        r"out\s+(?:until|through|vs|against|for\s+(?:sunday|monday|thursday|saturday|friday))",
    )
)
_CONTRACT = _rx(
    (
        r"contract",
        r"extension",
        r"extended",
        r"highest[- ]paid",
        r"restructur\w*",
        r"re[- ]?sign\w*",
        r"signs?",
        r"signed",
        r"deal",
        r"holdout",
        r"salary",
    )
)
_TRANSACTION = _rx((r"trade", r"traded", r"acquire\w*", r"released", r"waived", r"claimed", r"cut"))
_SUSPENSION = _rx(
    (
        r"suspen\w*",
        r"arrest\w*",
        r"banned",
        r"violat\w*",
        r"personal (?:reasons|matter\w*)",
        r"family",
        r"bereavement",
    )
)
_COACHING = _rx(
    (r"coach\w*", r"coordinator", r"play[- ]?calling", r"fired", r"hired", r"depth chart")
)

_CLAUSE_SPLIT = re.compile(r"[.;!?\n:]+|\s+plus\s+|\s+-\s+|\s+—\s+|,\s+while\s+", re.IGNORECASE)


def _norm(text: str) -> str:
    s = str(text or "").lower().replace("’", "'")
    s = re.sub(r"'s\b", "", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s.replace("-", " "))
    return re.sub(r"\s+", " ", s).strip()


def _name_in_clause(norm_name: str, clause: str) -> bool:
    if not norm_name:
        return False
    return re.search(r"\b" + re.escape(norm_name) + r"\b", _norm(clause)) is not None


def _clauses(item: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("headline", "summary", "body"):
        txt = str(item.get(key) or "")
        if not txt:
            continue
        for c in _CLAUSE_SPLIT.split(txt):
            c = c.strip()
            if c and c not in out:
                out.append(c)
    return out


def _scope_resolution(clause: str) -> str:
    """Rewrite negated/hedged returns and negated clearances into injury-CONFIRMING wording so
    resolution patterns only ever see genuine resolution."""
    out = _NEG_RETURN.sub(" out ", clause)
    out = _NOT_CLEARED.sub(" injured ", out)
    return out


def _classify_clause(clause: str) -> str:
    """Classify ONE clause that names the player."""
    text = _scope_resolution(clause)
    # An absence-of-finding phrase ("no structural damage") does not cancel an injury named
    # elsewhere in the clause ("... but ankle sprain keeps him out").
    residue = _NEGATED.sub(" ", text)
    residual_injury = _INJURY.search(residue)
    if _NEGATED.search(text) and not residual_injury:
        return NEGATED
    inj = residual_injury
    other_hits = [
        label
        for label, rx in (
            (CONTRACT, _CONTRACT),
            (TRANSACTION, _TRANSACTION),
            (SUSPENSION, _SUSPENSION),
            (COACHING, _COACHING),
        )
        if rx.search(text)
    ]
    ret = _RETURN.search(text)
    if not inj:
        if ret:
            return RETURN_TO_PLAY
        return other_hits[0] if other_hits else UNRELATED
    if ret:
        return RETURN_TO_PLAY
    if other_hits:
        # Injury vocabulary and a non-injury topic in one clause: unprovable which one the
        # claim is about.  Fail closed.
        return AMBIGUOUS
    if _HISTORICAL.search(text):
        return HISTORICAL
    if _RECOVERY.search(text):
        return RECOVERY_UPDATE
    if _SPECULATION.search(text):
        return SPECULATION
    return CONFIRMED_INJURY


def assess_item(
    item: dict[str, Any],
    *,
    player_name: str | None,
    position: Any = None,
    team: Any = None,
    name_collision: bool = False,
) -> dict[str, Any]:
    """Return ``{"classification", "attributed", "reason"}`` for one item and one player.

    ``classification == CONFIRMED_INJURY`` is the ONLY value that may feed the discount.
    """

    def out(cls: str, reason: str, attributed: bool = False) -> dict[str, Any]:
        return {"classification": cls, "attributed": attributed, "reason": reason}

    norm_name = normalize_lookup_name(player_name or "")
    if not norm_name:
        return out(UNRELATED, "player_identity_unavailable")
    if name_collision:
        return out(AMBIGUOUS, "same_name_players")
    mention = None
    for p in item.get("players") or []:
        if isinstance(p, dict) and normalize_lookup_name(p.get("name") or "") == norm_name:
            mention = p
            break
    if mention is None:
        return out(UNRELATED, "player_not_in_item_mentions")
    if mention.get("ambiguous"):
        return out(AMBIGUOUS, "item_marks_identity_ambiguous")
    m_pos, m_team = mention.get("position"), mention.get("team")
    if m_pos and position and pos_family(m_pos) != pos_family(position):
        return out(AMBIGUOUS, "position_mismatch")
    if m_team and team and str(m_team).strip().upper() != str(team).strip().upper():
        return out(AMBIGUOUS, "team_mismatch")
    classes = [_classify_clause(c) for c in _clauses(item) if _name_in_clause(norm_name, c)]
    if not classes:
        return out(UNRELATED, "player_not_named_in_text")
    # Strongest evidence the text gives about THIS player; resolving language first.
    for cls in (NEGATED, RETURN_TO_PLAY, AMBIGUOUS, HISTORICAL, RECOVERY_UPDATE, SPECULATION):
        if cls in classes:
            return out(cls, "classified_from_player_clause", True)
    if CONFIRMED_INJURY in classes:
        return out(CONFIRMED_INJURY, "injury_claim_in_player_clause", True)
    return out(classes[0], "non_injury_topic", True)
