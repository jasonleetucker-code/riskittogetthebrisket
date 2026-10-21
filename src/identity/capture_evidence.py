"""Upstream identity evidence of a scraper capture (outlier-integrity V2.1 §3.7).

The identity owner's record of what a SCRAPED source published about who each
of its entries is, and how each value reached a board row.  Two registered
prerequisites of the V2.1 wrong-player gate live here:

* **U2** — for every value ``Dynasty Scraper.py`` attaches on ``ktc``,
  ``ktcSfTep`` and ``idpTradeCalc``: the matching RUNG that carried the
  vendor's name onto the payload row, the entry's PAGE POSITION (its ordinal
  place in the vendor's published list) and the ACQUISITION PATH (in-page
  value-source capture, API intercept, direct-API / bulk-JS / autocomplete
  fallbacks, cache, recovered partial).
* **U2b** — the OBSERVED Superflex and TE-premium state of the capture: what
  the captured data itself shows (which value block a number was read from, the
  final checkbox state on the page), next to what the scraper REQUESTED.  An
  unobservable state is ``None``, never the requested value restated.

The scraper is an ADAPTER here, exactly as it is for ``name_primitives``: it
calls :class:`CaptureEvidenceCollector` at the points where it already holds
the facts, and this module owns the vocabulary, the consistency rule and the
sidecar schema.  Nothing here changes a value, a join or a vote:

* the sidecar is written next to the payload, never INTO it, so the raw
  payload and therefore the built board are byte-identical with or without it.
  The full sidecar stays OUT of git (gitignored ``data/identity_capture_evidence/``
  plus a 90-day Actions artifact on the refresh runner); git receives only a
  checksummed manifest of aggregate counts (see "Storage" below);
* nothing on the board path reads it.  Its future reader is outlier-integrity
  V2.1's Layer A, which lives in the detection branch (PR #1884) and is NOT part
  of this module or of ``main``; this module only COLLECTS, because identity
  evidence that was not recorded when the capture happened cannot be recovered
  later.  The loader below is a pure sidecar-to-payload binding check.

**Missing is never evidence.**  A field the vendor did not publish is absent
from the stamp; an attachment whose payload value no longer equals the
captured value (the row was renamed, merged or re-priced after capture) is
DROPPED and counted, never carried onto a row it may not describe; a sidecar
whose ``scrapeTimestamp`` is not the payload's is not read at all.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

SCHEMA_VERSION = "identity_capture_evidence.v1"

#: The payload-attached sources U2 covers (preregistration §3.7).
STAMPED_SOURCES: tuple[str, ...] = ("ktc", "ktcSfTep", "idpTradeCalc")

# ── Acquisition paths ───────────────────────────────────────────────────
ACQ_VALUE_SOURCE_CAPTURE = "value_source_capture"  # KTC in-page playersArray
ACQ_CACHE = "cache"  # the scraper's own name→value cache; nothing observed
ACQ_API_INTERCEPT = "api_intercept"
ACQ_DIRECT_API = "direct_api_fallback"
ACQ_BULK_JS = "bulk_js_fallback"
ACQ_AUTOCOMPLETE = "autocomplete_fallback"  # typed query, matched by SURNAME
ACQUISITION_PATHS: frozenset[str] = frozenset(
    {
        ACQ_VALUE_SOURCE_CAPTURE,
        ACQ_CACHE,
        ACQ_API_INTERCEPT,
        ACQ_DIRECT_API,
        ACQ_BULK_JS,
        ACQ_AUTOCOMPLETE,
    }
)
#: A capture cut by the source timeout whose values were kept (the scraper's
#: "recovered partial autocomplete" branch).  A capture-level flag, carried on
#: every stamp of that capture as ``capturePartial``.
CAPTURE_RECOVERED_PARTIAL = "recovered_partial"

# ── Matching rungs (how a vendor name reached the payload row) ─────────
#: The scraper's rostered-name map (``_canonical_map``).
RUNG_ROSTER_EXACT = "roster_exact"
RUNG_ROSTER_LOOKUP = "roster_lookup"
RUNG_ROSTER_INITIAL = "roster_initial"
RUNG_ROSTER_FUZZY = "roster_fuzzy"
RUNG_ROSTER_UNMAPPED = "roster_unmapped"
#: ``resolve_scraper_attach_v1`` methods, prefixed ``identity:``.
IDENTITY_RUNG_PREFIX = "identity:"
#: Row merges after the attach.
RUNG_MERGE_PUNCTUATION = "merge:punctuation_variant"
RUNG_MERGE_FIRST_NAME = "merge:first_name_variant"

_FUZZY_STEPS = frozenset({RUNG_ROSTER_FUZZY, "identity:fuzzy_guarded"})
_SURNAME_STEPS = frozenset({RUNG_ROSTER_INITIAL, "identity:initial_last"})
_FIRST_NAME_STEPS = frozenset({RUNG_MERGE_FIRST_NAME})

#: ``via`` values: how strongly the matching rung identifies the vendor entry.
#: Only ``VIA_SCRAPER_EXACT`` is an exact join rung; the others are low-evidence
#: rungs (fuzzy, surname, first-name variant) a reader must treat as weaker.
VIA_SCRAPER_EXACT = "scraper_exact"
VIA_SCRAPER_SURNAME = "scraper_surname"
VIA_SCRAPER_FUZZY = "scraper_fuzzy"
VIA_SCRAPER_FIRST_NAME = "scraper_first_name_variant"

# ── Published-field parsing (shared by the scraper and the U3 fetchers) ─
#: The CSV columns U3 appends to name-only boards.  Never a rank, value or
#: Sleeper-id column: those change what a board votes or how it joins.
IDENTITY_CSV_COLUMNS: tuple[str, ...] = ("position", "team")

#: Per ``site_raw`` board (CSV stem, equal to its registry key), the identity
#: columns U3 ADDED.  Readers whose registered methodology predates U3 - the
#: source-quality panel, the lineage-integrity sweep and content staleness in
#: ``check_source_health`` - ignore exactly these, so their behaviour is
#: byte-identical across the U3 cutover.  A column a board already carried
#: before U3 (``position`` on the KTC capture boards) is NOT listed and keeps
#: its meaning.  Pinned by ``tests/identity/test_u3_research_readers.py``.
U3_ADDED_COLUMNS: dict[str, tuple[str, ...]] = {
    **{
        key: IDENTITY_CSV_COLUMNS
        for key in (
            "ktc",
            "ktcSfTep",
            "idpTradeCalc",
            "dlfSf",
            "dlfIdp",
            "dlfRookieSf",
            "dlfRookieIdp",
            "fantasyCalc",
            "otcffbSf",
            "dynastyDaddySf",
            "flockFantasySf",
            "flockFantasySfRookies",
            "fantasyNavigatorSf",
        )
    },
    **{key: ("team",) for key in ("ktcCrowdSfTep", "ktcTradesSfTep", "ktcCrowdTradesSfTep")},
}


def u3_added_columns(board_key: object) -> frozenset[str]:
    """The (lower-case) column names U3 added to ``board_key``'s CSV; empty when none."""
    return frozenset(U3_ADDED_COLUMNS.get(str(board_key or ""), ()))


def published_position(raw: object) -> str:
    """The position a vendor published, as a CSV cell (``""`` = not published).

    Stripped and upper-cased, otherwise VERBATIM: no positional rank is
    stripped and no alias is folded here.  The identity owner reads an unknown
    position (``"WR12"``, ``"OL"``) as no evidence, never as a mismatch, so a
    verbatim cell can only ever under-claim.
    """
    return str(raw or "").strip().upper()


def published_team(raw: object) -> str:
    """The team a vendor published, as a CSV cell (``""`` = not published)."""
    return str(raw or "").strip().upper()


def _clean_age(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        age = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(age) or not (0.0 < age < 60.0):
        return None
    return age


def _clean_vendor_id(raw: object) -> str | None:
    if raw is None or isinstance(raw, bool):
        return None
    text = str(raw).strip()
    if not text:
        return None
    if isinstance(raw, float) and raw.is_integer():
        text = str(int(raw))
    return text


def url_params(url: object) -> dict[str, str]:
    """The query parameters of a captured page URL (first value per key)."""
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return {}
    return {k: v[0] for k, v in sorted(parse_qs(parsed.query).items()) if v}


def via_for_steps(steps: Iterable[str], acquisition: str | None) -> str:
    """The ``via`` for one attachment: the WEAKEST step decides.

    A fuzzy step anywhere → ``scraper_fuzzy``; a surname step (initial +
    surname expansion, or an autocomplete capture matched by surname) →
    ``scraper_surname``; a first-name-variant merge →
    ``scraper_first_name_variant``; otherwise ``scraper_exact``.
    """
    steps = set(steps)
    if steps & _FUZZY_STEPS:
        return VIA_SCRAPER_FUZZY
    if steps & _SURNAME_STEPS or acquisition == ACQ_AUTOCOMPLETE:
        return VIA_SCRAPER_SURNAME
    if steps & _FIRST_NAME_STEPS:
        return VIA_SCRAPER_FIRST_NAME
    return VIA_SCRAPER_EXACT


def _same_value(a: object, b: object) -> bool:
    try:
        fa, fb = float(a), float(b)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(fa) and math.isfinite(fb)):
        return False
    return round(fa, 2) == round(fb, 2)


@dataclass(frozen=True)
class _Entry:
    value: float
    acquisition: str
    page_position: int | None
    position: str | None
    team: str | None
    age: float | None
    vendor_id: str | None
    value_key: str | None
    queried_name: str | None


def _entry_fields(entry: _Entry) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in (
        ("pagePosition", entry.page_position),
        ("position", entry.position),
        ("team", entry.team),
        ("age", entry.age),
        ("vendorId", entry.vendor_id),
        ("valueKey", entry.value_key),
        ("queriedName", entry.queried_name),
    ):
        if val is not None:
            out[key] = val
    return out


class CaptureEvidenceCollector:
    """Accumulates U2 / U2b evidence during ONE scraper run.

    Every method is cheap and side-effect free outside this object; the
    scraper wraps its calls so an evidence failure can never fail a scrape.
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, list[_Entry]]] = {}
        self._toggles: dict[str, dict[str, Any]] = {}
        self._acquisitions: dict[str, Counter[str]] = {}
        self._partial: set[str] = set()
        #: ``{source: {payload row name: (vendor name, value, steps)}}``
        self._attached: dict[str, dict[str, tuple[str, float, tuple[str, ...]]]] = {}
        self._discarded_merges: Counter[str] = Counter()
        self._failures: Counter[str] = Counter()

    # ── capture side ────────────────────────────────────────────────────
    def reset_all(self) -> None:
        """Forget everything (a new scraper run starts clean)."""
        self.__init__()

    def reset_source(self, source: str) -> None:
        """Forget a source's capture (a retried attempt starts clean)."""
        self._entries.pop(source, None)
        self._toggles.pop(source, None)
        self._acquisitions.pop(source, None)
        self._partial.discard(source)

    def add_entry(
        self,
        source: str,
        vendor_name: str,
        value: object,
        *,
        acquisition: str,
        page_position: int | None = None,
        position: object = None,
        team: object = None,
        age: object = None,
        vendor_id: object = None,
        value_key: str | None = None,
        queried_name: str | None = None,
    ) -> None:
        """One published entry, keyed by the scraper's own name key (the
        ``FULL_DATA`` key, i.e. ``clean_name`` of the vendor's name)."""
        if acquisition not in ACQUISITION_PATHS:
            raise ValueError(f"unknown acquisition path {acquisition!r}")
        try:
            num = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if not math.isfinite(num) or not vendor_name:
            return
        entry = _Entry(
            value=num,
            acquisition=acquisition,
            page_position=int(page_position) if page_position is not None else None,
            position=published_position(position) or None,
            team=published_team(team) or None,
            age=_clean_age(age),
            vendor_id=_clean_vendor_id(vendor_id),
            value_key=str(value_key) if value_key else None,
            queried_name=queried_name or None,
        )
        self._entries.setdefault(source, {}).setdefault(str(vendor_name), []).append(entry)
        self._acquisitions.setdefault(source, Counter())[acquisition] += 1

    def record_ktc_capture(self, capture: Any, clean: Any, requested_superflex: bool) -> None:
        """U2 / U2b for the explicit KTC Crowd capture: every in-page row as an
        entry of ``ktc`` (base ``superflexValues.value``) and ``ktcSfTep``
        (``superflexValues.tepp``), keyed by the scraper's ``clean`` name, with
        its 1-based place in the ``playersArray`` and the identity fields the
        row publishes; then the observed format state of each board."""
        rows = tuple(getattr(capture, "rows", ()) or ())
        for index, row in enumerate(rows, start=1):
            name = clean(getattr(row, "name", "") or "")
            fields = {
                "acquisition": ACQ_VALUE_SOURCE_CAPTURE,
                "page_position": index,
                "position": getattr(row, "position", None),
                "team": getattr(row, "team", None),
                "age": getattr(row, "age", None),
                "vendor_id": getattr(row, "player_id", None),
            }
            base = getattr(row, "base_value", None)
            tepp = getattr(row, "tepp_value", None)
            if base is not None:
                self.add_entry(
                    "ktc", name, int(round(base)), value_key="superflexValues.value", **fields
                )
            if tepp is not None:
                self.add_entry(
                    "ktcSfTep", name, int(round(tepp)), value_key="superflexValues.tepp", **fields
                )
        for source, tep_field in (("ktc", False), ("ktcSfTep", True)):
            self.set_toggles(
                source,
                {
                    **ktc_toggles(
                        rows,
                        page_url=getattr(capture, "page_url", None),
                        requested_superflex=requested_superflex,
                        tep_field=tep_field,
                    ),
                    "captureContentHash": getattr(capture, "content_hash", None),
                },
            )

    def record_cache_capture(
        self,
        source: str,
        name_map: Mapping[str, Any],
        requested_superflex: bool,
        requested_tep: object,
    ) -> None:
        """A cache hit observed nothing: entries without page position or
        published fields, and an unobserved format state (never the requested
        state restated)."""
        for name, value in (name_map or {}).items():
            self.add_entry(source, name, value, acquisition=ACQ_CACHE)
        self.set_toggles(
            source,
            unobserved_toggles(
                requested_superflex=requested_superflex, requested_tep=requested_tep, basis="cache"
            ),
        )

    def record_entry_dicts(
        self,
        source: str,
        entries: Iterable[Mapping[str, Any]],
        acquisition: str,
        value_key_census: dict[str, int] | None = None,
    ) -> None:
        """Entries the scraper collected as dicts (``name``, ``value`` and,
        where present, ``pagePosition`` / ``position`` / ``team`` /
        ``valueKey``); ``value_key_census`` is updated in place."""
        for e in entries or ():
            if not isinstance(e, Mapping):
                continue
            self.add_entry(
                source,
                str(e.get("name") or ""),
                e.get("value"),
                acquisition=acquisition,
                page_position=e.get("pagePosition"),
                position=e.get("position"),
                team=e.get("team"),
                value_key=e.get("valueKey"),
            )
            key = e.get("valueKey")
            if key and value_key_census is not None:
                value_key_census[str(key)] = value_key_census.get(str(key), 0) + 1

    def record_checkbox_toggles(
        self,
        source: str,
        requested_superflex: bool,
        requested_tep: bool,
        superflex_checked: object,
        tep_checked: object,
        value_keys: Mapping[str, int] | None = None,
    ) -> None:
        self.set_toggles(
            source,
            checkbox_toggles(
                requested_superflex=requested_superflex,
                requested_tep=requested_tep,
                superflex_checked=superflex_checked,
                tep_checked=tep_checked,
                value_keys=value_keys,
            ),
        )

    def set_toggles(self, source: str, toggles: Mapping[str, Any]) -> None:
        """U2b: the capture's requested and OBSERVED format state."""
        self._toggles[source] = dict(toggles)

    def mark_recovered_partial(self, source: str) -> None:
        self._partial.add(source)

    def note_failure(self, method: str) -> None:
        """Count one collector call the scraper's best-effort wrapper swallowed."""
        self._failures[str(method)] += 1

    def entry_fields(self, source: str, vendor_name: str, value: object) -> dict[str, Any]:
        """The published identity fields of the entry that carried ``value``
        under ``vendor_name`` (for the U3 CSV columns); ``{}`` when unknown or
        ambiguous."""
        entry, ambiguous = self._select(source, vendor_name, value)
        if entry is None or ambiguous:
            return {}
        return {"position": entry.position or "", "team": entry.team or ""}

    # ── attach side ─────────────────────────────────────────────────────
    def attach(
        self, source: str, row_name: str, vendor_name: str, value: object, steps: Iterable[str]
    ) -> None:
        """The scraper attached ``value`` (published under ``vendor_name``) to
        payload row ``row_name`` through ``steps`` (rung names, in order)."""
        if source not in STAMPED_SOURCES:
            return
        try:
            num = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        self._attached.setdefault(source, {})[str(row_name)] = (
            str(vendor_name),
            num,
            tuple(str(s) for s in steps if s),
        )

    def merge(self, secondary: str, primary: str, step: str, moved_sources: Iterable[str]) -> None:
        """Row ``secondary`` merged into ``primary``: its attachment for every
        source in ``moved_sources`` (the slots ``primary`` took from it) moves
        with the merge step appended; every other attachment of ``secondary``
        is discarded (``primary`` kept its own value)."""
        moved = set(moved_sources)
        for source, by_row in self._attached.items():
            got = by_row.pop(str(secondary), None)
            if got is None:
                continue
            if source in moved:
                vendor_name, value, steps = got
                by_row[str(primary)] = (vendor_name, value, (*steps, step))
            else:
                self._discarded_merges[source] += 1

    # ── output ──────────────────────────────────────────────────────────
    def _select(self, source: str, vendor_name: str, value: object) -> tuple[_Entry | None, bool]:
        """``(entry, ambiguous)``: the entry of ``vendor_name`` carrying
        ``value``.  Several such entries that disagree on any published
        identity field are AMBIGUOUS: the stamp says so and lists every
        candidate, and no U3 CSV cell is written for it."""
        pool = [
            e
            for e in self._entries.get(source, {}).get(vendor_name, [])
            if _same_value(e.value, value)
        ]
        if not pool:
            return None, False
        fields = {(e.position, e.team, e.age, e.vendor_id) for e in pool}
        if len(fields) > 1:
            return pool[0], True
        return pool[0], False

    def build_sidecar(
        self,
        players: Mapping[str, Any],
        *,
        scrape_timestamp: str | None,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        """The sidecar, filtered against the FINAL payload ``players``.

        An attachment survives only when the payload row still exists and
        still carries exactly the captured value for that source."""
        sources_out: dict[str, Any] = {}
        census: dict[str, Any] = {}
        for source in STAMPED_SOURCES:
            attached_out: dict[str, Any] = {}
            dropped = Counter()
            for row_name, (vendor_name, value, steps) in sorted(
                self._attached.get(source, {}).items()
            ):
                prow = players.get(row_name) if isinstance(players, Mapping) else None
                if not isinstance(prow, Mapping):
                    dropped["rowMissing"] += 1
                    continue
                if not _same_value(prow.get(source), value):
                    dropped["valueMismatch"] += 1
                    continue
                entry, ambiguous = self._select(source, vendor_name, value)
                acquisition = entry.acquisition if entry is not None else None
                stamp: dict[str, Any] = {
                    "vendorName": vendor_name,
                    "value": value,
                    "rung": list(steps),
                    "via": via_for_steps(steps, acquisition),
                }
                if entry is None:
                    stamp["entry"] = "not_captured"
                    dropped["entryNotCaptured"] += 1
                else:
                    stamp["acquisition"] = acquisition
                    stamp.update(_entry_fields(entry))
                    if ambiguous:
                        stamp["entryAmbiguous"] = True
                    # Every entry the vendor published under this name (an
                    # in-source duplicate): a reader decides among them on
                    # their own evidence, never this module.
                    pool = self._entries.get(source, {}).get(vendor_name, [])
                    if len(pool) > 1:
                        stamp["candidates"] = [{"value": e.value, **_entry_fields(e)} for e in pool]
                        stamp["chosen"] = pool.index(entry)
                if source in self._partial:
                    stamp["capturePartial"] = True
                attached_out[row_name] = stamp
            src_block: dict[str, Any] = {
                "acquisition": dict(sorted(self._acquisitions.get(source, Counter()).items())),
                "toggles": self._toggles.get(source),
                "entryCount": sum(len(v) for v in self._entries.get(source, {}).values()),
                "attached": attached_out,
            }
            if source in self._partial:
                src_block["capture"] = CAPTURE_RECOVERED_PARTIAL
            sources_out[source] = src_block
            census[source] = {
                "stamped": len(attached_out),
                "dropped": dict(sorted(dropped.items())),
                "mergeDiscarded": int(self._discarded_merges.get(source, 0)),
            }
        # Collector calls the scraper's best-effort wrapper swallowed.  Always
        # present: 0 is an observation ("no evidence call failed"), and a
        # non-zero count says the stamps above may be incomplete.
        census["collectorErrors"] = {
            "total": int(sum(self._failures.values())),
            "byMethod": dict(sorted(self._failures.items())),
        }
        return {
            "schema": SCHEMA_VERSION,
            "scrapeTimestamp": scrape_timestamp,
            "generatedAt": generated_at or datetime.now(timezone.utc).isoformat(),
            "sources": sources_out,
            "census": census,
        }


# ── Storage: full evidence out of git, a checksummed manifest in git ────────
#
# The full sidecar is ~450 KB of JSON per scrape (~35 KB gzipped).  The refresh
# workflow force-adds ``data/scrape_state/`` and commits ``exports/archive/*.zip``
# every two hours, so carrying it there would grow git history without bound.
# So the evidence is split:
#
# * the FULL sidecar is written, gzip-compressed and byte-deterministic, to
#   ``data/identity_capture_evidence/`` - a gitignored directory that no refresh
#   step force-adds.  On the CI refresh runner it is uploaded as a GitHub Actions
#   artifact (90-day retention, the repository maximum); on the production box it
#   is pruned by ``src.maintenance.retention`` after
#   ``BOX_EVIDENCE_RETENTION_DAYS``;
# * a small MANIFEST - the sidecar's checksums, per-source aggregate counts, the
#   U2b observed-format block, and where the full file lives - is written to
#   ``data/scrape_state/identity_capture_manifest.json`` and archived in the
#   export bundle beside the payload it describes.
#
# The checksum is SHA-256 over the canonical (uncompressed) JSON bytes, so the
# full evidence verifies against git whatever container it travels in.

EVIDENCE_DIR_REL = Path("data") / "identity_capture_evidence"
MANIFEST_FILENAME = "identity_capture_manifest.json"
MANIFEST_REL = Path("data") / "scrape_state" / MANIFEST_FILENAME
MANIFEST_SCHEMA_VERSION = "identity_capture_manifest.v1"
#: Box-local copies are pruned after this many days (``src.maintenance.retention``).
#: They describe the BOX's own scrapes; the evaluated boards are the refresh's,
#: whose full evidence lives in the run artifact.
BOX_EVIDENCE_RETENTION_DAYS = 30
#: GitHub's maximum artifact retention for this (public) repository.
ARTIFACT_RETENTION_DAYS = 90
ARTIFACT_NAME_PREFIX = "identity-capture-evidence"


def canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    """The sidecar's canonical serialization (the bytes the checksum covers)."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (text + "\n").encode("utf-8")


def _gzip_deterministic(data: bytes) -> bytes:
    import gzip  # noqa: PLC0415
    import io as _io  # noqa: PLC0415

    buf = _io.BytesIO()
    # mtime=0 and no embedded filename: identical input -> identical bytes.
    with gzip.GzipFile(filename="", mode="wb", fileobj=buf, mtime=0, compresslevel=9) as gz:
        gz.write(data)
    return buf.getvalue()


def _sha256(data: bytes) -> str:
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(data).hexdigest()


def stamp_key(scrape_timestamp: object) -> str:
    """``YYYYMMDDTHHMMSSZ`` (UTC) for a scrape timestamp; ``unknown`` if unreadable.

    The compact form the retention pruner's filename-date rule reads."""
    if not scrape_timestamp:
        return "unknown"
    try:
        dt = datetime.fromisoformat(str(scrape_timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def evidence_filename(scrape_timestamp: object) -> str:
    return f"identity_capture_evidence_{stamp_key(scrape_timestamp)}.json.gz"


def artifact_name(run_id: object, run_attempt: object) -> str:
    """The Actions artifact name for one refresh run.  The workflow's
    ``upload-artifact`` step builds the same string from the same two values
    (pinned by ``tests/identity/test_capture_evidence_storage.py``)."""
    return f"{ARTIFACT_NAME_PREFIX}-{run_id}-{run_attempt}"


def artifact_pointer(env: Mapping[str, str]) -> dict[str, Any] | None:
    """Where a CI refresh run uploads the full evidence; ``None`` off CI."""
    run_id = str(env.get("GITHUB_RUN_ID") or "").strip()
    if not run_id or str(env.get("GITHUB_ACTIONS") or "").lower() != "true":
        return None
    attempt = str(env.get("GITHUB_RUN_ATTEMPT") or "1").strip() or "1"
    return {
        "kind": "github_actions_artifact",
        "repository": str(env.get("GITHUB_REPOSITORY") or "") or None,
        "runId": run_id,
        "runAttempt": attempt,
        "name": artifact_name(run_id, attempt),
        "retentionDays": ARTIFACT_RETENTION_DAYS,
    }


_MANIFEST_FIELD_PRESENCE = ("pagePosition", "position", "team", "age", "vendorId", "valueKey")


def build_manifest(
    payload: Mapping[str, Any],
    *,
    evidence_bytes: bytes,
    gzip_bytes: bytes,
    filename: str,
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The committed summary of one sidecar.  Aggregates only: no player row,
    stamp or vendor name enters git through it."""
    sources_in = payload.get("sources") if isinstance(payload, Mapping) else None
    sources_out: dict[str, Any] = {}
    for source in STAMPED_SOURCES:
        block = sources_in.get(source) if isinstance(sources_in, Mapping) else None
        block = block if isinstance(block, Mapping) else {}
        attached = block.get("attached")
        attached = attached if isinstance(attached, Mapping) else {}
        stamps = [st for st in attached.values() if isinstance(st, Mapping)]
        vias = Counter(str(st.get("via")) for st in stamps)
        fields = Counter(f for st in stamps for f in _MANIFEST_FIELD_PRESENCE if f in st)
        out: dict[str, Any] = {
            "entryCount": block.get("entryCount", 0),
            "acquisition": dict(block.get("acquisition") or {}),
            # U2b is a few hundred bytes and is exactly what readiness asks of a board.
            "toggles": block.get("toggles"),
            "stampsByVia": dict(sorted(vias.items())),
            "stampsWithField": dict(sorted(fields.items())),
        }
        if block.get("capture"):
            out["capture"] = block.get("capture")
        sources_out[source] = out
    return {
        "schema": MANIFEST_SCHEMA_VERSION,
        "evidenceSchema": payload.get("schema"),
        "scrapeTimestamp": payload.get("scrapeTimestamp"),
        "generatedAt": payload.get("generatedAt"),
        "evidence": {
            "filename": filename,
            "sha256": _sha256(evidence_bytes),
            "bytes": len(evidence_bytes),
            "gzipSha256": _sha256(gzip_bytes),
            "gzipBytes": len(gzip_bytes),
        },
        "census": payload.get("census"),
        "sources": sources_out,
        "storage": {
            "boxLocal": (EVIDENCE_DIR_REL / filename).as_posix(),
            "boxLocalRetentionDays": BOX_EVIDENCE_RETENTION_DAYS,
            "artifact": dict(artifact) if artifact else None,
        },
    }


def _atomic_write(path: Path, data: bytes) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def write_evidence(
    payload: Mapping[str, Any],
    root: Path,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Write the full gzipped sidecar under ``root/EVIDENCE_DIR_REL`` and the
    manifest to ``root/MANIFEST_REL``; returns the manifest.

    Serialization happens before any file is touched, so a payload that cannot
    be serialized leaves the previous evidence and manifest intact."""
    raw = canonical_bytes(payload)
    gz = _gzip_deterministic(raw)
    filename = evidence_filename(payload.get("scrapeTimestamp"))
    manifest = build_manifest(
        payload,
        evidence_bytes=raw,
        gzip_bytes=gz,
        filename=filename,
        artifact=artifact_pointer(env or {}),
    )
    manifest_bytes = canonical_bytes(manifest)
    _atomic_write(Path(root) / EVIDENCE_DIR_REL / filename, gz)
    _atomic_write(Path(root) / MANIFEST_REL, manifest_bytes)
    return manifest


# ── Verification and binding (read-only) ─────────────────────────────────────
STATE_BOUND = "bound"
STATE_MISSING = "missing"
STATE_UNREADABLE = "unreadable"
STATE_SCHEMA_MISMATCH = "schema_mismatch"
STATE_TIMESTAMP_MISMATCH = "scrape_timestamp_mismatch"
STATE_CHECKSUM_MISMATCH = "checksum_mismatch"


@dataclass(frozen=True)
class CaptureEvidence:
    """A sidecar bound to ONE payload (matching ``scrapeTimestamp``)."""

    sources: Mapping[str, Mapping[str, Any]]

    def stamp_for(self, source: str, row_name: str) -> Mapping[str, Any] | None:
        block = self.sources.get(source)
        if not isinstance(block, Mapping):
            return None
        attached = block.get("attached")
        if not isinstance(attached, Mapping):
            return None
        stamp = attached.get(row_name)
        return stamp if isinstance(stamp, Mapping) else None

    def toggles(self, source: str) -> Mapping[str, Any] | None:
        block = self.sources.get(source)
        got = block.get("toggles") if isinstance(block, Mapping) else None
        return got if isinstance(got, Mapping) else None


def _same_instant(a: object, b: object) -> bool:
    if not a or not b:
        return False
    try:
        da = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
        db = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
    except ValueError:
        return str(a) == str(b)
    if da.tzinfo is None:
        da = da.replace(tzinfo=timezone.utc)
    if db.tzinfo is None:
        db = db.replace(tzinfo=timezone.utc)
    return da == db


def _decompress(blob: bytes) -> bytes:
    import gzip  # noqa: PLC0415

    return gzip.decompress(blob) if blob[:2] == b"\x1f\x8b" else blob


def verify_evidence(blob: bytes, manifest: Mapping[str, Any]) -> tuple[dict | None, str]:
    """``(payload, state)``: the full evidence (gzipped or plain JSON bytes)
    checked against a committed manifest.  ``STATE_BOUND`` only when the
    canonical bytes hash to the manifest's ``evidence.sha256`` AND the
    ``scrapeTimestamp`` matches - an unverifiable file is never evidence."""
    if not isinstance(manifest, Mapping) or manifest.get("schema") != MANIFEST_SCHEMA_VERSION:
        return None, STATE_SCHEMA_MISMATCH
    expected = (manifest.get("evidence") or {}).get("sha256")
    try:
        raw = _decompress(bytes(blob))
        data = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, EOFError):
        return None, STATE_UNREADABLE
    if not isinstance(data, Mapping) or data.get("schema") != SCHEMA_VERSION:
        return None, STATE_SCHEMA_MISMATCH
    if not expected or _sha256(canonical_bytes(data)) != expected:
        return None, STATE_CHECKSUM_MISMATCH
    if not _same_instant(data.get("scrapeTimestamp"), manifest.get("scrapeTimestamp")):
        return None, STATE_TIMESTAMP_MISMATCH
    return dict(data), STATE_BOUND


def load_capture_evidence(
    root: Path,
    scrape_timestamp: object,
    manifest: Mapping[str, Any] | None = None,
) -> tuple[CaptureEvidence | None, str]:
    """``(evidence, state)`` for the payload stamped ``scrape_timestamp``.

    Reads ``root/EVIDENCE_DIR_REL/<file for that timestamp>`` and verifies it
    against ``manifest`` (default: ``root/MANIFEST_REL``).  Evidence from
    another scrape, or bytes that do not match the committed checksum, are not
    read at all."""
    root = Path(root)
    if manifest is None:
        try:
            manifest = json.loads((root / MANIFEST_REL).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None, STATE_MISSING
        except (OSError, ValueError):
            return None, STATE_UNREADABLE
    if not isinstance(manifest, Mapping) or manifest.get("schema") != MANIFEST_SCHEMA_VERSION:
        return None, STATE_SCHEMA_MISMATCH
    if not _same_instant(manifest.get("scrapeTimestamp"), scrape_timestamp):
        return None, STATE_TIMESTAMP_MISMATCH
    path = root / EVIDENCE_DIR_REL / evidence_filename(scrape_timestamp)
    try:
        blob = path.read_bytes()
    except FileNotFoundError:
        return None, STATE_MISSING
    except OSError:
        return None, STATE_UNREADABLE
    data, state = verify_evidence(blob, manifest)
    if data is None:
        return None, state
    sources = data.get("sources")
    if not isinstance(sources, Mapping):
        return None, STATE_SCHEMA_MISMATCH
    return CaptureEvidence(sources=sources), STATE_BOUND


def manifest_from_archive(archive: Path | bytes) -> dict[str, Any] | None:
    """The manifest an export-archive zip carries beside its payload, or
    ``None`` (boards produced before U2 shipped, or an unreadable zip) -
    absent stays absent."""
    import io as _io  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    source = _io.BytesIO(archive) if isinstance(archive, (bytes, bytearray)) else archive
    try:
        with zipfile.ZipFile(source) as zf:
            try:
                data = zf.read(MANIFEST_FILENAME)
            except KeyError:
                return None
    except (OSError, zipfile.BadZipFile):
        return None
    try:
        got = json.loads(data.decode("utf-8"))
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def ktc_toggles(
    rows: Iterable[Any],
    *,
    page_url: object,
    requested_superflex: bool,
    tep_field: bool,
) -> dict[str, Any]:
    """U2b for one KTC value board read from the in-page ``playersArray``.

    ``rows`` are ``KtcValueObservation``s.  Observed Superflex: a number read
    from the ``superflexValues`` block (the in-page projection builds that
    block from the player's own ``superflexValues``, so a base value present
    means the block was present).  Observed TE premium: ``"TE++"`` when the
    board's numbers come from ``superflexValues.tepp`` (``tep_field``),
    ``"none"`` when they come from the base ``superflexValues.value``.  The
    URL parameters are recorded verbatim; they are a request, not an
    observation."""
    rows = list(rows)
    sf_rows = sum(1 for r in rows if getattr(r, "base_value", None) is not None)
    tepp_rows = sum(1 for r in rows if getattr(r, "tepp_value", None) is not None)
    field_rows = tepp_rows if tep_field else sf_rows
    return {
        "basis": "in_page_players_array",
        "pageUrl": str(page_url or "") or None,
        "urlParams": url_params(page_url),
        "rows": len(rows),
        "superflex": {
            "requested": bool(requested_superflex),
            "observed": True if sf_rows else None,
            "evidence": "superflexValues.value present",
            "rowsObserved": sf_rows,
        },
        "tePremium": {
            "requested": "TE++" if tep_field else "none",
            "observed": ("TE++" if tep_field else "none") if field_rows else None,
            "evidence": "superflexValues.tepp" if tep_field else "superflexValues.value",
            "rowsObserved": field_rows,
        },
    }


def unobserved_toggles(
    *, requested_superflex: bool, requested_tep: object, basis: str
) -> dict[str, Any]:
    """U2b for a capture that observed no format state (e.g. the cache)."""
    return {
        "basis": basis,
        "superflex": {"requested": bool(requested_superflex), "observed": None},
        "tePremium": {"requested": requested_tep, "observed": None},
    }


def checkbox_toggles(
    *,
    requested_superflex: bool,
    requested_tep: bool,
    superflex_checked: object,
    tep_checked: object,
    value_keys: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """U2b for IDP Trade Calculator: the final DOM checkbox state read back
    after the scraper set it, plus the census of value keys the numbers were
    read from (``value_sftep`` = SF + TEP column).  A checkbox read that did
    not return a boolean is unobserved (``None``)."""

    def _bool(v: object) -> bool | None:
        return v if isinstance(v, bool) else None

    return {
        "basis": "dom_checkbox_final_state",
        "superflex": {"requested": bool(requested_superflex), "observed": _bool(superflex_checked)},
        "tePremium": {"requested": bool(requested_tep), "observed": _bool(tep_checked)},
        "valueKeys": dict(sorted((value_keys or {}).items())),
    }
