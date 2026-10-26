# Import Trade from Screenshot — operations runbook (C3-IMPORT-IMAGE)

## What it does

`POST /api/trade/import-screenshot` takes ONE screenshot of a trade (from any
trade calculator, league app or chat) and returns the **asset identities and
the side each was on**. It never reads values from the image: the calculator
prices every imported asset from the canonical board, exactly as if the user
had typed the names.

Pipeline (`src/trade/screenshot_import/`):

| stage | module | what it guarantees |
|---|---|---|
| decode | `image_input.py` | PNG/JPEG/WEBP magic-byte allowlist; ≤ 3 MB; ≤ 12 MP (Pillow bomb guard at the same bound); EXIF orientation applied; grayscale; dark mode (mean luminance < 110) inverted; < 1000 px wide upscaled 2x, else a long edge under 2400 px upscaled to 2400 (at most 2x — the browser sends a full-page desktop screenshot at 1600 px, where body text is too small to read reliably); longest side capped at 4096 px; **local polarity normalisation** (dark header bars, sidebars, buttons and browser chrome on a light page rewritten dark-on-white, so their text is read at all); re-encoded as PNG (all metadata dropped) |
| OCR | `ocr.py` | the **local `tesseract` binary** (`--psm 11`, `-l eng`, TSV on stdout, PNG on stdin — no temp files); one gateway `run_ocr`; ≤ 2 concurrent reads (non-blocking — a third gets `ocr_busy`); 12 s timeout; `OMP_THREAD_LIMIT=1` |
| layout | `layout.py` | words → rows → column segments; sides from side-label anchors ("You give / You get", "Send / Receive", "Team A / Team B", "Team 1 gets… / Team 2 gets…", …), which also define the **trade region** (one container per side); else strict two-column geometry, else **unassigned**; text outside the region, noise and equalizer regions go to `ignored` with a reason |
| parse | `parse.py` | pick labels normalised (narrow OCR repair inside pick tokens only) and parsed by the canonical pick owner `src/identity/picks.py`; player position/team hints read off the line |
| resolve | `resolve.py` | players through `resolve_canonical_v2` (refuses rather than guesses) joined to the board by Sleeper id; picks to the board row of their canonical grade |
| contract | `service.py` | `validate_extraction` checks the exact response shape before it leaves the server |

## Uncropped (full-page) screenshots

Users upload ordinary screenshots — the whole browser window or phone
screen, not a crop.  Those carry browser chrome, site navigation, insight /
recommendation widgets ("biggest riser: <player>") and ads around the trade.
Two mechanisms make that work (measured on a real full-browser KeepTradeCut
screenshot, where the base pipeline found 0 side labels, assigned nothing to
either side and put ~30 strings from the whole page in "Needs a side"):

1. **Light-on-dark text is read.**  Side labels are often white text in a
   dark bar on a light page.  The whole-image dark-mode inversion cannot fire
   (the page is light), and Tesseract's global binarisation turns the bar
   into one blob with the letters as holes, so no text line is found there.
   `image_input.normalize_local_polarity` finds dark PATCHES (area, not glyph
   interiors), rewrites each as dark-on-white and paints its edge white so no
   frame sits against the text.  The light page is left byte-identical.
2. **A pair of side labels defines the trade region.**  Side by side: one
   column per label, centred on the label and split half-way between the two
   label centres (tightened to the label's left edge when the list under it is
   left-aligned, which keeps a navigation sidebar out).  Stacked: one
   full-width column, side A ending where side B's label starts.  Each side's
   container ends at the first totals row / verdict / action button
   ("1 Total Pieces", "Fair Trade", "Copy Trade URL", …) or at a vertical gap
   of 8 line heights.  All of it is in multiples of the page's median line
   height — no pixel coordinate belongs to any one screenshot.  Lines outside
   every container are `ignored` as `outside_trade_region`; search
   placeholders as `search_placeholder`; row metadata ("QB11 · NYG · 23.4
   y.o.") is merged as a position/team **hint** for identity resolution.

**Safe fallback.**  With ONE side label, only lines left-aligned under it
take its side; nothing else is pulled onto it and no second side is inferred
from position (a full page always has some other column — a sidebar, a
widget — that would pass for one).  The one exception is text BELOW the
trade's end — its verdict or action buttons ("Fair Trade", "Copy Trade URL",
"Accept", never a totals row, since one side's list can continue below the
other's totals): that is the page under the trade (a "trending" widget, an
ad) and is `ignored` as `outside_trade_region` even with one label.  With NO side labels, nothing is placed on
a side (warning `trade_region_not_detected`), and an unassigned name-shaped
string the canonical resolver has no match, candidate or near-name for is
`ignored` as `unrecognized_text` rather than offered as "needs a side".
Anything with a candidate or suggestion stays for the person to decide;
nothing is guessed either way.

## Several screenshots of one trade

A trade often spans two phone screenshots.  Each is read on its own; the
dialog merges them (`frontend/lib/screenshot-import.js::mergeImages`):

* **Sides follow the side labels.**  Every anchored side carries
  `anchorFamily` (the label vocabulary, e.g. `"team 1/team 2"`) and
  `anchorSlot` (0 = first side, 1 = second), published by the server
  (`layout.py` decides them; the client never parses label text).  A
  follow-up shot showing only "Team 2 gets..." is added to Team 2's side, a
  shot listing its sides in the other order is matched by label, and a lone
  second-side label in the first shot goes to Side B.  Each screenshot's
  placement is recorded in `alignmentNotes`; a placement that moved assets
  off their position is explained in the review.
* **Fallback is positional, and said out loud.**  A screenshot with no side
  labels among labelled ones is placed by position with warning
  `side_alignment_unverified`; one whose labels contradict the others
  (another vocabulary, a side already taken, two sides onto one) with
  `side_alignment_conflict`.  Never a guess presented as a label match.
* **Overlap.**  Only an exact same-order run of >= 2 resolved assets at the
  seam of two consecutive screenshots, on the same merged side, is kept once
  (recorded with an undo).  A 1-asset match is flagged `possibleOverlap` and
  never merged — repeats are legal (#1619).
* Once both merged sides hold assets, the per-screenshot `missing_side`
  warnings are dropped (they described one screenshot, not the trade).

Item statuses: `resolved` (one board row), `needs_confirmation` (several
on-board candidates — the user picks; never auto-selected), `unresolved`
(with a `reason` such as `no_match`, `not_on_board`, `retired_pick_class`,
`pick_year_missing`, `identity_directory_unavailable`, `board_unavailable`;
`suggestions` may list near-names — never auto-selected). A pick label that
names an owner without parentheses ("2027 Team A 1st") resolves at the
GENERIC grade with warning `pick_owner_not_established`.

## Enabling it on the VPS

The OCR engine is a **system package**, not a Python dependency. The deploy
pipeline cannot install it (the deploy user's sudo allowlist does not include
`apt-get`), so an operator runs, once:

```bash
sudo apt-get update && sudo apt-get install -y tesseract-ocr
tesseract --version          # expect 5.x
sudo systemctl restart dynasty
```

`Pillow` (image decoding) ships through `requirements.txt` /
`requirements.lock.txt` with the normal deploy.

Until the package is installed the feature is **explicitly unavailable**, not
broken: the status endpoint reports `available: false, reason:
"tesseract_not_installed"`, the upload route answers 503 `ocr_unavailable`
("Screenshot reading is not set up on this server yet (install the
tesseract-ocr package)."), and the backend logs one warning at startup.

## Flag and rollback

Flag `trade_screenshot_import` (LIVE, default ON). Rollback:

```bash
RISKIT_FEATURE_TRADE_SCREENSHOT_IMPORT=0   # in the service environment
sudo systemctl restart dynasty              # flag reads are cached per process
```

Off → the upload route answers 404 `feature_disabled`; the status endpoint
reports `enabled: false`.

## Endpoints

* `GET /api/trade/import-screenshot/status` (signed-in) →
  `{"available", "reason", "engine": "tesseract", "version", "enabled"}`.
  Production proof: `tests/e2e/specs/prod-auth/screenshot-import-status.spec.js`
  (available, or a NAMED reason code; exactly these keys, no numbers,
  `no-store`; read-only, never uploads).
* `POST /api/trade/import-screenshot` (signed-in, not guest passes) — body
  `{"image": "<base64, optional data: URL prefix>", "index": 0..3}`. The
  response schema is documented and enforced in
  `src/trade/screenshot_import/service.py`.

Error codes: 400 `invalid_json` / `missing_image` / `invalid_index` /
`invalid_image_encoding` / `malformed_image` / `empty_image`; 403
`guest_read_only`; 404 `feature_disabled`; 413 `image_too_large`; 415
`unsupported_image_type`; 429 `rate_limited` (+ `Retry-After`); 503
`ocr_unavailable` / `ocr_busy` (+ `Retry-After: 5`); 504 `ocr_timeout`.

## Limits

| limit | value | where |
|---|---|---|
| request body | 4.3 MB for this route only (global cap stays 2 MB) | `server.py::_REQUEST_BYTES_BY_PATH`; nginx allows 10 MB |
| decoded image | 3 MB, 12 megapixels | `image_input.py` |
| per-user rate | 20 images / 10 minutes (token bucket) | `server.py::_SCREENSHOT_RATE_*`, `rate_limit.should_rate_limit_key` |
| concurrency | 2 OCR reads per process (non-blocking) | `ocr.MAX_CONCURRENT` |
| OCR timeout | 12 s | `ocr.DEFAULT_TIMEOUT_S` |

## Privacy

* The image is held in memory for the request only. It is never written to
  disk (tesseract reads stdin, writes stdout), never persisted, never logged.
* The OCR text is never logged. Log lines carry exception TYPE names only.
* Text read from an image is data: it is only compared against the board as a
  candidate asset string — never executed, evaluated or followed (an image
  saying "ignore previous instructions…" is just an ignored line).

## Metrics

`GET /api/metrics` → `screenshot_import`: route counts (`requests`, `ok`,
`rejected_image`, `rate_limited`, `unavailable`) and OCR gateway counts
(`requests`, `ok`, `unavailable`, `timeout`, `busy`, `error`). Counts only.

## Measuring accuracy

```bash
python scripts/screenshot_import_eval.py          # table
python scripts/screenshot_import_eval.py --json   # full report
```

It scores four things separately over `tests/fixtures/screenshot_import/`:
**trade region** (expected side assets inside a side container: recall /
precision, plus `distractorLeaks` — page players that became an item
anywhere), **extraction / OCR** (expected strings read at all), **side**
(extracted assets on the right side) and **identity** (extracted assets
mapped to the right board row).  The fixtures are synthetic screenshots
(regenerate with `python -m tests.trade.screenshot_import.synthetic
[scenario ...]` — name scenarios to avoid re-encoding the others' PNGs),
including phone screenshots at a 390-point viewport captured at 3x
(`mobile390_light_picks_idp`, `mobile390_dark_picks_idp`, with picks and IDP
players, and the owner trade as a two-shot pair `mobile390_multishot_1/2`,
whose real-tesseract payloads are committed as `extraction.json` and replayed
by the frontend merge tests — re-record with `--record-extractions`), plus
one REAL full-browser screenshot (`ktc_fullpage_browser`, a redacted
derivative: tab strip, bookmark bar and profile avatar blanked with solid
fill — never commit an unredacted original) and its crop (`ktc_cropped`).
Real-binary tests: `pytest -m tesseract tests/trade/screenshot_import`
(skipped where tesseract is not installed).

## Known limitations

* **Sides need evidence.** Tesseract reads words, not layout. Without side
  labels ("You give / You get", "Team A / Team B", …) and without two clean,
  vertically overlapping columns, the pipeline cannot tell which side an
  asset was on, so items land in the **unassigned** tray for the user to
  place (`trade_region_not_detected`, `low_layout_confidence`). This is
  deliberate: a guessed side is a wrong trade.
* **Trade-region assumptions.** Side-by-side containers assume the two
  columns are about equally wide and each list starts at (or left of) its
  label's centre; a calculator that right-aligns one side's names, or puts an
  unrelated name list directly under a side label before any totals row,
  would need its own rule.  A widget directly BELOW a side with no totals /
  verdict / button row and less than 8 line heights of gap would be read as
  part of that side.
* Stylised fonts, very small text, low-contrast themes, heavy compression and
  logos/avatars overlapping names reduce OCR quality. Surname typos are
  refused by the canonical resolver and surface as `unresolved` with
  suggestions, never as a silent match.
* Only English (`-l eng`) is installed/used.
* The fixture numbers describe the synthetic fixture set. **There is no
  universal accuracy claim** for arbitrary screenshots.
