"""Local report-only CLI. No scheduler, inference, Git mutation, merge, or deployment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from .planner import plan, satisfy
from .receipts import run_receipt
from .repository import inventory, phase_tasks, github_disposition, context, reconcile, work_units
from .routing import recommend
from .store import StewardStore
from .sync import observe, classify_movement, git, generated_conflicts, evidence_reuse


def github_snapshot():
    repo = "repos/jasonleetucker-code/riskittogetthebrisket"

    def read(endpoint, paginated=False):
        command = ["gh", "api", f"{repo}/{endpoint}"]
        if paginated:
            command += ["--paginate", "--slurp"]
        value = json.loads(subprocess.check_output(command, text=True, encoding="utf-8"))
        return [row for page in value for row in page] if paginated else value

    return {
        "head": read("commits/main")["sha"],
        "issues": read("issues?state=open&per_page=100", True),
        "pulls": read("pulls?state=open&per_page=100", True)
        + read("pulls?state=closed&per_page=30"),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def build_brief(
    repo: Path, store: StewardStore, available: list[str], remote: dict | None = None
) -> dict:
    revision, previous = store.read("campaign")
    observed = observe(repo, previous.get("origin_main") if previous else None)
    inv = inventory(repo)
    tasks = phase_tasks(repo, inv)
    reconciliation = reconcile(repo, inv, tasks, remote)
    units = work_units(tasks, inv, reconciliation)
    for task in units:
        saved = (previous or {}).get("task_states", {}).get(task["id"])
        if saved:
            task.update(saved)
            if task["state"] in {"VERIFIED", "PRODUCTION_VERIFIED"} and (
                task.get("evidence", {}).get("head") != observed["head"] or observed["dirty"]
            ):
                task["state"] = "IMPLEMENTED_UNVERIFIED"
                task["unresolved"].append(
                    "saved verification does not identify this clean candidate"
                )
    policy = json.loads((repo / "config/steward/routing.json").read_text(encoding="utf-8"))
    routes = []
    for task in tasks:
        classification = {
            "id": task["id"],
            "kind": task["kind"],
            "cross_system": task["id"] != "P8",
            "production_risk": "high" if task["risk"] == "high" else "normal",
            "context_refs": task["docs"],
        }
        routes.append(recommend(classification, policy, available=available))
    movement = classify_movement(observed, ["src/steward", "config/steward", "docs"])
    previous_documents = previous.get("documents", {}) if previous else {}
    stale = [p for p, metadata in inv["documents"].items() if previous_documents.get(p) != metadata]
    mapped = {key for task in tasks for key in task["todo_ids"]}
    uncovered = [
        row["id"] for row in reconciliation["manifest"] if row["phase"] == "NEEDS_INSPECTION"
    ]
    branches = git(
        repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/remotes/origin"
    ).splitlines()
    prs = (
        []
        if remote is None
        else [
            {
                "number": p["number"],
                "title": p["title"],
                "state": p["state"],
                "head": p["head"]["sha"],
                "url": p["html_url"],
                "disposition": github_disposition(p),
            }
            for p in remote["pulls"]
        ]
    )
    issues = (
        []
        if remote is None
        else [
            {"number": i["number"], "title": i["title"], "url": i["html_url"]}
            for i in remote["issues"]
            if "pull_request" not in i
        ]
    )
    open_unmapped = [i for i in issues if f"#{i['number']}" not in mapped]
    problems = []
    if remote is None:
        problems.append(
            "GitHub freshness/open work not observed; rerun with --github after fetching"
        )
    elif remote["head"] != observed["origin_main"]:
        problems.append("GitHub main differs from origin/main; fetch and reconcile")
    if observed["dirty"]:
        problems.append("working tree has local changes; candidate not integrated")
    if open_unmapped:
        problems.append(f"{len(open_unmapped)} live issues need phase reconciliation")
    result = {
        "schema_version": "steward-brief/v1",
        "objective": (previous or {}).get(
            "objective", "finish the site under current execution authority"
        ),
        **observed,
        "state_revision": revision,
        "knowledge_revision": store.read("knowledge_revision")[0],
        "previous_objective": previous.get("objective") if previous else None,
        "recent_completed_work": previous.get("completed", []) if previous else [],
        "partial_work": previous.get("partial", []) if previous else [],
        "launch": inv["launch"],
        "documents": inv["documents"],
        "stale_document_revisions": stale,
        "inventory_count": len(inv["observations"]),
        "manifest_rows": inv["manifest_rows"],
        "unmapped_ids": uncovered,
        "unmapped_open_issues": open_unmapped,
        "source_coverage": inv["missing_sources"],
        "reconciliation": reconciliation,
        "plan": plan(tasks),
        "unit_plan": plan(units),
        "routing": routes,
        "main_movement": movement,
        "pulls": prs,
        "open_issues": issues,
        "branches": branches,
        "remote_observed_at": remote.get("observed_at") if remote else None,
        "unresolved": problems,
        "next_action": "verify W1-27/28 actual production evidence windows and W1-30; inspect current authority for independent work",
        "handoff": "Read AI_INSTRUCTIONS.md. Fetch current main. Run python -m src.steward brief --github with observed available models. Reconcile current contracts, partial work, PRs and dependencies. Execute authorized site-completion work through required review/CI/production gates; preserve literal Week 1 30/30 and $0 incremental Steward policy.",
    }
    return result


def render(brief: dict) -> str:
    lines = [
        f"HEAD: {brief['head']}",
        f"origin/main: {brief['origin_main']}",
        f"Working tree: {'dirty' if brief['dirty'] else 'clean'}",
        f"Week 1: {brief['launch']['verified']}/30 literal VERIFIED",
        f"Inventory: {brief['manifest_rows']} manifest rows; {brief['inventory_count']} source observations",
        f"Main movement: {brief['main_movement']['classification']}",
        f"Coverage: {len(brief['unmapped_ids'])} unmapped manifest work items; source claims remain unverified",
        f"Open PRs: {sum(p['state'] == 'open' for p in brief['pulls']) if brief['remote_observed_at'] else 'UNKNOWN'}",
        f"State revision: {brief['state_revision']}; knowledge: {brief['knowledge_revision']}",
        f"Work units: {sum(len(p['tasks']) for p in brief['unit_plan']['phases'])}; "
        f"combined groups: {sum(len(p['tasks']) > 1 for p in brief['unit_plan']['phases'])}; "
        f"unsafe combinations rejected: {len(brief['unit_plan']['unsafe_combinations'])}",
    ]
    routes = {r["task_id"]: r for r in brief["routing"]}
    for phase in brief["plan"]["phases"]:
        key = phase["tasks"][0]
        route = routes[key]
        lines.append(
            f"{key}: {phase['objective']} | {phase['execution']} | {route['profile']} {route['model'] or 'UNAVAILABLE'}"
        )
    lines += [f"UNRESOLVED: {item}" for item in brief["unresolved"]]
    lines += [f"NEXT: {brief['next_action']}", f"HANDOFF: {brief['handoff']}"]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--state", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    brief = sub.add_parser("brief")
    brief.add_argument("--github", action="store_true")
    brief.add_argument("--json", action="store_true")
    brief.add_argument(
        "--save", action="store_true", help="persist observations and append a run receipt"
    )
    brief.add_argument("--available-model", action="append", default=[])
    route = sub.add_parser("route")
    route.add_argument("task", type=Path)
    route.add_argument("--owner", type=Path)
    route.add_argument("--available-model", action="append", default=[])
    ctx = sub.add_parser("context")
    ctx.add_argument("paths", nargs="+")
    ctx.add_argument("--max-chars", type=int, default=12000)
    remember = sub.add_parser("remember")
    remember.add_argument("record", type=Path)
    remember.add_argument("--evidence", type=Path, required=True)
    remember.add_argument("--expected-revision", type=int, required=True)
    retrieve = sub.add_parser("retrieve")
    retrieve.add_argument("topic")
    checkpoint = sub.add_parser("checkpoint")
    checkpoint.add_argument("record", type=Path)
    checkpoint.add_argument("--expected-revision", type=int, required=True)
    integration = sub.add_parser("check-integration")
    integration.add_argument("--base", required=True)
    integration.add_argument("--surfaces", nargs="+", required=True)
    integration.add_argument("--proof", type=Path)
    integration.add_argument("--evidence", type=Path)
    integration.add_argument(
        "--github", action="store_true", help="independently verify remote HEAD"
    )
    backup = sub.add_parser("backup")
    backup.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if args.command == "check-integration":
        observed = observe(repo, args.base)
        proof = json.loads(args.proof.read_text(encoding="utf-8")) if args.proof else None
        movement = classify_movement(observed, args.surfaces, automation_proof=proof)
        conflicts = generated_conflicts(repo, args.base, observed["head"], observed["origin_main"])
        result = {
            "observation": observed,
            "movement": movement,
            "generated_conflicts": conflicts,
            "authority": "report-only; no merge command",
        }
        remote_head = github_snapshot()["head"] if args.github else None
        result["github_head"] = remote_head
        result["candidate_clean"] = not observed["dirty"]
        result["remote_matches_origin"] = remote_head == observed["origin_main"]
        if args.evidence:
            evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
            result["evidence_reuse"] = evidence_reuse(
                evidence, candidate_head=observed["head"], movement=movement
            )
        print(json.dumps(result, indent=2))
        return (
            2
            if conflicts
            or observed["dirty"]
            or remote_head != observed["origin_main"]
            or movement["classification"] in {"UNKNOWN_REQUIRES_INSPECTION", "RELEVANT_BASE_MOVE"}
            else 0
        )
    if args.command == "context":
        print(json.dumps(context(repo, args.paths, max_chars=args.max_chars), indent=2))
        return 0
    if args.command == "route":
        task = json.loads(args.task.read_text(encoding="utf-8"))
        owner = json.loads(args.owner.read_text(encoding="utf-8")) if args.owner else None
        policy = json.loads((repo / "config/steward/routing.json").read_text(encoding="utf-8"))
        print(
            json.dumps(
                recommend(task, policy, available=args.available_model, owner=owner), indent=2
            )
        )
        return 0
    path = args.state or repo / ".agent-runtime/steward/state.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    store = StewardStore(path)
    try:
        if args.command == "brief":
            started = datetime.now(timezone.utc).isoformat()
            remote = github_snapshot() if args.github else None
            result = build_brief(repo, store, args.available_model, remote)
            if args.save:
                knowledge_revision, _ = store.read("knowledge_revision")
                knowledge = store.retrieve("campaign")
                receipt = run_receipt(
                    head=result["head"],
                    agent_os=git(repo, "hash-object", "docs/AGENT_OPERATING_SYSTEM.md"),
                    evidence=[
                        {
                            "kind": "repository_inventory",
                            "manifest_rows": result["manifest_rows"],
                            "documents": result["documents"],
                        }
                    ],
                    unresolved=result["unresolved"],
                    routes=result["routing"],
                    started_at=started,
                )
                raw = {
                    "source": "steward brief",
                    "at": started,
                    "repo_head": result["head"],
                    "content": {"receipt": receipt, "report": result, "github": remote},
                    "complete": True,
                }
                prior_revision, prior = store.read("campaign")
                if prior_revision != result["state_revision"]:
                    raise ValueError("campaign changed during report; rerun before saving")
                checkpoint = (prior or {}) | {
                    k: result[k]
                    for k in ("objective", "head", "origin_main", "documents", "next_action")
                }
                checkpoint["last_receipt"] = receipt["run_id"]
                prior_records = [
                    r
                    for r in knowledge["records"]
                    if r["layer"] == "working"
                    and r["authority"] == "observation"
                    and r.get("compiler") == "steward-brief/v1"
                ]
                compiled = {
                    "id": "brief-" + receipt["run_id"],
                    "layer": "working",
                    "topic": "campaign",
                    "summary": {
                        "objective": result["objective"],
                        "head": result["head"],
                        "origin_main": result["origin_main"],
                        "next_action": result["next_action"],
                        "unresolved": result["unresolved"],
                        "partial": result["partial_work"],
                        "launch": f"{result['launch']['verified']}/30",
                    },
                    "authority": "observation",
                    "evidence_ids": [receipt["run_id"]],
                    "repo_head": result["head"],
                    "at": started,
                    "compiler": "steward-brief/v1",
                }
                if prior_records:
                    compiled["supersedes"] = prior_records[-1]["id"]
                store.save_report(
                    evidence_id=receipt["run_id"],
                    raw=raw,
                    checkpoint=checkpoint,
                    knowledge=compiled,
                    expected_campaign=prior_revision,
                    expected_knowledge=knowledge_revision,
                )
            print(json.dumps(result, indent=2) if args.json else render(result))
        elif args.command == "remember":
            raw = json.loads(args.evidence.read_text(encoding="utf-8"))
            record = json.loads(args.record.read_text(encoding="utf-8"))
            store.append_evidence(raw["id"], raw["payload"])
            print(store.remember(record, expected_revision=args.expected_revision))
        elif args.command == "retrieve":
            result = store.retrieve(args.topic)
            head = git(repo, "rev-parse", "HEAD")
            result["current_head"] = head
            result["revision_mismatches"] = [
                r["id"] for r in result["records"] if r["repo_head"] != head
            ]
            print(json.dumps(result, indent=2))
        elif args.command == "checkpoint":
            record = json.loads(args.record.read_text(encoding="utf-8"))
            allowed = {
                "objective",
                "partial",
                "completed",
                "blockers",
                "next_action",
                "task_states",
            }
            if set(record) - allowed:
                raise ValueError("checkpoint cannot modify authority or repository observations")
            revision, previous = store.read("campaign")
            inv = inventory(repo)
            phases = phase_tasks(repo, inv)
            reconciliation = reconcile(repo, inv, phases, None)
            tasks = {t["id"]: t for t in phases + work_units(phases, inv, reconciliation)}
            for key, update in record.get("task_states", {}).items():
                if key not in tasks or set(update) - {"state", "evidence"}:
                    raise ValueError("invalid task checkpoint")
                candidate = tasks[key] | update
                if (
                    (key == "P0" or key.startswith("W1-"))
                    and not inv["launch"]["complete"]
                    and candidate["state"]
                    in {"VERIFIED", "PRODUCTION_VERIFIED", "SUPERSEDED", "ABANDONED"}
                ):
                    raise ValueError("literal launch contract is still incomplete")
                if candidate["state"] in {"VERIFIED", "PRODUCTION_VERIFIED"}:
                    validated = satisfy([tasks[key]], {key: update.get("evidence", {})})[0]
                    if validated["state"] != candidate["state"]:
                        raise ValueError("checkpoint completion lacks required production proof")
                plan([candidate])
            if revision != args.expected_revision:
                raise ValueError("stale campaign revision")
            merged = (previous or {}) | record
            merged["task_states"] = (previous or {}).get("task_states", {}) | record.get(
                "task_states", {}
            )
            print(store.write("campaign", merged, expected_revision=revision))
        elif args.command == "backup":
            store.backup(args.destination)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
