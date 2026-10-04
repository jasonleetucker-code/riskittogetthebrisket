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

`scripts/generate_leagues_contract.py` reads the live OpenAPI response schema
and writes `frontend/lib/generated/leagues-contract.js`. The generated file
contains JSDoc types and a small runtime parser. `useLeague.js` calls that
parser before caching a response. PR validation and production deployment
both run the generator in check mode, so a changed schema with stale frontend
output blocks integration. Regenerate with:

```sh
python -m scripts.generate_leagues_contract
python -m scripts.generate_leagues_contract --check
```

For the next critical endpoint: locate its live producer and frontend
consumer, define a closed response model in `src/api/schemas/`, validate
privacy variants explicitly, declare `response_model`, then add live-route,
OpenAPI and consumer parity tests. Preserve missing-versus-null semantics.
The generator covers this endpoint only. Other endpoints stay outside the
ratchet until each acquires an authoritative schema and an actual consumer.
