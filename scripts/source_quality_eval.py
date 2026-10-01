#!/usr/bin/env python3
"""Leakage-safe source-quality evaluation + source-weight challengers (Batch 3 B/C).

Rerunnable and append-friendly, suitable for a recurring job.  It PRODUCES
evidence only: no production weight, flag or value is changed, every candidate
is SHADOW, and promotion stays with the model-registry / feature-flag path and a
human review.

    python scripts/source_quality_eval.py --readiness-only
    python scripts/source_quality_eval.py \\
        --prereg docs/valuation/evidence/source-quality-2026-10-01/PREREGISTRATION.md \\
        --out-dir docs/valuation/evidence/source-quality-2026-10-01

``--ledger PATH`` adds the temporal ledger's ``source_value`` lane (production
box) to the git/CSV history; without it the run uses the repository history.

Exit codes: 0 evaluation written; 1 refused (e.g. preregistration not committed);
2 fatal input error.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.source_quality import SCHEMA  # noqa: E402
from src.source_quality import challengers as ch  # noqa: E402
from src.source_quality import evaluate as ev  # noqa: E402
from src.source_quality import metrics as mt  # noqa: E402
from src.source_quality import panel as pn  # noqa: E402
from src.source_quality import report  # noqa: E402

DEFAULT_CENSUS = REPO / "docs/sources/census/CENSUS_2026-10-01.json"
DEFAULT_LINEAGE = REPO / "config/sources/source_lineage.json"
PICKS_REASON = (
    "pick history: the KTC pick families exist only from 2026-09-09 and the IDP Trade "
    "Calculator's pick rows have not moved since July (census content staleness) -- there "
    "are never two independent MOVING pick markets over a preregistered horizon"
)


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def _git(*args: str) -> str:
    out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def _newest_payload() -> Path | None:
    files = sorted((REPO / "exports/latest").glob("dynasty_data_*.json"))
    return files[-1] if files else None


def source_quality_section(
    m: pn.Matrix, X: Mapping, lineage: Mapping, plan: ev.Plan, progress: Callable[[str], None]
) -> dict:
    cfg = plan.metrics
    ktc_lineage = ev.ktc_lineage_families(m, lineage)
    quality: dict = {
        "lead": {},
        "stability": {},
        "events": {},
        "futureAgreement": {},
        "leadSensitivity": {},
    }
    for u in (pn.OFFENSE, pn.IDP):
        fams = mt.families_in(X, m.universe == u)
        for h in cfg.horizons:
            progress(f"{u} h={h}: lead/lag, stability, agreement")
            quality["futureAgreement"][f"{u}:{h}"] = mt.future_agreement(m, X, u, h, cfg)
            for f in fams:
                quality["lead"].setdefault(f, {})[f"{u}:{h}"] = mt.lead_lag(m, X, f, u, h, cfg)
                quality["stability"].setdefault(f, {})[f"{u}:{h}"] = mt.stability(
                    m, X, f, u, h, cfg
                )
        for f in fams:
            quality["events"].setdefault(f, {})[u] = mt.event_response(m, X, f, u, cfg)
            hp = plan.primary_horizon
            sens: dict[str, Any] = {}
            for v, excl in (
                ("noKtcTargets", ev.KTC_FAMILIES),
                ("noKtcLineageTargets", ktc_lineage),
            ):
                sens[v] = mt.lead_lag(m, X, f, u, hp, cfg, exclude_targets=frozenset(excl - {f}))
            members = m.family_members().get(f, [])
            own = {
                m.specs[k].family for k in ev.lineage_partners(lineage, members) if k in m.specs
            } - {f}
            sens["noOwnLineageTargets"] = mt.lead_lag(
                m, X, f, u, hp, cfg, exclude_targets=frozenset(own)
            )
            sens["noOwnLineageTargets"]["excludedFamilies"] = sorted(own)
            sens["unconditionalOnFreshness"] = mt.lead_lag(m, X, f, u, hp, cfg, fresh_only=False)
            quality["leadSensitivity"].setdefault(f, {})[u] = sens
    return quality


def run(
    panel: pn.ObservationPanel,
    excluded: Mapping[str, str],
    census: Mapping[str, Any],
    lineage: Mapping[str, Any],
    plan: ev.Plan,
    *,
    payload: Path | None = None,
    realized: Mapping[str, float] | None = None,
    progress: Callable[[str], None] = _log,
) -> dict:
    """The whole evaluation on an already-built panel; returns the result dict."""
    span = panel.span()
    readiness = pn.readiness(panel)
    dates = pn.daily_grid(span[0], span[1])
    progress(f"building daily matrix {span[0]}..{span[1]} ({len(dates)} days)")
    m = pn.build_matrix(panel, dates)
    X = m.family_matrix()
    ktc_lineage = ev.ktc_lineage_families(m, lineage)
    variants = {
        "allTargets": frozenset(),
        "noKtcTargets": ev.KTC_FAMILIES,
        "noKtcLineageTargets": ktc_lineage,
    }

    quality = source_quality_section(m, X, lineage, plan, progress)
    c2 = ev.c2_data_volume(m, X, plan)
    progress(f"C2 data-volume gate: run={c2['run']}")
    progress("walk-forward evaluation")
    wf = ev.walk_forward(m, X, plan, c2["run"], variants, progress=progress)

    progress("final weights (all data, purged)")
    fam_of = ev.registry_families()
    final_family: dict = {}
    final_overrides: dict = {}
    final_diag: dict = {}
    for c in ev.CANDIDATES:
        w, per_u, diag = ev.candidate_weights(c, m, X, plan, c2["run"])
        final_diag[c] = diag
        if c == "C2_asset_class_reliability":
            if not c2["run"]:
                continue
            final_family[c] = {"pooled": w, "perUniverse": per_u}
            final_overrides[c] = ch.to_source_overrides(
                w, fam_of, ev.c2_per_source(per_u, w, census)
            )
        else:
            final_family[c] = w
            final_overrides[c] = ch.to_source_overrides(w, fam_of)

    impact = None
    picks_unchanged = {c: False for c in ev.CANDIDATES}
    if payload is not None and payload.exists():
        raw = json.loads(payload.read_text(encoding="utf-8"))
        impact = ev.board_impact(raw, final_overrides, progress=progress)
        for c, r in impact["candidates"].items():
            picks_unchanged[c] = r["picksMarketPriced"]["changed"] == 0
    result_gates = (
        ev.gates(wf, plan, m.dates, c2["run"], picks_unchanged) if wf.get("status") == "ok" else {}
    )

    parse_totals: dict = {}
    for k, vs in panel.versions.items():
        tot: dict = {}
        for v in vs:
            for kk, n in v.parse.items():
                tot[kk] = tot.get(kk, 0) + n
        parse_totals[k] = tot
    pmask = m.universe == pn.PICK
    pick_fams = sorted(f for f, a in X.items() if pmask.any() and (a[pmask] == a[pmask]).any())

    result = {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "SHADOW",
        "pins": {
            "panelDigest": ev.panel_digest(panel),
            "impactPayload": (
                {
                    "path": payload.resolve().relative_to(REPO).as_posix(),
                    "sha256": ev.sha256_file(payload),
                }
                if impact
                else None
            ),
        },
        "plan": {
            **{k: v for k, v in asdict(plan).items() if k != "metrics"},
            "metrics": asdict(plan.metrics),
        },
        "dataWindow": [span[0].isoformat(), span[1].isoformat()],
        "eligibility": {
            "evaluated": sorted(readiness),
            "excluded": dict(excluded),
            "families": m.family_members(),
            "rookieOnlyNotScored": sorted(k for k, s in m.specs.items() if s.rookie_only),
        },
        "readiness": readiness,
        "identity": {"perDate": m.identity, "parse": parse_totals, "assets": len(m.assets)},
        "picks": {
            "familiesWithPickObservations": pick_fams,
            "evaluated": False,
            "reason": PICKS_REASON,
        },
        "ktcLineageFamilies": sorted(ktc_lineage),
        "sourceQuality": quality,
        "c2DataVolume": c2,
        "walkForward": {
            "folds": wf.get("folds"),
            "status": wf.get("status"),
            "reason": wf.get("reason"),
        },
        "gates": result_gates,
        "finalWeights": final_family,
        "finalWeightDiagnostics": final_diag,
        "boardImpact": impact,
        "fundamentalForesight": mt.fundamental_foresight(m, X, realized, m.dates[-1]),
        "transactionFit": mt.transaction_fit(None),
    }
    return ev.to_jsonable(result)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--census", type=Path, default=DEFAULT_CENSUS)
    ap.add_argument("--lineage", type=Path, default=DEFAULT_LINEAGE)
    ap.add_argument(
        "--ledger", type=Path, default=None, help="optional temporal ledger (source_value lane)"
    )
    ap.add_argument(
        "--payload", type=Path, default=None, help="raw payload for the pipeline-space impact"
    )
    ap.add_argument("--prereg", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument(
        "--archive", type=Path, default=None, help="append-only JSONL of candidate evaluations"
    )
    ap.add_argument("--readiness-only", action="store_true")
    ap.add_argument("--skip-impact", action="store_true")
    ap.add_argument("--allow-uncommitted-prereg", action="store_true", help="tests only")
    ap.add_argument("--n-boot", type=int, default=None)
    ap.add_argument(
        "--realized", type=Path, default=None, help="optional {asset_key: outcome} JSON"
    )
    args = ap.parse_args(argv)

    from src.api import data_contract as dc

    if not args.census.exists():
        _log(f"census missing: {args.census}")
        return 2
    census = pn.load_census(args.census)
    lineage = json.loads(args.lineage.read_text(encoding="utf-8"))
    specs, excluded = pn.eligible_specs(census, dc._RANKING_SOURCES, dc._SOURCE_CSV_PATHS)
    _log(f"{len(specs)} eligible sources; reading point-in-time history")
    versions = pn.versions_from_git(REPO, specs)
    ledger_used = False
    if args.ledger and args.ledger.exists():
        for k, vs in pn.versions_from_ledger(args.ledger, specs).items():
            versions[k] = pn._dedupe(list(versions.get(k, [])) + list(vs))
        ledger_used = True
    panel = pn.ObservationPanel(specs, versions)
    span = panel.span()
    if span is None:
        _log("no history")
        return 2
    if args.readiness_only:
        print(
            json.dumps(
                {
                    "span": [span[0].isoformat(), span[1].isoformat()],
                    "excluded": excluded,
                    "sources": pn.readiness(panel),
                },
                indent=1,
            )
        )
        return 0

    if args.prereg is None or not args.prereg.exists():
        _log("refusing to score candidates without a preregistration (--prereg)")
        return 1
    rel = args.prereg.resolve().relative_to(REPO).as_posix()
    prereg_commit = _git("log", "-1", "--format=%H", "--", rel)
    dirty = bool(_git("status", "--porcelain", "--", rel))
    if (not prereg_commit or dirty) and not args.allow_uncommitted_prereg:
        _log(
            "refusing: the preregistration must be committed, unmodified, before candidates are scored"
        )
        return 1

    plan = ev.Plan(metrics=mt.Config(n_boot=args.n_boot)) if args.n_boot else ev.Plan()
    payload = None if args.skip_impact else (args.payload or _newest_payload())
    realized = json.loads(args.realized.read_text(encoding="utf-8")) if args.realized else None
    result = run(panel, excluded, census, lineage, plan, payload=payload, realized=realized)
    changed = (
        _git(
            "diff",
            "--stat",
            prereg_commit,
            "--",
            "src/source_quality",
            "scripts/source_quality_eval.py",
        )
        if prereg_commit
        else None
    )
    result["pins"].update(
        {
            "codeRevision": _git("rev-parse", "HEAD"),
            "workingTreeDirty": bool(
                _git(
                    "status",
                    "--porcelain",
                    "--",
                    "src/source_quality",
                    "scripts/source_quality_eval.py",
                )
            ),
            "sourceQualityChangedSincePrereg": changed or None,
            "preregistration": {
                "path": rel,
                "sha256": ev.sha256_file(args.prereg),
                "commit": prereg_commit or None,
            },
            "census": {
                "path": args.census.resolve().relative_to(REPO).as_posix(),
                "sha256": ev.sha256_file(args.census),
            },
            "lineage": {"sha256": ev.sha256_file(args.lineage)},
            "ledgerUsed": ledger_used,
        }
    )
    out_dir = args.out_dir or (REPO / "data" / "source_quality")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = span[1].isoformat()
    (out_dir / f"results_{stamp}.json").write_text(
        json.dumps(result, indent=1, sort_keys=True), encoding="utf-8"
    )
    (out_dir / f"REPORT_{stamp}.md").write_text(report.markdown(result), encoding="utf-8")
    archive = args.archive or (out_dir / "evaluations.jsonl")
    with archive.open("a", encoding="utf-8") as fh:
        for rec in ev.archive_records(result):
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    _log(f"wrote {out_dir}")
    for c, g in result["gates"].items():
        _log(f"  {c}: {g.get('disposition')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
