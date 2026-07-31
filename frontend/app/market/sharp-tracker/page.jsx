"use client";

import { useEffect, useState } from "react";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";

// ── Sharp Tracker ────────────────────────────────────────────────────
// Market intelligence from a QUALIFIED cohort of dynasty managers,
// scored by our own Sharp Score.  Deliberately NOT league-scoped: it
// answers "what is the smart money doing", which has nothing to do with
// which league you happen to have selected.
//
// This is NOT Insider Trading (/league/insider-trading), which is
// league-scoped and whose cohort is simply the managers in your league
// with no skill filter at all.  The two shipped merged; they are now
// separate products with separate routes, services, and cohorts.
//
// The cohort is built by outward graph traversal from every league this
// platform observes — Sleeper publishes no global user or league
// directory, so there is no way to enumerate all managers and no honest
// way to pretend otherwise.  Until the discovery job has run and enough
// managers clear the eligibility bar, this page says exactly that
// rather than showing a thin board dressed up as a market.

const METHODOLOGY_VERSION = "sharp-v2";

function CohortStat({ label, value, note }) {
  return (
    <div style={{ minWidth: 150 }}>
      <div
        className="muted"
        style={{
          fontSize: "0.68rem",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        {label}
      </div>
      <div style={{ fontFamily: "var(--mono)", fontSize: "1.35rem", fontWeight: 700 }}>
        {value == null ? "—" : value.toLocaleString()}
      </div>
      {note ? (
        <div className="muted" style={{ fontSize: "0.66rem" }}>
          {note}
        </div>
      ) : null}
    </div>
  );
}

export default function SharpTrackerPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    fetch("/api/sharp/cohort")
      .then(async (r) => {
        if (r.ok) return r.json();
        // 503 = the discovery job hasn't produced a cohort yet.  That
        // is a real, expected state on a growing network, not an
        // error, and it renders as its own explanation below.
        if (r.status === 503) return { status: "cohort_building" };
        throw new Error(`HTTP ${r.status}`);
      })
      .then((payload) => {
        if (!active) return;
        setData(payload);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        setError(String(err?.message || err));
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  if (loading) return <LoadingState message="Loading Sharp Tracker…" />;

  const cohort = data?.cohort || {};
  const building = !data || data.status !== "ok";
  const managersWithRecords =
    cohort.managersWithRecords ?? data?.records?.managersWithRecords ?? 0;
  const discoveryHasManagers = (cohort.observableManagers || 0) > 0;
  const recordsAreEmpty = discoveryHasManagers && managersWithRecords === 0;
  const buildingTitle = recordsAreEmpty
    ? "Historical manager records are being collected"
    : "The sharp cohort is still being built";
  const buildingMessage = recordsAreEmpty
    ? "Manager discovery is working, but discovery alone cannot calculate a Sharp Score. " +
      "The records crawler is now walking those leagues' completed seasons to collect wins, " +
      "playoff results, championships, and finishes. The board opens as soon as enough of " +
      "those managers have complete multi-season evidence."
    : "Sleeper publishes no global directory of users or leagues, so a manager pool " +
      "can only grow outward from leagues we already observe. Discovery and historical-record " +
      "jobs advance that graph on a schedule, and this board opens once enough managers have " +
      "the multi-season history needed to be scored. It will stay empty rather than show a " +
      "handful of managers labelled as a market.";

  return (
    <section>
      <PageHeader
        title="Sharp Tracker"
        subtitle="What a qualified cohort of dynasty managers is buying and selling, across every league we observe."
      />

      {error ? (
        <div className="card">
          <EmptyState title="Couldn't load the sharp cohort" message={error} />
        </div>
      ) : null}

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
          <CohortStat
            label="Observable"
            value={cohort.observableManagers}
            note="managers seen in any crawled league"
          />
          <CohortStat
            label="Records"
            value={managersWithRecords}
            note="managers with historical season results"
          />
          <CohortStat
            label="Evaluable"
            value={cohort.evaluableManagers}
            note="enough history to score"
          />
          <CohortStat
            label="Qualified"
            value={cohort.qualifiedManagers}
            note="cleared the Sharp Score bar"
          />
          <CohortStat
            label="Leagues"
            value={cohort.observedLeagues}
            note="all leagues reached by discovery"
          />
        </div>
        <div className="muted" style={{ fontSize: "0.68rem", marginTop: 10 }}>
          Methodology {data?.methodologyVersion || METHODOLOGY_VERSION}
          {data?.generatedAt ? ` · updated ${new Date(data.generatedAt).toLocaleString()}` : ""}
        </div>
      </div>

      {building ? (
        <div className="card">
          <EmptyState title={buildingTitle} message={buildingMessage} />
        </div>
      ) : null}

      <div className="card" style={{ marginTop: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 6, fontSize: "0.82rem" }}>
          What qualifies a manager as sharp
        </div>
        <ul
          className="muted"
          style={{ fontSize: "0.72rem", lineHeight: 1.7, paddingLeft: 18, margin: 0 }}
        >
          <li>Multi-season record — win rate, playoff and championship rate, median finish</li>
          <li>Roster quality relative to their league&apos;s average, age- and depth-adjusted</li>
          <li>Consistency across several independent leagues, not one lucky season</li>
          <li>Sustained activity, and no abandoned or inactive rosters</li>
          <li>Minus an explicit uncertainty penalty when history is thin</li>
        </ul>
        <div className="muted" style={{ fontSize: "0.7rem", marginTop: 8 }}>
          League count alone never qualifies anyone. Every qualified manager stores its
          component scores, so the reason is always inspectable. Signals describe manager
          behaviour — not predictions about player outcomes — and low-volume signals are
          labelled as such.
        </div>
      </div>
    </section>
  );
}
