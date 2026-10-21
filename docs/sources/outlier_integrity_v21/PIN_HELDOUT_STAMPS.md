# Pinning the G1 / G2 identity stamps (operational, not frozen)

**Status: operational procedure.** It sits beside [`HELDOUT_RULE.json`](HELDOUT_RULE.json) so Stage 4
sees it. It edits no frozen rule, threshold or population. Authority: owner decision 2026-10-21,
**"Artifacts + pin held-out (Recommended)"**, recorded in
[`DEVIATION_PROPOSAL_U2_EVIDENCE_STORAGE.md`](DEVIATION_PROPOSAL_U2_EVIDENCE_STORAGE.md) and intake
row `IV21-U2S` in `docs/OWNER_REQUESTED_TODO.md`.

## Why

Each refresh board in `exports/archive/` carries a small manifest
(`identity_capture_manifest.json`) holding the SHA-256 of its full U2/U2b stamps. The stamps
themselves live in that refresh run's GitHub Actions artifact, which expires after **90 days**.
The wrong-player gate is evaluated on **G1 and G2**, so their stamps must outlive their artifacts.
Every other board's stamps may expire.

## When

As soon as G1 and G2 are fixed by `HELDOUT_RULE.json` (earliest 2026-11-25; G2 moves with any
window extension, at most to 2026-12-02), and **before** their artifacts expire (90 days after each
board's refresh; for G1, no earlier than 2027-02-02). Pin each board once. If a window extension
moves G2, pin the new G2; an earlier pin of a board that is no longer G2 may stay.

## How

For each of G1 and G2, using the archive zip `exports/archive/dynasty_export_<stamp>.zip` that
the held-out manifest names (from the commit that ADDED it; `git show <sha>:<path>` if the
14-day retention has pruned it from the tree):

```bash
ARCHIVE=exports/archive/dynasty_export_<stamp>.zip

# 1. Where are its stamps?  --sealed prints only scrapeTimestamp, the evidence sha256
#    and the download command (no census: the board is sealed until Stage 4).
python scripts/verify_identity_capture_evidence.py --sealed --archive "$ARCHIVE"

# 2. Download the artifact named there.
gh run download <runId> -R <repo> -n identity-capture-evidence-<runId>-<attempt> -D /tmp/g1

# 3. Verify against the ARCHIVED manifest and pin.  Nothing is written unless it verifies.
python scripts/verify_identity_capture_evidence.py --pin --label G1 \
    --archive "$ARCHIVE" --evidence /tmp/g1/identity_capture_evidence_<UTC>.json.gz

# 4. Commit the pin directory (explicit path).
git add docs/sources/outlier_integrity_v21/pinned_stamps/dynasty_export_<stamp>/
```

The pin writes `docs/sources/outlier_integrity_v21/pinned_stamps/<archive stem>/`:

| file | content |
|---|---|
| `identity_capture_evidence_<UTC>.json.gz` | the verified stamps, deterministic gzip of the canonical JSON |
| `identity_capture_manifest.json` | the archived manifest it verified against |
| `PIN.json` | archive name and SHA-256, label, scrapeTimestamp, evidence SHA-256, artifact pointer; written last, so its presence means the pin is complete |

Re-running a pin of the same evidence is a no-op. A pin of DIFFERENT evidence for the same archive
is refused, never overwritten. `verify_pinned(<dir>)` in the same script re-verifies a committed pin.

## Seal

`--pin` and `--sealed` print only hashes and timestamps. It verifies a checksum and does not read or summarize
the stamps' content. That is the same class of read the seal allows the manifest builder ("add-commit,
hashes, scrapeTimestamp and completeness"). If the lane judges a pin to be a read of an H board
anyway, it logs that in `DEVIATIONS.md` before the Stage 4 run commit, as the seal requires.

## If a stamp file is missing, expired or does not verify

The wrong-player gate is **BLOCKED (dependency)** for that board. It is never inferred as passing,
and no other board's stamps may be substituted.
