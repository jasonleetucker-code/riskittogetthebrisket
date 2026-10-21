# Deviation: where the V2.1 U2 / U2b evidence is stored

**Status: DECIDED — owner, 2026-10-21.** The owner answered in the coordinator's session; the
selected option label, verbatim: **"Artifacts + pin held-out (Recommended)"**.

What the decision says (as relayed by the coordinator):

* the deviation below is **approved**: the full U2/U2b stamps live in the 90-day CI artifact
  (plus the 30-day box copy), and git keeps the checksummed manifest;
* **pinning requirement:** when G1 and G2 are selected (earliest 2026-11-25), their full stamps
  must be **verified against the manifest checksum and committed into the repository**, so the
  evaluation evidence is permanent. Procedure: [`PIN_HELDOUT_STAMPS.md`](PIN_HELDOUT_STAMPS.md);
* every other board's full stamps **may expire** with their artifacts.

The option label is the owner's own selection. The surrounding sentences are the coordinator's
relay of what that option meant, not owner-typed text.

This file edits no frozen rule. The V2.1 lane transcribes the entry at the end into
`docs/sources/outlier_integrity_v21/DEVIATIONS.md` as a `V21-D` entry. Intake row: `IV21-U2S` in
`docs/OWNER_REQUESTED_TODO.md`. The text below is the proposal as approved.

## What the registration says

* Preregistration section 3.7 lists U2, U2b, U3 and VID by **content** only. It names no storage
  path and no format for them.
* `HELDOUT_RULE.json` (`identityPrerequisite`): the wrong-player gate is evaluable only if **G1 and
  G2 both carry** the U2, U2b and U3 scraper evidence stamps, and VID was live in the producing
  refresh.
* The held-out boards are the `exports/archive/dynasty_export_*.zip` archives that the automated
  refresh added to `main`.

## What the implementation does, and why

The owner asked (2026-10-21) that the per-refresh sidecar not grow git history without bound. The
full U2/U2b sidecar is about 480 KB of JSON per refresh (about 44 KB gzipped). The refresh
force-adds `data/scrape_state/` and commits `exports/` every two hours. That put the sidecar in four
committed places per refresh: `data/scrape_state`, `exports/latest`, `dynasty_export_latest.zip`
and the archive zip. Measured, that is about 136 KB of git objects per refresh, or about 1.6 MB per
day.

| Evidence | Where it lives now | In git? |
|---|---|---|
| **U3** (position, team) | Trailing CSV columns of each board, inside the archive zip | yes, unchanged |
| **U2b** (observed Superflex / TE state) | Inside the per-board **manifest** (`toggles` per source) | yes |
| **U2 census** (stamps per source, dropped / merge counts, `collectorErrors`, stamps by rung strength and by field) | Manifest | yes |
| **U2 full stamps** (per-row rung, page position, acquisition, published fields) | gzip file, **bound by the manifest's SHA-256** over its canonical JSON | **no** |
| **VID** map | `data/identity/vendor_id_map.jsonl`, single writer = the refresh | yes |

The manifest (about 2 KB) is written to `data/scrape_state/identity_capture_manifest.json` and archived
**inside the same zip as the board it describes**. The full stamps live in:

1. the refresh run's GitHub Actions artifact `identity-capture-evidence-<runId>-<attempt>`,
   retained **90 days** (this public repository's maximum); the manifest records `runId`,
   `runAttempt`, the artifact name and the repository;
2. a box-local copy under the gitignored `data/identity_capture_evidence/`, pruned after
   **30 days**. It describes the production box's own scrapes, not the held-out boards.

`scripts/verify_identity_capture_evidence.py --archive <zip> --evidence <file>` verifies a retrieved
file against the archived manifest. A file that does not hash to the committed SHA-256 is never
evidence.

## The interpretation that needs approval

"G1 and G2 **carry** the U2 stamps" is read as follows: the board carries U3 and U2b inline, and it
carries U2 **by checksum-bound reference** rather than inline. If the owner reads "carry" as inline
only, the alternative is to put the full sidecar back into the archive zip. That would restore about
44 KB per refresh of git growth (about 0.5 MB per day) and nothing else would change.

## Risk the owner should see

* **Expiry.** The full U2 stamps of a refresh board expire 90 days after that refresh. The first
  stamped H_ORIGIN board is the first refresh after #1910 merges (the refresh runs the scraper from
  `main`, so production deploy is not needed for stamps). Its artifact therefore expires about
  90 days after the merge, around late January 2027 for a late-October merge. As decided, the
  stamps of **G1 and G2** must be **downloaded, verified and committed** once they are selected
  (earliest 2026-11-25), and before their artifacts expire (`PIN_HELDOUT_STAMPS.md`). G1 is the
  first complete H_ORIGIN board at or after 2026-11-04, so its artifact expires no earlier than
  2027-02-02. If a gate board's stamps expire unpinned, the wrong-player gate is BLOCKED for it; it
  is never inferred as passing.
* **Visibility.** Artifacts of a public repository can be downloaded by any signed-in GitHub user.
  The full stamps add matching rungs and page positions to vendor rows whose values are already
  public in the tracked archive zips. No application route serves them.

## DEVIATIONS entry (approved; for the lane to transcribe)

> **V21-Dxx (storage of the U2 / U2b evidence; owner-approved 2026-10-21, "Artifacts + pin held-out
> (Recommended)").** Preregistration 3.7 names no storage for U2/U2b. To keep git history bounded
> (owner, 2026-10-21), each refresh archives a manifest beside the board: U2b toggles, U2 census,
> collector-error count, SHA-256 of the full stamps. The full stamps are kept outside git, as a
> 90-day Actions artifact plus a 30-day box-local copy, verifiable against that checksum. "G1 and
> G2 carry the stamps" is read as U3 and U2b inline and U2 by checksum-bound reference. When G1 and
> G2 are selected, their full stamps are verified against the archived manifest and committed
> under `docs/sources/outlier_integrity_v21/pinned_stamps/` (`PIN_HELDOUT_STAMPS.md`); other
> boards' stamps may expire. An expired or unverifiable stamp file makes the wrong-player gate
> BLOCKED for that board.
