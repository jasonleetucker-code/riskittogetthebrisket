"""The deep-tail rookie VOTE rule has its own registry field.

WHY THIS EXISTS
===============
Two concepts used to share one flag.  ``excludes_rookies`` is a FACTUAL
coverage claim -- "this board structurally cannot list a rookie" -- read by
``_expected_sources_for_position``, ``sparse_evidence`` and the source
census.  The vote loop's "self-correcting rookie exclusion" (#134, April
2026) -- a rookie ranked past 80 % of a source's pool casts no vote from it
-- is a METHODOLOGY choice that happened to key on the same flag.

G2-D3 (#2001) corrected the factual flag to False for ``fantasyProsIdp`` and
``dlfIdp`` because both CSVs DO rank rookies, which silently switched the
methodology off.  The rule now rides on ``drop_deep_tail_rookies`` alone,
set on exactly those two sources so the pre-#2001 voting is restored while
the owner decides the rule on its own merits.

Pinned here, on synthetic rows (no live board, hard gate):

* the new field ALONE drives the skip;
* ``excludes_rookies`` no longer does;
* the registry declares the field on exactly the two sources, beside a
  False factual flag, and the frontend mirror agrees.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

from src.api import data_contract as dc
from src.api.data_contract import _compute_unified_rankings

_FP = "fantasyProsIdp"
_POOL = 20  # defenders FP ranks; the rookie is the 21st (deep tail)


def _synthetic_rank(rank: int) -> int:
    return dc._RANK_TO_SYNTHETIC_VALUE_OFFSET * 100 - rank * 100


def _row(name: str, position: str, *, rookie: bool = False, **sites: Any) -> dict[str, Any]:
    original_ranks = {
        key: float((dc._RANK_TO_SYNTHETIC_VALUE_OFFSET * 100 - v) / 100)
        for key, v in sites.items()
        if v and v >= dc._RANK_TO_SYNTHETIC_VALUE_OFFSET * 50
    }
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "assetClass": "idp" if position in ("DL", "LB", "DB") else "offense",
        "rookie": rookie,
        "canonicalSiteValues": dict(sites),
        "sourceOriginalRanks": original_ranks,
        "values": {
            "overall": max((v or 0) for v in sites.values()) if sites else 0,
            "rawComposite": None,
            "finalAdjusted": None,
            "displayValue": None,
        },
    }


def _board(*, rookie_fp_rank: int) -> list[dict[str, Any]]:
    rows = [
        _row(
            f"Receiver {i:02d}",
            "WR",
            ktcCrowdSfTep=9900 - i * 200,
            idpTradeCalc=9900 - i * 120,
        )
        for i in range(1, 21)
    ]
    for i in range(1, _POOL + 1):
        # Leave FP rank ``rookie_fp_rank`` free for the rookie.
        fp_rank = i if i < rookie_fp_rank else i + 1
        rows.append(
            _row(
                f"Defender {i:02d}",
                "LB",
                idpTradeCalc=6400 - i * 150,
                fantasyProsIdp=_synthetic_rank(fp_rank),
            )
        )
    rows.append(
        _row(
            "Rookie Tail",
            "LB",
            rookie=True,
            idpTradeCalc=6400 - 10 * 150,
            fantasyProsIdp=_synthetic_rank(rookie_fp_rank),
        )
    )
    return rows


def _fp_entry() -> dict[str, Any]:
    return next(s for s in dc._RANKING_SOURCES if s["key"] == _FP)


def _rookie_votes_fp(*, rookie_fp_rank: int, **registry: Any) -> bool:
    rows = _board(rookie_fp_rank=rookie_fp_rank)
    with mock.patch.dict(_fp_entry(), registry):
        _compute_unified_rankings(rows, {})
    rookie = next(r for r in rows if r["canonicalName"] == "Rookie Tail")
    return _FP in (rookie.get("sourceRanks") or {})


def test_the_deep_tail_field_drives_the_skip():
    # Rank 21 of a 21-row pool is past 80 %: no FP vote under the rule ...
    assert not _rookie_votes_fp(
        rookie_fp_rank=_POOL + 1, drop_deep_tail_rookies=True, excludes_rookies=False
    )
    # ... and the same rank votes once the rule is off.
    assert _rookie_votes_fp(
        rookie_fp_rank=_POOL + 1, drop_deep_tail_rookies=False, excludes_rookies=False
    )


def test_the_rule_only_bites_in_the_deep_tail():
    # Rank 5 of 21 is inside the top 80 %: the rule leaves the vote alone.
    assert _rookie_votes_fp(rookie_fp_rank=5, drop_deep_tail_rookies=True, excludes_rookies=False)


def test_excludes_rookies_no_longer_drives_the_skip():
    assert _rookie_votes_fp(
        rookie_fp_rank=_POOL + 1, drop_deep_tail_rookies=False, excludes_rookies=True
    )


def test_the_threshold_is_the_pre_decoupling_value():
    assert dc.DEEP_TAIL_ROOKIE_POOL_FRACTION == 0.80


def test_registry_declares_the_rule_on_exactly_the_two_sources():
    flagged = {s["key"] for s in dc._RANKING_SOURCES if s.get("drop_deep_tail_rookies")}
    assert flagged == {"fantasyProsIdp", "dlfIdp"}
    for key in flagged:
        src = next(s for s in dc._RANKING_SOURCES if s["key"] == key)
        # The factual coverage claim stays False (G2-D3): both CSVs rank rookies.
        assert src.get("excludes_rookies") is False, key


def test_registry_export_carries_both_fields_separately():
    by_key = {s["key"]: s for s in dc.get_ranking_source_registry()}
    for key in ("fantasyProsIdp", "dlfIdp"):
        assert by_key[key]["dropsDeepTailRookies"] is True
        assert by_key[key]["excludesRookies"] is False
    assert by_key["idpTradeCalc"]["dropsDeepTailRookies"] is False
