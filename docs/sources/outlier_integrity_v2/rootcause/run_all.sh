#!/bin/bash
# Outlier-integrity-v2 root-cause reproduction (directive deliverable A).
#
# Creates a throwaway sparse worktree of CODE_SHA, pins CSVs/ + data/ to each
# input commit, builds
#   A   = production defaults (DLF IDP held)
#   B   = dlf_offense_only_vote=0 in this local process only (DLF IDP restored)
#   Bnf = B with the decision-bearing IDP filter stood down (diagnostic only)
# then analyses.  Never changes any branch; removes the worktree when done.
# Inputs are public valuation data committed to the repository.
#
# usage: bash run_all.sh [OUT_DIR]      (OUT_DIR defaults to a fresh temp dir)
set -euo pipefail
R=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$(git -C "$R" rev-parse --show-toplevel)}
CODE_SHA=${CODE_SHA:-f631607ff327c520b7979d8e6ba3aef34ce73106}   # origin/main when measured
OUT=${1:-$(mktemp -d)}
W=$(mktemp -d)/wt-rc
git -C "$REPO" worktree add --no-checkout -q --detach "$W" "$CODE_SHA"
trap 'git -C "$REPO" worktree remove --force "$W" || true' EXIT
( cd "$W" && git sparse-checkout set --no-cone '/*' '!/data/ros/aggregate/history/' '!/data/raw/' '!/data/raw_sources/' '!/data/identity/identity_report_*' && git checkout -q )
mkdir -p "$OUT"
# pin2015 = newest complete archive dynasty_export_20261019_201546 (refresh d9680440a5)
# pin0527 = the input the documented 31/18/10/3 was measured on (refresh eb10d3e12d)
for pin in d9680440a5:pin2015 eb10d3e12d:pin0527; do
  c=${pin%%:*}; tag=${pin##*:}
  git -C "$REPO" show "$c:exports/latest/dynasty_data_2026-10-19.json" > "$OUT/payload_$c.json"
  "$R/pin_inputs.sh" "$W" "$c" | tail -1 > "$OUT/inputs_$tag.sha"
  ( cd "$W"
    python "$R/rc_build.py" "$W" "$OUT/payload_$c.json" "$OUT/A_$tag.json"
    python "$R/rc_build.py" "$W" "$OUT/payload_$c.json" "$OUT/B_$tag.json" RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0
    python "$R/rc_build.py" "$W" "$OUT/payload_$c.json" "$OUT/Bnf_$tag.json" RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0 RC_NO_IDP_FILTER=1 )
  python3 "$R/rc_analyze.py" "$OUT/A_$tag.json" "$OUT/B_$tag.json" "$OUT/analysis_$tag" > "$OUT/analysis_$tag.txt"
  python3 "$R/rc_decompose.py" "$OUT/A_$tag.json" "$OUT/B_$tag.json" "$OUT/Bnf_$tag.json" "$OUT/decompose_$tag.json" > /dev/null
  python3 "$R/rc_tables.py" "$OUT" "$tag" > /dev/null
done
echo "done: $OUT/vote_tables_pin2015.txt $OUT/vote_tables_pin0527.txt"
