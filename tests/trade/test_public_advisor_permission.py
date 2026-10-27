"""R2-10: the public advisor's source-permission launch leg rejects anything
that is not a complete, current owner approval covering every voting source
(``src/trade/public_advisor_permission.py``) — not merely "some file exists".
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from src.trade import public_advisor_permission as perm

TODAY = dt.date(2026, 10, 20)
VOTING = ("ktcCrowdSfTep", "ktcTradesSfTep", "signalsSf", "idpTradeCalc")
PROVIDERS = {
    "ktcCrowdSfTep": "keepTradeCut",
    "ktcTradesSfTep": "keepTradeCut",
    "signalsSf": "signalsFantasy",
    "idpTradeCalc": "idpTradeCalculator",
}


def _record(**over):
    rec = {
        "recordType": perm.RECORD_TYPE,
        "schemaVersion": perm.SCHEMA_VERSION,
        "scope": perm.SCOPE,
        "approvedBy": "owner",
        "approvedAt": "2026-10-19",
        "reviewBy": "2026-12-31",
        "providers": {
            "keepTradeCut": "approved",
            "signalsFantasy": "approved",
            "idpTradeCalculator": "approved",
        },
        "sources": {},
    }
    rec.update(over)
    return rec


def _problem(rec, *, voting=VOTING, today=TODAY):
    return perm.record_problem(rec, voting_sources=voting, provider_of=PROVIDERS.get, today=today)


def test_complete_current_record_passes():
    assert _problem(_record()) is None


def test_source_level_approval_covers_a_key_without_a_provider_entry():
    rec = _record(providers={"keepTradeCut": "approved"}, sources={})
    assert _problem(rec) == "uncovered:idpTradeCalc"
    rec["sources"] = {"signalsSf": "approved", "idpTradeCalc": "approved"}
    assert _problem(rec) is None


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        ([], "not_an_object"),
        ("approved", "not_an_object"),
        (_record(recordType="something_else"), "wrong_record_type"),
        (_record(schemaVersion=2), "unsupported_schema_version"),
        (_record(schemaVersion=True), "unsupported_schema_version"),
        (_record(scope="private_calculator"), "wrong_scope"),
        (_record(approvedBy=""), "approver_missing"),
        (_record(approvedBy=None), "approver_missing"),
        (_record(approvedAt="20261019"), "dates_malformed"),
        (_record(reviewBy=None), "dates_malformed"),
        (_record(approvedAt="2026-10-21"), "approved_in_future"),
        (_record(approvedAt="2026-10-19", reviewBy="2026-10-18"), "dates_inconsistent"),
        (_record(providers=["keepTradeCut"]), "permissions_malformed"),
        (_record(providers={"keepTradeCut": "yes"}), "permissions_malformed"),
        (_record(sources={"": "approved"}), "permissions_malformed"),
    ],
)
def test_malformed_records_fail_closed(record, reason):
    assert _problem(record) == reason


def test_stale_record_fails_closed():
    rec = _record(approvedAt="2026-01-01", reviewBy="2026-10-19")
    assert _problem(rec) == "stale"
    assert _problem(rec, today=dt.date(2026, 10, 19)) is None  # reviewBy is inclusive


def test_partial_record_fails_closed():
    rec = _record(providers={"keepTradeCut": "approved", "signalsFantasy": "approved"})
    assert _problem(rec) == "uncovered:idpTradeCalc"


def test_new_voting_source_makes_an_old_record_stale_by_construction():
    assert _problem(_record()) is None
    assert _problem(_record(), voting=(*VOTING, "brandNewSource")) == "uncovered:brandNewSource"


@pytest.mark.parametrize("state", ["denied", "unknown"])
def test_denied_or_unresolved_anywhere_refuses(state):
    prov = _record()
    prov["providers"]["signalsFantasy"] = state
    expected = ("denied" if state == "denied" else "unresolved") + ":signalsSf"
    assert _problem(prov) == expected
    # Deny / unknown at the source level beats an approved provider.
    src = _record(sources={"ktcTradesSfTep": state})
    assert _problem(src) == expected.replace("signalsSf", "ktcTradesSfTep")
    # ... and a source-level approval does not override a denied provider.
    if state == "denied":
        both = _record(sources={"signalsSf": "approved"})
        both["providers"]["signalsFantasy"] = "denied"
        assert _problem(both) == "denied:signalsSf"


def test_unrecorded_provider_is_uncovered_not_assumed():
    rec = _record()
    assert (
        perm.record_problem(
            rec, voting_sources=("mystery",), provider_of=lambda _k: None, today=TODAY
        )
        == "uncovered:mystery"
    )


def test_no_voting_sources_cannot_prove_coverage():
    assert _problem(_record(), voting=()) == "voting_sources_unknown"


# ── Path handling ──────────────────────────────────────────────────────────


def _write(tmp_path, rel, body):
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body if isinstance(body, str) else json.dumps(body), encoding="utf-8")
    return rel


def _path_problem(tmp_path, rel):
    return perm.record_path_problem(
        rel, repo=tmp_path, voting_sources=VOTING, provider_of=PROVIDERS.get, today=TODAY
    )


def test_valid_record_file_passes(tmp_path):
    rel = _write(tmp_path, "docs/owner/PERMISSION.json", _record())
    assert _path_problem(tmp_path, rel) is None


@pytest.mark.parametrize(
    ("rel", "reason"),
    [
        (None, "unrecorded"),
        ("", "unrecorded"),
        ("README.md", "path_not_allowed"),
        ("docs/owner/BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md", "path_not_allowed"),
        ("config/trade/public_advisor.json", "path_not_allowed"),
        ("/etc/passwd", "path_not_allowed"),
        ("../../etc/passwd.json", "path_not_allowed"),
        ("docs/owner/../../config/x.json", "path_not_allowed"),
        ("docs\\owner\\PERMISSION.json", "path_not_allowed"),
        ("docs/owner/ABSENT.json", "missing"),
    ],
)
def test_path_rules(tmp_path, rel, reason):
    assert _path_problem(tmp_path, rel) == reason


def test_unparseable_and_oversized_files_fail_closed(tmp_path):
    rel = _write(tmp_path, "docs/owner/BROKEN.json", "{not json")
    assert _path_problem(tmp_path, rel) == "unreadable"
    big = _write(tmp_path, "docs/owner/BIG.json", " " * (perm.MAX_RECORD_BYTES + 1))
    assert _path_problem(tmp_path, big) == "too_large"


def test_symlink_escaping_the_record_dir_is_refused(tmp_path):
    outside = tmp_path / "elsewhere.json"
    outside.write_text(json.dumps(_record()), encoding="utf-8")
    (tmp_path / "docs" / "owner").mkdir(parents=True)
    (tmp_path / "docs" / "owner" / "LINK.json").symlink_to(outside)
    assert _path_problem(tmp_path, "docs/owner/LINK.json") == "path_not_allowed"


def test_real_repo_design_doc_no_longer_opens_the_leg():
    """The exact weak case the review found: an existing repo file."""
    for rel in ("README.md", "docs/owner/BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md"):
        assert perm.record_path_problem(rel) == "path_not_allowed"


def test_real_voting_source_registry_is_non_empty():
    keys = perm.voting_source_keys()
    assert keys and all(isinstance(k, str) and k for k in keys)


# ── The owner checklist (read-only) ─────────────────────────────────────────

_WITH_ORPHAN = (*VOTING, "orphanSource")


def _checklist(voting=_WITH_ORPHAN):
    return perm.permission_checklist(voting_sources=voting, provider_of=PROVIDERS.get)


def test_checklist_covers_exactly_the_voting_sources_once():
    rows = _checklist()
    listed = [s for r in rows for s in r["sources"]]
    assert sorted(listed) == sorted(_WITH_ORPHAN)
    assert len(listed) == len(set(listed))
    orphan = [r for r in rows if r["provider"] is None]
    assert orphan == [
        {
            "provider": None,
            "sources": ["orphanSource"],
            "providerEntry": None,
            "orEverySourceEntry": ['sources["orphanSource"]'],
        }
    ]


def test_answering_every_provider_entry_is_sufficient():
    rows = _checklist()
    rec = _record(
        providers={r["provider"]: "approved" for r in rows if r["provider"]},
        sources={r["sources"][0]: "approved" for r in rows if r["provider"] is None},
    )
    assert _problem(rec, voting=_WITH_ORPHAN) is None


def test_answering_every_source_entry_is_sufficient_but_some_is_not():
    rows = _checklist()
    every = {s: "approved" for r in rows for s in r["sources"]}
    assert _problem(_record(providers={}, sources=every), voting=_WITH_ORPHAN) is None
    ktc = next(r for r in rows if r["provider"] == "keepTradeCut")
    assert len(ktc["sources"]) == 2
    partial = {k: v for k, v in every.items() if k != ktc["sources"][1]}
    assert _problem(_record(providers={}, sources=partial), voting=_WITH_ORPHAN) == (
        f"uncovered:{ktc['sources'][1]}"
    )


def test_the_unanswered_template_can_never_open_the_gate():
    tpl = perm.unanswered_template(voting_sources=_WITH_ORPHAN, provider_of=PROVIDERS.get)
    assert _problem(tpl, voting=_WITH_ORPHAN) == "approver_missing"
    # Even with an approver and valid dates, every answer is still "unknown".
    filled = {**tpl, "approvedBy": "someone", "approvedAt": "2026-10-19", "reviewBy": "2026-12-31"}
    assert _problem(filled, voting=_WITH_ORPHAN).startswith("unresolved:")
    assert set(tpl["providers"].values()) == {"unknown"}
    assert tpl["sources"] == {"orphanSource": "unknown"}


def test_real_checklist_names_every_real_voting_source():
    rows = perm.permission_checklist()
    assert sorted(s for r in rows for s in r["sources"]) == sorted(perm.voting_source_keys())
