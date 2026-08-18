"""The contract's freshness budget must never be laxer than the alert owner's.

AUDIT FINDING F-18 (2026-08-18)
───────────────────────────────
Two owners answer "how stale may this source's FETCH be", and they disagreed
on **22 of 22** sources:

    resolve_threshold (config/source_staleness.json) : 24h, uniformly
    _SOURCE_MAX_AGE_HOURS (this contract)            : 6h x13, 168h x2, 720h x5

Seven contract budgets were 168h or 720h, and every justification in the file
cited the VENDOR'S PUBLICATION CADENCE — "refresh ~monthly, so allow a 30-day
window" (yahooBoone), "refreshes monthly as a new FP article"
(fantasyProsFitzmaurice), "Substack article updated periodically" (idpShow).

But the signal is not publication.  All seven carry a
``data/scrape_state/<key>_last_success`` stamp, which
``_build_source_timestamps`` PREFERS over CSV mtime and which records FETCH
SUCCESS by construction — and all seven measured 1.1-1.7 hours old.  A 720h
budget is roughly 400x the observed fetch interval.

THE REPO ALREADY DECIDED THIS, AND APPLIED IT TO TWO OF NINE
────────────────────────────────────────────────────────────
``src/api/data_contract.py``, verbatim, on ``fantasyNavigatorSf`` /
``pfkDynasty``:

    # mtime measures fetch success, not the vendors' editorial cadence …
    # (An earlier 720h/168h pair conflated this with how often the vendors
    # PUBLISH — which mtime cannot observe; Codex review on PR #532.)

So repairing the rest applies an existing owner decision rather than
inventing a policy.  Census item S-6 — *is stale evidence still a
full-weight vote?* — is a different question and stays owner-gated.

WHY THIS TEST IS RELATIONAL
───────────────────────────
It asserts ``contract budget <= alert threshold`` rather than any absolute
number, so it invents nothing of its own — the same shape
``test_source_floor_invariant`` uses for scraper-floor >= contract-floor.

The direction matters and is the whole point.  The CONTRACT owner decides
whether a row's evidence counts as current, via the B11 freshness axis; the
ALERT owner decides whether a human is told.  A source the alert engine
calls stale while the board still counts its evidence as current is audit
finding F-6's failure mode with confidence blind to it.

IMPACT, MEASURED
────────────────
Rebuilding the contract with all seven held to 24h moved **0
confidenceBucket and 0 confidenceLabel** across 1109 rows — everything is
currently fresh, so the budget only bites during an outage.  That is the
honest figure, and it corrects a larger number reported upstream.
"""

from __future__ import annotations

import pytest

from src.api.data_contract import _SOURCE_MAX_AGE_HOURS
from src.api.source_health_alerts import load_thresholds, resolve_threshold

#: Sources allowed to be laxer than the alert engine, each with the reason and
#: the follow-up that removes it.  **Empty, and it must stay empty**: an entry
#: here means the board would count evidence as current after the operator has
#: already been told it is stale.  Same self-burning-down convention as
#: ``test_source_floor_invariant._KNOWN_FLOOR_GAPS``.
_KNOWN_LAXER_BUDGETS: dict[str, str] = {}


def _alert_threshold(key: str) -> float:
    return float(resolve_threshold(key, load_thresholds()))


def test_there_are_budgets_to_check_at_all() -> None:
    """Guards every assertion below against passing vacuously."""
    assert len(_SOURCE_MAX_AGE_HOURS) >= 15


@pytest.mark.parametrize("key", sorted(_SOURCE_MAX_AGE_HOURS))
def test_contract_budget_is_not_laxer_than_the_alert_threshold(key: str) -> None:
    if key in _KNOWN_LAXER_BUDGETS:
        pytest.skip(f"allowlisted: {_KNOWN_LAXER_BUDGETS[key]}")
    budget = float(_SOURCE_MAX_AGE_HOURS[key])
    threshold = _alert_threshold(key)
    assert budget <= threshold, (
        f"{key}: the board counts evidence current for {budget}h while the alert "
        f"engine calls it stale at {threshold}h — the operator is told and the "
        f"board is not"
    )


def test_the_allowlist_is_empty() -> None:
    """Stated as its own assertion so adding an entry is a deliberate, visible
    act rather than something a parametrised skip hides."""
    assert _KNOWN_LAXER_BUDGETS == {}, _KNOWN_LAXER_BUDGETS


def test_allowlist_entries_are_still_real() -> None:
    """Self-burning-down: an entry whose budget now complies must be removed,
    so the list can only shrink."""
    for key, reason in _KNOWN_LAXER_BUDGETS.items():
        assert key in _SOURCE_MAX_AGE_HOURS, f"{key} allowlisted but has no budget"
        assert float(_SOURCE_MAX_AGE_HOURS[key]) > _alert_threshold(
            key
        ), f"{key} now complies — remove it from _KNOWN_LAXER_BUDGETS ({reason})"


def test_the_stamp_is_still_the_preferred_signal() -> None:
    """The whole finding rests on the measured signal being FETCH SUCCESS.

    ``_build_source_timestamps`` prefers ``<key>_last_success`` over CSV mtime.
    If that preference were ever reversed, the signal would become "when the
    file last changed" and the publication-cadence reasoning these budgets
    were originally written for would become defensible again — so the
    relational invariant above would need revisiting rather than silently
    continuing to hold.

    Read from the AST, not a comment: this module's own docstring quotes the
    field name repeatedly.
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "src/api/data_contract.py").read_text()
    tree = ast.parse(src)
    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_build_source_timestamps"
        ),
        None,
    )
    assert fn is not None, "_build_source_timestamps not found"
    body = ast.get_source_segment(src, fn) or ""
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))
    assert "_last_success" in code, "the fetch-success stamp is no longer read"
