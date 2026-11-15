/**
 * Adding an asset on /trade, on either layout (TC-D2).
 *
 * Desktop and tablet: the inline per-side search.  Phones (< 768 px): an
 * "Add to Side X" button that opens one bottom-sheet search per side.  Both
 * expose the same labelled input ("Search to add a player to Side X") and the
 * same result rows, so a spec drives either through these two calls:
 *
 *   const input = await openTradeSearch(page, "A");
 *   ...fill + click a result...
 *   await closeTradeSheet(page);   // no-op on the inline layout
 */
const { expect } = require("@playwright/test");

async function openTradeSearch(page, sideLabel) {
  const inline = page.locator(`input[aria-label="Search to add a player to Side ${sideLabel}"]`);
  const addButton = page.getByRole("button", { name: `Add to Side ${sideLabel}`, exact: true });
  await expect(inline.or(addButton).first()).toBeVisible({ timeout: 60_000 });
  if (await addButton.isVisible().catch(() => false)) {
    await addButton.click();
    await expect(page.getByRole("dialog", { name: `Add to Side ${sideLabel}` })).toBeVisible({
      timeout: 30_000,
    });
  }
  const input = page.getByLabel(`Search to add a player to Side ${sideLabel}`);
  await input.click();
  return input;
}

async function closeTradeSheet(page) {
  const done = page.getByRole("dialog").getByRole("button", { name: "Done" });
  if (await done.isVisible().catch(() => false)) {
    await done.click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  }
}

module.exports = { openTradeSearch, closeTradeSheet };
