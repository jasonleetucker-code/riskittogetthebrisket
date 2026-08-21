# PSI post-deploy verification — production, 2026-08-20

**PSI is live on `chaseupside.com`.** Verified by rendering production in a real
browser, not inferred from a green deploy.

**Not fully verified, and named rather than inferred:** the two *migrated*
surfaces — the `/rankings` body and the Player File — are private, and this
environment has no production credentials. That is precisely the gap `V1-111`
still carries for **L4**.

## 1. What was rendered, and how

Production HTML/CSS/JS, executed in Chromium at 1366×768 and 390×844.

Chromium in this sandbox cannot reach the public internet — every navigation to
`https://chaseupside.com` returns `ERR_CONNECTION_RESET`, with the agent proxy's
relay log showing only Chrome's own `clients2.google.com` telemetry and none of
our navigations. `curl` tunnels fine through the same proxy (`CONNECT
chaseupside.com:443` → `200 Connection Established`), so the block is specific to
the browser, not to egress.

So a minimal loopback mirror (`http.server` + `requests`, which honours
`HTTPS_PROXY`) re-serves production's bytes on `127.0.0.1:8099`, and Chromium
renders that. **The bytes are production's and the execution is real**; the only
difference is the origin the browser sees. Stated because it bounds the claim: it
proves what production serves and how it renders, and it would not catch an
origin-dependent defect (a cookie `Domain`, a CSP `host-source`, an absolute
redirect). Recorded so the method can be disputed rather than assumed.

## 2. Result — the shell is live everywhere

Six renders (2 viewports × `/login`, `/league`, anonymous `/rankings`), all
identical on the shell:

| probe | value |
|---|---|
| `header` class | `shell-topbar psi-editorial` |
| `.psi-editorial` nodes | 3 |
| console errors | **0** |
| page errors | **0** |

The editorial cream header with the `CU` monogram block renders on every route, on
both viewports.

## 3. The dark page bodies are correct, and this is the part that looks wrong

`getComputedStyle(document.body).backgroundColor` is `rgb(11, 13, 16)` — `#0b0d10`,
the terminal palette — and the body font is `jetbrainsMono`, not the editorial
serif stack.

**That is the design, not a failed deploy.** The migration is route-by-route: only
`/rankings` and the Player File were migrated in #984, so every other page body
stays on the terminal palette beneath the now-editorial shared shell until its own
route migrates. It is the north star's own migration method, and the lane declared
it as a deliberate temporary split.

Worth stating plainly because the first thing anyone sees on production is a
**dark login page with a cream header**, which reads like a half-finished deploy
and is not one.

## 4. Auth gate intact

Anonymous `GET /rankings` → **307** → `/login?next=%2Frankings`, on both
viewports. The Next middleware gate survives the shell restyle — worth checking
explicitly, since `middleware.js` + `lib/public-routes.js` are the only page auth
gate in the system and the shell change touched the components around it.

## 5. Board did not move

`/api/status` on production, after the deploy:

```
contract.health.ok  : True
structuralErrors    : 0
sourceHealthErrors  : 0
normalizationHealth : True
player_count        : 1111
data_date           : 2026-08-20
```

Consistent with the pinned-input golden-board diff run earlier across this wave's
merges (0 values moved, 0 ranks changed). A frontend-only migration must not move
a published value, and none did.

## 6. What L4 still requires

An authenticated render of the migrated `/rankings` board and a Player File **on
production**, plus a real consumer of them. Both are recorded as open in
`V1-111`'s contract row. The local-build evidence for those surfaces is real and
detailed (`docs/psi/PR_A_VISUAL_VERIFICATION_2026-08-20.md`) but it is a
statement about the branch, not about production, and the two must not be
conflated.
