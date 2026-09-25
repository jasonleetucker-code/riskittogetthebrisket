"""FantasyPros IDP metadata never crosses between players who share a name key.

"Byron Murphy II" (DT, SEA) and "Byron Murphy Jr." (CB, MIN) both reduce to the
canonical match key ``byron murphy``.  The metadata lookup used to be a flat
``key -> row`` map, so the later CSV row overwrote the earlier and the DT was
stamped with the CB's ranks (effective 162 / original 74 instead of 116 / 116).
That surfaced as ``test_no_combined_player_loses_direct_rank`` failing on the
committed FantasyPros CSV.
"""

from __future__ import annotations

from src.api.data_contract import _select_fp_meta

_II = {"_name": "Byron Murphy II", "fantasyProsIdpFamily": "DL", "fantasyProsIdpOriginalRank": 116}
_JR = {"_name": "Byron Murphy Jr.", "fantasyProsIdpFamily": "DB", "fantasyProsIdpOriginalRank": 74}


def test_single_candidate_is_used_as_before():
    assert _select_fp_meta([_II], "Byron Murphy", "DL") is _II


def test_exact_name_wins_a_collision():
    assert _select_fp_meta([_II, _JR], "Byron Murphy II", "DL") is _II
    assert _select_fp_meta([_II, _JR], "Byron Murphy Jr.", "DB") is _JR


def test_position_family_breaks_a_collision_without_an_exact_name():
    assert _select_fp_meta([_II, _JR], "Byron Murphy", "DT") is _II
    assert _select_fp_meta([_II, _JR], "Byron Murphy", "CB") is _JR


def test_still_ambiguous_means_no_stamp_not_a_guess():
    other_dl = {**_JR, "fantasyProsIdpFamily": "DL", "_name": "Byron Murphy Sr."}
    assert _select_fp_meta([_II, other_dl], "Byron Murphy", "DL") is None
    assert _select_fp_meta([_II, _JR], "Byron Murphy", "") is None
    assert _select_fp_meta([], "Byron Murphy", "DL") is None
