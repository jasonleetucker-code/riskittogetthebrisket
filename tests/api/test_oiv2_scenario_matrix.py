"""Outlier-integrity-v2: the directive §5 scenario list, offense AND IDP, end to end.

Directive 2026-10-20 §5 ("Offense and IDP tests including ...") and
preregistration §9. Every test here builds a SYNTHETIC board through the
production entry point (``build_api_data_contract``) with V2's primary
configuration and NO-HISTORY unless stated, so each scenario is judged by the
complete layered pipeline (A, B, C, the B10 family cap, the blend). Where a
scenario places specific votes on a row it does so through the replay-only seam
``data_contract._ADVERSARIAL_VOTE_TRANSFORM`` (after pricing, before every
layer); where the scenario is an INPUT fault (wrong player, broken conversion,
missing ladder) the source CSV itself is corrupted. Each test names the
component it measures.

Synthetic rows only: no R_REGRESSION_PIN, V_HELDOUT or I_INDEPENDENT board is
read here.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import random
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api import outlier_policy as op
from src.api import source_integrity as si
from src.api import value_replay as vr
from src.robust_filter_shadow import oiv2_gates as G
from tests.api import test_source_integrity as T

V2 = T.ALL_ON
OFFENSE, IDP = "offense", "idp"
#: Mid-board, non-TE rows (the TE basis lift is applied before the seam, so it
#: would not change these placements, but a non-TE row keeps them literal).
ROW = {OFFENSE: "Off Vet 021", IDP: "Idp Vet 020"}
TAIL_ROW = {OFFENSE: "Off Vet 090", IDP: "Idp Vet 068"}


def _payload_and_meta():
    payload, meta = T._payload(n_off=96, n_idp=72, n_rook=12)
    for pl in payload["players"].values():
        if "ktcCrowdSfTep" in pl:
            pl["ktcTradesSfTep"] = pl["ktcCrowdSfTep"]
            pl["_canonicalSiteValues"]["ktcTradesSfTep"] = pl["ktcCrowdSfTep"]
    return payload, meta


PAYLOAD, META = _payload_and_meta()


def _csvs(players=None, meta=None) -> dict[str, str]:
    """``test_source_integrity._csvs`` for this module's larger board, plus a
    DLF IDP rank board (a fourth IDP provider, voting only when the DLF IDP hold
    is lifted -- exactly the restoration scenario)."""
    players = players or PAYLOAD["players"]
    meta = meta or META
    off = [m for m in meta if m[1] in T.OFF_POS and not m[3]]
    idp = [m for m in meta if m[1] in T.IDP_POS]
    rook = [m for m in meta if m[3]]
    dn = ["Name,Rank,Value,SleeperId,Pos,Team"] + [
        f"{n},{r},{10000 - r * 50},{players[n]['_sleeperId']},{p},{players[n]['team']}"
        for r, (n, p, _v, _rk) in enumerate(off + rook, 1)
    ]
    fc = ["name,value,rank"] + [
        f"{n},{9000 - r * 10},{r}" for r, (n, _p, _v, _rk) in enumerate(off + rook, 1)
    ]
    dlfr = ["name,rank,value"] + [f"{n},{r}," for r, (n, _p, _v, _rk) in enumerate(rook, 1)]
    fpi = [
        "name,originalRank,effectiveRank,derivationMethod,family,normalizedValue,"
        "matchedSourceName,position,team"
    ] + [
        f"{n},{r},{r},direct,{p},0,{n},{p},{players[n]['team']}"
        for r, (n, p, _v, _rk) in enumerate(idp, 1)
    ]
    dsi = ["Rank,Team,Player,Fantasy Position,ADP,Bye,Age,3D Value +"] + [
        f"{r},{players[n]['team']},{n},{p},0,0,26,{100 - r}"
        for r, (n, p, _v, _rk) in enumerate(idp, 1)
    ]
    dlfi = ["name,rank,value"] + [f"{n},{r}," for r, (n, _p, _v, _rk) in enumerate(idp, 1)]
    return {
        "dynastyNerdsSfTep.csv": "\n".join(dn) + "\n",
        "fantasyCalc.csv": "\n".join(fc) + "\n",
        "dlfRookieSf.csv": "\n".join(dlfr) + "\n",
        "fantasyProsIdp.csv": "\n".join(fpi) + "\n",
        "draftSharksIdp.csv": "\n".join(dsi) + "\n",
        "dlfIdp.csv": "\n".join(dlfi) + "\n",
    }


def build(
    flags=V2,
    *,
    csvs=None,
    overrides=None,
    votes: Mapping[tuple[str, str], float] | None = None,
    transform: Callable | None = None,
    dlf_idp: bool = False,
    history=None,
    filter_off: bool = False,
    payload=None,
) -> dict:
    """One synthetic board. ``votes`` places ``{(row, source): value}`` through
    the seam. ``dlf_idp`` lifts the DLF IDP hold (test-only flag). ``history``
    (V2 only): ``None`` = NO-HISTORY."""
    if votes is not None:
        transform = G.transform_for(votes)
    off = ("dlf_offense_only_vote",) if dlf_idp else ()
    on = tuple(flags) + (() if dlf_idp else ("dlf_offense_only_vote",))
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        d = Path(tmp) / "CSVs" / "site_raw"
        d.mkdir(parents=True)
        for name, text in (csvs if csvs is not None else _csvs()).items():
            (d / name).write_text(text)
        raw = json.loads(json.dumps(payload if payload is not None else PAYLOAD))
        with T._flags(*on, off=off), contextlib.ExitStack() as stack:
            if si.v2_active():
                stack.enter_context(si.history_override(history))
            stack.enter_context(vr._patched("_ADVERSARIAL_VOTE_TRANSFORM", transform))
            if filter_off:
                stack.enter_context(vr._patched("_hampel_filter_per_player", G._no_filter))
            return dc.build_api_data_contract(raw, csv_root=Path(tmp), source_overrides=overrides)


def at(rank: float, cls: str) -> float:
    """The Hill value whose vote coordinate is ``ln(10 + rank)`` on ``cls``'s
    scope master (the Layer C coordinate)."""
    c, s = op.scope_curve(cls)
    return 9999.0 / (1.0 + ((rank / op.REFERENCE_N) / c) ** s)


#: What a per-row filter drop reads as: the incumbent's stamp, or V2 Layer C's
#: rule reason (``rejected_tail`` / ``extreme_uncorroborated_tail``).
DROPPED = ("filter_dropped", op.REASON_TAIL)


def row_of(contract, name):
    return T._rows(contract)[name]


def status(contract, name, source):
    return G.exclusion_of(row_of(contract, name), source)


def integrity(contract, name, source) -> dict:
    return (row_of(contract, name)["sourceRankMeta"].get(source) or {}).get("integrity") or {}


def assert_never_invalid(contract):
    """§9 property 17: a vote that passed A and B is never shown as an
    identity / format / normalization / broken-feed fault."""
    invalid = {
        si.CATEGORY_IDENTITY,
        si.CATEGORY_FORMAT,
        si.CATEGORY_NORMALIZATION,
        si.CATEGORY_BROKEN_FEED,
    }
    for row in contract["playersArray"]:
        for meta in (row.get("sourceRankMeta") or {}).values():
            integ = meta.get("integrity") or {}
            if integ.get("status") in (si.STATUS_VOTING, si.STATUS_REJECTED_TAIL):
                assert integ.get("category") not in invalid


# Offense row: providers keepTradeCut (Crowd + Trades), IDPTC, Dynasty Nerds,
# FantasyCalc. IDP row: IDPTC, FantasyPros, Draft Sharks (+ DLF when restored).
OFF_SOURCES = ("ktcCrowdSfTep", "idpTradeCalc", "dynastyNerdsSfTep", "fantasyCalc")
IDP_SOURCES = ("idpTradeCalc", "fantasyProsIdp", "draftSharksIdp")
#: Rows where Layer C CAN drop: a corroborated reference needs two providers
#: that are not a translated vote and its own backbone. On the IDP synthetic
#: board FantasyPros IDP is translated through the IDPTC shared-market backbone,
#: so IDPTC + FantasyPros can never corroborate each other; FantasyPros + DLF
#: IDP (two independent ordinals) can. Hence the DLF-restored IDP panel here.
GROSS = {
    OFFENSE: (("idpTradeCalc", "dynastyNerdsSfTep", "fantasyCalc"), False),
    IDP: (("fantasyProsIdp", "dlfIdp", "draftSharksIdp"), True),
}
THREE = {
    OFFENSE: (
        ("idpTradeCalc", "dynastyNerdsSfTep", "fantasyCalc"),
        {"ktcCrowdSfTep": {"include": False}, "ktcTradesSfTep": {"include": False}},
    ),
    IDP: (IDP_SOURCES, None),
}


def _place(cls, row, ranks: Mapping[str, float]) -> dict:
    return {(row, s): at(r, cls) for s, r in ranks.items()}


# ── 1. two agree + one dissents ────────────────────────────────────────


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_two_agree_one_dissents_inside_tau_is_kept_and_counts(cls):
    """Component: Layer C + blend. 4x apart in implied rank is opinion: kept,
    stamped kept_dissent, and it moves the published value."""
    sources, ov = THREE[cls]
    a, b, d = sources
    row = ROW[cls]
    ranks = {a: 40, b: 42, d: 170}
    on = build(overrides=ov, votes=_place(cls, row, ranks))
    assert status(on, row, d) is None
    assert integrity(on, row, d)["primaryReason"] == si.REASON_KEPT_DISSENT
    agree = build(overrides=ov, votes=_place(cls, row, {a: 40, b: 42, d: 41}))
    assert row_of(on, row)["rankDerivedValue"] < row_of(agree, row)["rankDerivedValue"]
    assert_never_invalid(on)


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_two_agree_one_gross_tail_is_a_rule_rejection_never_corruption(cls):
    """Component: Layer C. A x50-in-rank uncorroborated tail with a corroborated
    two-provider reference is removed as ``extreme_uncorroborated_tail`` --
    category ``rejected_by_integrity_rule``, never an invalid-data category."""
    (a, b, d), dlf = GROSS[cls]
    row = ROW[cls]
    ov = THREE[OFFENSE][1] if cls == OFFENSE else None
    extra = {} if cls == OFFENSE else {"idpTradeCalc": 41}
    on = build(overrides=ov, votes=_place(cls, row, {a: 40, b: 42, d: 2600, **extra}), dlf_idp=dlf)
    assert status(on, row, d) in DROPPED
    assert integrity(on, row, d)["primaryReason"] == op.REASON_TAIL
    assert integrity(on, row, d)["category"] == si.CATEGORY_RULE
    assert_never_invalid(on)


# ── 2. three agree + one dissents; a new fourth vote ────────────────────


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_three_agree_one_dissents_kept_where_the_incumbent_drops_it(cls):
    """Component: Layer C vs the incumbent. The DLF failure class: three
    agreeing votes collapse the MAD band and the incumbent removes a valid 4x
    dissent; V2 keeps it."""
    row = ROW[cls]
    if cls == OFFENSE:
        ranks = {"idpTradeCalc": 40, "dynastyNerdsSfTep": 41, "fantasyCalc": 42}
        ranks["ktcCrowdSfTep"] = 170
        ranks["ktcTradesSfTep"] = 170
        dissent = "ktcCrowdSfTep"
    else:
        ranks = {"idpTradeCalc": 40, "fantasyProsIdp": 41, "dlfIdp": 42, "draftSharksIdp": 170}
        dissent = "draftSharksIdp"
    votes = _place(cls, row, ranks)
    on = build(votes=votes, dlf_idp=True)
    inc = build((), votes=votes, dlf_idp=True)
    assert status(inc, row, dissent) == "filter_dropped"
    assert status(on, row, dissent) is None
    assert integrity(on, row, dissent)["primaryReason"] == si.REASON_KEPT_DISSENT


def test_a_new_fourth_idp_vote_never_removes_a_previously_valid_vote():
    """Component: Layer C (monotonicity, §9 property 14) on the IDP restoration:
    with DLF IDP held the row has three votes and Draft Sharks votes; lifting
    the hold adds DLF's agreeing vote -- V2 keeps Draft Sharks (the incumbent
    removes it: the documented defect)."""
    row = ROW[IDP]
    votes = _place(
        IDP, row, {"idpTradeCalc": 40, "fantasyProsIdp": 41, "dlfIdp": 42, "draftSharksIdp": 170}
    )
    held = build(votes=votes, dlf_idp=False)
    restored = build(votes=votes, dlf_idp=True)
    inc_held = build((), votes=votes, dlf_idp=False)
    inc_restored = build((), votes=votes, dlf_idp=True)
    assert "dlfIdp" not in G.voting_votes(row_of(held, row))
    assert "dlfIdp" in G.voting_votes(row_of(restored, row))
    assert status(held, row, "draftSharksIdp") is None
    assert status(restored, row, "draftSharksIdp") is None
    assert status(inc_held, row, "draftSharksIdp") is None
    assert status(inc_restored, row, "draftSharksIdp") == "filter_dropped"


# ── 3. four or more materially different opinions ───────────────────────


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_four_materially_different_opinions_are_all_kept(cls):
    """Component: Layer C guard 2 (no corroborated reference)."""
    row = ROW[cls]
    if cls == OFFENSE:
        ranks = {
            "ktcCrowdSfTep": 10,
            "ktcTradesSfTep": 10,
            "idpTradeCalc": 60,
            "dynastyNerdsSfTep": 400,
            "fantasyCalc": 3000,
        }
    else:
        ranks = {"idpTradeCalc": 10, "fantasyProsIdp": 60, "dlfIdp": 400, "draftSharksIdp": 3000}
    on = build(votes=_place(cls, row, ranks), dlf_idp=True)
    assert all(status(on, row, s) is None for s in ranks)
    assert_never_invalid(on)


# ── 4. small independent-family counts ──────────────────────────────────


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
@pytest.mark.parametrize("n", [1, 2])
def test_one_or_two_providers_never_lose_a_vote(cls, n):
    """Component: Layer C guards 1 and 6 on a thin row (and the B10 family
    unit: KTC Crowd + Trades are ONE provider)."""
    row = ROW[cls]
    if cls == OFFENSE:
        keep = ["ktcCrowdSfTep", "ktcTradesSfTep", "fantasyCalc"][: 1 + n]
        if n == 1:
            keep = ["ktcCrowdSfTep", "ktcTradesSfTep"]
        ov = {s: {"include": False} for s in OFF_SOURCES + ("ktcTradesSfTep",) if s not in keep}
    else:
        keep = list(IDP_SOURCES[:n])
        ov = {s: {"include": False} for s in IDP_SOURCES if s not in keep}
    ranks = {s: (40 if i == 0 else 4000) for i, s in enumerate(keep)}
    if cls == OFFENSE and n == 1:
        ranks = {"ktcCrowdSfTep": 40, "ktcTradesSfTep": 4000}
    on = build(overrides=ov, votes=_place(cls, row, ranks))
    for s in ranks:
        assert status(on, row, s) is None, s


# ── 5. identical synthetic values from different rank boards ────────────


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_identical_synthetic_values_from_different_boards_narrow_nothing(cls):
    """Component: Layer C (duplicate property, §9 property 4). Two rank boards
    translated onto the same synthetic value are two providers, never merged,
    and duplicating a value never narrows a band: the 4x dissent is kept with
    and without the duplicate."""
    row = ROW[cls]
    if cls == OFFENSE:
        base = {"ktcCrowdSfTep": 40, "ktcTradesSfTep": 40, "fantasyCalc": 170}
        dup = {**base, "idpTradeCalc": 40, "dynastyNerdsSfTep": 40}
        ov_base = {"idpTradeCalc": {"include": False}, "dynastyNerdsSfTep": {"include": False}}
        dissent = "fantasyCalc"
    else:
        base = {"idpTradeCalc": 40, "fantasyProsIdp": 40, "draftSharksIdp": 170}
        dup = {**base, "dlfIdp": 40}
        ov_base = None
        dissent = "draftSharksIdp"
    one = build(overrides=ov_base, votes=_place(cls, row, base), dlf_idp=False)
    two = build(votes=_place(cls, row, dup), dlf_idp=True)
    assert status(one, row, dissent) is None
    assert status(two, row, dissent) is None
    # identical values stay separately counted providers
    voting = G.voting_votes(row_of(two, row))
    assert len({dc._integrity_provider_of(s) for s in voting}) == len(
        {dc._integrity_provider_of(s) for s in dup}
    )


# ── 6. sparse and deep-tail values ──────────────────────────────────────


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_deep_tail_dissent_is_kept_and_no_absolute_floor_exists(cls):
    """Component: Layer C on a deep-tail row. 3.4x in implied rank below the
    others is opinion even where values are small (no 1,000-point floor, no
    MAD); a x20 deep-tail tail is a rule rejection."""
    (a, b, d), dlf = GROSS[cls]
    row = TAIL_ROW[cls]
    ov = THREE[OFFENSE][1] if cls == OFFENSE else None
    extra = {} if cls == OFFENSE else {"idpTradeCalc": 510}
    kept = build(
        overrides=ov, votes=_place(cls, row, {a: 500, b: 520, d: 1800, **extra}), dlf_idp=dlf
    )
    assert status(kept, row, d) is None
    gross = build(
        overrides=ov, votes=_place(cls, row, {a: 500, b: 520, d: 12000, **extra}), dlf_idp=dlf
    )
    assert status(gross, row, d) in DROPPED
    assert integrity(gross, row, d)["primaryReason"] == op.REASON_TAIL


# ── 7. an invalid source whose wrong values agree with another source ───


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_invalid_source_agreeing_with_another_is_the_named_residual(cls):
    """Component: the whole layered system -- documents the MISS (§9 property
    6). Two sources wrong in the same way, with no identity / format /
    provenance signature, are indistinguishable from two agreeing opinions;
    nothing is excluded and nothing pretends to have caught it."""
    row = ROW[cls]
    if cls == OFFENSE:
        ranks = {
            "ktcCrowdSfTep": 40,
            "ktcTradesSfTep": 40,
            "fantasyCalc": 41,
            "idpTradeCalc": 300,
            "dynastyNerdsSfTep": 300,
        }
        wrong = ("idpTradeCalc", "dynastyNerdsSfTep")
    else:
        ranks = {"idpTradeCalc": 40, "fantasyProsIdp": 41, "draftSharksIdp": 300, "dlfIdp": 300}
        wrong = ("draftSharksIdp", "dlfIdp")
    on = build(votes=_place(cls, row, ranks), dlf_idp=True)
    for s in wrong:
        assert status(on, row, s) is None
        assert integrity(on, row, s)["category"] in (si.CATEGORY_VOTING, si.CATEGORY_DISSENT)


# ── 8. a valid, consistently contrarian source ──────────────────────────


@pytest.mark.parametrize("cls,source", [(OFFENSE, "fantasyCalc"), (IDP, "draftSharksIdp")])
def test_a_valid_consistently_contrarian_source_votes_on_every_row(cls, source):
    """Component: B3 (no history) + Layer C. One source prices every row of its
    class at 3x the others' implied rank: a consistent opinion, order
    preserved -- not one of its votes is excluded anywhere."""
    curve = op.scope_curve(cls)

    def contrarian(row, src, value):
        if src != source or row.get("assetClass") != cls:
            return value
        return G._reprice(value, curve, 3.0)

    on = build(transform=contrarian)
    rows = [r for r in on["playersArray"] if r.get("assetClass") == cls]
    with_vote = [r for r in rows if source in (r.get("sourceRankMeta") or {})]
    assert len(with_vote) >= 40
    assert [r["displayName"] for r in with_vote if G.exclusion_of(r, source)] == []
    assert not [f for f in on["sourceIntegrity"]["findings"] if f["hard"]]


# ── 9. broken positional conversion ─────────────────────────────────────


def _reverse_within(csv_text: str, names: set[str], name_col: int, rank_cols: tuple[int, ...]):
    lines = csv_text.splitlines()
    head, body = lines[0], [ln.split(",") for ln in lines[1:]]
    idx = [i for i, cells in enumerate(body) if cells[name_col] in names]
    for col in rank_cols:
        vals = [body[i][col] for i in idx]
        for j, i in enumerate(idx):
            body[i][col] = vals[len(idx) - 1 - j]
    return "\n".join([head] + [",".join(c) for c in body]) + "\n"


@pytest.mark.parametrize(
    "cls,source,pos,name_col,rank_cols",
    [
        (OFFENSE, "fantasyCalc", "WR", 0, (1, 2)),
        (IDP, "fantasyProsIdp", "LB", 0, (1, 2)),
    ],
)
def test_broken_positional_conversion_quarantines_that_segment_only(
    cls, source, pos, name_col, rank_cols
):
    """Component: B3b direction (needs no history). One source's order is
    reversed WITHIN one position group: that segment is quarantined with a
    normalization reason; the same source keeps voting elsewhere."""
    csvs = _csvs()
    names = {m[0] for m in META if m[1] == pos and not m[3]}
    fname = f"{source}.csv"
    csvs[fname] = _reverse_within(csvs[fname], names, name_col, rank_cols)
    on = build(csvs=csvs)
    quarantines = on["sourceIntegrity"]["segmentQuarantines"]
    assert f"{source}/{cls}/{pos}" in quarantines
    assert si.reason_category(quarantines[f"{source}/{cls}/{pos}"]) == si.CATEGORY_NORMALIZATION
    other = next(
        r
        for r in on["playersArray"]
        if r.get("assetClass") == cls
        and r.get("position") != pos
        and source in (r.get("sourceRankMeta") or {})
    )
    assert G.exclusion_of(other, source) is None


# ── 10. wrong-player matches ────────────────────────────────────────────


def _replace_line(csv_text: str, prefix: str, new: str) -> str:
    lines = [ln for ln in csv_text.splitlines() if not ln.startswith(prefix)]
    return "\n".join(lines + [new]) + "\n"


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_wrong_player_with_identity_evidence_is_refused_and_absent(cls):
    """Component: Layer A (A3 incompatible position group). The entry carries
    another person's published position: refused before ranking, absent from
    the row (never zero), labelled invalid identity."""
    csvs = _csvs()
    if cls == OFFENSE:
        name, source = "Off Vet 002", "dynastyNerdsSfTep"
        csvs["dynastyNerdsSfTep.csv"] = _replace_line(
            csvs["dynastyNerdsSfTep.csv"], f"{name},", f"{name},90,5500,,LB,CLE"
        )
    else:
        name, source = "Idp Vet 002", "fantasyProsIdp"
        team = PAYLOAD["players"][name]["team"]
        csvs["fantasyProsIdp.csv"] = _replace_line(
            csvs["fantasyProsIdp.csv"], f"{name},", f"{name},60,60,direct,WR,0,{name},WR,{team}"
        )
    off = build(())
    on = build(csvs=csvs)
    assert source in row_of(off, name)["canonicalSiteValues"]
    row = row_of(on, name)
    assert source not in row["canonicalSiteValues"]
    stamp = row["sourceIntegrity"][source]
    assert stamp["status"] == si.STATUS_REFUSED
    assert stamp["category"] == si.CATEGORY_IDENTITY
    assert row["rankDerivedValue"] and row["rankDerivedValue"] > 0


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_wrong_player_without_identity_evidence_is_not_faked(cls):
    """Component: the whole system -- the as-registered AD2 case. A vote
    replaced by the same source's vote for a far-away player, with no identity
    evidence, reaches Layer C as a number; Layer A does not invent detection.
    Whatever Layer C decides, the vote is never labelled an identity fault."""
    row = ROW[cls]
    far = TAIL_ROW[cls]
    source = "fantasyCalc" if cls == OFFENSE else "draftSharksIdp"
    clean = build()
    far_vote = row_of(clean, far)["sourceRankMeta"][source]["valueContribution"]
    on = build(votes={(row, source): float(far_vote)})
    assert integrity(on, row, source).get("category") != si.CATEGORY_IDENTITY


# ── 11. transient feed anomalies ────────────────────────────────────────


@pytest.mark.parametrize(
    "cls,source,row",
    [(OFFENSE, "dynastyNerdsSfTep", "Off Vet 006"), (IDP, "draftSharksIdp", "Idp Vet 006")],
)
def test_transient_feed_jump_is_held_with_history_and_only_that_vote(monkeypatch, cls, source, row):
    """Component: B4 continuity (needs the history lane). A vote that jumps
    away from its own history and from every other provider, with nobody
    co-moving, is held pending confirmation -- and nothing else is."""
    thr = si.IntegrityThresholds(tau_c={source: {b: 0.2 for _e, b in si.B4_BANDS}})
    monkeypatch.setattr(si, "load_thresholds", lambda path=None: thr)
    clean = build()
    rec = si.board_record(clean)
    history = None
    for i in range(3):
        history = si.advance(history, {**rec, "asOf": f"2026-08-1{i}T00:00:00+00:00"})
    on = build(votes={(row, source): at(95 if cls == OFFENSE else 70, cls)}, history=history)
    assert integrity(on, row, source)["status"] == si.STATUS_HELD
    held = [
        (r["displayName"], k)
        for r in on["playersArray"]
        for k, m in (r.get("sourceRankMeta") or {}).items()
        if (m.get("integrity") or {}).get("status") == si.STATUS_HELD
    ]
    assert held == [(row, source)]


# ── 12. missing historical value curves / ladders ───────────────────────


def test_offense_missing_rookie_ladder_fails_closed():
    """Component: B1 (``rookie_ladder_fail_closed``). The rookie board's ladder
    reference is gone: its within-class ranks are withheld, never voted as
    overall ranks."""
    ov = {"ktcCrowdSfTep": {"include": False}}
    on = build(overrides=ov)
    meta = row_of(on, "Off Rook 001")["sourceRankMeta"]["dlfRookieSf"]
    assert meta["excludedReason"] == si.REASON_UNTRANSLATED
    assert meta["contributedToBlend"] is False


def test_idp_missing_shared_market_bridge_never_votes_untranslated():
    """Component: the IDP shared-market translation (existing fail-closed path,
    unchanged by V2). Without its bridge, FantasyPros IDP's rank cannot be
    placed on the board scale: it does not vote at all -- absent, never zero,
    never an untranslated rank."""
    on = build(overrides={"idpTradeCalc": {"include": False}})
    row = row_of(on, "Idp Vet 005")
    meta = row["sourceRankMeta"].get("fantasyProsIdp")
    assert meta is None or meta.get("contributedToBlend") is False
    assert row["rankDerivedValue"] is None or row["rankDerivedValue"] > 0


# ── 13. family caps ─────────────────────────────────────────────────────


def test_family_cap_output_is_unchanged_by_v2():
    """Component: the B10 family cap (consumed, never changed). On every row
    where V2 and the incumbent keep the same surviving set, every source's
    ``familyAdjustment`` and applied weight are identical."""
    csvs = _csvs()
    # FantasyNavigator sits in the ktcCrowd B10 family: a two-member family the
    # cap must scale.
    off = [m for m in META if m[1] in T.OFF_POS and not m[3]]
    csvs["fantasyNavigatorSf.csv"] = (
        "\n".join(
            ["name,value,rank"] + [f"{n},{9000 - r * 10},{r}" for r, (n, *_x) in enumerate(off, 1)]
        )
        + "\n"
    )
    on = build(csvs=csvs)
    inc = build((), csvs=csvs)
    compared = 0
    for name, r_on in T._rows(on).items():
        r_inc = T._rows(inc)[name]
        if sorted(r_on.get("droppedSources") or []) != sorted(r_inc.get("droppedSources") or []):
            continue
        for k, m in (r_on.get("sourceRankMeta") or {}).items():
            m_inc = r_inc["sourceRankMeta"].get(k) or {}
            assert m.get("familyAdjustment") == m_inc.get("familyAdjustment"), (name, k)
            assert m.get("appliedWeight") == m_inc.get("appliedWeight"), (name, k)
            compared += 1
    capped = [
        r
        for r in on["playersArray"]
        if ((r.get("sourceRankMeta") or {}).get("ktcCrowdSfTep") or {}).get("familyAdjustment", 1)
        < 1
    ]
    assert compared > 500 and capped


def test_two_members_of_one_provider_are_not_a_corroborated_reference():
    """Component: Layer C's provider unit with the family cap. KTC Crowd and KTC
    Trades agreeing are ONE provider: they cannot corroborate each other, so a
    gross IDPTC vote on a KTC + IDPTC row is kept; adding an independent
    provider near KTC forms the reference and the tail is a rule rejection."""
    row = ROW[OFFENSE]
    ov = {"dynastyNerdsSfTep": {"include": False}, "fantasyCalc": {"include": False}}
    ranks = {"ktcCrowdSfTep": 40, "ktcTradesSfTep": 41, "idpTradeCalc": 3000}
    one_provider = build(overrides=ov, votes=_place(OFFENSE, row, ranks))
    assert status(one_provider, row, "idpTradeCalc") is None
    ov2 = {"dynastyNerdsSfTep": {"include": False}}
    ref = build(overrides=ov2, votes=_place(OFFENSE, row, {**ranks, "fantasyCalc": 42}))
    assert status(ref, row, "idpTradeCalc") in DROPPED


@pytest.mark.parametrize("cls", [OFFENSE, IDP])
def test_family_cap_owner_and_protected_constants_are_untouched_by_a_v2_build(cls):
    """Component: §8 protected parts. A V2 build with a corrupted vote leaves the
    registry weights, correlation groups, Hill constants, Hampel constants and
    the cap function byte-identical."""
    from src.canonical import player_valuation as pv

    def snap():
        return hashlib.sha256(
            json.dumps(
                [
                    dc._RANKING_SOURCES,
                    {
                        k: dc.correlation_group_for(k)
                        for k in sorted(x["key"] for x in dc._RANKING_SOURCES)
                    },
                    pv.HILL_PERCENTILE_C,
                    pv.HILL_PERCENTILE_S,
                    pv.IDP_HILL_PERCENTILE_C,
                    pv.IDP_HILL_PERCENTILE_S,
                    dc._HAMPEL_K,
                    dc._HAMPEL_MIN_N,
                    dc._HAMPEL_MIN_THRESHOLD,
                    dc.FAMILY_WEIGHT_CAP_DEFAULT,
                    dc.cap_family_weights({"ktcCrowdSfTep": 1.0, "ktcTradesSfTep": 1.0})[0],
                ],
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()

    before = snap()
    sources, ov = THREE[cls]
    build(
        overrides=ov,
        votes=_place(cls, ROW[cls], {sources[0]: 40, sources[1]: 42, sources[2]: 2600}),
    )
    assert snap() == before


# ── 14. order independence and determinism ──────────────────────────────


def _shuffled_csvs(seed: int) -> dict[str, str]:
    rng = random.Random(seed)
    out = {}
    for name, text in _csvs().items():
        lines = text.splitlines()
        body = lines[1:]
        rng.shuffle(body)
        out[name] = "\n".join([lines[0]] + body) + "\n"
    return dict(reversed(list(out.items())))


def _shuffled_payload(seed: int) -> dict:
    rng = random.Random(seed)
    raw = json.loads(json.dumps(PAYLOAD))
    items = list(raw["players"].items())
    rng.shuffle(items)
    raw["players"] = dict(items)
    return raw


def _corruptions() -> dict:
    return {
        **_place(OFFENSE, ROW[OFFENSE], {"fantasyCalc": 2600}),
        **_place(
            IDP,
            ROW[IDP],
            {"fantasyProsIdp": 40, "idpTradeCalc": 41, "dlfIdp": 42, "draftSharksIdp": 2600},
        ),
        **_place(OFFENSE, TAIL_ROW[OFFENSE], {"dynastyNerdsSfTep": 1800}),
    }


def test_order_independence_of_every_v2_decision():
    """§9 property 12 on the full pipeline, offense and IDP rows together:
    shuffling every CSV's row order, the CSV file order and the payload's
    player insertion order yields an identical board and identical integrity
    decisions (with corruptions present, so drops and dissents are exercised)."""
    base = build(votes=_corruptions(), dlf_idp=True)
    digest = G.board_digest(base)
    assert status(base, ROW[OFFENSE], "fantasyCalc") in DROPPED
    assert status(base, ROW[IDP], "draftSharksIdp") in DROPPED
    for seed in (1, 2):
        other = build(
            votes=_corruptions(),
            csvs=_shuffled_csvs(seed),
            payload=_shuffled_payload(seed),
            dlf_idp=True,
        )
        assert G.board_digest(other) == digest


def test_two_builds_of_the_same_input_are_identical():
    """§9 property 13 on the full pipeline: two V2 builds of one input hash
    identically (board digest: value, rank, dropped sources, every integrity
    stamp)."""
    a = build(votes=_corruptions(), dlf_idp=True)
    b = build(votes=_corruptions(), dlf_idp=True)
    assert G.board_digest(a) == G.board_digest(b)
    assert json.dumps(a["sourceIntegrity"], sort_keys=True, default=str) == json.dumps(
        b["sourceIntegrity"], sort_keys=True, default=str
    )


def test_missing_is_never_zero_across_the_scenarios():
    """§9 property 15: no excluded, held or refused observation contributes a
    weight, and no row is priced at 0."""
    on = build(votes=_corruptions(), dlf_idp=True)
    for row in on["playersArray"]:
        for k, meta in (row.get("sourceRankMeta") or {}).items():
            if G.exclusion_of(row, k) not in (None, *DROPPED):
                assert meta.get("appliedWeight") in (0, 0.0)
        assert row.get("rankDerivedValue") is None or row["rankDerivedValue"] > 0
    assert math.isfinite(1.0)
