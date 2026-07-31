# Sharp Tracker production ingestion

## Operational state

The unified Sharp Tracker uses two independent read-only upstream jobs:

1. Sleeper graph discovery and season-record crawling.
2. Public FFPC dynasty-page ingestion.

Both write to the same platform-scoped ledger. The market endpoint then
aggregates canonical assets into one table while retaining source breakdowns.

## Sleeper population

`dynasty-sharp-discovery.timer` grows the public Sleeper graph. The records
job follows it and collects completed season evidence required by Sharp Score
v2. Production deployment now installs, reloads, enables, and immediately
starts both jobs. The records bootstrap uses a 5,000-call budget and a
one-hour service timeout; later daily runs resume from the persistent fair
queue.

Sleeper managers appear as automated qualifiers only after the unchanged
Sharp Score v2 evidence and scoring gates are satisfied.

## FFPC population

`config/sharp/ffpc_sources.json` contains explicitly selected, unauthenticated
public dynasty `LeagueHome.aspx` pages. The adapter performs GET requests only.
It parses visible standings and transactions, normalizes multi-line action
cells, deduplicates the two team perspectives of one trade, resolves assets
onto canonical Sleeper player IDs, and stores unresolved assets for review.

`dynasty-ffpc-sharp.timer` runs once per day at 05:20 UTC with up to a
15-minute randomized delay. It is persistent, so a missed run fires after the
host returns. Deployment also triggers the first run immediately.

One broken public page produces a partial-success report and does not prevent
other configured leagues from updating.

## Qualification labels

- `automated_qualified`: passed Sharp Score v2.
- `curated_high_stakes`: explicitly verified curated record.
- `provisional_public`: observed trade activity from a configured public FFPC
  dynasty league, but historical evidence is insufficient for Sharp Score v2.

Provisional activity is intentionally usable in the default combined market
view at a conservative configured quality weight. It is never described as an
automated qualification. League-scoped identities still cannot satisfy
multi-league Sharp Score requirements.

## Manual operations

```bash
python scripts/crawl_ffpc_sharp.py --public-only --dry-run --verbose
python scripts/crawl_ffpc_sharp.py --public-only
python scripts/crawl_sharp_records.py --budget 5000
systemctl list-timers --all | grep -E 'sharp|ffpc'
journalctl -u dynasty-sharp-records.service -n 200 --no-pager
journalctl -u dynasty-ffpc-sharp.service -n 200 --no-pager
```
