# Request trace correlation pilot

`src/utils/request_context.py` owns request and trace context. The existing
FastAPI middleware accepts a well-formed W3C `traceparent`, keeps its trace ID,
creates a server span ID, and returns `X-Request-Id`, `X-Trace-Id` and a response
`traceparent`. Invalid or absent context starts a new trace.

The first instrumented journey is browser `useLeague.js` → production nginx
or the Next `/api/leagues` bridge → FastAPI `/api/leagues`. The browser mints
trace context with `crypto.getRandomValues`; the Next bridge passes it through
without forwarding any extra credentials. Production nginx already forwards
ordinary request headers to the backend. FastAPI writes one structured
`http.server.request` event to its current log stream for this route. The
event contains IDs, method, route template, status, duration, failure class,
process commit and verified frontend artifact ID. Unavailable identity stays
null. It contains no cookies, auth tokens, raw URL/query, username, league
contents or request/response body. Export failure is fail-open.

This is a bounded pilot, not a collector or second telemetry store. No other
route or background pipeline is claimed to have spans yet. To investigate a
request, read its `X-Trace-Id` response header and search the backend logs for
that exact `trace_id`; `request_id` links to existing error/audit logging.
The log volume is one event per `/api/leagues` request, including failures.
