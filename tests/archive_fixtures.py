"""One rule for "give me a real board to test against".

WHY THIS EXISTS
───────────────
Several deterministic tests build a real contract from the tracked
export archive rather than a synthetic fixture, and that is the right
call — the properties they check (source correlation leaks, the
consensus-edge input seam, snapshot round-trips) are properties of how
~21 real sources interact, and a three-source fixture would pass while
the live board was broken.

Each of them reached for ``sorted(archive.glob(...))[-1]`` — *the newest*
bundle.  That silently made them a function of the most recent scrape's
HEALTH.  On 2026-08-16 one KTC fetch timed out (300 s against a 39-run
baseline of ~18.8 s) and the resulting bundle carried an empty KTC board;
twelve consensus-edge tests in the blocking gate then failed with
``'offense' not found in set()`` — no code defect, no board defect, just
a provider that did not answer that once.

A seam test needs *a real complete board*, not *the latest board*.  This
module supplies exactly that: the newest archived scrape that the
contract's OWN source-health definition calls complete.  Deterministic
(the archive is tracked), immune to a single bad scrape, and it degrades
by SKIPPING rather than by passing vacuously.

It does not soften any assertion, and it is not a livedata exemption:
these tests stay in the blocking gate.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from tests import fake_clock as _fake_clock

REPO = Path(__file__).resolve().parents[1]
ARCHIVE = REPO / "exports" / "archive"


def _degraded_critical_sources(payload: dict) -> list[str]:
    """Critical sources this scrape failed to complete.

    Classification comes from the contract validator's own constants, so
    "critical" means here exactly what it means in ``contractHealth``.
    """
    from src.api.data_contract import (
        TOLERABLE_PARTIAL_SOURCES,
        critical_primary_for_run_source,
    )

    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    summary = settings.get("sourceRunSummary") if isinstance(settings, dict) else None
    if not isinstance(summary, dict):
        return []
    degraded: list[str] = []
    for key in ("partialSources", "failedSources", "timedOutSources"):
        for src in summary.get(key) or []:
            name = str(src)
            if name in TOLERABLE_PARTIAL_SOURCES:
                continue
            if critical_primary_for_run_source(name) is not None:
                degraded.append(name)
    return degraded


def has_published_slot_class(payload: dict) -> bool:
    """True when a vendor published SLOT prices for an ACTIVE draft class.

    The rookie tether only runs in that phase (C1-U6-D2); between the draft
    and the next season's order, every class is priced as tiers.  Uses the
    contract's own evidence rules, so "slotted" and "active" mean the same
    thing here as in the build.

    ACTIVE matters since #1414 (PR #1442): vendors keep publishing a class's
    slot prices after its rookie draft, and a class the draft-class lifecycle
    has retired leaves the board before the tether pass — so a payload whose
    only slotted class is retired has no tether population either.  The
    evaluation is the build's own (``board_pick_class_lifecycle`` over the
    payload's ``sleeper`` block); if it cannot be evaluated the class is kept,
    exactly as the build keeps it.
    """
    from src.api.data_contract import published_slot_years

    years = published_slot_years(payload.get("pickAnchorsProvenance"))
    if not years:
        return False
    try:
        from src.api.draft_class_evidence import board_pick_class_lifecycle
        from src.identity.pick_lifecycle import retired_seasons

        board, _per_league = board_pick_class_lifecycle(payload.get("sleeper"), years)
        retired = set(retired_seasons(board))
    except Exception:  # noqa: BLE001 — unknown never retires (the build's rule)
        retired = set()
    return bool(set(years) - retired)


def newest_complete_raw_payload(
    require: Callable[[dict], bool] | None = None,
) -> tuple[dict | None, str | None]:
    """``(payload, archive_name)`` for the newest COMPLETE archived scrape.

    ``(None, None)`` when the archive is absent or every bundle in it is
    source-degraded — in which case callers skip, because a degraded
    board cannot answer the question they are asking.

    ``require`` narrows the search to scrapes in a given PHASE (e.g.
    :func:`has_published_slot_class`) for tests whose property only exists
    in that phase.  Same skip-not-pass degradation.
    """
    if not ARCHIVE.is_dir():
        return None, None
    for archive in sorted(ARCHIVE.glob("dynasty_export_*.zip"), reverse=True):
        try:
            with zipfile.ZipFile(archive) as zf:
                names = [
                    n
                    for n in zf.namelist()
                    if n.startswith("dynasty_data_") and n.endswith(".json")
                ]
                if not names:
                    continue
                payload = json.loads(zf.read(names[0]))
        except (OSError, ValueError, zipfile.BadZipFile):
            continue
        if not isinstance(payload, dict):
            continue
        if _degraded_critical_sources(payload):
            continue
        if require is not None and not require(payload):
            continue
        return payload, archive.name
    return None, None


_CONTRACT_CACHE: dict[str, dict[str, Any]] = {}


def newest_complete_contract(
    require: Callable[[dict], bool] | None = None,
) -> tuple[dict | None, str | None]:
    """``(contract, archive_name)``: ``build_api_data_contract`` over
    :func:`newest_complete_raw_payload`.

    The contract is built once per archive per process and the SAME object is
    handed to every caller, so treat it as READ-ONLY (``copy.deepcopy`` before
    mutating).  ``(None, None)`` degrades like the raw helper, and callers
    skip.  This is the deterministic stand-in for ``exports/latest`` in a test
    that checks an invariant of the build rather than the health of today's
    scrape (CLAUDE.md "Rule for new tests").
    """
    payload, name = newest_complete_raw_payload(require)
    if payload is None or name is None:
        return None, None
    contract = _CONTRACT_CACHE.get(name)
    if contract is None:
        from src.api.data_contract import build_api_data_contract

        contract = build_api_data_contract(payload)
        _CONTRACT_CACHE[name] = contract
    return contract, name


# ── The PINNED board ───────────────────────────────────────────────────────
#
# ``newest_complete_*`` above answer "a real complete board", but the NEWEST
# one -- and ``build_api_data_contract(payload)`` with no ``csv_root`` reads
# TODAY's ``CSVs/site_raw`` and ``data/scrape_state`` beside that archived
# payload.  A blocking test built that way is a function of the latest data
# refresh, and froze production deploys five times in three weeks (#2172,
# #2199 and the three before: a team that traded its picks away, a provider
# gone stale, one CSV row moving).
#
# The pinned board is ONE complete board's full inputs frozen together in a
# committed fixture (``tests/pinned_board_build.py`` builds it and documents
# the refresh): the raw payload, every source CSV and the scrape-state stamps
# from the same refresh commit.  ``build_pinned_contract`` builds it with
# ``csv_root`` pointed at that tree, the clock frozen to the board's own
# as-of and the temporal ledger isolated, so the result is the same on every
# machine on every day.  It never skips: the fixture is committed, and a
# missing or modified one is a loud failure.
#
# Use it for any hard-gate test that needs a real complete board.  Use the
# newest helpers only for a test that is ABOUT the latest refresh -- and that
# test is ``livedata`` (``tests/test_pinned_board.py`` enforces this).

PINNED_BOARD_ZIP = REPO / "tests" / "fixtures" / "pinned_board" / "board.zip"

_PINNED: dict[str, Any] = {}


def pinned_board_manifest() -> dict[str, Any]:
    """The fixture's manifest (provenance, as-of, per-file sha256)."""
    manifest = _PINNED.get("manifest")
    if manifest is None:
        if not PINNED_BOARD_ZIP.is_file():
            raise FileNotFoundError(
                f"{PINNED_BOARD_ZIP.relative_to(REPO)} is missing; it is a committed "
                "fixture (rebuild with `python -m tests.pinned_board_build`)"
            )
        with zipfile.ZipFile(PINNED_BOARD_ZIP) as zf:
            manifest = json.loads(zf.read("manifest.json"))
        _PINNED["manifest"] = manifest
    return manifest


def pinned_board_label() -> str:
    """``pinned:<archive name>`` -- the label the pinned helpers return."""
    return f"pinned:{pinned_board_manifest()['archive']}"


def pinned_board_as_of() -> datetime:
    """The board's own observation time (its ``scrapeTimestamp``)."""
    raw = str(pinned_board_manifest()["asOf"]).replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _pinned_extract() -> Path:
    import atexit
    import shutil
    import tempfile

    base = Path(tempfile.mkdtemp(prefix="riskit-pinned-board-"))
    atexit.register(shutil.rmtree, base, True)
    with zipfile.ZipFile(PINNED_BOARD_ZIP) as zf:
        zf.extractall(base)
    return base


def _pinned_verify(base: Path) -> None:
    """Every file matches the manifest -- so a test that writes into the
    shared tree fails loudly instead of quietly changing later builds."""
    for name, digest in pinned_board_manifest()["files"].items():
        path = base / name
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual != digest:
            raise AssertionError(
                f"pinned board file {name} no longer matches its manifest "
                "(a test wrote into the shared pinned tree, or the fixture is corrupt)"
            )
    tree = base / "tree"
    expected = {n for n in pinned_board_manifest()["files"] if n.startswith("tree/")}
    present = {p.relative_to(base).as_posix() for p in tree.rglob("*") if p.is_file()}
    if present != expected:
        raise AssertionError(
            f"pinned board tree gained or lost files: {sorted(present ^ expected)[:5]} "
            "(a test wrote into the shared pinned tree)"
        )


def pinned_board_root() -> Path:
    """The extracted input tree -- pass it as ``csv_root``.  Integrity-checked
    on every call."""
    base = _PINNED.get("base")
    if base is None:
        base = _pinned_extract()
        _PINNED["base"] = base
    _pinned_verify(base)
    return base / "tree"


def pinned_board_payload() -> tuple[dict, str]:
    """``(raw_payload, label)`` -- a fresh private copy per call."""
    raw = _PINNED.get("raw")
    if raw is None:
        with zipfile.ZipFile(PINNED_BOARD_ZIP) as zf:
            raw = zf.read("raw_payload.json")
        _PINNED["raw"] = raw
    return json.loads(raw), pinned_board_label()


_REAL_DATETIME = datetime
_REAL_DATE = date


class _FrozenClockMeta(type):
    """``isinstance(x, <frozen class>)`` answers for the REAL class, so a
    ``datetime`` created before the freeze still passes a type check made
    during it."""

    def __instancecheck__(cls, obj: object) -> bool:
        return isinstance(obj, _REAL_DATE if cls is _FrozenDate else _REAL_DATETIME)

    def __subclasscheck__(cls, sub: type) -> bool:
        return issubclass(sub, _REAL_DATE if cls is _FrozenDate else _REAL_DATETIME)


class _FrozenDatetime(_fake_clock.REAL_DATETIME, metaclass=_FrozenClockMeta):
    """``datetime`` whose ``now`` / ``utcnow`` / ``today`` answer the frozen instant."""

    frozen: datetime = datetime(2000, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        at = cls.frozen
        if tz is not None:
            return at.astimezone(tz)
        return at.astimezone(timezone.utc).replace(tzinfo=None)

    @classmethod
    def utcnow(cls):  # type: ignore[override]
        return cls.frozen.astimezone(timezone.utc).replace(tzinfo=None)

    @classmethod
    def today(cls):  # type: ignore[override]
        return cls.now()


class _FrozenDate(_fake_clock.REAL_DATE, metaclass=_FrozenClockMeta):
    @classmethod
    def today(cls):  # type: ignore[override]
        return _FrozenDatetime.frozen.astimezone(timezone.utc).date()


_PROJECT_MODULE_PREFIXES = ("src.", "scripts.")
_CLOCK_DEPTH = [0]


@contextlib.contextmanager
def frozen_build_clock(as_of: datetime | None = None) -> Iterator[datetime]:
    """Freeze ``datetime.now()`` / ``date.today()`` at ``as_of`` (default: the
    pinned board's as-of) for project code, for the duration of a build.

    Rebinds the stdlib ``datetime.datetime`` / ``datetime.date`` (so a lazy
    ``from datetime import datetime`` inside the build binds the frozen class)
    and every ``datetime`` / ``date`` binding in already-imported ``src`` /
    ``scripts`` / ``server`` modules.  On exit every binding to the frozen
    classes, anywhere in ``sys.modules``, is restored.  ``time.time`` is NOT
    frozen: it only ages TTL caches, and a frozen clock would hang a polling
    loop.  Not thread-safe; tests build on one thread.
    """
    import datetime as _dtmod

    at = as_of or pinned_board_as_of()
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    previous = _FrozenDatetime.frozen
    if _CLOCK_DEPTH[0]:
        # Nested (a pinned build inside a module already running under the
        # pinned environment): the bindings are already frozen; only the
        # instant may differ, and the outer freeze must survive the exit.
        _FrozenDatetime.frozen = at
        _CLOCK_DEPTH[0] += 1
        try:
            yield at
        finally:
            _CLOCK_DEPTH[0] -= 1
            _FrozenDatetime.frozen = previous
        return
    _CLOCK_DEPTH[0] += 1
    swaps = {_REAL_DATETIME: _FrozenDatetime, _REAL_DATE: _FrozenDate}
    _FrozenDatetime.frozen = at
    _dtmod.datetime = _FrozenDatetime  # type: ignore[misc]
    _dtmod.date = _FrozenDate  # type: ignore[misc]
    try:
        for name, module in list(sys.modules.items()):
            if module is None or not (
                name.startswith(_PROJECT_MODULE_PREFIXES) or name == "server"
            ):
                continue
            namespace = getattr(module, "__dict__", None)
            if not isinstance(namespace, dict):
                continue
            for attr, value in list(namespace.items()):
                if value is _REAL_DATETIME or value is _REAL_DATE:
                    namespace[attr] = swaps[value]
        yield at
    finally:
        _dtmod.datetime = _REAL_DATETIME  # type: ignore[misc]
        _dtmod.date = _REAL_DATE  # type: ignore[misc]
        restore = {_FrozenDatetime: _REAL_DATETIME, _FrozenDate: _REAL_DATE}
        this_module = sys.modules.get(__name__)
        for module in list(sys.modules.values()):
            namespace = getattr(module, "__dict__", None)
            if module is this_module or not isinstance(namespace, dict):
                continue
            for attr, value in list(namespace.items()):
                if value is _FrozenDatetime or value is _FrozenDate:
                    namespace[attr] = restore[value]
        _FrozenDatetime.frozen = previous
        _CLOCK_DEPTH[0] -= 1


@contextlib.contextmanager
def pinned_build_environment(*, freeze_clock: bool = True) -> Iterator[Path]:
    """Everything a build reads, pinned; yields the pinned ``csv_root``.

    * the contract's DEFAULT input root (``data_contract._default_input_root``,
      what every ``csv_root=None`` resolves to) is the pinned tree, so a build
      reached through any entry point -- ``value_replay.build``,
      ``build_rankings_delta_payload``, a script -- reads the pinned CSVs and
      scrape state, never today's;
    * the clock is frozen at the board's own as-of (``frozen_build_clock``)
      unless ``freeze_clock=False``.  The module-wide ``pinned_board_inputs``
      fixture passes False: a freeze lasting a whole module would also freeze
      ``src`` code a synthetic test drives with stamps from the REAL clock.
      That costs no determinism -- measured, the build reads the wall clock
      only for its ``generatedAt`` stamps, and
      ``tests/test_pinned_board.py`` fails if that ever stops being true;
    * the temporal ledger (``rankChange``'s comparator) is a path inside the
      pinned tree that does not exist: gitignored, CI has none and a developer
      machine may, so pointing both at "absent" makes them answer the same.
    """
    root = pinned_board_root()
    from src.api import data_contract as _dc
    from src.history import store as _ledger_store

    real_ledger = _ledger_store.DB_PATH
    real_root = _dc._default_input_root
    _ledger_store.DB_PATH = root / "data" / "temporal_ledger.sqlite"
    _dc._default_input_root = lambda: root
    try:
        if freeze_clock:
            with frozen_build_clock(pinned_board_as_of()):
                yield root
        else:
            yield root
    finally:
        _dc._default_input_root = real_root
        _ledger_store.DB_PATH = real_ledger


def build_pinned_contract(payload: dict | None = None, **kwargs: Any) -> dict[str, Any]:
    """``build_api_data_contract`` over the pinned board, hermetically.

    ``payload`` defaults to a fresh copy of the pinned raw payload; pass one
    (e.g. a mutated copy) to build it against the pinned CSVs and state.
    ``kwargs`` go to ``build_api_data_contract`` (``source_overrides``, ...);
    ``csv_root`` is always the pinned tree.  Returns a new contract.
    """
    from src.api.data_contract import build_api_data_contract

    if payload is None:
        payload, _ = pinned_board_payload()
    if "csv_root" in kwargs:
        raise TypeError("build_pinned_contract always reads the pinned tree; csv_root is fixed")
    with pinned_build_environment() as root:
        return build_api_data_contract(payload, csv_root=root, **kwargs)


def pinned_board_contract() -> tuple[dict, str]:
    """``(contract, label)`` for the pinned board, built once per process.

    The SAME object is handed to every caller: treat it as READ-ONLY
    (``copy.deepcopy`` before mutating).  Never ``None`` -- the fixture is
    committed -- so a caller never skips.
    """
    contract = _PINNED.get("contract")
    if contract is None:
        contract = build_pinned_contract()
        _PINNED["contract"] = contract
    return contract, pinned_board_label()
