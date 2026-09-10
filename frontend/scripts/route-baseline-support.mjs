export function percentile(values, p) {
  const xs = values.filter(Number.isFinite).sort((a, b) => a - b);
  return xs.length ? xs[Math.max(0, Math.ceil((p / 100) * xs.length) - 1)] : null;
}

export function summarise(samples) {
  const keys = ["ttfbMs", "fcpMs", "usefulMs", "lcpMs", "inpMs", "cls", "longTaskMs", "longTaskCount", "interactionMs", "domContentLoadedMs", "loadMs", "encodedBytes", "decodedBytes", "transferBytes", "requestCount", "domNodes"];
  const out = {};
  for (const k of keys) {
    const values = samples.map((s) => s?.[k]).filter(Number.isFinite);
    out[k] = { p50: percentile(values, 50), p95: percentile(values, 95), n: values.length };
  }
  out.usefulMissing = samples.filter((s) => s?.usefulMs == null).length;
  out.errors = samples.filter((s) => s?.error).length;
  out.interactionErrors = samples.filter((s) => s?.interactionError).length;
  return out;
}

/** Runs in the browser, and in jsdom tests. Skeletons, spacers and staged
 * React streaming copies must not count as a useful page.
 */
export function hasUsefulElement(selector) {
  return [...document.querySelectorAll(selector)].some((element) => {
    if (element.closest('[hidden], [aria-hidden="true"], [aria-busy="true"]')) return false;
    if (element.matches('[class*="skeleton"], [class*="loading"]')) return false;
    if (element.querySelector('[class*="skeleton"], [role="progressbar"]')) return false;
    const style = getComputedStyle(element);
    if (style.visibility === "hidden" || style.display === "none" || style.opacity === "0") return false;
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) return false;
    return Boolean(element.textContent?.trim()) || element.matches("input,select,button");
  });
}

export function validateRunOptions(args, knownRoutes) {
  if (!Number.isInteger(args.runs) || args.runs < 1) throw new Error("--runs must be a positive integer");
  if (!["desktop", "mobile", "both"].includes(args.viewport)) throw new Error("--viewport must be desktop, mobile or both");
  if (!Number.isFinite(args.cpu) || args.cpu < 1) throw new Error("--cpu must be at least 1");
  if (!["none", "4g"].includes(args.network)) throw new Error("--network must be none or 4g");
  if (!Number.isFinite(args.timeout) || args.timeout <= 0) throw new Error("--timeout must be positive");
  if (args.routes?.some((r) => !knownRoutes.includes(r))) throw new Error("--routes contains an unknown route template");
}
