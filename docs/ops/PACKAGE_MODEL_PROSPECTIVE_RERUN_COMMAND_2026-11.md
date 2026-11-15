# Package model: prospective re-run, pinned manual box command (early November 2026)

**Status: PREPARED, NOT RUN.** Running it on the production box needs a separate owner authorization (owner
decision Package 5C, 2026-10-21). PR #1873 stays open and unmerged. Nothing here changes `geom_q078_v1`
(q = 0.78), any served value, any flag or any deploy.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 1. What this is

It is the optional prospective re-run named in `docs/valuation/PACKAGE_MODEL_PHASE3_RESEARCH_2026-10-20.md`
§9.4, and in the frozen protocol, `docs/valuation/evidence/package_model_phase3_2026-10-20/PREREGISTRATION.md`
§2.3:

- Trades dated after **2026-10-20** (the freeze date) have not been seen by anyone.
- Once at least **2,000 unequal-count** trades exist after that date, the same pinned Phase 3 command reports the
  prospective tests (`PROSPECTIVE_MIN_UNEQUAL = 2000`).
- The research recommendation is already **KEEP `geom_q078_v1`**. This run would *confirm* a KEEP. It is not a
  gate for a change, and no new analysis is added here.

No research is duplicated. This sheet only makes the existing Phase 3 command exact and safe to repeat.

## 2. Why not PR #1873's job

PR #1873 is a `workflow_dispatch` job. It is kept open per the owner, but it does not run this evaluation:

| check | #1873 | needed |
|---|---|---|
| script run | `package_model_phase2_research.py --market-ledger-only` (Phase 2) | `package_model_phase3_research.py --box` (Phase 3, which defines the prospective population) |
| pinned phase 2 script | `1363738634af…` (= `d1c9e5e9`, the Phase 2 commit) | `97498d256992…` (= the frozen Phase 3 pin and current main) |
| pinned hybrid script | `80a29c54c393…` | `80a29c54c393…` at the Phase 3 pin; main has since moved to `098337d89a8b…` |
| pinned guard | `8faf319d9073…` | `8faf319d9073…` at the Phase 3 pin; main has since moved to `5c208fe8ee18…` |
| delivery | merge to `main`, which triggers a production deploy | none: a manual command, no merge, no deploy |

Measured on 2026-10-21 with `git show <ref>:scripts/<file> | sha256sum`. **Against current main, all three of
#1873's pins are stale** (the integration report's "2 of 3" compared against a different reference). Against the
frozen Phase 3 pin, two match and the Phase 2 script does not. The Phase 3 script is not in #1873 at all.

## 3. The pin

**Commit `d7a881bc13f508a7755c13adf746cbd57c449ada`** is the commit of the preregistered Phase 3 production run.
The preregistration says the protocol "is fixed by the code at the pinned commit that runs it". This commit is on
`main`.

| file at the pin | sha256 |
|---|---|
| `scripts/package_model_phase3_research.py` | `7bc9360b76a612bf8c897d0f1c6040ed3d3f26a8d33a0136bc9125d4389f11a5` |
| `scripts/package_model_phase2_research.py` | `97498d256992cd7ec99fe6f22e17fab2c905c97410ce64d67dea2b8df3f0e65d` |
| `scripts/package_model_hybrid_research.py` | `80a29c54c393ee7e99d59eb7868ba817308f52fbe74cd7dff1c434c5db056514` |
| `scripts/research_readonly_guard.py` | `8faf319d907388ab4942cd03bd61e02905952f54784b4b0f6fd5abe30294cf43` |

How these were verified (2026-10-21):
- From the git objects: `git show d7a881bc1:scripts/<file> | sha256sum`.
- From the exact URLs the command downloads
  (`https://raw.githubusercontent.com/jasonleetucker-code/riskittogetthebrisket/<pin>/scripts/<file>`). All four
  match byte for byte.

**Why the frozen pin and not current main.**
- The Phase 3 and Phase 2 scripts are byte-identical on `main` today.
- Two files changed after the pin:
  - `package_model_hybrid_research.py` changed in #1898. `level` was renamed `level_v1_legacy`, and an alias was
    kept "for the frozen Phase 1-3 callers".
  - `research_readonly_guard.py` changed in `2fee3850`, so the guard now removes its scratch directory by absolute
    path.
- Pinning the frozen commit runs exactly the preregistered *research scripts*. Its guard's one weakness (a
  scratch directory can be left behind) is contained by the wrapper below: `TMPDIR` is the command's own temp
  directory, which the `trap` removes.

**What is NOT pinned: the valuation pipeline.**
- The scripts rebuild every archived board with the box's deployed `src/`.
- Phase 3 ran on deployed `fd798c3e`. Since the pin, `src/api/data_contract.py` alone has changed in 17 commits.
- The run stamps `deployedCodeSha`. Any difference from the 2026-10-20 run therefore mixes three things:
  - new trades;
  - late-collected pre-freeze trades;
  - board-pipeline changes.
- §6 says how that is reported.

**Compatibility with the deployed `src/`.** The scripts import the box's deployed application code
(`RISKIT_APP_DIR`). Checked against current main (`ce22d5de7`): every `src` attribute the four pinned scripts use
still exists. That covers `market_trade_report`, `market_trade_eval`, `package_model`, `fairness_bands`,
`build_api_data_contract`, `IdentityContext` and `normalize_player_name`. A local rehearsal of the pinned
`--box` path under the guard, against current main, reached the ledger check and exited 2
(`no_market_trade_ledger_on_this_host`) with no import error.

## 4. When to run it

- The prospective tests appear only when `prospective.unequal >= 2000`.
- In the Phase 3 run:
  - 58% of graded trades were unequal-count (10,893 of 18,690);
  - 63% of ledger groups were graded (18,690 of 29,638).
  - So about **5,400 post-freeze ledger groups** are needed.
- Phase 3 §9.4 estimated about two weeks at October volume, so the earliest sensible date is
  **2026-11-03 or 2026-11-04**.
- Run the step 0 readiness count first. It is one read-only count.
- A run that comes up short is harmless: it prints `"reported": false` and the counts. It is still a wasted
  slot, though, so wait and re-run.

Start it between **09:30 and 13:30 UTC**. That slot avoids the box's writers:
- the Sharp crawl passes, 04:20 to about 07:30 UTC;
- the transaction crawl at 02:20, 08:20, 14:20 and 20:20;
- the market-trade ledger rebuild at 08:52 UTC (`dynasty-market-trade-ledger`).

The rebuild replaces the file atomically, so an open read-only connection keeps reading the old copy. Avoiding it
just keeps the run on one ledger build.

## 5. The command

Run it as the **service user** (`dynasty`), never root. The simplest way is from your own machine:

```bash
ssh -p <port> dynasty@<host> 'bash -s' < package_model_prospective_box.sh > prospective_run.json
```

Here `package_model_prospective_box.sh` is the script below, copied verbatim:

```bash
#!/usr/bin/env bash
# Package-model prospective re-run (Phase 3 protocol, frozen pin).  READ-ONLY.
# Writes only inside one mktemp dir, removed on exit.  Prints aggregates on stdout.
set -Eeuo pipefail
PIN=d7a881bc13f508a7755c13adf746cbd57c449ada
APP_DIR=/home/dynasty/trade-calculator
RAW="https://raw.githubusercontent.com/jasonleetucker-code/riskittogetthebrisket/$PIN/scripts"
[[ "$(id -un)" != root ]] || { echo "run as the service user, not root" >&2; exit 64; }
umask 077
WORK="$(mktemp -d /tmp/pkg-prospective.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
cd "$WORK"
for f in package_model_phase3_research.py package_model_phase2_research.py \
         package_model_hybrid_research.py research_readonly_guard.py; do
  curl -fsSL --proto '=https' --max-time 60 "$RAW/$f" -o "$WORK/$f"
done
sha256sum --check --strict --quiet - >&2 <<'PINS'
7bc9360b76a612bf8c897d0f1c6040ed3d3f26a8d33a0136bc9125d4389f11a5  package_model_phase3_research.py
97498d256992cd7ec99fe6f22e17fab2c905c97410ce64d67dea2b8df3f0e65d  package_model_phase2_research.py
80a29c54c393ee7e99d59eb7868ba817308f52fbe74cd7dff1c434c5db056514  package_model_hybrid_research.py
8faf319d907388ab4942cd03bd61e02905952f54784b4b0f6fd5abe30294cf43  research_readonly_guard.py
PINS
PY=/home/dynasty/.venvs/trade-calculator/bin/python
[[ -x "$PY" ]] || PY="$APP_DIR/.venv/bin/python"
[[ -x "$PY" ]] || { echo "no app python found" >&2; exit 2; }
LEDGER="$APP_DIR/data/market_trades/underlying_trades.sqlite"
[[ -f "$LEDGER" ]] || { echo "no market-trade ledger on this host" >&2; exit 2; }
# Step 0 (readiness): post-freeze ledger groups.  About 5,400 are needed.
"$PY" -B -c 'import sqlite3,sys; c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True); print("post_freeze_groups", c.execute("SELECT COUNT(*) FROM underlying_trades WHERE substr(occurred_date,1,10) > ?",("2026-10-20",)).fetchone()[0], file=sys.stderr)' \
  "$LEDGER"
# Step 1: the frozen Phase 3 run, under the read-only audit-hook guard.
TMPDIR="$WORK" RISKIT_APP_DIR="$APP_DIR" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  timeout 2700 nice -n 19 ionice -c3 \
  "$PY" -B "$WORK/package_model_phase3_research.py" --box --max-lag-days 7
```

What it does:
- It refuses to run as root.
- It downloads exactly four files at the pin and refuses to run if any sha256 differs.
- It never `cd`s into the app directory, and never calls `git`, `systemctl`, `sudo` or `pip`.
- The Python guard is installed before any application import. It refuses every file write outside its scratch
  directory, any read-write SQLite connection, any subprocess and any network connection, and the run exits 3 if
  a write or process start was refused.
- Peak memory last time was 1,157 MB, and the run is CPU- and I/O-niced.
- The only network access is the four `curl` downloads from GitHub before Python starts.

## 6. Acceptance checks on the output

Do these before quoting or committing anything:

1. Exit status 0, and `readOnlyGuard.refusedWriteOrProcessAttempts == 0`.
2. Network refusals are expected (about 273 last time), all from `_resolve_league_context`.
   - The 2026-10-20 offline parity audit showed the guarded fallback changes 0 of 136,558 board values at
     `fd798c3e`. It checks only that network fallback, not board drift between deployed versions.
   - `reproductionOfPhase2Report` re-scores trades through 2026-10-19 and compares them with the first report.
     A bin that moves by more than 0.01 cannot by itself say whether the boards changed (a new `deployedCodeSha`)
     or late-collected pre-freeze trades were added (compare its `n` with 18,588).
   - Report such a move as **unattributed drift**, with both figures. Attributing it would need a separate,
     separately authorized board comparison. Until then, treat the prospective tests as conditional on it.
3. `prospective.reported == true` and `prospective.unequal >= 2000`. Otherwise it is too early; see §4.
4. The output is aggregate-only. The script calls `assert_aggregate_only` itself. Also check by eye that there
   is no 9+ digit run and no `player:` / `mpick:` / `utrade:` / `@` string.
5. Commit the file byte-for-byte as
   `docs/valuation/evidence/package_model_phase3_2026-10-20/production_prospective_run_<date>.json` and record its
   sha256. Interpret it under the frozen rules R1–R4 (Phase 3 §9.3). The selections are re-made on discovery, so
   they can differ from 2026-10-20 if late-collected pre-freeze trades were added.

## 7. Not authorized by this sheet

- Running it on the box. That needs a separate owner authorization.
- Merging, closing or editing PR #1873.
- Any change to `geom_q078_v1`, q, the fairness methodology, a flag or a served value. A prospective result that
  disagreed with KEEP would be brought back to the owner, never acted on.
