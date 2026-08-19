import re
from pathlib import Path

from src.sharp.consensus import aggregate_person_consensus


def movement(asset, manager, person, action, league):
    return {
        "canonicalAssetId": asset,
        "managerKey": manager,
        "canonicalManagerKey": person,
        "action": action,
        "leagueKey": league,
    }


def test_one_person_with_many_leagues_casts_one_vote():
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:1", "person:a", "add", "l2"),
        movement("p1", "sleeper:1", "person:a", "add", "l3"),
        movement("p1", "sleeper:2", "person:b", "drop", "l4"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 1.0, "sleeper:2": 1.0})["p1"]
    assert result["personBuys"] == 1
    assert result["personSells"] == 1
    assert result["personVotes"] == 2
    assert result["personNet"] == 0


def test_multiple_accounts_for_one_person_do_not_multiply_consensus():
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "ffpc:1", "person:a", "add", "l2"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 0.9, "ffpc:1": 0.8})["p1"]
    assert result["personVotes"] == 1
    assert result["personBuys"] == 1


def test_opposite_portfolio_moves_are_mixed_not_two_votes():
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:1", "person:a", "drop", "l2"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 1.0})["p1"]
    assert result["personVotes"] == 0
    assert result["mixedPersonSignals"] == 1


def test_shared_network_receives_diminishing_independence_weight():
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:2", "person:b", "add", "l2"),
        movement("p1", "sleeper:3", "person:c", "add", "l3"),
    ]
    result = aggregate_person_consensus(
        rows,
        {"sleeper:1": 1.0, "sleeper:2": 1.0, "sleeper:3": 1.0},
        {"sleeper:1": "Network A", "sleeper:2": "Network A", "sleeper:3": "Independent"},
    )["p1"]
    assert result["personVotes"] == 3
    assert result["weightedPersonVolume"] < 3.0
    assert result["networkCount"] == 2


def test_concentration_is_undefined_not_diversified_when_nothing_is_weighted():
    """``networkConcentration`` is a SHARE of weighted volume.

    With no weighted volume there is no share for any network to hold, so
    the ratio does not exist — and ``0.0`` is the one value that reads as
    its exact opposite, "no single network dominates". ``None`` is what
    ``roster_percentage`` publishes for ``cohortCoveragePct`` in the same
    situation, and this keeps the two consistent.
    """
    rows = [movement("p1", "sleeper:1", "person:a", "add", "l1")]
    # Quality 0 means the vote carries no weight, so the denominator is 0
    # while the movement itself is still a real, counted observation.
    result = aggregate_person_consensus(rows, {"sleeper:1": 0.0})["p1"]
    assert result["weightedPersonVolume"] == 0
    assert result["networkConcentration"] is None
    # The raw evidence is untouched — only the ratio is withheld.
    assert result["personBuys"] == 1


def test_concentration_is_reported_when_it_is_defined():
    """The withholding must be specific to the undefined case, or it would
    hide a real concentration finding."""
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:2", "person:b", "add", "l2"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 1.0, "sleeper:2": 1.0})["p1"]
    assert result["weightedPersonVolume"] > 0
    assert isinstance(result["networkConcentration"], float)


def test_an_explicitly_zero_quality_manager_does_not_vote_at_full_weight():
    """A manager scored 0.0 is the LOWEST possible quality.

    ``float(person["quality"] or 1.0)`` promoted that to 1.0 — the highest —
    so a worthless vote carried full weight into both the consensus and the
    concentration cap. The default already happens upstream when a manager
    is absent from the quality map, so the second one could only ever
    overwrite a real measurement.
    """
    rows = [movement("p1", "sleeper:1", "person:a", "add", "l1")]
    zero = aggregate_person_consensus(rows, {"sleeper:1": 0.0})["p1"]
    full = aggregate_person_consensus(rows, {"sleeper:1": 1.0})["p1"]
    assert zero["weightedPersonVolume"] == 0
    assert full["weightedPersonVolume"] == 1.0
    # The vote is still COUNTED as evidence — only its weight is zero.
    assert zero["personBuys"] == full["personBuys"] == 1


def test_a_manager_absent_from_the_quality_map_still_defaults_to_full():
    """The upstream default is the intended one and must survive the fix."""
    rows = [movement("p1", "sleeper:9", "person:a", "add", "l1")]
    result = aggregate_person_consensus(rows, {})["p1"]
    assert result["weightedPersonVolume"] == 1.0


# ---------------------------------------------------------------------------
# personManagerQuality: four states, none of which may read as another
# ---------------------------------------------------------------------------


def test_zero_voters_reports_unknown_manager_quality_not_maximum():
    """NO QUALIFYING VOTERS IS UNKNOWN, NOT PERFECT.

    ``quality_total / voters if voters else 1.0`` answered the question
    "how good are the managers behind this signal?" with **1.0 — the
    highest possible score** — precisely when nobody qualified to answer
    it. That is the MISSING IS NEVER ZERO invariant inverted: missing
    became the maximum rather than the minimum, which is the more
    dangerous direction because it reads as a green light.

    Reachability is exact, not theoretical. An asset enters the
    aggregation on any add or drop, but ``voters`` only increments when a
    person's net is non-zero. So an asset every person both added AND
    dropped inside the window is emitted with ``mixedPersonSignals > 0``
    and ``personVotes: 0`` — a row about which the cohort expressed no
    net opinion at all, stamped with perfect manager quality.

    ``None`` is not a new convention here: ``personAgreement`` three
    lines below and ``networkConcentration`` above already answer the
    identical ``voters == 0`` case with ``None``.
    """
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:1", "person:a", "drop", "l2"),
        movement("p1", "sleeper:2", "person:b", "add", "l3"),
        movement("p1", "sleeper:2", "person:b", "drop", "l4"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 1.0, "sleeper:2": 1.0})["p1"]
    assert result["personVotes"] == 0
    assert result["mixedPersonSignals"] == 2
    assert result["personManagerQuality"] is None
    # The three undefined-on-no-voters quantities now agree with each other.
    assert result["personAgreement"] is None
    assert result["networkConcentration"] is None
    # The raw evidence is untouched; only the derived ratios are withheld.
    assert result["personBuys"] == 0
    assert result["personSells"] == 0


def test_a_measured_zero_manager_quality_stays_zero():
    """UNKNOWN AND WORST ARE DIFFERENT ANSWERS.

    The repair must not overshoot into treating a genuinely measured 0.0
    as missing. A cohort of one manager scored 0.0 HAS an answer, and the
    answer is the floor.
    """
    rows = [movement("p1", "sleeper:1", "person:a", "add", "l1")]
    result = aggregate_person_consensus(rows, {"sleeper:1": 0.0})["p1"]
    assert result["personVotes"] == 1
    assert result["personManagerQuality"] == 0.0
    assert result["personManagerQuality"] is not None


def test_manager_quality_is_the_mean_over_qualifying_voters():
    """With voters present the value is the plain mean, unchanged."""
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:2", "person:b", "add", "l2"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 1.0, "sleeper:2": 0.5})["p1"]
    assert result["personVotes"] == 2
    assert result["personManagerQuality"] == 0.75


def test_mixed_only_asset_is_still_emitted_as_a_row():
    """The row must not be deleted to dodge the question.

    Suppressing zero-voter assets would trade a wrong number for missing
    evidence of real churn. The row stays; its derived ratios are
    honestly unavailable.
    """
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:1", "person:a", "drop", "l2"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 1.0})
    assert "p1" in result
    assert result["p1"]["mixedPersonSignals"] == 1
    assert result["p1"]["personManagerQuality"] is None


# ---------------------------------------------------------------------------
# Consumer guard
# ---------------------------------------------------------------------------

_UNDEFINED_WITHOUT_A_VOTER = (
    "personManagerQuality",
    "personAgreement",
    "networkConcentration",
)

# ``x or 1``, ``x || 1``, ``x ?? 0``, ``float(x or 1.0)`` -- every shape that
# turns a deliberate ``None`` back into a confident number.
_COERCION = re.compile(r"(\|\||\bor\b|\?\?)\s*-?\d")

_SEARCH_ROOTS = ("src", "scripts", "frontend/lib", "frontend/components", "frontend/app")
_SEARCH_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_files():
    root = _repo_root()
    for name in _SEARCH_ROOTS:
        base = root / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix not in _SEARCH_SUFFIXES:
                continue
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            yield path
    for extra in ("server.py",):
        path = root / extra
        if path.is_file():
            yield path


def test_no_consumer_coerces_an_undefined_person_quantity_back_to_a_number():
    """Fixing the producer is only half of it.

    ``personManagerQuality`` now publishes ``None`` when no voter qualified.
    A consumer writing ``quality || 1`` would restore the exact false green
    the producer stopped emitting, one layer further from the evidence and
    correspondingly harder to find. There is no such consumer today -- this
    keeps it that way rather than trusting a grep taken once.

    Deliberately scoped to a coercion to a NUMBER. Reading the field,
    formatting it, or branching on ``is None`` are all fine; substituting a
    value for the missing one is not.
    """
    offenders = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not any(field in text for field in _UNDEFINED_WITHOUT_A_VOTER):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if not any(field in line for field in _UNDEFINED_WITHOUT_A_VOTER):
                continue
            if path.name == "consensus.py" and "if voters else" in line:
                continue  # the producer's own definition
            if _COERCION.search(line):
                offenders.append(f"{path.relative_to(_repo_root())}:{number}: {line.strip()}")
    assert offenders == [], "undefined person quantity coerced to a number:\n" + "\n".join(
        offenders
    )


def test_the_consumer_guard_would_actually_catch_a_regression(tmp_path):
    """A scanner nobody has seen fail is not evidence.

    ``_COERCION`` must match the shapes it exists to catch, in both
    languages, or the guard above passes for the wrong reason.
    """
    caught = [
        'quality = person["personManagerQuality"] or 1.0',
        "const q = person.personManagerQuality || 1;",
        "const q = person.personManagerQuality ?? 0;",
        'weight = float(row["personAgreement"] or 1)',
    ]
    for line in caught:
        assert _COERCION.search(line), line
    ignored = [
        'if person["personManagerQuality"] is None:',
        'label = fmt(person["personManagerQuality"])',
        'quality = person.get("personManagerQuality")',
    ]
    for line in ignored:
        assert not _COERCION.search(line), line
