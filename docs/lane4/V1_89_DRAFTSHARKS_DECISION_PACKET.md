# V1-89 — DraftSharks acquisition: decision packet and repair record

**Lane 4 (Market / FAAB / Sharp).  Owner decision OD-04: re-mint / accept /
retire.  Measured 2026-08-25 against `main` `13456dd5`.**

Claude 5 owns reconciliation, merge, deployment, L3 verification and ledger
promotion.  Nothing here edits V1 status.

---

## 1. What the fetchers actually authenticate with

Recorded because "credentials may be needed" is not an actionable statement
and this question had been asked three times.

| fetcher | mechanism |
|---|---|
| `scripts/fetch_draftsharks.py` (offense + IDP) | **username/password login that mints a session.**  Reads `DRAFTSHARKS_EMAIL` + `DRAFTSHARKS_PASSWORD` from the gitignored `.env`, drives headless Chromium through `/login`, requires an `_identity` cookie to be issued, and persists four auth cookies to `draftsharks_session.json` at mode 0600.  Cached cookies are tried first; a page returning without the league marker triggers an automatic re-mint. |
| `scripts/fetch_draftsharks_ros.py` | **consumes that cookie jar only.**  No credentials, no login flow of its own. |

Not a pre-minted cookie the operator pastes in, not an API token, not
persisted browser state.  **No owner credential action is required, and none
should be requested.**

## 2. Measured state

Feeds, at `origin/main` `13456dd5`:

| feed | file | rows × cols | sha256[:16] | previous sha256[:16] | diff |
|---|---|---|---|---|---|
| `draftSharks` | `draftSharksSf.csv` | 441 × 13 | `cc4b31a8016b12ee` | `5cdbd0c763e4c70f` | 518 lines |
| `draftSharksIdp` | `draftSharksIdp.csv` | 410 × 13 | `c45a01e7e51e3506` | `27647e9eef9a7336` | 382 lines |
| `draftSharksRos` (SF) | `draftSharksRosSf.csv` | 250 × 7 | `7f38d30e295d314d` | `a18601030aca6428` | 368 lines |
| `draftSharksRos` (IDP) | `draftSharksRosIdp.csv` | 425 × 7 | `e833b1e02fbea0be` | `0769d0a2239738b5` | 712 lines |

Ages: fetch 2.7 h (stamps 23:05:49Z / 23:06:01Z), content last **changed**
4.6 h, content **re-confirmed byte-identical against upstream** at the 2.7 h
fetch.  All three pages expose an upstream publication marker —
`<time datetime="2026-08-25T00:15:02Z">` — i.e. the vendor published 1.6 h
ago, *after* our last fetch.  That is ordinary 2-hourly cadence lag, not
staleness.

Differences are substantive rather than cosmetic: rank reorderings (Jayden
Daniels ↔ Lamar Jackson at 6/7) and projection movement (Drake Maye 1-year
449 → 447).

Consumption is real: in the built contract `draftSharks` carries **412**
players and `draftSharksIdp` **245**, against declared floors of 190 / 85.

## 3. OD-04 — **A. HEALTHY_CURRENT**

Authenticated access works and content is demonstrably current.  **Accept.**
Do not re-mint.  Do not retire.

## 4. Why L3 was still blocked, and what this PR repairs

Two gaps, both engineering, neither an owner action.

### 4a. DraftSharks content-age was structurally unobservable

`scripts/check_source_health.measure_content_staleness` reads exactly one
evidence lane — the tracked `exports/archive/*.zip` bundles — and those
bundles are assembled from `Dynasty Scraper.py`'s own `FULL_DATA` maps.  Any
source acquired by a standalone fetcher writes straight into `CSVs/site_raw/`
and therefore **never entered an archive at all**.  The archive carried three
`site_raw` members: `ktc`, `ktcSfTep`, `idpTradeCalc`.

Control run before the repair: 8-day-stale DraftSharks CSVs substituted into
the tree with fetch stamps left current produced a health verdict
**byte-identical** to the healthy run (`22 fresh / content-stale: 1
(idpTradeCalc)`).  A synthetic-archive control confirmed the detector's logic
*does* discriminate (frozen 5 d vs moving 0 d) when it is given the bytes.
The detector was never wrong; it was never given the bytes.

**Repair.**  `src/sources/site_raw_mirror.py` owns the list of raw vendor CSVs
that must reach the bundle and copies them verbatim into
`exports/latest/site_raw/` during the existing export pass.  No second
detector, no new health vocabulary, no second archive writer.  The manifest
gains `siteRawMirrored`.

Two properties recorded rather than hidden:

* **Absent is absent.**  A missing source file is skipped, never written as an
  empty placeholder — a placeholder would make a never-acquired source read as
  perfectly byte-stable, which is the exact failure being removed.
* **One-run lag.**  `scheduled-refresh.yml` runs the scraper *before* the
  DraftSharks fetchers, so the bundle written by run N carries the CSVs
  acquired by run N-1.  A constant offset does not distort a "how long has this
  been byte-identical" measurement, and closing it would require a second
  archive writer.

### 4b. ROS could not prove it was looking at the league's board

`fetch_draftsharks.py` proves each pass is league-scored by showing the
WebAssembly worker rewrote values away from the static
`data-scoring-value-*` public defaults, and fails closed otherwise.
`fetch_draftsharks_ros.py` had no equivalent: it checked that a cookie *file*
existed and published whatever came back.  An expired jar still renders a
public board and still exits 0.

**That proof cannot be copied mechanically.**  Measured 2026-08-25, the ROS
pages carry **zero** `data-scoring-value` attributes, so there is no public
default to diverge from; a look-alike predicate would be true of every page,
authenticated or not.

**Repair.**  `prove_ros_page_is_league_scoped` asserts the two strongest things
the ROS pages actually expose, and requires **both**:

1. the authenticated **league marker** is present in the rendered shell —
   measured 0 occurrences on all three pages unauthenticated;
2. the rendered **row count** meets a per-URL floor.

Either alone is bypassable: a cached shell can carry the marker with no board
behind it, and a full public board can carry no marker at all.  Failure raises
`RosAuthError`, which aborts **before any CSV is written**, so both last-good
files survive and `run_fetcher` leaves the freshness stamp where it was.

Floors are `120` (SF) and `200` (IDP) — bracketed by measurement, not pinned to
a snapshot: an unauthenticated fetch renders **25** rows, the authenticated
boards carried **250** and **425**.  They must not be tightened toward today's
counts; the vendor reshaped both boards between 2026-07-30 and 2026-08-25.

A pre-existing silent-degradation bug was fixed alongside it, because the new
gate would otherwise make it reachable: a failed SF fetch overwrote last-good
with a header-only file, while the IDP branch already guarded against exactly
that.

## 5. Documentation corrections

Both the ROS fetcher and the ROS adapter asserted that `/ros-rankings/idp` is a
978-row 1QB mirror over a universe identical to the SF board, and that the
name-first union therefore "contributes zero".  **Re-measured 2026-08-25 that
is false in every part**: SF 250 rows, IDP 425 rows genuinely restricted to
DB/DL/LB, 66 names in common, and the union contributes **358** players.

The claim has now been wrong twice in opposite directions, so both docstrings
were rewritten as rules that do not depend on a count: the two pages are
separate acquisitions whose populations may differ at any time, each carries
its own `total_ranked` so the scales union safely, and the size of the
contribution is measured when it matters and never assumed.  The adapter's
stale "PR 1 proxy / PR 2 swap" header was replaced with what the module does
today.

No weight, bridge, dedup, Hill, valuation, rank or IDP-translation change.

## 6. L3 re-execution recipe for Claude 5

Local repair is FEATURE_GREEN.  L3 needs the deployed box:

1. deploy the exact merged SHA;
2. confirm the production DraftSharks fetch succeeds (`run_fetcher` stamps
   `draftSharks` / `draftSharksIdp` / `draftSharksRos` — stamps advance only on
   exit 0);
3. confirm the authenticated dynasty/IDP proof succeeded — the run passed
   `_prove_pass_is_league_scored`, so a non-zero exit is the only alternative;
4. confirm the independent ROS proof succeeded — a public or truncated board
   now exits 2 with `auth_required:` / `implausible_population:` on stderr and
   writes nothing;
5. confirm all four DraftSharks files appear under `site_raw/` in the newest
   `exports/archive/*.zip`, and in `manifest.json` under `siteRawMirrored`;
6. confirm `measure_content_staleness()` now returns keys `draftSharksSf`,
   `draftSharksIdp`, `draftSharksRosSf`, `draftSharksRosIdp`;
7. confirm a currently-publishing DraftSharks does **not** false-alert
   (`daysSinceChange` 0-1 while the vendor is live);
8. confirm the stale-content control **does** alert — freeze the mirrored
   bytes across archives beyond `contentStaleness.defaultDays` and require a
   `Content unchanged` warning naming DraftSharks;
9. confirm `idpTradeCalc`'s existing content-age reading is unchanged.

Steps 5-6 are the ones that were structurally impossible before this PR.

## 7. Known limits, stated

* The mirror covers the four DraftSharks files only.  **19 other sources
  acquired by standalone fetchers remain outside the content-age lane** — the
  same class of blindness, out of scope here, and worth its own unit.
* Whole-file content age masks a frozen sub-section: `idpTradeCalc.csv` reads
  hours old whole-file while its pick rows have been frozen for 40 days.  The
  detector already measures pick rows separately; nothing equivalent exists for
  other sub-populations.
* The ROS row floors are a plausibility gate, not a correctness proof.  A
  vendor serving a full-size but wrong board would pass them.
