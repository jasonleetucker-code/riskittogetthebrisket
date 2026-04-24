"""NFL data ingest + derivatives (Phases 2, 6, 7, 8 of the
2026-04 upgrade).

This package hosts everything that pulls from outside our
own ranking pipeline:

* ``ingest`` — weekly stats + snap counts + schedule, via
  nfl_data_py when installed, via a stub when not.
* ``cache`` — TTL file cache for the heavy parquet slices.
* ``freshness`` — "don't alert on mid-week, pre-republish data"
  guard.
* ``injury_feed`` — ESPN public injuries endpoint.
* ``depth_charts`` — ESPN team depth charts.
* ``usage_windows`` — rolling 4-week usage snapshots used by
  the signal engine and the matchup preview UI.

Every module degrades gracefully when its data source is
unavailable: calls return ``None`` / empty containers and a
structured-log line notes why.  Nothing here raises on a
transient upstream failure — the consumer gets no data and
handles it.
"""
