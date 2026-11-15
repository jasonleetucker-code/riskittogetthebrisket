/**
 * Same-origin check for the Next dev/E2E bridge routes (/api/<x>/[...path]).
 *
 * A bridge forwards a browser POST to FastAPI and presents the BACKEND origin,
 * so the backend's own CSRF check can no longer see the browser's origin — the
 * bridge must make that check itself, once, here.
 *
 * Compare the Origin header with the host the BROWSER addressed (the Host
 * header), never with `new URL(request.url).origin`: under `next start`,
 * request.url can carry Next's own bind host (`localhost`) while the browser
 * is on `127.0.0.1`, which refused every same-origin POST.  A cross-site page
 * cannot forge a browser's Origin, so the comparison still refuses it.
 */

/** The origin the browser used to reach this Next server. */
export function browserOrigin(request) {
  const incoming = new URL(request.url);
  const host = request.headers.get("x-forwarded-host") || request.headers.get("host");
  return host ? `${incoming.protocol}//${host}` : incoming.origin;
}

/** True only when the request carries an Origin equal to the browser's own. */
export function isSameOriginRequest(request) {
  const origin = request.headers.get("origin");
  return Boolean(origin) && origin === browserOrigin(request);
}
