/**
 * csv-cell.js — the ONE client-side owner of CSV cell safety.
 *
 * WHY IT EXISTS
 * ─────────────
 * Every server CSV export already neutralizes spreadsheet formulas through
 * `src/public_league/csv_export.py::neutralize_csv_text` (and `_cell`).  The
 * four client-side exports (/rankings, the /trade workspace, the /draft
 * review, the IDPTC rookie board) only quoted on `"` / `,` / newlines, so a
 * Sleeper team or manager name such as `=HYPERLINK("…")` reached the user's
 * spreadsheet as a live formula (CSV / formula injection, CWE-1236).
 *
 * THE RULE (a byte-for-byte mirror of the Python owner)
 * ─────────────────────────────────────────────────────
 * TEXT is prefixed with `'` when a spreadsheet would execute it:
 *   - it starts with a tab or carriage return (Excel strips those and then
 *     evaluates what follows), or
 *   - its first character after any leading whitespace / control characters
 *     (` \t\r\n\v\f\0`, U+FEFF, U+00A0 — the Python `_LEADING_SKIP`) is one
 *     of `= + - @`.
 * The decision is made by TYPE before the text rule runs: a real number is
 * written as a number and never neutralized, so `-3.5` stays a number a
 * spreadsheet can sum.  `tests/fixtures/csv_formula_cases.json` is read by
 * both this module's vitest and `tests/api/test_task13_security_hardening.py`
 * so the two implementations cannot drift apart silently.
 *
 * One deliberate JS-only rule: a non-finite number (NaN, ±Infinity) is
 * written as an EMPTY cell.  In JavaScript it is how a missing value usually
 * surfaces after `Number(undefined)` / `Math.round(NaN)`; printing "NaN"
 * would publish an artifact and printing 0 would turn a missing value into
 * a real one (MISSING IS NEVER ZERO).  The Python owner never receives one —
 * its inputs are parsed JSON, which cannot carry them.
 *
 * Every client CSV builder goes through `csvField` / `csvLine`;
 * `frontend/__tests__/csv-cell.test.js` fails a new `text/csv` download
 * that does not.
 */

const FORMULA_TRIGGERS = new Set(["=", "+", "-", "@"]);
// Mirrors src/public_league/csv_export.py::_LEADING_SKIP exactly.
const LEADING_SKIP = new Set([" ", "\t", "\r", "\n", "\x0b", "\x0c", "\x00", "﻿", " "]);

/**
 * Prefix `'` to TEXT a spreadsheet would execute as a formula.
 * Non-string input is returned unchanged — decide by type before calling.
 */
export function neutralizeCsvText(text) {
  if (typeof text !== "string" || !text) return text;
  if (text[0] === "\t" || text[0] === "\r") return "'" + text;
  let i = 0;
  while (i < text.length && LEADING_SKIP.has(text[i])) i += 1;
  if (i < text.length && FORMULA_TRIGGERS.has(text[i])) return "'" + text;
  return text;
}

function isRealNumber(value) {
  return typeof value === "number" || typeof value === "bigint";
}

function numberText(value) {
  if (typeof value === "bigint") return String(value);
  return Number.isFinite(value) ? String(value) : "";
}

/** Mirrors csv_export._flatten: lists pipe-joined, objects as `k=v; k=v`. */
function flatten(value) {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (isRealNumber(value)) return numberText(value);
  if (Array.isArray(value)) return value.map(flatten).join(" | ");
  if (typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype) {
    return Object.entries(value)
      .map(([k, v]) => `${k}=${flatten(v)}`)
      .join("; ");
  }
  return String(value);
}

/**
 * One CSV cell's TEXT — the mirror of `csv_export._cell`.
 *
 * A genuine number (not a boolean) is written as a number, unchanged; every
 * other value is flattened to text and formula-neutralized as a whole.
 * `null` / `undefined` become an empty cell.  No CSV quoting is applied —
 * that is `csvField`'s job, exactly as Python's `csv` module quotes what
 * `_cell` returns.
 */
export function csvCell(value) {
  if (isRealNumber(value)) return numberText(value);
  return neutralizeCsvText(flatten(value));
}

const NEEDS_QUOTES = /[",\r\n]/;

/** `csvCell` plus RFC 4180 quoting — what a builder writes between commas. */
export function csvField(value) {
  const text = csvCell(value);
  return NEEDS_QUOTES.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** One CSV line: every cell through `csvField`, comma-joined. */
export function csvLine(cells) {
  return (cells || []).map(csvField).join(",");
}
