"""Launch-gate check for the owner's public source-permission record (R2-10).

Directive 2026-10-20 §9 / §16 gate 6: the public Brisket Trade Advisor may not
launch until the source-permission questions (design OD-3a-d) are resolved.
The launch gate (``public_trade_advisor_api._launch_gate_reason``) used to
accept ANY existing file inside the repo as that record — ``README.md`` opened
the leg.  This module is the one place the record is validated, and it fails
closed on anything malformed, partial or stale.

The record is a JSON file the OWNER writes under ``docs/owner/`` and names in
``config/trade/public_advisor.json::approvedSourcePermissionRecord``.  Nothing
here writes, proposes or infers one.  Shape (schema version 1)::

    {
      "recordType": "brisket_trade_advisor_source_permission",
      "schemaVersion": 1,
      "scope": "public_fairness_verdict",
      "approvedBy": "<who approved>",
      "approvedAt": "YYYY-MM-DD",
      "reviewBy": "YYYY-MM-DD",
      "providers": {"<provider>": "approved" | "denied" | "unknown", ...},
      "sources":   {"<source key>": "approved" | "denied" | "unknown", ...}
    }

Rules (every one fails closed):

* the path is relative, under ``docs/owner/``, ends in ``.json``, resolves
  inside the repository (no symlink escape) and is a regular file of bounded
  size;
* the body is one JSON object with the exact ``recordType`` /
  ``schemaVersion`` / ``scope``, a non-empty ``approvedBy`` and ISO dates with
  ``approvedAt <= today <= reviewBy`` — past ``reviewBy`` the record is STALE
  (the owner sets that date; no staleness constant is invented here);
* EVERY source key registered to vote on the canonical board
  (``data_contract._RANKING_SOURCES``) is covered: by its own ``sources``
  entry, else by its recorded provider's ``providers`` entry
  (``source_census.provider_of``).  A key with no entry and no recorded
  provider is uncovered — never assumed.  ``denied`` / ``unknown`` at either
  level refuses (deny wins over an approval at the other level).  A source
  added to the board after the record was written is therefore uncovered, so
  the record goes stale by construction when the voting set changes.

The returned reason is INTERNAL (logs / tests); it is never published.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

RECORD_TYPE = "brisket_trade_advisor_source_permission"
SCHEMA_VERSION = 1
SCOPE = "public_fairness_verdict"
RECORD_DIR = "docs/owner"
MAX_RECORD_BYTES = 256 * 1024
_STATES = frozenset({"approved", "denied", "unknown"})

_REPO = Path(__file__).resolve().parents[2]


def _today() -> _dt.date:
    """The check's clock (UTC date) — a test seam."""
    return _dt.datetime.now(_dt.timezone.utc).date()


def _iso_date(raw: Any) -> _dt.date | None:
    if not isinstance(raw, str) or len(raw) != 10:
        return None
    try:
        return _dt.date.fromisoformat(raw)
    except ValueError:
        return None


def _state_map(raw: Any) -> dict[str, str] | None:
    """``{key: state}`` with every key a non-empty str and every state in
    :data:`_STATES`; ``None`` when malformed.  Absent means empty."""
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        return None
    out: dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not k.strip() or v not in _STATES:
            return None
        out[k] = str(v)
    return out


def record_problem(
    record: Any,
    *,
    voting_sources: Iterable[str],
    provider_of: Callable[[str], str | None],
    today: _dt.date,
) -> str | None:
    """``None`` when ``record`` (a parsed JSON value) is a complete, current
    owner approval covering every voting source; otherwise the first problem."""
    if not isinstance(record, Mapping):
        return "not_an_object"
    if record.get("recordType") != RECORD_TYPE:
        return "wrong_record_type"
    sv = record.get("schemaVersion")
    if isinstance(sv, bool) or sv != SCHEMA_VERSION:
        return "unsupported_schema_version"
    if record.get("scope") != SCOPE:
        return "wrong_scope"
    approved_by = record.get("approvedBy")
    if not isinstance(approved_by, str) or not approved_by.strip():
        return "approver_missing"
    approved_at = _iso_date(record.get("approvedAt"))
    review_by = _iso_date(record.get("reviewBy"))
    if approved_at is None or review_by is None:
        return "dates_malformed"
    if approved_at > today:
        return "approved_in_future"
    if review_by < approved_at:
        return "dates_inconsistent"
    if today > review_by:
        return "stale"
    providers = _state_map(record.get("providers"))
    sources = _state_map(record.get("sources"))
    if providers is None or sources is None:
        return "permissions_malformed"
    keys = sorted({str(k) for k in voting_sources if k})
    if not keys:
        return "voting_sources_unknown"
    for key in keys:
        provider = provider_of(key)
        source_state = sources.get(key)
        provider_state = providers.get(provider) if provider else None
        if source_state is None and provider_state is None:
            return f"uncovered:{key}"
        if "denied" in (source_state, provider_state):
            return f"denied:{key}"
        if "unknown" in (source_state, provider_state):
            return f"unresolved:{key}"
    return None


def _resolve_record_path(rel: str, repo: Path) -> Path | None:
    text = str(rel or "").strip()
    if not text or text.startswith(("/", "\\")) or "\\" in text:
        return None
    if not text.endswith(".json"):
        return None
    record_dir = (repo / RECORD_DIR).resolve()
    try:
        path = (repo / text).resolve()
    except (OSError, ValueError):
        return None
    if record_dir not in path.parents:
        return None
    return path


def voting_source_keys() -> list[str]:
    """Every source key registered to vote on the canonical board."""
    from src.api.data_contract import _RANKING_SOURCES  # noqa: PLC0415

    return [str(s.get("key") or "") for s in _RANKING_SOURCES if s.get("key")]


def record_path_problem(
    rel: str | None,
    *,
    repo: Path | None = None,
    voting_sources: Iterable[str] | None = None,
    provider_of: Callable[[str], str | None] | None = None,
    today: _dt.date | None = None,
) -> str | None:
    """Validate the configured record path end to end.  ``None`` = the record
    is a complete, current owner approval; otherwise the internal reason."""
    if not rel:
        return "unrecorded"
    root = repo or _REPO
    path = _resolve_record_path(rel, root)
    if path is None:
        return "path_not_allowed"
    try:
        if not path.is_file():
            return "missing"
        if path.stat().st_size > MAX_RECORD_BYTES:
            return "too_large"
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    if provider_of is None:
        from src.sources.source_census import provider_of as _provider_of  # noqa: PLC0415

        provider_of = _provider_of
    return record_problem(
        record,
        voting_sources=voting_source_keys() if voting_sources is None else voting_sources,
        provider_of=provider_of,
        today=today or _today(),
    )


# ── Owner checklist (read-only; never a record) ─────────────────────────────


def permission_checklist(
    *,
    voting_sources: Iterable[str] | None = None,
    provider_of: Callable[[str], str | None] | None = None,
) -> list[dict[str, Any]]:
    """What the owner's OD-3 record must answer, one row per PROVIDER, from
    the live voting-source registry.

    Each row is ``{"provider", "sources", "providerEntry", "orEverySourceEntry"}``:
    ``sources`` are the voting keys that provider covers; they are approved
    by the one ``providerEntry`` OR by EVERY entry of ``orEverySourceEntry``
    (one per key -- approving some keys leaves the rest uncovered).  A
    ``denied`` / ``unknown`` at either level refuses, so a per-source denial
    beats a provider approval.  A key with no recorded provider gets its own
    row with ``provider: None`` and ``providerEntry: None`` -- only its
    per-source entry can cover it.  This states
    what is MISSING; it never proposes, writes or infers an approval."""
    if provider_of is None:
        from src.sources.source_census import provider_of as _provider_of  # noqa: PLC0415

        provider_of = _provider_of
    raw = voting_source_keys() if voting_sources is None else voting_sources
    keys = sorted({str(k) for k in raw if k})
    by_provider: dict[str | None, list[str]] = {}
    for key in keys:
        by_provider.setdefault(provider_of(key), []).append(key)
    rows: list[dict[str, Any]] = []
    for provider in sorted(by_provider, key=lambda p: (p is None, p or "")):
        srcs = by_provider[provider]
        if provider is None:
            for key in srcs:
                rows.append(
                    {
                        "provider": None,
                        "sources": [key],
                        "providerEntry": None,
                        "orEverySourceEntry": [f'sources["{key}"]'],
                    }
                )
            continue
        rows.append(
            {
                "provider": provider,
                "sources": srcs,
                "providerEntry": f'providers["{provider}"]',
                "orEverySourceEntry": [f'sources["{k}"]' for k in srcs],
            }
        )
    return rows


def unanswered_template(
    *,
    voting_sources: Iterable[str] | None = None,
    provider_of: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """A schema-shaped record with EVERY answer left open: no approver, no
    dates, every provider ``"unknown"``.  It is a form for the owner to fill
    in, and :func:`record_problem` refuses it as it stands (pinned by test),
    so committing it unchanged can never open the launch gate."""
    rows = permission_checklist(voting_sources=voting_sources, provider_of=provider_of)
    return {
        "recordType": RECORD_TYPE,
        "schemaVersion": SCHEMA_VERSION,
        "scope": SCOPE,
        "approvedBy": "",
        "approvedAt": "",
        "reviewBy": "",
        "providers": {r["provider"]: "unknown" for r in rows if r["provider"] is not None},
        "sources": {r["sources"][0]: "unknown" for r in rows if r["provider"] is None},
    }
