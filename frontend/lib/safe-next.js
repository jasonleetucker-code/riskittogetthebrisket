// Client-side mirror of server.py::_sanitize_next_path — PARSE AND COMPARE.
// Defense in depth for the post-login redirect: the backend always returns a
// sanitized `redirect`, but if it ever omitted it, `?next=` must not become an
// open redirect.  Returns a same-origin path (+query/hash) or `fallback`.
const BASE = "https://x.invalid";

export function sanitizeNextPath(raw, fallback = "/") {
  const value = String(raw ?? "").trim();
  if (!value) return fallback;
  // Refuse (not repair): control chars incl. TAB/CR/LF, and backslashes.
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f\\]/.test(value)) return fallback;
  if (!value.startsWith("/") || value.startsWith("//")) return fallback;
  try {
    const u = new URL(value, BASE);
    if (u.origin !== BASE) return fallback;
    const out = `${u.pathname}${u.search}${u.hash}`;
    // Re-check the SERIALIZED result, not just the input: URL normalization
    // collapses dot segments, so "/..//evil.com" (which passes every guard
    // above) serializes to "//evil.com" -- a protocol-relative, cross-origin
    // reference once handed to the router.  Judge what we emit.
    if (!out.startsWith("/") || out.startsWith("//") || out.startsWith("/\\")) return fallback;
    return out;
  } catch {
    return fallback;
  }
}
