#!/usr/bin/env bash
# W08 evidence regeneration. Run from the repo root with the stack up.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SECRET=$(cat /tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/e2e_secret.txt)
curl -s -c /tmp/audit-cookies-w08.txt -X POST http://127.0.0.1:8000/api/test/create-session \
  -H "Authorization: Bearer $SECRET" >/dev/null
# contract.json is the payload every .mjs harness reads (view=app == the legacy
# dict path; /api/dynasty-data is what the browser actually fetches).
curl -s -b /tmp/audit-cookies-w08.txt "http://127.0.0.1:8000/api/data?view=app" -o "$HERE/contract.json"
cd "$HERE"
node rows.mjs        # -> rows.json      (materialised board, zero-value census)
node symmetry.mjs    # -> symmetry.json  (W08-F009)
node mono2.mjs       # -> monotonicity-full.json  (W08-F003)
node mono3.mjs       # -> monotonicity-multi.json (W08-F003, non-1v1)
node vacopy.mjs      # -> va-recipient.json       (W08-F002)
node picks.mjs       # -> pick-ownership.json     (W08-F005)
node picks2.mjs      # pick-label resolution trace (W08-F004/F005)
node picks3.mjs      # -> pick-zero-and-collapse.json (W08-F005/F006)
node js_va.mjs       # -> js_va.json     (W08-F010, diff against src/trade/ktc_va.py)
cd - >/dev/null
.venv/bin/python "$HERE/tep_override_divergence.py"   # W08-F001
.venv/bin/python "$HERE/raw_mode_class_drift.py"      # W08-F007
# Browser probes (request interception per AUDIT_PROTOCOL.md):
( cd "$HERE" && /home/user/riskittogetthebrisket/.venv/bin/python page_probe2.py )  # W08-F004
( cd "$HERE" && /home/user/riskittogetthebrisket/.venv/bin/python page_probe3.py )  # W08-F011
( cd "$HERE" && /home/user/riskittogetthebrisket/.venv/bin/python page_probe5.py )  # W08-F007/F012
