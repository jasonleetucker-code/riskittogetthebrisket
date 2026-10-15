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
| decode | `image_input.py` | PNG/JPEG/WEBP magic-byte allowlist; ≤ 3 MB; ≤ 12 MP (Pillow bomb guard at the same bound); EXIF orientation applied; grayscale; dark mode (mean luminance < 110) inverted; < 1000 px wide upscaled 2x; longest side capped at 4096 px; re-encoded as PNG (all metadata dropped) |
| OCR | `ocr.py` | the **local `tesseract` binary** (`--psm 11`, `-l eng`, TSV on stdout, PNG on stdin — no temp files); one gateway `run_ocr`; ≤ 2 concurrent reads (non-blocking — a third gets `ocr_busy`); 12 s timeout; `OMP_THREAD_LIMIT=1` |
| layout | `layout.py` | words → rows → column segments; sides from side-label anchors ("You give / You get", "Send / Receive", "Team A / Team B", …), else strict two-column geometry, else **unassigned**; noise and equalizer regions go to `ignored` with a reason |
| parse | `parse.py` | pick labels normalised (narrow OCR repair inside pick tokens only) and parsed by the canonical pick owner `src/identity/picks.py`; player position/team hints read off the line |
| resolve | `resolve.py` | players through `resolve_canonical_v2` (refuses rather than guesses) joined to the board by Sleeper id; picks to the board row of their canonical grade |
| contract | `service.py` | `validate_extraction` checks the exact response shape before it leaves the server |

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

It scores **extraction** (asset strings read on the right side: recall /
precision) separately from **resolution** (extracted strings mapped to the
right board row) over `tests/fixtures/screenshot_import/` (synthetic
screenshots; regenerate with `python -m tests.trade.screenshot_import.synthetic`).
Real-binary tests: `pytest -m tesseract tests/trade/screenshot_import`
(skipped where tesseract is not installed).

## Known limitations

* **Sides need evidence.** Tesseract reads words, not layout. Without side
  labels ("You give / You get", "Team A / Team B", …) and without two clean,
  vertically overlapping columns, the pipeline cannot tell which side an
  asset was on, so items land in the **unassigned** tray for the user to
  place (`low_layout_confidence`). This is deliberate: a guessed side is a
  wrong trade.
* Stylised fonts, very small text, low-contrast themes, heavy compression and
  logos/avatars overlapping names reduce OCR quality. Surname typos are
  refused by the canonical resolver and surface as `unresolved` with
  suggestions, never as a silent match.
* Only English (`-l eng`) is installed/used.
* The fixture numbers describe the synthetic fixture set. **There is no
  universal accuracy claim** for arbitrary screenshots.
