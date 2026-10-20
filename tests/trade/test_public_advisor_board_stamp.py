"""The advisor reads the board stamp through the shared owner (#1871).

``trade_analyze_runtime.contract_generation`` is the ONE reader the analyze
receipt (``analyze_service.contract_provenance``) and in-flight key share:
top-level ``generatedAt`` with a ``meta.generatedAt`` fallback.  The advisor's
snapshot generation must agree with it rather than keep a private rule.
"""

from __future__ import annotations

from src.api.trade_analyze_runtime import contract_generation
from src.trade import analyze_service, public_advisor


def test_top_level_and_meta_fallback_name_the_same_generation() -> None:
    top = {"generatedAt": "2026-10-20T05:00:00+00:00"}
    legacy = {"meta": {"generatedAt": "2026-10-20T05:00:00+00:00"}}
    assert public_advisor.generation_for(top) == public_advisor.generation_for(legacy)
    assert contract_generation(top) == contract_generation(legacy)


def test_top_level_stamp_wins_over_meta() -> None:
    both = {"generatedAt": "A", "meta": {"generatedAt": "B"}}
    assert public_advisor.generation_for(both) == public_advisor.generation_for(
        {"generatedAt": "A"}
    )
    assert analyze_service.contract_provenance(both)["boardStamp"] == "A"


def test_scrape_timestamp_is_only_a_last_resort() -> None:
    assert public_advisor.generation_for({"scrapeTimestamp": "S"}) != public_advisor.generation_for(
        {}
    )
    assert public_advisor.generation_for({"generatedAt": "A", "scrapeTimestamp": "S"}) == (
        public_advisor.generation_for({"generatedAt": "A"})
    )


def test_advisor_has_no_private_stamp_reader() -> None:
    import inspect

    src = inspect.getsource(public_advisor.generation_for)
    assert 'get("meta")' not in src
    assert "contract_generation" in inspect.getsource(public_advisor._board_stamp)
