"""Markdown rendering of a source-quality result (Section M report)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _ci(e: Mapping[str, Any] | None, nd: int = 3) -> str:
    if not e or e.get("point") is None:
        return "—"
    lo, hi = (e.get("ci90") or [None, None])[:2]
    p = f"{e['point']:.{nd}f}"
    if lo is None:
        return f"{p} (CI —)"
    return f"{p} [{lo:.{nd}f}, {hi:.{nd}f}]"


def _lead_row(f: str, by: Mapping[str, Any], horizons: list[int], u: str) -> str | None:
    cells = []
    any_ok = False
    for h in horizons:
        r = by.get(f"{u}:{h}") or {}
        if r.get("status") == "ok":
            any_ok = True
            cells.append(f"{_ci(r['betaGap'])} · n={r['cells']} · b={r['betaGap']['blocks']}")
        else:
            cells.append(f"insufficient ({r.get('reason', '—')})")
    return f"| `{f}` | " + " | ".join(cells) + " |" if any_ok or cells else None


def markdown(r: Mapping[str, Any]) -> str:
    plan = r["plan"]
    horizons = plan["metrics"]["horizons"]
    hp = plan["primary_horizon"]
    L: list[str] = []
    L.append("# Source-quality evaluation — leakage-safe, point-in-time (SHADOW)")
    L.append("")
    L.append(
        "Evidence only. No production weight, flag or value changed; every candidate is **SHADOW**; "
        "promotion belongs to the model-registry / feature-flag path and a human review. "
        "Agreement with independent future evidence is reported — it is **never** called accuracy, "
        "and KTC parity is never a target."
    )
    L.append("")
    p = r["pins"]
    L.append("| pin | value |")
    L.append("|---|---|")
    L.append(f"| code revision | `{p['codeRevision']}` |")
    L.append(
        f"| preregistration | `{p['preregistration']['path']}` sha256 `{p['preregistration']['sha256'][:16]}…` commit `{(p['preregistration']['commit'] or '')[:12]}` |"
    )
    L.append(
        f"| evaluator changed since prereg | {('yes: ' + p['sourceQualityChangedSincePrereg'].splitlines()[-1]) if p.get('sourceQualityChangedSincePrereg') else 'no'} |"
    )
    L.append(f"| census | `{p['census']['path']}` sha256 `{p['census']['sha256'][:16]}…` |")
    L.append(f"| panel digest | `{p['panelDigest'][:16]}…` (ledger used: {p['ledgerUsed']}) |")
    if p.get("impactPayload"):
        L.append(
            f"| impact payload | `{p['impactPayload']['path']}` sha256 `{p['impactPayload']['sha256'][:16]}…` |"
        )
    L.append(f"| data window | {r['dataWindow'][0]} → {r['dataWindow'][1]} |")
    L.append(f"| generated | {r['generatedAt']} |")
    L.append("")

    L.append("## Challenger dispositions (primary horizon %d days, harness space)" % hp)
    L.append("")
    L.append(
        "| candidate | disposition | Δ MALE (champion − candidate; >0 better) | champion MALE | cells · blocks |"
    )
    L.append("|---|---|---|---|---|")
    for c, g in (r.get("gates") or {}).items():
        agg = (g.get("strata") or {}).get("ALL") or {}
        L.append(
            f"| {c} | **{g.get('disposition')}** | {_ci(agg.get('deltaMALE'), 5)} | {_ci(agg.get('championMALE'), 4)} | "
            f"{agg.get('cells', '—')} · {agg.get('blocks', '—')} |"
        )
    L.append("")
    for c, g in (r.get("gates") or {}).items():
        if g.get("failed") or g.get("missingEvidence") or g.get("reason"):
            L.append(f"**{c}**")
            for x in g.get("failed") or []:
                L.append(f"- failed — {x}")
            for x in g.get("missingEvidence") or []:
                L.append(f"- missing — {x}")
            for x in g.get("notEvaluable") or []:
                L.append(f"- reported only — {x}")
            if g.get("reason"):
                L.append(f"- {g['reason']}")
            L.append("")

    L.append("### Strata and target sensitivity (Δ MALE, 90% date-block CI)")
    L.append("")
    strata = ["ALL", "OFFENSE", "IDP", "elite", "core", "depth", "sparse", "rookie", "inSeason"]
    L.append("| candidate | variant | " + " | ".join(strata) + " |")
    L.append("|---|---|" + "---|" * len(strata))
    for c, g in (r.get("gates") or {}).items():
        for v, by in (g.get("variants") or {}).items():
            cells = []
            for s in strata:
                e = by.get(s) or {}
                cells.append(
                    _ci(e.get("deltaMALE"), 4) + f" ({e.get('cells', 0)})"
                    if e.get("status") == "ok"
                    else "n/a"
                )
            L.append(f"| {c} | {v} | " + " | ".join(cells) + " |")
    L.append("")

    L.append("## Learned weights (final, all data, purged) — SHADOW")
    L.append("")
    fw = r.get("finalWeights") or {}
    fams = sorted(
        {f for c, w in fw.items() for f in (w.get("pooled", w) if isinstance(w, dict) else {})}
    )
    L.append("| family | " + " | ".join(fw) + " |")
    L.append("|---|" + "---|" * len(fw))
    for f in fams:
        row = []
        for c, w in fw.items():
            ww = w.get("pooled", w)
            row.append(f"{ww.get(f, 1.0):.3f}")
        L.append(f"| `{f}` | " + " | ".join(row) + " |")
    L.append("")
    for c, w in fw.items():
        if isinstance(w, dict) and w.get("perUniverse"):
            L.append(
                f"{c} column shows its pooled weight (used for keys covering both universes); per universe:"
            )
            L.append("")
            for u, ww in w["perUniverse"].items():
                L.append(f"- {u}: " + ", ".join(f"`{f}` {v:.3f}" for f, v in sorted(ww.items())))
            L.append("")
    for c, d in (r.get("finalWeightDiagnostics") or {}).items():
        if isinstance(d, dict) and d.get("reason"):
            L.append(f"- {c}: {d['reason']}")
        elif isinstance(d, dict):
            for k, dd in d.items():
                if isinstance(dd, dict) and dd.get("reason"):
                    L.append(f"- {c} [{k}]: {dd['reason']}")
    L.append("")

    q = r["sourceQuality"]
    for u in ("OFFENSE", "IDP"):
        L.append(
            f"## Market lead/lag — {u} (β_gap: share of the family's disagreement the independent market closes)"
        )
        L.append("")
        L.append("| family | " + " | ".join(f"h={h}d" for h in horizons) + " |")
        L.append("|---|" + "---|" * len(horizons))
        for f, by in sorted(q["lead"].items()):
            if any(k.startswith(u + ":") for k in by):
                row = _lead_row(f, by, horizons, u)
                if row:
                    L.append(row)
        L.append("")
        L.append(f"Sensitivity at h={hp}d (β_gap):")
        L.append("")
        L.append(
            "| family | all targets | no KTC targets | no KTC-lineage targets | no own-lineage targets | not freshness-conditioned |"
        )
        L.append("|---|---|---|---|---|---|")
        for f, by in sorted(q["leadSensitivity"].items()):
            s = by.get(u)
            if not s:
                continue
            base = (q["lead"].get(f) or {}).get(f"{u}:{hp}") or {}

            def cell(x):
                return _ci(x.get("betaGap")) if x and x.get("status") == "ok" else "insufficient"

            L.append(
                f"| `{f}` | {cell(base)} | {cell(s.get('noKtcTargets'))} | {cell(s.get('noKtcLineageTargets'))} | "
                f"{cell(s.get('noOwnLineageTargets'))} | {cell(s.get('unconditionalOnFreshness'))} |"
            )
        L.append("")
        L.append(f"## Stability / noise — {u} (h={hp}d)")
        L.append("")
        L.append(
            "| family | self-reversal | move confirmation | abandoned-move rate (large moves) | origins with a move | median |move| |"
        )
        L.append("|---|---|---|---|---|---|")
        for f, by in sorted(q["stability"].items()):
            s = by.get(f"{u}:{hp}")
            if not s or s.get("status") != "ok":
                continue
            L.append(
                f"| `{f}` | {_ci(s.get('selfReversal'))} | {_ci(s.get('moveConfirmation'))} | "
                f"{_ci(s.get('abandonedMoveRate'))} ({s.get('largeMoves', 0)}) | {s['originsWithAnyMove']}/{s['origins']} | {s.get('medianAbsMove')} |"
            )
        L.append("")
        L.append(f"## Event responsiveness — {u} (events defined by the OTHER families' consensus)")
        L.append("")
        L.append(
            "| family | events | capture rate | mean lead days when captured (+ = earlier than market) |"
        )
        L.append("|---|---|---|---|")
        for f, by in sorted(q["events"].items()):
            e = by.get(u)
            if not e:
                continue
            if e.get("status") != "ok":
                L.append(f"| `{f}` | — | insufficient ({e.get('reason')}) | — |")
                continue
            L.append(
                f"| `{f}` | {e['events']} | {_ci(e['captureRate'])} | {_ci(e['meanLeadDaysWhenCaptured'], 2)} |"
            )
        L.append("")
        L.append(
            f"## Future independent-market agreement — {u} (relative to peers on the same cells; not accuracy)"
        )
        L.append("")
        L.append("| family | " + " | ".join(f"h={h}d" for h in horizons) + " |")
        L.append("|---|" + "---|" * len(horizons))
        fa = q["futureAgreement"]
        fams_u = sorted({f for h in horizons for f in (fa.get(f"{u}:{h}") or {})})
        for f in fams_u:
            L.append(
                f"| `{f}` | "
                + " | ".join(_ci((fa.get(f"{u}:{h}") or {}).get(f), 4) for h in horizons)
                + " |"
            )
        L.append("")

    imp = r.get("boardImpact")
    if imp:
        L.append(
            "## Whole-board impact through the override path (latest inputs; impact, not a score)"
        )
        L.append("")
        L.append(
            f"Equal-weight override reproduces the champion board: **{imp['equalWeightOverrideReproducesChampion']}**."
        )
        L.append("")
        L.append(
            "| candidate | rows changed | top-200 membership changes | offense max | IDP max | pick rows changed (market-priced) | sparse rows changed (max) | rookies changed (max) | max family share (row) | mean row HHI |"
        )
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        ch_conc = imp["champion"]["concentration"]
        L.append(
            f"| champion | 0 | 0 | 0 | 0 | 0 (0) | 0 | 0 | {ch_conc['maxShareAnyRow']} | {ch_conc['meanRowHHI']} |"
        )
        for c, x in imp["candidates"].items():
            bg = x["boardDiff"]["byGroup"]
            off = max(
                (v["maxAbs"] for g, v in bg.items() if g in ("QB", "RB", "WR", "TE")), default=0
            )
            idp = (bg.get("IDP") or {}).get("maxAbs", 0)
            L.append(
                f"| {c} | {x['boardDiff']['rowsChanged']} | {x['boardDiff']['top200MembershipChanges']} | {off} | {idp} | "
                f"{x['picks']['changed']} ({x['picksMarketPriced']['changed']}) | {x['sparse']['changed']} ({x['sparse']['maxAbs']}) | {x['rookies']['changed']} ({x['rookies']['maxAbs']}) | "
                f"{x['concentration']['maxShareAnyRow']} | {x['concentration']['meanRowHHI']} |"
            )
        L.append("")
        sp = next(iter(imp["candidates"].values()), {}).get("sparse") or {}
        if "maxFamilies" in sp:
            L.append(
                f"Sparse = non-pick rows with at most {sp['maxFamilies']} independent families "
                f"(the harness's preregistered sparse threshold); rows with an unknown family "
                f"count are excluded, not counted as sparse ({sp['unknownFamilyCount']} rows)."
            )
            L.append("")
        for c, x in imp["candidates"].items():
            L.append(
                f"**{c}** rank bands: "
                + "; ".join(
                    f"{k}: moved {v['moved']}/{v['rows']}, max {v['maxAbsRankMove']}"
                    for k, v in x["rankBands"].items()
                    if k != "top24Changes"
                )
            )
            if x["rankBands"]["top24Changes"]:
                L.append(
                    "top-24 changes: "
                    + ", ".join(
                        f"{t['asset']} {t['rankBefore']}→{t['rankAfter']}"
                        for t in x["rankBands"]["top24Changes"]
                    )
                )
            L.append(
                "largest moves: "
                + ", ".join(
                    f"{m['asset']} ({m['group']}) {m['delta']:+}"
                    for m in x["boardDiff"]["largestMoves"][:8]
                )
            )
            L.append("")
        L.append(
            "Sensitivity to one family disappearing (rows changed / top-200 changes), champion vs candidates:"
        )
        L.append("")
        names = list(imp["candidates"])
        L.append("| family removed | champion | " + " | ".join(names) + " |")
        L.append("|---|---|" + "---|" * len(names))
        for f, v in imp["champion"]["leaveFamilyOut"].items():
            cells = [
                f"{imp['candidates'][c]['leaveFamilyOut'][f]['rowsChanged']} / {imp['candidates'][c]['leaveFamilyOut'][f]['top200MembershipChanges']}"
                for c in names
            ]
            L.append(
                f"| `{f}` | {v['rowsChanged']} / {v['top200MembershipChanges']} | "
                + " | ".join(cells)
                + " |"
            )
        L.append("")

    L.append("## Data, identity and coverage")
    L.append("")
    L.append(
        f"- Evaluated sources ({len(r['eligibility']['evaluated'])}): "
        + ", ".join(f"`{k}`" for k in r["eligibility"]["evaluated"])
    )
    L.append(
        "- Excluded (census, fails closed): "
        + "; ".join(f"`{k}` {v}" for k, v in r["eligibility"]["excluded"].items())
    )
    L.append(
        "- Rookie-only boards parsed but not scored (not on the overall rank scale): "
        + ", ".join(f"`{k}`" for k in r["eligibility"]["rookieOnlyNotScored"])
    )
    L.append(f"- Picks: not evaluated — {r['picks']['reason']}.")
    L.append(
        f"- KTC-lineage families (excluded from targets in the sensitivity variant): {', '.join(r['ktcLineageFamilies'])}"
    )
    L.append(
        f"- Fundamental foresight: {r['fundamentalForesight'].get('status')} — {r['fundamentalForesight'].get('missing', '')}"
    )
    L.append(
        f"- Transaction fit: {r['transactionFit'].get('status')} — {r['transactionFit'].get('missing', '')}"
    )
    L.append("")
    L.append(
        "| source | versions | first | last | median rows | identity withheld (max per date) | parse drops (all versions) |"
    )
    L.append("|---|---|---|---|---|---|---|")
    for k, v in r["readiness"].items():
        ident = r["identity"]["perDate"].get(k) or {}
        parse = r["identity"]["parse"].get(k) or {}
        drops = {kk: n for kk, n in parse.items() if kk not in ("rows", "kept") and n}
        L.append(
            f"| `{k}` | {v['distinctVersions']} | {v['first']} | {v['last']} | {v['medianRows']} | "
            f"{', '.join(f'{a}={b}' for a, b in ident.items()) or '—'} | {', '.join(f'{a}={b}' for a, b in drops.items()) or '—'} |"
        )
    L.append("")
    return "\n".join(L) + "\n"
