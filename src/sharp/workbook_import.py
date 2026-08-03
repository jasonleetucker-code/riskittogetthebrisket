"""Dependency-free importer for the researched dynasty-sharps workbook.

The production image does not need a spreadsheet library.  XLSX files are ZIP
containers of XML parts, and this reader intentionally supports the subset the
research workbook uses: shared strings, inline strings, booleans, and scalar
values.  It discovers sheets and headers dynamically; no row count is fixed.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

_REQUIRED_SHEETS = {
    "Final 100",
    "Candidate Pool",
    "Sharp Tracker",
    "FFPC & High Stakes",
    "Near Misses",
    "Sources",
    "Methodology & QC",
}

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def normalize_identity(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", raw.casefold())


def stable_person_id(name: str) -> str:
    return "sharp_person:" + hashlib.sha1(normalize_identity(name).encode("utf-8")).hexdigest()[:16]


def _column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref or "")
    if not letters:
        return 0
    value = 0
    for char in letters.group(0):
        value = value * 26 + (ord(char) - 64)
    return value - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    out: list[str] = []
    for item in root.findall(f"{{{_MAIN_NS}}}si"):
        out.append("".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t")))
    return out


def _sheet_targets(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rels = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
    }
    targets: dict[str, str] = {}
    for sheet in workbook.findall(f".//{{{_MAIN_NS}}}sheet"):
        name = sheet.attrib["name"]
        rel_id = sheet.attrib[f"{{{_REL_NS}}}id"]
        target = rels[rel_id].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        targets[name] = target
    return targets


def _cell_value(cell: ET.Element, shared: list[str]) -> Any:
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t"))
    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    if value_node is None:
        return None
    raw = value_node.text or ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    if kind == "b":
        return raw == "1"
    if kind in {"str", "e"}:
        return raw
    try:
        number = float(raw)
        return int(number) if number.is_integer() else number
    except ValueError:
        return raw


def read_workbook(path: Path | str) -> dict[str, list[list[Any]]]:
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        targets = _sheet_targets(archive)
        sheets: dict[str, list[list[Any]]] = {}
        for name, target in targets.items():
            root = ET.fromstring(archive.read(target))
            rows: list[list[Any]] = []
            for row_node in root.findall(f".//{{{_MAIN_NS}}}row"):
                values: list[Any] = []
                for cell in row_node.findall(f"{{{_MAIN_NS}}}c"):
                    index = _column_index(cell.attrib.get("r", "A1"))
                    while len(values) <= index:
                        values.append(None)
                    values[index] = _cell_value(cell, shared)
                rows.append(values)
            sheets[name] = rows
    missing = sorted(_REQUIRED_SHEETS - set(sheets))
    if missing:
        raise ValueError(f"workbook is missing required sheet(s): {', '.join(missing)}")
    return sheets


def _table(sheet: list[list[Any]], first_header: str) -> list[dict[str, Any]]:
    header_index = None
    for index, row in enumerate(sheet):
        if row and str(row[0] or "").strip() == first_header:
            header_index = index
            break
    if header_index is None:
        raise ValueError(f"header {first_header!r} not found")
    headers = [str(value or "").strip() for value in sheet[header_index]]
    output = []
    for row in sheet[header_index + 1 :]:
        if not any(value not in (None, "") for value in row):
            continue
        output.append(
            {header: row[i] if i < len(row) else None for i, header in enumerate(headers)}
        )
    return output


def _text(value: Any) -> str | None:
    value = str(value or "").strip()
    return value or None


def _public_handle(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    lowered = text.casefold()
    placeholders = (
        "no current handle",
        "not publicly verified",
        "none",
        "unknown",
        "n/a",
    )
    if any(lowered.startswith(item) for item in placeholders):
        return None
    handle = text.lstrip("@").strip()
    if not handle or " " in handle:
        return None
    return handle


def _split_name(name: str) -> tuple[str, str, str | None]:
    overrides = {
        "Jax Falcone (Scott Boulanger)": ("Scott Boulanger", "Jax Falcone", "Jax Falcone"),
        "Matt Desrosiers (Matty Kiwoom)": ("Matt Desrosiers", "Matty Kiwoom", "Matty Kiwoom"),
    }
    return overrides.get(name, (name, name, None))


def build_snapshot(path: Path | str) -> dict[str, Any]:
    sheets = read_workbook(path)
    final_rows = _table(sheets["Final 100"], "Name")
    pool_rows = _table(sheets["Candidate Pool"], "Candidate")
    tracker_rows = _table(sheets["Sharp Tracker"], "Name")
    ffpc_rows = _table(sheets["FFPC & High Stakes"], "Name")
    near_rows = _table(sheets["Near Misses"], "Name")
    source_rows = _table(sheets["Sources"], "Source")
    methodology_rows = sheets["Methodology & QC"]
    category_rows = sheets["Category Summary"]
    tracker = {str(row["Name"]): row for row in tracker_rows}
    ffpc = {str(row["Name"]): row for row in ffpc_rows}

    confidence_score = {"Very high": 95, "High": 85, "Moderate": 72}
    tracker_score = {
        "Tier A — strongest public signal": 90,
        "Tier B — useful public signal": 70,
        "Tier C — situational public signal": 50,
    }
    trackability_base = {"Yes": 55, "Possibly": 35, "No": 10}

    people: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    accounts: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    memberships: list[dict[str, Any]] = []
    identity_candidates: list[dict[str, Any]] = []

    for row_number, row in enumerate(final_rows, start=5):
        raw_name = str(row["Name"])
        canonical, display, pseudonym = _split_name(raw_name)
        person_id = stable_person_id(canonical)
        tracker_row = tracker.get(raw_name)
        ffpc_row = ffpc.get(raw_name)
        confidence = confidence_score.get(_text(row.get("Confidence level")), 70)
        trackability = trackability_base.get(_text(row.get("Publicly Trackable?")), 20)
        if tracker_row:
            trackability = max(
                trackability,
                tracker_score.get(_text(tracker_row.get("Practical tracking priority")), 50),
            )
        sleeper_claim = _text(row.get("Verified Sleeper username"))
        if sleeper_claim and sleeper_claim.casefold() == "not publicly verified":
            sleeper_claim = None
        if sleeper_claim:
            # A named username to chase is better than nothing to chase, but
            # it is a lead, not a verified account.  Trackability only reaches
            # the top of the scale once ``refresh_memberships`` sees a
            # genuinely verified platform account.
            trackability = max(trackability, 80)
        if ffpc_row:
            trackability = max(
                trackability, 65 if ffpc_row.get("Publicly Trackable?") == "Yes" else 50
            )
        curated_score = min(100, confidence + (5 if tracker_row else 0) + (3 if ffpc_row else 0))
        specialties = [
            item.strip()
            for item in str(row.get("Dynasty specialties") or "").split(",")
            if item.strip()
        ]
        searchable = " ".join(
            specialties
            + [str(row.get("Primary category") or ""), str(row.get("Selection bucket") or "")]
        ).casefold()
        flags = {
            "idp_specialist": "idp" in searchable,
            "devy_c2c_specialist": any(
                term in searchable for term in ("devy", "c2c", "campus-to-canton")
            ),
            "high_stakes_specialist": any(term in searchable for term in ("ffpc", "high-stakes")),
        }
        people.append(
            {
                "person_id": person_id,
                "canonical_name": canonical,
                "public_display_name": display,
                "pseudonym": pseudonym,
                "primary_public_handle": _public_handle(row.get("Primary public handle")),
                "current_affiliation": _text(
                    row.get("Current platform, company, podcast, website, or affiliation")
                ),
                "primary_category": _text(row.get("Primary category")),
                "dynasty_specialties": specialties,
                "why_included": _text(row.get("Why this person qualifies as a sharp")),
                "evidence_of_prominence": _text(row.get("Evidence of prominence")),
                "evidence_of_skill": _text(row.get("Evidence of skill or successful performance")),
                "competition_record": _text(
                    row.get("High-stakes or competition record, when applicable")
                ),
                "primary_content_link": _text(row.get("Primary content links or profile links")),
                "activity_status": _text(row.get("Current activity status")),
                "workbook_confidence": _text(row.get("Confidence level")),
                "best_potential_use": _text(row.get("Best potential use")),
                "publicly_trackable_assessment": _text(row.get("Publicly Trackable?")),
                "known_public_identifiers": _text(row.get("Known Public Identifiers")),
                "selection_bucket": _text(row.get("Selection bucket")),
                "curated_expertise_score": curated_score,
                "trackability_score": trackability,
                "candidate_status": "curated_included",
                "current_activity": True,
                "source_workbook_sheet": "Final 100",
                "source_workbook_row": row_number,
                **flags,
            }
        )
        if pseudonym:
            aliases.append(
                {
                    "person_id": person_id,
                    "alias": pseudonym,
                    "alias_type": "pseudonym",
                    "active": True,
                    "confidence": 1.0,
                    "source": "Final 100",
                }
            )
        handle_value = _public_handle(row.get("Primary public handle"))
        if handle_value:
            aliases.append(
                {
                    "person_id": person_id,
                    "alias": handle_value,
                    "alias_type": "social_handle",
                    "platform": "x",
                    "active": True,
                    "confidence": 1.0,
                    "source": "Final 100",
                }
            )
            accounts.append(
                {
                    "account_id": f"x:handle:{handle_value.casefold()}",
                    "person_id": person_id,
                    "platform": "x",
                    "username": handle_value,
                    "display_name": display,
                    "profile_url": f"https://x.com/{handle_value}",
                    "verification_status": "verified",
                    "verification_confidence": 1.0,
                    "verification_method": "workbook_public_handle",
                    "evidence_url": _text(row.get("Source 2 URL")),
                    "active_status": "active",
                }
            )
        # The workbook's "Verified Sleeper username" column is a research
        # claim, not proof of account ownership.  Its supporting URLs are
        # podcast/company pages that establish why the PERSON belongs in the
        # universe -- they say nothing about who holds the Sleeper handle.
        # Four of the eight claimed usernames are exact lowercase transforms
        # of the person's X handle, which is precisely the handle==username
        # inference the brief forbids.  So every claimed username enters as a
        # CANDIDATE and is re-derived against the public Sleeper API by
        # ``curated.resolve_sleeper_candidates``.  Nothing here may write
        # ``verified``.
        if sleeper_claim:
            claimed = sleeper_claim.casefold()
            handle_derived = bool(handle_value and handle_value.casefold() == claimed)
            identity_candidates.append(
                {
                    "candidate_id": f"cand:sleeper:{person_id.split(':')[-1]}:{claimed}",
                    "person_id": person_id,
                    "platform": "sleeper",
                    "candidate_username": claimed,
                    "verification_status": "unresolved",
                    # A named research claim outranks a machine-generated
                    # guess, but stays far below anything that could be read
                    # as ownership.
                    "confidence": 0.35 if not handle_derived else 0.25,
                    "candidate_generation_method": (
                        "workbook_claimed_username_matching_public_handle"
                        if handle_derived
                        else "workbook_claimed_username"
                    ),
                    "recommended_action": "resolve_against_public_api_then_manual_verify",
                    "manual_review_required": True,
                }
            )
            evidence.append(
                {
                    "person_id": person_id,
                    "evidence_type": "workbook_username_claim",
                    "description": (
                        f"Workbook 'Verified Sleeper username' column asserts {claimed!r}"
                        + (
                            " -- identical to the person's public X handle, so it may be an"
                            " inference rather than an observation."
                            if handle_derived
                            else " independently of the person's public handle."
                        )
                        + " Supporting URLs establish curated inclusion, not account ownership."
                    ),
                    "source_url": _text(row.get("Source 1 URL")) or _text(row.get("Source 2 URL")),
                    "supports_match": False,
                    "reviewed_status": "pending",
                    "source_workbook_sheet": "Final 100",
                    "source_workbook_row": row_number,
                }
            )
        if handle_value and (
            not sleeper_claim or handle_value.casefold() != sleeper_claim.casefold()
        ):
            identity_candidates.append(
                {
                    "candidate_id": "cand:sleeper:"
                    + person_id.split(":")[-1]
                    + ":"
                    + handle_value.casefold(),
                    "person_id": person_id,
                    "platform": "sleeper",
                    "candidate_username": handle_value,
                    "verification_status": "unresolved",
                    "confidence": 0.2,
                    "candidate_generation_method": "exact_public_handle",
                    "recommended_action": "search_official_api_then_manual_verify",
                    "manual_review_required": True,
                }
            )
        for source_column in ("Source 1 URL", "Source 2 URL"):
            url = _text(row.get(source_column))
            if url:
                evidence.append(
                    {
                        "person_id": person_id,
                        "evidence_type": "workbook_source",
                        "description": f"{source_column} supporting curated inclusion",
                        "source_url": url,
                        "supports_match": True,
                        "reviewed_status": "accepted",
                        "source_workbook_sheet": "Final 100",
                        "source_workbook_row": row_number,
                    }
                )
        if tracker_row:
            evidence.append(
                {
                    "person_id": person_id,
                    "evidence_type": "sharp_tracker_selection",
                    "description": _text(tracker_row.get("Why useful for a Sharp Tracker")),
                    "source_url": _text(tracker_row.get("Source 1 URL")),
                    "supports_match": True,
                    "confidence_contribution": 0.05,
                    "reviewed_status": "accepted",
                    "source_workbook_sheet": "Sharp Tracker",
                    "source_workbook_row": next(
                        (
                            index
                            for index, item in enumerate(tracker_rows, start=5)
                            if item is tracker_row
                        ),
                        None,
                    ),
                    "metadata": {
                        "observableData": _text(
                            tracker_row.get("Public data that may be observed")
                        ),
                        "trackingPriority": _text(tracker_row.get("Practical tracking priority")),
                        "caveat": _text(tracker_row.get("Important caveat")),
                    },
                }
            )
        if ffpc_row:
            evidence.append(
                {
                    "person_id": person_id,
                    "evidence_type": "ffpc_high_stakes",
                    "description": _text(ffpc_row.get("Documented accomplishments")),
                    "source_url": _text(ffpc_row.get("Source 1 URL")),
                    "supports_match": True,
                    "confidence_contribution": 0.05,
                    "reviewed_status": "accepted",
                    "source_workbook_sheet": "FFPC & High Stakes",
                    "source_workbook_row": next(
                        (
                            index
                            for index, item in enumerate(ffpc_rows, start=5)
                            if item is ffpc_row
                        ),
                        None,
                    ),
                    "metadata": {
                        "contestOrLeague": _text(ffpc_row.get("Contest or league involvement")),
                        "publicIdentifiers": _text(ffpc_row.get("Public identifiers")),
                        "lawfulTrackingAssessment": _text(
                            ffpc_row.get("Lawful tracking assessment")
                        ),
                    },
                }
            )
            identifier = _text(ffpc_row.get("Public identifiers")) or display
            identity_candidates.append(
                {
                    "candidate_id": "cand:ffpc:"
                    + person_id.split(":")[-1]
                    + ":"
                    + hashlib.sha1(identifier.encode("utf-8")).hexdigest()[:8],
                    "person_id": person_id,
                    "platform": "ffpc",
                    "candidate_display_name": display,
                    "candidate_team_or_entry_name": identifier,
                    "verification_status": "possible",
                    "confidence": 0.45,
                    "candidate_generation_method": "workbook_public_competition_identifier",
                    "evidence_url": _text(ffpc_row.get("Source 1 URL")),
                    "recommended_action": "match_against_public_ffpc_managers_and_review",
                    "manual_review_required": True,
                }
            )
        memberships.append(
            {
                "person_id": person_id,
                "curated_industry_sharp": True,
                "algorithmically_qualified_sharp": False,
                # Super Sharp requires a VERIFIED platform identity.  The
                # workbook cannot confer it, so the import never sets it;
                # ``curated.refresh_memberships`` derives it from accounts
                # that actually resolved.  Seeding it here would have made
                # the population look eight-strong on day one without a
                # single ownership check behind it.
                "verified_super_sharp": False,
                "membership_state": "curated_only",
                "inclusion_reason": "Research-verified Final 100 workbook inclusion",
                "curated_weight": round(curated_score / 100, 3),
                "trackability_weight": round(trackability / 100, 3),
                **flags,
            }
        )

    candidate_pool = []
    for row_number, row in enumerate(pool_rows, start=5):
        raw_name = str(row["Candidate"])
        canonical, display, pseudonym = _split_name(raw_name)
        outcome = _text(row.get("Outcome"))
        status = {
            "Selected — Final 100": "curated_included",
            "Near miss": "research_candidate",
            "Screened out": "screened_out",
        }.get(outcome, "research_candidate")
        if raw_name == "Mike Tagliere":
            status = "inactive_or_historical"
        candidate_pool.append(
            {
                "person_id": stable_person_id(canonical),
                "canonical_name": canonical,
                "public_display_name": display,
                "pseudonym": pseudonym,
                "candidate_status": status,
                "candidate_outcome": outcome,
                "screening_note": _text(row.get("Screening note")),
                "selection_bucket": _text(row.get("Final-list bucket")),
                "workbook_sheet": "Candidate Pool",
                "workbook_row": row_number,
            }
        )

    research_people = []
    for row_number, row in enumerate(near_rows, start=5):
        raw_name = str(row["Name"])
        canonical, display, pseudonym = _split_name(raw_name)
        status = "research_candidate"
        if raw_name == "Mike Tagliere":
            status = "inactive_or_historical"
        if "Fritz Pollard" in raw_name:
            status = "insufficient_identity_information"
        research_people.append(
            {
                "person_id": stable_person_id(canonical),
                "canonical_name": canonical,
                "public_display_name": display,
                "pseudonym": pseudonym,
                "candidate_status": status,
                "reason_omitted": _text(row.get("Reason omitted")),
                "primary_evidence_notes": _text(row.get("Primary evidence/notes")),
                "source_url": _text(row.get("Source URL")),
                "source_workbook_sheet": "Near Misses",
                "source_workbook_row": row_number,
                "curated_expertise_score": 45 if status == "research_candidate" else 20,
                "trackability_score": 20,
            }
        )
        near_url = _text(row.get("Source URL"))
        if near_url:
            evidence.append(
                {
                    "person_id": stable_person_id(canonical),
                    "evidence_type": "near_miss_source",
                    "description": _text(row.get("Primary evidence/notes"))
                    or _text(row.get("Reason omitted")),
                    "source_url": near_url,
                    "supports_match": True,
                    "reviewed_status": "accepted",
                    "source_workbook_sheet": "Near Misses",
                    "source_workbook_row": row_number,
                }
            )

    sources = [
        {
            "source_id": f"workbook_source:{row_number}",
            "name": _text(row.get("Source")),
            "source_type": _text(row.get("Type")),
            "why_used": _text(row.get("Why used")),
            "url": _text(row.get("URL")),
            "workbook_sheet": "Sources",
            "workbook_row": row_number,
        }
        for row_number, row in enumerate(source_rows, start=5)
    ]

    return {
        "schema_version": 1,
        "workbook_name": Path(path).name,
        # Provenance: the snapshot is a derived artifact, so it records which
        # bytes produced it and what the parser actually saw.  Without these a
        # hand-edited snapshot is indistinguishable from a parsed one.
        "workbook_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "sheet_inventory": [
            {
                "sheet": name,
                "rows": len(rows),
                "columns": max((len(row) for row in rows), default=0),
            }
            for name, rows in sheets.items()
        ],
        "counts": {
            "candidate_pool_rows": len(pool_rows),
            "final_100": len(people),
            "sharp_tracker_subset": len(tracker_rows),
            "ffpc_high_stakes_subset": len(ffpc_rows),
            "near_misses": len(near_rows),
            "sources": len(source_rows),
            # Named "claimed", not "verified", because that is what the
            # workbook column actually is.  No account is verified at import.
            "workbook_claimed_sleeper_usernames": sum(
                1
                for candidate in identity_candidates
                if str(candidate.get("candidate_generation_method") or "").startswith(
                    "workbook_claimed_username"
                )
            ),
            "verified_platform_accounts": sum(
                1 for account in accounts if account["verification_status"] == "verified"
            ),
            "identity_candidates": len(identity_candidates),
        },
        "people": people,
        "research_people": research_people,
        "candidate_pool": candidate_pool,
        "aliases": aliases,
        "platform_accounts": accounts,
        "identity_evidence": evidence,
        "identity_candidates": identity_candidates,
        "model_memberships": memberships,
        "sources": sources,
        "workbook_methodology": methodology_rows,
        "category_summary": category_rows,
    }


def write_snapshot(workbook_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    snapshot = build_snapshot(workbook_path)
    Path(output_path).write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshot
