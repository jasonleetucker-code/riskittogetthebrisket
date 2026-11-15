# Read-only production research runner — investigation and proposal (2026-10-20)

**Status: PROPOSAL. Nothing here is installed, merged or active.** The owner asked (2026-10-20) whether a
permanent, secure, read-only research workflow can exist without triggering unnecessary production
deployments. This note answers that and holds the workflow drafted on 2026-10-19 so it is not lost. It is
**inert text**: a code block in a Markdown file under `docs/`, not a file under `.github/workflows/`.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 1. Why there is no such workflow today

* **A dispatchable workflow must already be on `main`.** GitHub only offers `workflow_dispatch` for a file
  that exists on the default branch. The run then uses the file from the requested ref.
* **Any merge to `main` deploys.** `deploy.yml` runs on every push to `main` except `data/**` and
  `exports/**`. A workflow-only merge therefore causes a production deploy.
* **Every on-box workflow uses the deploy key.** All 23 existing on-box workflows reuse
  `DEPLOY_SSH_PRIVATE_KEY`, which has full deploy power. A research job holding that key can, in principle,
  do anything the deploy user can. Read-only behaviour then rests on the script, not on the platform.
* **The repository is public.** Actions logs and artifacts are world-readable.

## 2. Options

| option | deploy triggered? | read-only enforced by | owner / admin action |
|---|---|---|---|
| **A. Ride the next release train.** Add the research workflow (and the research scripts) to the next normal release, so it reaches `main` with a deploy that happens anyway. | no extra deploy | the script's audit hook (`scripts/research_readonly_guard.py`) | approve its inclusion in a train |
| **B. Exclude non-runtime paths from deploy.** Add `.github/workflows/research-*.yml` (and optionally `docs/**`) to `deploy.yml` `paths-ignore`. | no, for those paths | the script's audit hook | owner decision: it changes the deploy trigger |
| **C. Dedicated read-only box identity (recommended permanent design).** Combined with A or B for getting the file onto `main`. | per A / B | the **kernel**, not just the script | admin creates a user and a key (below) |

## 3. Option C in detail (defence in depth)

1. **A separate unix user** `research-ro` on the box:
   * no login shell for humans;
   * group-read only on `data/market_trades/`, `exports/archive/` and the app's `src/`;
   * no write permission anywhere in the app tree.
2. **A separate SSH key** held as a separate secret, e.g. `RESEARCH_RO_SSH_PRIVATE_KEY`, in a protected
   `research` environment with required reviewers. Its `authorized_keys` entry is pinned to a forced command:

   ```
   command="/usr/local/bin/research-ro-run",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA… research-ro
   ```

   A leaked research key then cannot deploy, write, open a shell or tunnel.
3. **`/usr/local/bin/research-ro-run`** (root-owned, reviewed once):
   * accepts only a 40-hex commit SHA and a script name from a fixed allowlist;
   * downloads `scripts/<name>` and `scripts/research_readonly_guard.py` for that SHA from the public
     repository (raw URLs) and checks them against a sha256 sent with the request;
   * runs them as:

     ```
     systemd-run --wait --pipe --uid=research-ro \
       -p ProtectSystem=strict -p ProtectHome=read-only -p PrivateTmp=yes \
       -p PrivateNetwork=yes -p NoNewPrivileges=yes -p MemoryMax=2G -p CPUQuota=50% \
       -p Nice=19 -p IOSchedulingClass=idle -p RuntimeMaxSec=1800 …
     ```

     That gives a kernel-enforced read-only filesystem, no network, and bounded memory and CPU. Only stdout
     comes back.
4. **The workflow** (draft below) takes `commit_sha` as input instead of running whatever ref was dispatched.
   It refuses non-40-hex input, prints aggregates only (the script's `assert_aggregate_only` refuses
   identifier-like output), and uploads one JSON artifact with 30-day retention.

**Recommendation:** C, with the file reaching `main` by A. B is a reasonable owner choice but is a
deploy-policy change.

## 4. The 2026-10-19 draft workflow (preserved, inert)

This is the draft written for this research (option A or B delivery, deploy key, script-level guard), updated on
2026-10-20 to upload the guard and run from the temp dir. It is kept for reference. Under option C it would switch to the research key and the forced command.

```yaml
name: Package Model Market-Ledger Evaluation

# Research evidence for the package Value Adjustment (owner directives
# 2026-10-19, Phases 1-2: docs/valuation/PACKAGE_MODEL_PHASE2_RESEARCH_2026-10-19.md).
#
# The Sharp / KTC market-trade ledger (data/market_trades/underlying_trades.sqlite)
# is box-local, so the only place every package-model candidate can be graded on
# the full archive is the production host.  This reuses the deploy path's SSH
# capability, exactly like signals-onbox-verification.yml, to run
# ``scripts/package_model_phase2_research.py --market-ledger-only`` from a temp
# dir against the DEPLOYED checkout:
#
#   * READ-ONLY: the ledger is opened ``mode=ro`` (market_trade_report.
#     open_canonical_ledger); archived boards are read from exports/archive; the
#     script writes nothing on the host (stdout only), touches no timer, store,
#     value, config or service, and runs at ``nice 19``;
#   * the production package model is NOT changed: candidates are scored in this
#     one process only.
#
# THIS REPOSITORY IS PUBLIC: the log and the artifact are readable by anyone.
# The script prints aggregates only (counts, means, confidence intervals) and
# ``assert_aggregate_only`` refuses to emit anything identifier-like (league,
# user, transaction or asset ids).  The runner's copy of the scripts is uploaded
# into a mktemp dir and removed on exit.

on:
  workflow_dispatch:
    inputs:
      max_lag_days:
        description: Max days between a trade and the archived board that prices it
        type: string
        required: false
        default: "7"

permissions:
  contents: read

concurrency:
  group: package-model-market-ledger
  cancel-in-progress: false

jobs:
  evaluate:
    name: Package-model market-ledger evaluation
    runs-on: ubuntu-latest
    timeout-minutes: 45
    environment: production
    steps:
      - name: Checkout
        uses: actions/checkout@v7

      - name: Configure production SSH
        env:
          DEPLOY_SSH_PRIVATE_KEY: ${{ secrets.DEPLOY_SSH_PRIVATE_KEY }}
          DEPLOY_KNOWN_HOSTS: ${{ secrets.DEPLOY_KNOWN_HOSTS }}
          DEPLOY_PORT: ${{ secrets.DEPLOY_PORT }}
        shell: bash
        run: |
          set -Eeuo pipefail
          install -d -m 700 "$HOME/.ssh"
          printf '%s\n' "$DEPLOY_SSH_PRIVATE_KEY" | sed 's/\r$//' > "$HOME/.ssh/id_ed25519"
          printf '%s\n' "$DEPLOY_KNOWN_HOSTS" | sed 's/\r$//' > "$HOME/.ssh/known_hosts"
          chmod 600 "$HOME/.ssh/id_ed25519"
          chmod 644 "$HOME/.ssh/known_hosts"
          ssh-keygen -y -f "$HOME/.ssh/id_ed25519" >/dev/null
          echo "PORT=${DEPLOY_PORT:-22}" >> "$GITHUB_ENV"

      - name: Run the evaluation on the host (read-only)
        env:
          DEPLOY_HOST: ${{ secrets.DEPLOY_HOST }}
          DEPLOY_USER: ${{ secrets.DEPLOY_USER }}
          APP_DIR: ${{ vars.PROD_APP_DIR || '/home/dynasty/trade-calculator' }}
          MAX_LAG_DAYS: ${{ inputs.max_lag_days }}
        shell: bash
        run: |
          set -Eeuo pipefail
          [[ "$MAX_LAG_DAYS" =~ ^[0-9]+$ ]] || { echo "max_lag_days must be an integer" >&2; exit 2; }
          SSH=(ssh -i "$HOME/.ssh/id_ed25519"
            -o BatchMode=yes -o StrictHostKeyChecking=yes
            -o UserKnownHostsFile="$HOME/.ssh/known_hosts"
            -o ConnectTimeout=15 -o ServerAliveInterval=15
            -p "$PORT" "$DEPLOY_USER@$DEPLOY_HOST")
          DIAG_DIR="$("${SSH[@]}" 'mktemp -d /tmp/package-model-ledger.XXXXXX')"
          for f in package_model_phase2_research.py package_model_hybrid_research.py research_readonly_guard.py; do
            "${SSH[@]}" "cat > $(printf %q "$DIAG_DIR")/$f" < "scripts/$f"
          done
          # The interpreter is the app's own venv and RISKIT_APP_DIR points the
          # scripts at the DEPLOYED checkout (src/, exports/archive, data/).  The
          # run starts in the temp dir (never the app dir) and the script installs
          # scripts/research_readonly_guard.py before importing any app code.
          "${SSH[@]}" "set -Eeuo pipefail; trap 'rm -rf -- $(printf %q "$DIAG_DIR")' EXIT; \
            PY=/home/dynasty/.venvs/trade-calculator/bin/python; \
            [[ -x \$PY ]] || PY=$(printf %q "$APP_DIR")/.venv/bin/python; \
            cd $(printf %q "$DIAG_DIR") && \
            RISKIT_APP_DIR=$(printf %q "$APP_DIR") nice -n 19 ionice -c3 \$PY -B \
              $(printf %q "$DIAG_DIR")/package_model_phase2_research.py \
              --market-ledger-only --max-lag-days $MAX_LAG_DAYS" > package-model-market-ledger.json
          python3 - <<'EOF'
          import json
          d = json.load(open("package-model-market-ledger.json"))
          m = d.get("marketLedgerCalibration") or {}
          print(json.dumps({k: d.get(k) for k in ("deployedCodeSha", "ledgerBuiltAt",
                "ledgerDatedGroupsSince20260701")}, indent=1))
          print(json.dumps((m.get("audit") or {}), indent=1)[:4000])
          cal = (m.get("calibration") or {}).get("byModel") or {}
          for model, per in cal.items():
              allp = per.get("all") or {}
              print(model, {b: (v.get("n"), v.get("meanSigned"), v.get("ci95"))
                            for b, v in allp.items() if b != "equal"})
          EOF

      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v7
        with:
          name: package-model-market-ledger
          path: package-model-market-ledger.json
          retention-days: 30
```

## 5. What the one-off production run (2026-10-20) used instead

The owner chose to run the script by hand on the box (Option 2). The command downloads the three scripts at a
pinned, reviewed commit, verifies their sha256, and runs them from a temp dir under the same audit-hook guard. It
needs no workflow, no merge and no deploy. The exact command is recorded with the results in
`docs/valuation/PACKAGE_MODEL_PHASE2_RESEARCH_2026-10-19.md`.

A finding from rehearsing the guard: `build_api_data_contract` makes a live Sleeper GET for league context
(`src/api/data_contract.py`, `_resolve_league_context`). The guard refuses it, and the build falls back to its
configured league context. Rehearsed on 30 archived boards, the boards were byte-identical with and without
network, so the refusal does not change any graded value. The script reports these refusals
(`refusedNetworkAttempts` / `refusedNetworkCallers`) and does not treat them as fatal. Any refused write, delete,
SQLite read-write open or process start exits 3.
