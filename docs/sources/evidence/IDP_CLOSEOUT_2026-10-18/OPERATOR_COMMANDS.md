# On-box evidence requests: Signals IDP (Decision 7) and package model (Decision 8)

Owner closeout 2026-10-18, PART 2. Both inputs are **box-local** and absent from the
evaluation environment:

| input | expected path on the production box | here |
|---|---|---|
| Signals IDP boards | `data/sources/signals/board/signalsIdp{Dl,Lb,Db}.csv` (private, gitignored, written by the `dynasty-signals-values` timer) | **absent** (`data/sources/` does not exist) |
| Production trade archive | `data/market_trades/` raw archive + `data/intel` ledger, read by `src/trade/market_trade_report.build_ledger` | **absent**; a dry run of the command below returns 0 raw observations and 0 underlying trades |

Nothing was fabricated in their place. Both commands are **read-only**. Neither changes a
hold, a threshold, a timestamp, a denominator, q or any served value.

Run them from the **deployed checkout** (`$APP_DIR`, the directory the
`dynasty.service` unit runs from), after this PR is deployed. The Signals command uses
the `--signals-dependence-only` mode this PR adds to `scripts/idp_rehab_eval.py`.

## D7 — Signals IDP dependence analysis

```bash
cd "$APP_DIR"
PAYLOAD="$(ls -1 exports/latest/dynasty_data_*.json | tail -1)"
python3 scripts/idp_rehab_eval.py --signals-dependence-only \
    --payload "$PAYLOAD" --out /tmp/signals_idp_dependence.json
```

**What it computes.** For each Signals family board (DL, LB, DB) it uses only that
family's on-board IDP identities. It compares the Signals order with each voting-capable
IDP board: IDP Trade Calculator, Draft Sharks IDP, FantasyPros IDP, DLF IDP and the IDP
Show combined board. For each pair it reports the Spearman correlation and the
leave-pair-out residual, using the same estimators as the public matrix
(`scripts/audit/lineage_integrity_sweep.py`).

**Return:** the whole of `/tmp/signals_idp_dependence.json`. It is aggregate only:
correlations, residuals, overlap counts, board row counts and duplicate-identity counts.
It never contains a player name, rank or value, so it is safe to paste into this public
repository.

If it reports `"state": "not_provisioned"`, the collector has not written the boards.
Run the Signals On-Box Verification workflow with `collect: true` first.

### Why this is the next diagnostic

Round 1 failed promotion-gate criterion 6 (IDP p90 move 30.07%; one offense row moved)
and criterion 6b (signed bias LB −6.24%, DB −9.95%). See
`docs/sources/SIGNALS_FANTASY_INTEGRATION.md` §10.8.1.

The dependence matrix separates the two explanations still open:

* **Shared-lineage copy.** If Signals' family order is near-identical to one voter, its
  vote is a correlated copy, like the IDP Trade Calculator ≡ IDP Show IDP-only finding.
  Look for a residual near 1 against one board.
* **Independent opinion.** If the residuals are modest against every board, the bias
  that failed 6b is genuine disagreement (LB) or a coverage artefact (DB, 25 Signals-only
  rows). It is not double counting.

The DL p90 decomposition named in §10.8.1 (ranked vs off-cap rows, families
before → after, haircut lifts) is a separate counts-only extension of
`scripts/verify_signals_onbox.py`. It is **not** part of this request.

The hold stays either way. A genuinely different challenger must be preregistered
before it is tested.

## D8 — package-model evaluation on the production trade archive

```bash
cd "$APP_DIR"
python3 - > /tmp/package_model_onbox.json <<'PY'
import json, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, ".")
from src.api.data_contract import build_api_data_contract
from src.trade import market_trade_eval as ev
from src.trade import market_trade_report as report
from src.valuation_math import package_model as pm

export = sorted(Path("exports/latest").glob("dynasty_data_*.json"))[-1]
raw = json.loads(export.read_text(encoding="utf-8"))
board = ev.BoardIndex(build_api_data_contract(raw))
bdate = date.fromisoformat(str(raw.get("date")))
result = report.build_ledger()          # read-only; persists nothing
groups = result["grouping"].groups
models = [pm.active_model_id(), *pm.shadow_model_ids()]   # geom_q078_v1, ktc_2026_04
out = {
    "export": export.name,
    "boardDate": bdate.isoformat(),
    "rawObservations": len(result.get("observations") or []),
    "underlyingTrades": len(groups),
    "topology": ev.summarize_topology(groups),
    "models": {m: ev.residual_report(groups, board, board_date=bdate, model_id=m) for m in models},
}
print(json.dumps(out, indent=1, default=str))
PY
```

This is the existing evaluation, run once per registered package model:

* `market_trade_eval.residual_report` is what `scripts/market_trade_ledger.py` runs for
  the active model, here with `model_id` set explicitly;
* trade grouping and dedupe are unchanged;
* the look-ahead guard is unchanged: the board must date at or before the trade, at most
  7 days earlier;
* package values come from `src.valuation_math.package_model.adjusted_pair_totals`.

It does not rebuild or persist the canonical ledger. That is the `--no-persist` path,
without the report write.

**Return:** the whole of `/tmp/package_model_onbox.json`. It holds counts and residual
summaries (n, median, p90, share above 20%) per source and per model. It holds no other
league's trade contents.

**Reading rules (Decision 8).** `geom_q078_v1` with q = 0.78 stays the active model, and
q is not recalibrated from this output. Accepted trades are market observations, not
ground-truth fair values. KTC-derived sources are partly in-sample (see the report's
notes).

**Known limit.** The existing harness grades against one board, the newest export, so
only trades in the 7 days before it are eligible. A point-in-time-per-trade board is
not part of the existing script. Adding one would be a new methodology unit, not this
request.
