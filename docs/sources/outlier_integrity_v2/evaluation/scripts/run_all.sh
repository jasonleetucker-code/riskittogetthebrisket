#!/bin/bash
# Reproduce the directive §6 board comparison (boards A-D, A'-C'', no-filter
# attribution boards) on both R pins, and the incumbent-only D4 check on the
# newest I_INDEPENDENT board.
#
# usage: run_all.sh REPO WORK_DIR OUT_DIR
#   REPO      a clone of the repository (read-only use: git objects + worktree add)
#   WORK_DIR  scratch directory (a throwaway sparse worktree is created here)
#   OUT_DIR   where the reports are written
# env: CODE_SHA (default eb06823c57, the V2 code commit evaluated)
set -euo pipefail
REPO=$(cd "$1" && pwd); WORK=$(mkdir -p "$2" && cd "$2" && pwd); OUT=$(mkdir -p "$3" && cd "$3" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
CODE_SHA=${CODE_SHA:-eb06823c57}
TREE="$WORK/tree"
REL=docs/sources/outlier_integrity_v2
git -C "$REPO" worktree add --no-checkout --detach "$TREE" "$CODE_SHA"
( cd "$TREE" && git sparse-checkout set --no-cone '/*' '!/data/ros/aggregate/history/' '!/data/raw/' \
    '!/data/raw_sources/' '!/data/identity/identity_report_*' && git checkout -q )
for pin in d9680440a5:pin2015 eb10d3e12d:pin0527; do
  c=${pin%%:*}; tag=${pin##*:}
  git -C "$REPO" show "$c:exports/latest/dynasty_data_2026-10-19.json" > "$WORK/payload_$tag.json"
  bash "$TREE/$REL/rootcause/pin_inputs.sh" "$TREE" "$c" | tail -1 > "$OUT/inputs_$tag.sha"
  ( cd "$TREE" && python3 "$HERE/oiv2_abcd_extract.py" "$WORK/payload_$tag.json" "$tag" "$WORK/x_$tag.json.gz" 2>&1 \
      | grep -v "Source CSV missing" | tail -1 )
  python3 "$HERE/oiv2_abcd_analyze.py" "$WORK/x_$tag.json.gz" "$TREE/$REL/manifests/REGRESSION_SET.json" "$OUT"
done
# newest I_INDEPENDENT board: incumbent-only boards (no V2 build on held-out data)
git -C "$REPO" show d9c3a70209:exports/latest/dynasty_data_2026-10-20.json > "$WORK/payload_i052241.json"
bash "$TREE/$REL/rootcause/pin_inputs.sh" "$TREE" d9c3a70209 | tail -1 > "$OUT/inputs_i052241.sha"
( cd "$TREE" && python3 "$HERE/oiv2_abcd_extract.py" "$WORK/payload_i052241.json" i052241_incumbent_only \
    "$WORK/x_i052241.json.gz" --boards "A,B',Anf,B'nf" 2>&1 | grep -v "Source CSV missing" | tail -1 )
python3 "$HERE/oiv2_abcd_theo_iboard.py" "$WORK/x_i052241.json.gz" "$OUT/THEO_JOHNSON_I052241.md"
bash "$HERE/oiv2_abcd_team_history.sh" "$TREE" > "$OUT/team_history.txt"
for f in "$OUT"/abcd_*.json; do gzip -n -f "$f"; done
git -C "$REPO" worktree remove --force "$TREE"
echo "done: $OUT"
