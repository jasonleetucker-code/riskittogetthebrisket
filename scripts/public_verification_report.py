"""The ONE owner of what a production-verification run may PUBLISH.

This repository is PUBLIC, so every GitHub Actions log line and every uploaded
artifact is readable by anyone.  The production verifiers
(``scripts/verify_v1_authenticated.py`` and
``scripts/verify_lane4_production.py --mode remote``) run with a real session
against the deployed origin and see private response bodies: Sharp manager
quality, FAAB recommendations, starter deltas, Sleeper owner ids, the
roster-percentage cohort, raw error bodies.  Their full reports are for a
private host; what reaches a public log or artifact goes through here.

Posture — the same as ``tests/e2e/prod-auth-safe-reporter.js``, made stricter
because these reports are built from API bodies rather than test prose:

* **Default deny.**  A check publishes ``id``, ``row``, ``status``,
  ``denominator`` and a code-authored ``title``.  Its ``detail`` (free text
  that interpolates response values) is NEVER published.  Its ``evidence`` is
  published only for keys the PRODUCER explicitly allowlists for that check
  id, and only when the value has the declared kind.
* **Kinds, not trust.**  Allowed value kinds are counts, finite numbers,
  booleans, explicit ``null`` (missing is never zero — a ``null`` stays
  ``null``), lower-case reason/enum codes, ISO timestamps, short version
  strings, git SHAs, and maps over a FIXED key set.  A value of the wrong kind
  is dropped, never coerced — a string in a count field does not become 0.
* **Withholding is visible.**  Each check reports ``evidenceWithheld``: how
  many evidence keys it did not publish.  "Nothing to say" and "not allowed to
  say it" must not read the same.
* **Defense in depth.**  Any published string containing a supplied secret (the
  session cookie value) is dropped, as is anything shaped like a
  ``jason_session=`` header.

What deliberately cannot pass: player names, team names, Sleeper owner /
roster / league ids, asset ids, FAAB bid amounts, manager-quality values,
starter deltas, response bodies, exception messages, request payloads.

Stdlib only — the GitHub runner installs nothing for these scripts.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

SCHEMA = "public-verification-report/v1"

#: Every status either producer can emit.  Anything else is published as
#: ``"invalid_status"`` so a vocabulary drift is visible rather than silent.
STATUS_VOCABULARY = frozenset(
    {
        "pass",
        "fail",
        "unmeasurable",
        "blocked",
        "error",
        "inconclusive",
        "unverifiable_unauthenticated",
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,39}$")
_ROW_RE = re.compile(r"^(-|[A-Za-z0-9][A-Za-z0-9_.:\-]{0,39})$")
#: Code-authored check titles: plain prose punctuation only, bounded.
_TITLE_RE = re.compile(r"^[A-Za-z0-9 .,:;()/'+\-_=<>§#&!?—→]{1,200}$")
_ENUM_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
#: ``state`` / ``reason`` codes, optionally qualified:
#: ``target_format_unverifiable:tep,superflex``.
_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}(:[a-z0-9_]{1,40}(,[a-z0-9_]{1,40}){0,9})?$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})?$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.\-]{0,39}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.\-]{1,253}(:\d{1,5})?$")
_LEAGUE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SESSION_HEADER_RE = re.compile(r"jason_session\s*=", re.I)

# ── value kinds ────────────────────────────────────────────────────────
COUNT = "count"
NUMBER = "number"
BOOL = "bool"
ENUM = "enum"
REASON = "reason"
TIMESTAMP = "timestamp"
VERSION = "version"
SHA = "sha"


def count_map(keys: Iterable[str]) -> tuple[str, frozenset[str]]:
    """A map over a FIXED key set whose values are counts."""
    return ("count_map", frozenset(keys))


def enum_map(keys: Iterable[str]) -> tuple[str, frozenset[str]]:
    """A map over a FIXED key set whose values are enum codes."""
    return ("enum_map", frozenset(keys))


def reason_list(max_items: int = 10) -> tuple[str, int]:
    """A short list of reason/enum codes (e.g. unprovable format axes)."""
    return ("reason_list", max_items)


class _Drop:
    """Sentinel: the value failed its kind and is not published."""


_DROP = _Drop()


def _is_count(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _clean_scalar(kind: str, value: Any) -> Any:
    if value is None:
        return None  # explicit null is a real, publishable answer: unknown
    if kind == COUNT:
        return value if _is_count(value) else _DROP
    if kind == NUMBER:
        return value if _is_number(value) else _DROP
    if kind == BOOL:
        return value if isinstance(value, bool) else _DROP
    if not isinstance(value, str):
        return _DROP
    pattern = {
        ENUM: _ENUM_RE,
        REASON: _REASON_RE,
        TIMESTAMP: _TIMESTAMP_RE,
        VERSION: _VERSION_RE,
        SHA: _SHA_RE,
    }.get(kind)
    if pattern is None or not pattern.match(value):
        return _DROP
    return value


def clean_value(kind: Any, value: Any) -> Any:
    """``value`` if it has the declared ``kind``, else the drop sentinel."""
    if isinstance(kind, tuple):
        shape, arg = kind
        if value is None:
            return None
        if shape in ("count_map", "enum_map"):
            if not isinstance(value, Mapping) or not set(value) <= arg:
                return _DROP
            inner = COUNT if shape == "count_map" else ENUM
            out = {k: _clean_scalar(inner, v) for k, v in value.items()}
            return _DROP if any(v is _DROP for v in out.values()) else out
        if shape == "reason_list":
            if not isinstance(value, (list, tuple)) or len(value) > arg:
                return _DROP
            out_list = [_clean_scalar(REASON, v) for v in value]
            return _DROP if any(v is _DROP or v is None for v in out_list) else out_list
        return _DROP
    return _clean_scalar(kind, value)


def _contains_secret(value: Any, secrets: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        return bool(_SESSION_HEADER_RE.search(value)) or any(s and s in value for s in secrets)
    if isinstance(value, Mapping):
        return any(
            _contains_secret(k, secrets) or _contains_secret(v, secrets) for k, v in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(v, secrets) for v in value)
    return False


def _usable_secrets(secrets: Iterable[str] | None) -> tuple[str, ...]:
    # A secret shorter than 8 characters would scrub ordinary words/numbers.
    return tuple(s for s in (secrets or ()) if isinstance(s, str) and len(s) >= 8)


def public_check(
    check_id: Any,
    row: Any,
    title: Any,
    status: Any,
    evidence: Mapping[str, Any] | None,
    allowed: Mapping[str, Any] | None,
    *,
    denominator: Any = None,
    secrets: Iterable[str] | None = None,
) -> dict[str, Any]:
    """One check, reduced to its publishable fields."""
    secret_t = _usable_secrets(secrets)
    out: dict[str, Any] = {
        "id": check_id if isinstance(check_id, str) and _ID_RE.match(check_id) else "invalid_id",
        "row": row if isinstance(row, str) and _ROW_RE.match(row) else None,
        "status": status if status in STATUS_VOCABULARY else "invalid_status",
    }
    if isinstance(title, str) and _TITLE_RE.match(title) and not _contains_secret(title, secret_t):
        out["title"] = title
    if denominator is not None:
        out["denominator"] = denominator if _is_count(denominator) else None
    published: dict[str, Any] = {}
    withheld = 0
    for key, value in (evidence or {}).items():
        kind = (allowed or {}).get(key)
        if kind is None:
            withheld += 1
            continue
        cleaned = clean_value(kind, value)
        if cleaned is _DROP or _contains_secret(cleaned, secret_t):
            withheld += 1
            continue
        published[key] = cleaned
    out["evidence"] = published
    out["evidenceWithheld"] = withheld
    return out


def status_counts(checks: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return dict(sorted(counts.items()))


def public_report(
    *,
    producer: str,
    generated_at: str,
    origin: Any,
    league: Any,
    checks: list[dict[str, Any]],
    exit_code: int,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The whole public document.  ``checks`` must come from :func:`public_check`."""
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "sanitized": True,
        "producer": producer,
        "generatedAt": generated_at if _TIMESTAMP_RE.match(str(generated_at)) else None,
        "origin": origin if isinstance(origin, str) and _ORIGIN_RE.match(origin) else None,
        "league": league if isinstance(league, str) and _LEAGUE_RE.match(league) else None,
        "counts": status_counts(checks),
        "exitCode": exit_code,
        "checks": checks,
        "withheld": "check detail text, request payloads and response bodies are never "
        "published; see the producer's private report on a private host",
    }
    if extra:
        report.update(extra)
    return report


def summary_lines(report: Mapping[str, Any]) -> list[str]:
    """One human line per check for the job log — ids and statuses only."""
    lines = [
        f"[{report.get('producer')}] {' '.join(f'{k}={v}' for k, v in report['counts'].items())}"
        f" -> exit {report.get('exitCode')}"
    ]
    for c in report["checks"]:
        lines.append(f"  {c['status']:<28} {c['id']:<16} {c.get('row') or '-'}")
    return lines
