from __future__ import annotations

import json
import os
import re
from pathlib import Path


RAW_FALLBACK_JSON_RE = re.compile(r"^dynasty_data_\d{4}-\d{2}-\d{2}\.json$", re.IGNORECASE)
RAW_FALLBACK_JS_RE = re.compile(r"window\.DYNASTY_DATA\s*=\s*(\{[\s\S]*\})\s*;?", re.IGNORECASE)


def _dedupe_paths_case_insensitive(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _display_path(base_dir: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(base_dir.resolve()).as_posix()
    except Exception:
        return path.name


def _parse_json_object(text: str) -> tuple[dict | None, str | None]:
    if not text:
        return None, "File was empty."
    try:
        parsed = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    if not isinstance(parsed, dict):
        return None, "Parsed value was not an object."
    return parsed, None


def _parse_dynasty_data_js(text: str) -> tuple[dict | None, str | None]:
    if not text:
        return None, "File was empty."
    match = RAW_FALLBACK_JS_RE.search(text)
    if not match:
        return None, "window.DYNASTY_DATA assignment was not found."
    return _parse_json_object(match.group(1))


def _json_candidates(base_dir: Path, data_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for directory in [data_dir, base_dir]:
        if not directory.exists():
            continue
        try:
            names = os.listdir(directory)
        except Exception:
            continue
        for name in names:
            if RAW_FALLBACK_JSON_RE.match(str(name)):
                candidates.append(directory / name)
    return _dedupe_paths_case_insensitive(candidates)


def _js_candidates(base_dir: Path, data_dir: Path) -> list[Path]:
    return _dedupe_paths_case_insensitive(
        [
            base_dir / "dynasty_data.js",
            data_dir / "dynasty_data.js",
        ]
    )


def _mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except Exception:
        return -1


def scan_raw_fallback_health(
    base_dir: Path,
    data_dir: Path,
    *,
    checked_at: str | None = None,
) -> tuple[dict, list[Path]]:
    skipped_records: list[dict[str, str]] = []
    skipped_paths: list[Path] = []
    selected_source = None
    selected_source_type = None

    json_candidates = sorted(_json_candidates(base_dir, data_dir), key=_mtime_ns, reverse=True)
    js_candidates = [path for path in _js_candidates(base_dir, data_dir) if path.exists()]
    candidate_count = len([path for path in json_candidates if path.exists()]) + len(js_candidates)

    for candidate in json_candidates:
        if not candidate.exists():
            continue
        try:
            parsed, reason = _parse_json_object(candidate.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            parsed, reason = None, str(exc)
        if parsed is not None:
            selected_source = _display_path(base_dir, candidate)
            selected_source_type = "json"
            break
        skipped_records.append(
            {
                "file": _display_path(base_dir, candidate),
                "reason": str(reason or "Unknown parse failure."),
            }
        )
        skipped_paths.append(candidate)

    if selected_source is None:
        for candidate in js_candidates:
            try:
                parsed, reason = _parse_dynasty_data_js(candidate.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                parsed, reason = None, str(exc)
            if parsed is not None:
                selected_source = _display_path(base_dir, candidate)
                selected_source_type = "js"
                break
            skipped_records.append(
                {
                    "file": _display_path(base_dir, candidate),
                    "reason": str(reason or "Unknown parse failure."),
                }
            )
            skipped_paths.append(candidate)

    status = "ok"
    if selected_source is None:
        status = "warning" if skipped_records else "missing"
    elif skipped_records:
        status = "warning"

    payload = {
        "status": status,
        "selected_source": selected_source,
        "selected_source_type": selected_source_type,
        "skipped_file_count": len(skipped_records),
        "skipped_files": skipped_records,
        "candidate_count": candidate_count,
    }
    if checked_at:
        payload["checked_at"] = checked_at

    return payload, skipped_paths
