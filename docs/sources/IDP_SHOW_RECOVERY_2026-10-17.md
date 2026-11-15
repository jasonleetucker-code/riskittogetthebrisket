# The IDP Show — recovery investigation (2026-10-17)

Owner master package 2026-10-17, Workstream D.  Two independent problems, examined separately,
because a successful login does not make stale content fresh.

## 1. Collection (engineering)

| fact | evidence |
|---|---|
| The prod timer (`dynasty-idpshow-fetch`, every 2 h at :32) committed its last refresh at **2026-10-07T20:32Z** (`911411cb4`); every 2 h before that it committed | `git log -- data/scrape_state/idpShowCombined_last_success` |
| No refresh landed at 2026-10-17T20:32Z either | `git log origin/main` after that time |
| Its last committed status files still say `HEALTHY` (observed 2026-10-07T20:32Z), which is consistent with the script exiting **before** committing on a both-fetches-failed run, so a failure's class never reached the repo | `data/scrape_state/idpShow*_last_status.json`, `deploy/idpshow_fetch_and_push.sh` |
| The GitHub refresh's alternative credential path is **not configured** — `IDPSHOW_SESSION_JSON` is empty | Scheduled Data Refresh run 39059853594 log: `IDPSHOW_SESSION_JSON not configured; skipping idpShow` |

The failure class (expired jar, paywall, git push auth, chart change) is not observable from the repo.
This PR adds `scripts/verify_idpshow_onbox.py` + `idpshow-onbox-verification.yml`, which answers it from
the box: jar presence / age / per-cookie expiry (names only, never values), the unit's last result and
its own `[idpshow` journal lines, and — with the jar — whether each article is readable and which charts
it embeds.  `collect: true` starts the existing service once.

It also makes the GitHub secret a complete credential path: when `IDPSHOW_SESSION_JSON` is set, the
scheduled refresh now fetches the **combined (voting)** board too, recording its dataset state only on a
successful fetch, as the timer does.  Previously the secret drove only the non-voting IDP-only board.

## 2. Upstream publication (vendor)

Measured from public endpoints, no credential used:

| board | role | post last updated (Substack API) | chart | latest published version | Datawrapper `lastModifiedAt` |
|---|---|---|---|---|---|
| `idpShowCombined` (offense + IDP) | **voting** | 2026-06-22 | `U8I37` | **v4** (v5…v15 → 404) | **2026-08-19** |
| `idpShow` (IDP only) | non-voting (diagnostic) | **2026-10-08** | not visible without auth | — | — |

* The combined board's chart has had **no new version since v4**.  Re-fetching it with a valid session
  returns the same August content, and freshness weighting will correctly keep it quarantined.
  Nothing in this PR changes that, and no timestamp is edited.
* The vendor **republished the IDP-only dynasty post on 2026-10-08** — one day after our last
  successful collection.  Whether its chart content changed needs an authenticated read (the on-box
  verifier reports `upstreamDiffersFromCommitted` per board).
* The vendor's other recent rankings posts are **rest-of-season / weekly** (`2026-rest-of-season-idp-rankings*`,
  `week-N-idp-rankings-and-tiers`).  Those are seasonal-lane evidence and are barred from the dynasty pool
  by the source-domain boundary; they are not a replacement for the dynasty board.

## 3. Path back to voting

1. **Credential** (owner): a fresh browser-minted jar, either on the box at
   `/var/lib/idpshow-fetch/idpshow_session.json` (mode 600, owned by the app user) or as the
   `IDPSHOW_SESSION_JSON` repository secret (`{"cookies": [...]}`).
2. **Verify**: dispatch `idpshow-onbox-verification.yml` (`collect: true`).  Accept only
   `articleState: readable` for both boards.
3. **Upstream**: if the combined chart is still v4 / 2026-08-19, the combined board stays quarantined
   by freshness weighting — correctly.
4. **Candidate**: if the IDP-only board's content has changed since our 10-07 copy, it becomes the
   provider family's candidate dynasty IDP voter.  Activation is not automatic: the IDP-only board is
   unregistered today (the 2026-08-20 decision made the combined board the family's sole voter), so
   switching the family's voting board needs (a) a coverage / identity / position check, (b) the
   lineage check against IDP Trade Calculator (`config/sources/source_lineage.json`), and (c) owner
   approval.  The provider keeps one family vote either way.
5. If neither board changes for a further full cadence after a working credential is proven, record
   the vendor as `upstream_inactive` and evaluate replacements.
