"""Fail-closed report-only controller for Site Steward Phase 1.

The controller owns no scheduler and performs no repository, product, or
production mutation. It validates the committed run contract, enforces the
owner-authorized zero-spend boundary, checks HALT and the Week 1 launch gate,
records idempotency in private SQLite, and appends private JSONL receipts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from .store import ConflictError, StewardStore

_PHASE1_AUTONOMY = "A_REPORT_ONLY"
_PHASE1_MODE = "report_only"
_RECEIPT_VERSION = "steward-phase1-receipt/v1"
_RUN_STATE_PREFIX = "phase1-run:"
_WEEK1_ROW = re.compile(r"^\| W1-(\d{2}) \|.*\| ([A-Z_ ]+) \|$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


class ContractError(ValueError):
    """The supplied run contract does not satisfy committed schema/policy."""


@dataclass(frozen=True)
class ControllerResult:
    status: str
    receipt: dict[str, Any]
    duplicate: bool = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        encoding="utf-8",
    ).strip()


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _ensure_private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def _iso_datetime(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate_run_contract(contract: dict[str, Any], schema_path: Path) -> None:
    """Validate the complete Phase-1 run-contract object from the canonical schema."""

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    definitions = schema.get("$defs", {})
    run_schema = definitions.get("autonomousRunContract")
    budget_schema = definitions.get("budget")
    _require(isinstance(run_schema, dict), "schema missing autonomousRunContract")
    _require(isinstance(budget_schema, dict), "schema missing budget definition")

    required = set(run_schema.get("required", []))
    properties = run_schema.get("properties", {})
    missing = required - contract.keys()
    unknown = set(contract) - set(properties)
    _require(not missing, f"missing run-contract fields: {sorted(missing)}")
    _require(not unknown, f"unknown run-contract fields: {sorted(unknown)}")

    _require(
        contract.get("schema_version") == "steward-run/v1",
        "unsupported run schema",
    )
    _require(
        isinstance(contract.get("run_id"), str) and bool(contract["run_id"]),
        "run_id is required",
    )
    _require(
        isinstance(contract.get("goal"), str) and bool(contract["goal"]),
        "goal is required",
    )

    lanes = set(properties["lane"]["enum"])
    modes = set(definitions["runMode"]["enum"])
    autonomy = set(definitions["autonomyClass"]["enum"])
    _require(
        contract.get("lane") in lanes,
        "lane is not allowed by the canonical schema",
    )
    _require(
        contract.get("mode") in modes,
        "mode is not allowed by the canonical schema",
    )
    _require(
        contract.get("autonomy_class") in autonomy,
        "autonomy_class is not allowed by the canonical schema",
    )

    array_fields = (
        "allowed_actions",
        "denied_actions",
        "allowed_paths",
        "allowed_domains",
    )
    for field in array_fields:
        if field not in contract:
            continue
        value = contract[field]
        _require(isinstance(value, list), f"{field} must be an array")
        _require(
            all(isinstance(item, str) for item in value),
            f"{field} must contain strings",
        )
        _require(
            len(value) == len(set(value)),
            f"{field} must contain unique items",
        )

    budget = contract.get("budget")
    _require(isinstance(budget, dict), "budget must be an object")
    budget_required = set(budget_schema.get("required", []))
    budget_properties = budget_schema.get("properties", {})
    budget_missing = budget_required - budget.keys()
    budget_unknown = set(budget) - set(budget_properties)
    _require(not budget_missing, f"missing budget fields: {sorted(budget_missing)}")
    _require(not budget_unknown, f"unknown budget fields: {sorted(budget_unknown)}")

    for field, spec in budget_properties.items():
        value = budget[field]
        if spec.get("type") == "integer":
            _require(type(value) is int, f"budget.{field} must be an integer")
        elif spec.get("type") == "number":
            _require(
                type(value) in (int, float),
                f"budget.{field} must be numeric",
            )
        minimum = spec.get("minimum")
        if minimum is not None:
            _require(value >= minimum, f"budget.{field} is below its minimum")

    _require(
        isinstance(contract.get("halt_sentinel"), str) and bool(contract["halt_sentinel"]),
        "halt_sentinel is required",
    )
    _require(
        _iso_datetime(contract.get("created_at")),
        "created_at must be an ISO date-time",
    )

    if contract["autonomy_class"] == "A_REPORT_ONLY":
        _require(
            contract["mode"] == "report_only",
            "Class A must use report_only mode",
        )
    if contract["autonomy_class"] in {
        "C_PREAUTHORIZED_INTEGRATION",
        "D_CONSEQUENTIAL",
    }:
        _require(
            bool(contract.get("owner_authorization_ref")),
            "Class C/D requires owner authorization",
        )
    if contract["autonomy_class"] == "D_CONSEQUENTIAL":
        _require(contract["mode"] == "assisted", "Class D must use assisted mode")


def mechanically_count_week1(contract_path: Path) -> tuple[int, int]:
    """Return (literal rows, VERIFIED rows) from the frozen Week 1 table."""

    rows = []
    for line in contract_path.read_text(encoding="utf-8").splitlines():
        match = _WEEK1_ROW.match(line)
        if match:
            rows.append((match.group(1), match.group(2).strip()))
    ids = [row_id for row_id, _ in rows]
    if len(rows) != 30 or len(set(ids)) != 30:
        message = f"Week 1 denominator drift: expected 30 literal rows, found {len(rows)}"
        raise RuntimeError(message)
    return len(rows), sum(status == "VERIFIED" for _, status in rows)


class Phase1Controller:
    """Deterministic, report-only outer controller for the initial Steward phase."""

    def __init__(self, repo: str | Path, runtime_root: str | Path | None = None):
        self.repo = Path(repo).resolve()
        self.runtime_root = (
            Path(runtime_root).resolve()
            if runtime_root is not None
            else self.repo / ".agent-runtime" / "steward"
        )
        _ensure_private_dir(self.runtime_root)
        self.receipt_dir = self.runtime_root / "receipts"
        _ensure_private_dir(self.receipt_dir)
        self.db_path = self.runtime_root / "state.sqlite3"
        self.store = StewardStore(self.db_path)
        _ensure_private_file(self.db_path)

    def close(self) -> None:
        self.store.close()

    def __enter__(self) -> "Phase1Controller":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _halt_path(self, contract: dict[str, Any]) -> Path:
        configured = Path(contract["halt_sentinel"])
        if configured.is_absolute():
            return configured
        return self.repo / configured

    def _preflight(self, contract: dict[str, Any]) -> dict[str, Any]:
        _require(
            contract["autonomy_class"] == _PHASE1_AUTONOMY,
            "Phase 1 permits Class A only",
        )
        _require(
            contract["mode"] == _PHASE1_MODE,
            "Phase 1 permits report_only mode only",
        )
        _require(
            float(contract["budget"]["max_usd"]) == 0.0,
            "Phase 1 max_usd must remain exactly 0",
        )

        rows, verified = mechanically_count_week1(
            self.repo / "docs" / "season-launch" / "WEEK_1_LAUNCH_CONTRACT.md"
        )
        if verified != rows:
            message = f"Week 1 launch gate is incomplete: {verified}/{rows} VERIFIED"
            raise RuntimeError(message)

        head = _git(self.repo, "rev-parse", "HEAD")
        if not _SHA.fullmatch(head):
            raise RuntimeError("could not observe an exact repository HEAD")
        branch = _git(self.repo, "rev-parse", "--abbrev-ref", "HEAD")
        dirty = bool(_git(self.repo, "status", "--porcelain"))
        if dirty:
            raise RuntimeError("report-only preflight requires a clean repository")
        return {
            "repo_head": head,
            "branch": branch,
            "week1": {"rows": rows, "verified": verified},
            "budget_max_usd": 0.0,
        }

    def _append_receipt(self, receipt: dict[str, Any]) -> None:
        day = receipt["ended_at"][:10]
        path = self.receipt_dir / f"{day}.jsonl"
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            line = (json.dumps(receipt, sort_keys=True, allow_nan=False) + "\n").encode()
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
        _ensure_private_file(path)

    def _record(self, receipt: dict[str, Any]) -> None:
        state_name = _RUN_STATE_PREFIX + receipt["run_id"]
        revision, existing = self.store.read(state_name)
        if existing is not None:
            raise ConflictError(f"duplicate run id: {receipt['run_id']}")
        self.store.write(state_name, receipt, expected_revision=revision)
        self._append_receipt(receipt)

    def run(self, contract: dict[str, Any]) -> ControllerResult:
        """Perform one bounded report-only run and persist its audit receipt."""

        schema_path = self.repo / "config" / "steward" / "contracts.schema.json"
        validate_run_contract(contract, schema_path)
        run_id = contract["run_id"]
        state_name = _RUN_STATE_PREFIX + run_id
        _, previous = self.store.read(state_name)
        if previous is not None:
            return ControllerResult(
                status="DUPLICATE",
                receipt=previous,
                duplicate=True,
            )

        started_at = _utc_now()
        status = "DONE"
        blockers: list[str] = []
        preflight: dict[str, Any] = {}

        if self._halt_path(contract).exists():
            status = "HALTED"
            blockers.append("HALT sentinel present before run")
        else:
            try:
                preflight = self._preflight(contract)
            except (ContractError, RuntimeError, subprocess.CalledProcessError) as exc:
                status = "BLOCKED"
                blockers.append(str(exc))

        receipt = {
            "schema_version": _RECEIPT_VERSION,
            "run_id": run_id,
            "lane": contract["lane"],
            "mode": contract["mode"],
            "autonomy_class": contract["autonomy_class"],
            "status": status,
            "started_at": started_at,
            "ended_at": _utc_now(),
            "preflight": preflight,
            "blockers": blockers,
            "actions": [],
            "cost": {"usd": 0.0},
            "mutation": {
                "repository": False,
                "product": False,
                "production": False,
            },
        }
        self._record(receipt)
        return ControllerResult(status=status, receipt=receipt)
