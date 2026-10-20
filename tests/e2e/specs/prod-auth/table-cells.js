/**
 * Reading a DataTable cell's VISIBLE content in the prod-auth specs.
 *
 * Since #1849 (CQ-30) a DataTable with disclosure rows renders a
 * visually hidden `<button class="ds-table__disclosure" aria-expanded>`
 * as the FIRST child of its first never-hidden column
 * (frontend/components/ds/DataTable.jsx).  It is hidden with
 * clip-path + a 1px box, not `display: none` — it is the row's keyboard
 * stop and must stay in the accessibility tree — so it is still in the
 * DOM, still in `innerText`, and still matched by a substring
 * `getByText`.
 *
 * Two V1 specs read those cells as if they held only the visible
 * content, and both failed on build 9d07b9cebf (V1 run 39380287586):
 *
 *   - v1-111 read `td[data-col="rank"]` with `innerText()` and got
 *     "Source breakdown for <name>1", so `parseInt` was NaN;
 *   - v1-62 matched the top row's player name with
 *     `getByText(name, { exact: false })`, which also matched
 *     "Source breakdown for <name>" — a strict-mode violation.
 *
 * The product was right both times.  These helpers let a spec read the
 * content a sighted user sees, while the disclosure itself is asserted
 * explicitly (its label and `aria-expanded`), never ignored silently.
 *
 * Deliberately dependency-free: `cellTextWithoutDisclosure` runs INSIDE
 * the page via `locator.evaluate` (so it may reference nothing outside
 * its own body), and is unit-tested in jsdom by
 * frontend/__tests__/components/e2e-prod-auth-table-cells.test.jsx against the real
 * DataTable markup.
 */

/** The DataTable disclosure toggle (frontend/components/ds/DataTable.jsx). */
const DISCLOSURE_SELECTOR = ".ds-table__disclosure";

/**
 * A cell's rendered text with any DataTable disclosure toggle removed.
 *
 * Keeps `innerText` semantics (CSS-hidden content excluded, whitespace
 * as rendered) for everything else, so a spec that used to call
 * `innerText()` on the cell reads exactly what it read before #1849.
 * jsdom has no `innerText`; `textContent` is the fallback there.
 *
 * @param {Element} el the cell (or any element) to read
 * @param {string} [selector] the toggle selector; defaults to
 *   DISCLOSURE_SELECTOR's value (repeated literally because this body is
 *   serialized into the page and cannot see module scope)
 * @returns {string} trimmed visible text
 */
function cellTextWithoutDisclosure(el, selector) {
  const sel = selector || ".ds-table__disclosure";
  const read = (node) => {
    let out = "";
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === 3) {
        out += child.textContent;
      } else if (child.nodeType === 1) {
        if (child.matches(sel)) continue;
        if (child.querySelector(sel)) {
          out += read(child);
        } else {
          out +=
            typeof child.innerText === "string"
              ? child.innerText
              : child.textContent;
        }
      }
    }
    return out;
  };
  return read(el).trim();
}

/**
 * Playwright wrapper: the visible text of the (single) cell `locator`
 * resolves to, disclosure toggle excluded.
 *
 * @param {import("@playwright/test").Locator} locator
 * @returns {Promise<string>}
 */
async function readCellText(locator) {
  return locator.evaluate(cellTextWithoutDisclosure, DISCLOSURE_SELECTOR);
}

module.exports = {
  DISCLOSURE_SELECTOR,
  cellTextWithoutDisclosure,
  readCellText,
};
