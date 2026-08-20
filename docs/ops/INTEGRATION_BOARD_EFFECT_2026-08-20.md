# Board effect of the 2026-08-20 integration segment: zero

`CLAUDE.md` rule 4 requires verifying downstream effects for any value or
ranking change. This records that verification for the ten merges landed
overnight, **as one measurement over the whole segment** rather than a claim
repeated per PR.

## What was measured

Base `64a0f4640` → head `3a62da3cd`, covering:

#927, #932, #933, #929, #937, #934, **#915**, #941, #935, #925.

**Code is the only variable.** The segment also carries 74 changed files under
`data/` / `CSVs/` / `exports/` (routine 2-hourly refresh drift). Reverting the
whole segment including its data would measure the vendors, not our code, so
the base capture reverts **only** the 120 non-data files — restoring each to its
`64a0f4640` content, and deleting the ones that did not exist then — while
`data/`, `CSVs/` and `exports/` stay at head.

Both captures via `scripts/golden_board.py`, diffed with
`scripts/board_diff.py`.

## Result

```
rows: 1111 -> 1111     ranked: 740 -> 740     priced: 849 -> 849
picks: 162 -> 162      idp:    398 -> 398

VALUES: 0 moved, 0 newly priced, 0 newly unpriced
RANKS:  0 changed
```

## Why this was worth measuring rather than assuming

**#915 is a scoring change** — "Exact league scoring (#802): every configured
rule now scored". A change with that description is exactly the kind that could
move canonical value, and "it shouldn't" is not evidence.

Zero is the *correct* answer here, and the architecture says why: #915's work
lands in `src/league_comparison/`, `src/nfl_data/` and `src/bdvm/`, which serve
league comparison, realized points and the fundamental-value engine. None of
them is `_compute_unified_rankings`, and BDVM is explicitly forbidden from
writing `rankDerivedValue`. The measurement confirms the boundary held in
practice, on a real board, rather than only in the module graph.

The same measurement covers the Wave A train (#933 / #929 / #937 / #934), which
was separately captured at `8b9c28289 → 1c1c52e1b` and also reported 0/0. That
sub-measurement is what `V1-130`'s L2 evidence cites.

## Reproducing

```bash
BASE=64a0f4640
git diff --name-only $BASE..HEAD | grep -vE '^(data|CSVs|exports)/' > /tmp/seg_src.txt
python3 scripts/golden_board.py --out /tmp/board_now.json
while read -r f; do
  if git cat-file -e "$BASE:$f" 2>/dev/null; then git checkout "$BASE" -- "$f"; else rm -f "$f"; fi
done < /tmp/seg_src.txt
python3 scripts/golden_board.py --out /tmp/board_segbase.json
git checkout HEAD -- . && git clean -fdq -- src scripts frontend tests docs deploy
python3 scripts/board_diff.py /tmp/board_segbase.json /tmp/board_now.json
```
