# Progressive API response contracts

`GET /api/leagues` is the first typed response boundary. Its authoritative
models are in `src/api/schemas/leagues.py`; the route in `server.py` declares
the response model and validates the appropriate view before returning it.
FastAPI publishes the two variants in OpenAPI. The existing JSON field names,
anonymous/authenticated distinction, and `Cache-Control: no-store` remain.

The anonymous model has no user-default fields. The authenticated model can
carry the current user's default key and team. Both forbid undeclared fields,
so an accidental raw Sleeper ID or username map fails validation rather than
being serialized. `rosterSettings` remains an operator-defined JSON object;
its contents are intentionally not frozen by this pilot.

For the next critical endpoint: locate its live producer and frontend
consumer, define a closed response model in `src/api/schemas/`, validate
privacy variants explicitly, declare `response_model`, then add live-route,
OpenAPI and consumer parity tests. Preserve missing-versus-null semantics.
Generated frontend types and a stale-output CI check are the next dependent
unit; their absence does not count as frontend parity in this pilot.
