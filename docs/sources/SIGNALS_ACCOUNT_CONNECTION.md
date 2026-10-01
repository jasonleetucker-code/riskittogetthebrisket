# Signals account connection — passwordless email login (2026-10-01)

**Owner directive 2026-10-01** (intake: `docs/OWNER_REQUESTED_TODO.md`). The owner's Signals
account signs in with an emailed one-time code; there is no password. This record covers the
owner-controlled connection that lets the box collect authenticated Signals surfaces unattended.
Permission is resolved and owner-attested (`SIGNALS_FANTASY_INTEGRATION.md` §1) and is not
reopened here.

| | |
|---|---|
| Owner module | `src/sources/signals_auth.py` (store, lock, renewal, failure classes, notice) |
| Operations CLI | `scripts/signals_connect.py` |
| Box timer | `deploy/systemd/dynasty-signals-auth-renew.{service,timer}.template` (every 6 h) |
| Owner notice | `server.py` signal-alerts sweep → existing ops SMTP channel (`ALERT_TO`) |
| Tests | `tests/sources/test_signals_auth.py` (synthetic tokens, local stub endpoint) |
| Consumers | none yet. A paid-surface collector calls `get_access_token()`; it does not depend on Unit A's `claude/signals-adapter` code, and that code does not depend on this. |

## 1. Rules that do not bend

- The owner types the email address and the code into the **real Signals page**, in a
  **fresh, non-persistent Playwright context** opened by `connect`. The owner's normal browser
  profile is never used.
- Only the Signals Cognito keys for the signed-in user are read, inside the page. Analytics and
  other localStorage entries never reach Python.
- No code path starts a sign-in, requests a code, or sends a login email. A dead credential
  stops collection. It is never retried in a loop.
- Codes, cookies, tokens and session files never go into chat, issues, commits, logs, CI
  artifacts, fixtures or data exports. Secrets move to the box over SSH **stdin**, never argv.
- Status reports expiry times, states and an 8-hex SHA-256 fingerprint. It never reports a
  token value.

## 2. What was observed vs what is unknown

**Observed.** Shipped config of `https://webapp.signalsfantasy.com`, bundle
`assets/index-D9PR2evB.js`, fetched read-only on 2026-10-01 (a handful of GETs). The login page
was also opened headless with nothing typed: it showed one `type=email` field and no password
field, and the only localStorage key was a guest Cognito identity id.

| Fact | Value | Source |
|---|---|---|
| Provider | AWS Cognito via Amplify JS v6 (Gen 2 `amplify_outputs`) | bundle |
| Region / user pool / app client | `us-east-2` / `us-east-2_Zqml90OCW` / `7ud6sc23s8g3td1h5bfho9mua4` | bundle config |
| Identity pool | `us-east-2:1b765dd7-…`; unauthenticated identities enabled | bundle config |
| Sign-in flow | `signIn({authFlowType:"USER_AUTH", preferredChallenge:"EMAIL_OTP"})`, then `confirmSignIn({challengeResponse: code})`. `passwordless.email_otp_enabled: true`, `mfa_configuration: "NONE"` | bundle app code |
| Token storage | `window.localStorage` (Amplify `DefaultStorage`). Keys: `CognitoIdentityServiceProvider.<clientId>.<username>.{accessToken,idToken,refreshToken,clockDrift,deviceKey,deviceGroupKey,randomPasswordKey,signInDetails}` plus `…<clientId>.LastAuthUser`. No cookie storage configured | bundle |
| Refresh call the site uses | `GetTokensFromRefreshToken` with `ClientId`, `RefreshToken`, and `DeviceKey` when present. Adopts `AuthenticationResult.RefreshToken` when returned, else keeps the old one | bundle |
| Device tracking | Client code confirms a device when Cognito returns `NewDeviceMetadata` and sends `DeviceKey` on refresh | bundle |
| Data API | AppSync GraphQL; `default_authorization_type: AMAZON_COGNITO_USER_POOLS` | bundle config |

**Unknown until the owner's real session is observed.** These are not Cognito defaults
assumed to be Signals settings:

| Question | How it becomes known |
|---|---|
| Refresh-token lifetime | Not readable client-side (Cognito refresh tokens are opaque). It is learned only when a renewal is refused as expired. `status` says so and never guesses. |
| Rotation enabled? | On the first real renewal, by whether the response carries a new refresh token. `status.refreshTokenRotationEvidence`: `unobserved` → `rotating` / `not rotating`. Handled either way. |
| Device tracking required? | By whether the captured session holds `deviceKey`. It is captured and sent when present (`status.deviceKeyPresent`). |
| Access/ID token lifetime | Read from each real token's `exp` claim, never assumed (`status.accessTokenExpiresAt`). |
| Which token AppSync expects | Decided by the future collector. `get_access_token(token="accessToken" or "idToken")` serves both. |
| Entitlement of paid surfaces for this account | Decided on the first authenticated data request (`classify_data_response`). |

## 3. How it works

- **Store location.** Resolved as `--store-dir`, then `$RISKIT_SIGNALS_AUTH_DIR`, then a per-OS
  default:
  - Box: `/var/lib/signals-auth`.
  - Windows: `%LOCALAPPDATA%\riskit\signals-auth`.
  - Linux without `/var/lib/signals-auth`: `~/.local/state/riskit/signals-auth`.

  Any path inside this repository, inside any git checkout (including the
  `/var/lib/*-fetch/repo` clones) or inside a web root is **refused** (`StorePathError`). The
  directory is 0700 and the files are 0600, owner-checked on POSIX.
- **Files.**
  - `signals_session.json`: the secret. It matches the repo-wide `*_session.json` ignore.
  - `signals_auth_status.json`: non-secret health and the notice episode.
  - `.signals_auth.lock`.
- **Atomic writes.** Each write goes temp (O_EXCL, 0600) → fsync → `os.replace` → directory
  fsync.
- **One renewal owner.** `renew()` takes an exclusive `flock` (`msvcrt` on Windows) and
  **re-reads the session under the lock**. If another process already renewed, its token is
  used. Concurrent workers can therefore never spend the same refresh token twice, and a
  rotated token can never be overwritten by a stale copy.
- **Renew before expiry.** A token is renewed when within `skew` (default 300 s) of `exp`. An
  expired access token is routine (`status.state = renewal_due`), never a stop. If an early
  renewal fails transiently, the still-valid token keeps being served.
- **Refresh routing.** The refresh token is sent only to
  `https://cognito-idp.<region>.amazonaws.com/`. The region comes from the token's own `iss`
  claim and is validated. Production has no endpoint override; tests pass one as a parameter.

## 4. Failure classes

| Class | Trigger | Behaviour | `acquisition_state` |
|---|---|---|---|
| `reconnect_required` | Cognito `NotAuthorizedException` (revoked / expired / invalid refresh token), `RefreshTokenReuseException`, user gone, a malformed store, or a capture that a new email code would be needed to replace | Collection stops. Later calls short-circuit with **no network call**. One notice episode opens. | `AUTH_REQUIRED` |
| `transient` | Network error, 5xx, `TooManyRequests` / `LimitExceeded` (Retry-After honoured, capped at 30 s) | Up to 3 attempts per renewal, then the error is raised. No episode, no lock-out: the next run tries again. | `UNAVAILABLE` |
| `access_denied` | A data request refused **after** one fresh renewal (`classify_data_response`: a 401/403 means renew-and-retry once, then this) | Stops and notifies. The notice says this is *not* an expired login. | `AUTH_REQUIRED` |
| `refresh_refused` | Other Cognito 4xx (bad parameter, unknown client/pool, WAF `ForbiddenException`) | Stops and notifies with the provider error type | `AUTH_REQUIRED` |

**Notice.** The daily signal-alerts sweep (15:00 UTC) calls `deliver_reconnect_notice`, which
sends **at most one email per episode**. `noticeDeliveredAt` is stamped only after a
successful send, so an unconfigured or failing mailer does not use the episode up (the same
rule as `ops_alerts` F-20). The email carries the class, reason, start time and the exact
commands, and no token. A reconnect or import closes the episode (`lastResolvedEpisode`).
**Last-good Signals data is untouched**: this module never writes the collector's store.

## 5. Operations (PowerShell, from the repo root on the owner's Windows machine)

```powershell
# 0. One-time prerequisites (already present on this machine)
pip install playwright; python -m playwright install chromium

# Optional check: opens the real page headless, reports, stores nothing, types nothing
python scripts/signals_connect.py connect --dry-run --headless

# 1. Connect. A Chromium window opens on the Signals sign-in page.
python scripts/signals_connect.py connect
#    -> In THAT window: type your Signals email, continue, then type the code Signals emails you.
#       Type the code only into the Signals window, never into this terminal or a chat.
#       The script notices the sign-in, captures the session and closes the window
#       (without signing out). It waits up to 10 minutes (--timeout).

# 2. Check it (redacted)
python scripts/signals_connect.py status

# 3. Move it to the box: session over ssh stdin, then the local copy is deleted (not revoked)
python scripts/signals_connect.py provision --host chaseupside              # alias logs in as dynasty
python scripts/signals_connect.py provision --host chaseupside --sudo-user dynasty   # alias logs in as root

# Later
python scripts/signals_connect.py reconnect   # after a reconnect notice; then provision again
python scripts/signals_connect.py disconnect  # delete the local session
python scripts/signals_connect.py disconnect --revoke   # also revoke at Cognito (kills the box copy too)
```

On the box (as `dynasty`, from `/home/dynasty/trade-calculator`):

```bash
/home/dynasty/.venvs/trade-calculator/bin/python scripts/signals_connect.py status
/home/dynasty/.venvs/trade-calculator/bin/python scripts/signals_connect.py renew --force   # one deliberate attempt
systemctl list-timers 'dynasty-signals-auth-renew*'; journalctl -u dynasty-signals-auth-renew -n 50
```

- **Store creation.** `provision` creates `/var/lib/signals-auth` (0700, owned by the
  importing user) via `sudo -n install` when it is missing. If that sudo rule is absent, create
  it once as root: `install -d -m 0700 -o dynasty -g dynasty /var/lib/signals-auth`.
- **Why provisioning deletes the local copy.** With rotation enabled, two holders of one
  refresh token race. Whichever renews first invalidates the other, and the loser would report
  a false `reconnect_required`. The box is the single renewal owner. Use `--keep-local` only
  for debugging.
- **`status` reports two separate things:**
  - `authentication`: the auth health above.
  - `sourceDataFreshness`: read verbatim from the collector's own
    `data/sources/signals/<board>/dataset_state.json` (`health`, `healthSince`,
    `upstreamPublishedAt`). It is never recomputed, and it reads `not_collected` when that
    store does not exist.
- **Exit codes:**

  | Command | Exit 0 | Exit 1 | Exit 2 |
  |---|---|---|---|
  | `renew` | renewed, not due, or not connected | transient | stopped |
  | `connect` | session stored | an existing session is present; use `reconnect` | timeout, window closed, or capture rejected |

## 6. What is proven and what is not

**Proven by tests** (`tests/sources/test_signals_auth.py`; 37 pass, 1 POSIX-permission test
skipped on Windows; Linux CI is authoritative):
- store refusal inside the repo, any git checkout and web roots; per-OS default outside the
  checkout; env override validated;
- 0600 files / 0700 dir (POSIX);
- the session read back by a new store instance (restart);
- `deploy.sh` removes only its frontend staging/old build dirs under `APP_DIR`, has no
  `git clean`, and never names the store;
- capture validation (missing refresh token, foreign issuer, client mismatch, ID token posing as
  access);
- redaction of `status`, the status file, CLI output and the notice;
- renewal with rotation and without it; no network when not due; renewal inside the skew
  window; `DeviceKey` forwarded;
- revoked and expired → `reconnect_required` with no retry and one episode; transient bounded
  at 3 with no episode and recovery afterwards; throttle then success; early-renewal transient
  keeps the valid token; WAF → `refresh_refused`;
- one notice per episode, not used up when the mailer is unconfigured or failing;
- **6 concurrent processes → exactly one Cognito call; 5 concurrent forced renewals under
  strict rotation → all succeed and the final stored token is the live one.** With the lock
  disabled the same test fails (`refresh_token_invalid`), so it does detect lost rotations;
- `provision` puts the secret only on stdin, never in argv;
- `import-session` reads stdin; the CLI refuses an in-repo store.

**Not proven here; needs the owner's real sign-in:**
- that the real capture contains a refresh token (and whether it holds a `deviceKey`);
- the first real renewal against Cognito, and with it the rotation evidence;
- the real token lifetimes;
- survival on the box across an actual service restart and deploy (the path is outside
  `APP_DIR`, so by construction it survives — still to be observed);
- the timer running there;
- delivery of a real notice.

One successful renewal is **not** evidence of indefinite access: the refresh token's lifetime
stays unknown until it ends.

## 7. Limitation on unattended access

**A renewal that cannot be saved.** If Cognito answers but the new tokens cannot
be written (disk full, process killed between the response and the save), a
ROTATED refresh token is lost and the next renewal fails as reused. No code can
fully prevent that window. A failed save is recorded as `persist_failed`, so the
reconnect notice names the real cause instead of looking like a revocation.

- **How long it lasts.** Unattended access lasts as long as the Signals app client's
  refresh-token validity, which is configured by Signals and not observable here. Cognito
  allows 1 hour to 10 years, and its default is 30 days.
- **Rotation does not extend it.** Regular renewal keeps access tokens current and detects
  revocation within about 6 hours. It does not stretch a fixed refresh-token lifetime. Whether
  Signals' rotation settings re-issue tokens with a fresh lifetime is unknown.
- **When it ends, the owner reconnects.** That is one email code, typed by the owner, and
  this system notifies once.
- **What would remove the limit.** Only a provider-issued integration credential: a Signals
  API key, an OAuth client-credentials grant, or a long-lived personal access token scoped
  read-only to the owner's account. Signals publishes none (`SIGNALS_FANTASY_INTEGRATION.md`
  §3: "Public API — none described"). Obtaining one is a provider request for the owner.
- **No workaround.** Nothing here attempts to get around this: no automated code retrieval and
  no inbox access.

## 8. Engineering applicability (brief)

| Mechanism | Disposition |
|---|---|
| Replay fixtures / provenance | **APPLY_NOW** — synthetic tokens, local stub endpoint |
| Property / concurrency tests | **APPLY_NOW** — multi-process rotation test with a negative control |
| Persistence / deployment identity | **APPLY_NOW** — atomic 0600 writes, store outside the checkout pinned by test |
| Observability | **ALREADY_COVERED** — the existing ops SMTP channel and journald |
| Typed API contracts | **NOT_RELEVANT** — no API surface added |
| Secret manager | **DEFERRED_BY_AUTHORITY** — a file store per the owner directive; a vault is a separate decision |
