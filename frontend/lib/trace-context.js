/** Mint a W3C traceparent for a browser request when cryptographic randomness exists. */
export function newTraceparent() {
  if (!globalThis.crypto?.getRandomValues) return null;
  const bytes = new Uint8Array(24);
  globalThis.crypto.getRandomValues(bytes);
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  const traceId = hex.slice(0, 32);
  const spanId = hex.slice(32);
  if (/^0+$/.test(traceId) || /^0+$/.test(spanId)) return null;
  return `00-${traceId}-${spanId}-01`;
}
