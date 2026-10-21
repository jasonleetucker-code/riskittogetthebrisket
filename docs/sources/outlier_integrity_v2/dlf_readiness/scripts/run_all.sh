#!/bin/bash
# Reproduce the directive §9 / prereg §15 DLF restoration readiness report on
# both R pins (pin2015, pin0527).
#
# usage: run_all.sh REPO WORK_DIR OUT_DIR
#   REPO      a clone of the repository (read-only use: git objects + worktree add)
#   WORK_DIR  scratch directory (a throwaway sparse worktree is created here)
#   OUT_DIR   where the reports are written
# env: CODE_SHA (default 766468a75a: V2 code eb06823c57 + the §6 evaluation docs)
#
# Cost: 8 full builds per pin, sequential; about 2-4 s each and ~300 MB peak RSS.
set -euo pipefail
REPO=$(cd "$1" && pwd); WORK=$(mkdir -p "$2" && cd "$2" && pwd); OUT=$(mkdir -p "$3" && cd "$3" && pwd)
HERE=$(cd "$(dirname "$0")" && pwd)
CODE_SHA=${CODE_SHA:-766468a75a}
TREE="$WORK/tree"
REL=docs/sources/outlier_integrity_v2
git -C "$REPO" worktree add --no-checkout --detach "$TREE" "$CODE_SHA"
( cd "$TREE" && git sparse-checkout set --no-cone '/*' '!/data/ros/aggregate/history/' '!/data/raw/' \
    '!/data/raw_sources/' '!/data/identity/identity_report_*' && git checkout -q )
for pin in d9680440a5:pin2015 eb10d3e12d:pin0527; do
  c=${pin%%:*}; tag=${pin##*:}
  git -C "$REPO" show "$c:exports/latest/dynasty_data_2026-10-19.json" > "$WORK/payload_$tag.json"
  bash "$TREE/$REL/rootcause/pin_inputs.sh" "$TREE" "$c" | tail -1 > "$OUT/inputs_$tag.sha"
  ( cd "$TREE" && python3 "$HERE/oiv2_dlf_readiness.py" "$WORK/payload_$tag.json" "$tag" "$OUT" 2>&1 \
      | grep -v "Source CSV missing" | tail -1 )
done
git -C "$REPO" worktree remove --force "$TREE"
echo "done: $OUT"
