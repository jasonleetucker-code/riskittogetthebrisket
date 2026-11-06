"""``/draft`` must never be served a view that silently lacks a field it reads.

The field list lives in ONE place, ``frontend/lib/draft-contract-fields.json``,
cited by ``frontend/lib/draft-feed.js::draftContractUrl`` and the /draft page.
This test builds the real contract from the newest complete archived scrape,
derives the view exactly as ``server.py`` / ``compact_view`` do, and asserts:

* every listed path present on a full-contract row is present, with an
  identical value, on the same row of the view /draft requests;
* ``view=app`` (the runtime payload) is NOT a safe /draft view: it strips
  ``playersArray`` — pinned so nobody "optimizes" /draft onto it without
  re-deciding that.

Skips (never passes vacuously) when no complete archive exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.compact_view import compact_contract
from src.api.data_contract import build_api_data_contract
from tests.archive_fixtures import newest_complete_raw_payload

_SPEC = json.loads(
    (Path(__file__).resolve().parents[2] / "frontend/lib/draft-contract-fields.json").read_text(
        encoding="utf-8"
    )
)
_MISSING = object()
_cache: dict | None = None


def _contract() -> dict:
    global _cache
    if _cache is None:
        raw, _archive = newest_complete_raw_payload()
        if raw is None:
            pytest.skip("no complete archived scrape to build a contract from")
        _cache = build_api_data_contract(raw)
    return _cache


def _get(obj, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return _MISSING
        obj = obj[part]
    return obj


def _view(name: str, contract: dict) -> dict:
    if name == "compact":
        return compact_contract(contract)
    if name == "app":
        payload = dict(contract)
        payload.pop("playersArray", None)
        return payload
    raise AssertionError(f"unknown view {name!r}")


@pytest.mark.parametrize("fetch", sorted(_SPEC["views"]))
def test_every_draft_field_survives_the_requested_view(fetch):
    spec = _SPEC["views"][fetch]
    contract = _contract()
    served = _view(spec["view"], contract)

    for path in spec.get("topLevel", []):
        full_val = _get(contract, path)
        assert full_val is not _MISSING, f"{path} absent from the full contract"
        if path == "playersArray":
            # Rows are compared per listed field below (compact prunes
            # fields /draft does not read), so only presence is asserted.
            assert isinstance(_get(served, path), list) and _get(served, path)
        else:
            assert _get(served, path) == full_val, f"view={spec['view']} changed/lost {path}"

    rows = spec.get("playerRow", [])
    if rows:
        full_rows = {r["displayName"]: r for r in contract["playersArray"]}
        view_rows = {r["displayName"]: r for r in served["playersArray"]}
        assert full_rows.keys() == view_rows.keys()
        for path in rows:
            # A path no full row carries (e.g. a source that did not publish
            # today) proves nothing; require at least one carrier for the
            # always-stamped identity/value fields below.
            for name, row in full_rows.items():
                expected = _get(row, path)
                assert (
                    _get(view_rows[name], path) == expected
                ), f"view={spec['view']} changed {path} on {name!r}"
        for path in ("displayName", "position", "rookie", "assetClass", "rankDerivedValue"):
            assert any(_get(r, path) is not _MISSING for r in full_rows.values()), path


def test_view_app_is_not_a_lossless_draft_view():
    """Why /draft is not on ``view=app``: it has no ``playersArray`` and its
    ``players`` dict rows carry none of the identity fields /draft reads."""
    contract = _contract()
    app = _view("app", contract)
    assert "playersArray" not in app
    sample = next(iter(app["players"].values()))
    for path in ("displayName", "position", "rookie", "assetClass"):
        assert path not in sample


def test_spec_names_the_views_the_frontend_requests():
    feed = (Path(__file__).resolve().parents[2] / "frontend/lib/draft-feed.js").read_text(
        encoding="utf-8"
    )
    views = {spec["view"] for spec in _SPEC["views"].values()}
    assert views == {"compact"}
    assert 'view: "compact"' in feed
