"use client";

import AnchorChart from "./AnchorChart";

const POSITIONS = ["DL", "LB", "DB"];

function n(value, digits = 3) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

function ScoringSummary({ label, summary }) {
  if (!summary) return null;
  const active = summary.active_idp_stats || {};
  const unknown = summary.unknown_idp_keys || {};
  return (
    <div className="idp-lab-scoring">
      <span className="badge">{label}</span>
      <span className="muted text-sm">league {summary.league_id}</span>
      <ul className="idp-lab-scoring-list">
        {Object.entries(active).map(([k, v]) => (
          <li key={k}>
            <code>{k}</code> × {n(v, 2)}
          </li>
        ))}
        {!Object.keys(active).length && <li className="muted">No IDP stats scored.</li>}
      </ul>
      {Object.keys(unknown).length > 0 && (
        <p className="idp-lab-warning-list" style={{ margin: "var(--space-xs) 0 0" }}>
          Unmapped IDP keys (add to KEY_ALIASES):{" "}
          {Object.entries(unknown)
            .map(([k, v]) => `${k} (${Number(v).toFixed(2)})`)
            .join(", ")}
        </p>
      )}
    </div>
  );
}

function LineupSummary({ lineup, label }) {
  if (!lineup) return null;
  return (
    <div className="idp-lab-lineup">
      <span className="badge">{label}</span>
      <span className="muted text-sm">{lineup.team_count} teams</span>
      <dl className="idp-lab-lineup-list">
        <div>
          <dt>DL starters</dt>
          <dd>{lineup.dl_starters}</dd>
        </div>
        <div>
          <dt>LB starters</dt>
          <dd>{lineup.lb_starters}</dd>
        </div>
        <div>
          <dt>DB starters</dt>
          <dd>{lineup.db_starters}</dd>
        </div>
        <div>
          <dt>IDP flex</dt>
          <dd>{lineup.idp_flex_starters}</dd>
        </div>
        <div>
          <dt>Offense starters</dt>
          <dd>{lineup.offense_starters}</dd>
        </div>
      </dl>
    </div>
  );
}

function ChainBlock({ label, chain }) {
  if (!chain) return null;
  const seasonMap = chain.seasons || {};
  return (
    <div className="idp-lab-chain">
      <div className="idp-lab-chain-header">
        <span className="badge">{label}</span>
        <code className="idp-lab-chain-id">{chain.input_league_id || "—"}</code>
      </div>
      <ul className="idp-lab-chain-list">
        {Object.keys(seasonMap)
          .sort((a, b) => Number(b) - Number(a))
          .map((season) => {
            const entry = seasonMap[season];
            return (
              <li
                key={season}
                className={entry.resolved ? "idp-lab-chain-ok" : "idp-lab-chain-miss"}
              >
                <span>{season}</span>
                <span className="muted">
                  {entry.resolved ? entry.league_name || entry.league_id : entry.reason}
                </span>
              </li>
            );
          })}
      </ul>
      {chain.warnings?.length ? (
        <ul className="idp-lab-warning-list">
          {chain.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function SectionBuckets({ run }) {
  const perSeason = run.per_season || {};
  const keys = Object.keys(perSeason).sort();
  return (
    <section className="card idp-lab-section">
      <h2>Season-by-season VOR</h2>
      {keys.map((season) => {
        const entry = perSeason[season];
        if (!entry?.resolved) {
          return (
            <div key={season} className="idp-lab-season idp-lab-season-missing">
              <h3>{season}</h3>
              <p className="muted">{entry?.reason || "Not resolved."}</p>
            </div>
          );
        }
        return (
          <div key={season} className="idp-lab-season">
            <h3>
              {season}{" "}
              <span className="muted text-sm">
                universe={entry.universe_size} | adapter={entry.adapter}
              </span>
            </h3>
            {(entry.test_rules_borrowed || entry.my_rules_borrowed) && (
              <p className="muted text-sm idp-lab-borrow-note">
                {entry.test_rules_borrowed && (
                  <>Test-league rules borrowed from season {entry.test_rules_source_season}.{" "}</>
                )}
                {entry.my_rules_borrowed && (
                  <>My-league rules borrowed from season {entry.my_rules_source_season}.</>
                )}
              </p>
            )}
            {POSITIONS.map((pos) => {
              const buckets = entry.buckets?.[pos] || [];
              if (!buckets.length) return null;
              return (
                <div key={pos} className="idp-lab-bucket-block">
                  <div className="idp-lab-subheading">
                    <strong>{pos}</strong>
                    <span className="muted">
                      replacement test={n(entry.replacement_test?.[pos]?.replacement_points)}{" "}
                      / mine={n(entry.replacement_mine?.[pos]?.replacement_points)}
                    </span>
                  </div>
                  <div className="table-wrap">
                    <table className="table idp-lab-bucket-table">
                      <thead>
                        <tr>
                          <th>Bucket</th>
                          <th>#</th>
                          <th>Center (test)</th>
                          <th>Center (mine)</th>
                          <th>Ratio</th>
                          <th>Merged from</th>
                        </tr>
                      </thead>
                      <tbody>
                        {buckets.map((b, i) => (
                          <tr key={i}>
                            <td>{b.label}</td>
                            <td>{b.count}</td>
                            <td>{n(b.center_vor_test)}</td>
                            <td>{n(b.center_vor_mine)}</td>
                            <td>{b.ratio_mine_over_test == null ? "—" : n(b.ratio_mine_over_test, 3)}</td>
                            <td className="muted">{(b.merged_from || []).join(", ") || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </section>
  );
}

function SectionMultipliers({ run }) {
  const multipliers = run.multipliers || {};
  return (
    <section className="card idp-lab-section">
      <h2>Multi-year calibration summary</h2>
      {POSITIONS.map((pos) => {
        const posBlock = multipliers[pos];
        if (!posBlock?.buckets?.length) {
          return (
            <div key={pos} className="muted">
              No multipliers generated for {pos}.
            </div>
          );
        }
        return (
          <div key={pos} className="idp-lab-mult-block">
            <div className="idp-lab-subheading">
              <strong>{pos}</strong>
              <span className="muted">per-bucket multipliers</span>
            </div>
            <div className="table-wrap">
              <table className="table idp-lab-mult-table">
                <thead>
                  <tr>
                    <th>Bucket</th>
                    <th>#</th>
                    <th>Intrinsic</th>
                    <th>Market</th>
                    <th>Final</th>
                  </tr>
                </thead>
                <tbody>
                  {posBlock.buckets.map((b, i) => (
                    <tr key={i}>
                      <td>{b.label}</td>
                      <td>{b.count}</td>
                      <td>{n(b.intrinsic, 4)}</td>
                      <td>{n(b.market, 4)}</td>
                      <td>
                        <strong>{n(b.final, 4)}</strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </section>
  );
}

function SectionAnchors({ run }) {
  return (
    <section className="card idp-lab-section">
      <h2>Anchor curves</h2>
      <div className="idp-lab-anchor-grid">
        {POSITIONS.map((pos) => (
          <AnchorChart key={pos} position={pos} anchors={run.anchors} />
        ))}
      </div>
    </section>
  );
}

function SectionRecommendation({ run }) {
  const rec = run.recommendation || {};
  const lines = rec.summary_lines || [];
  const notes = rec.notes || [];
  return (
    <section className="card idp-lab-section">
      <h2>Recommendation</h2>
      {lines.length ? (
        <ul className="idp-lab-rec-list">
          {lines.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ul>
      ) : (
        <p className="muted">No recommendation available.</p>
      )}
      {notes.length ? (
        <ul className="idp-lab-warning-list">
          {notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      ) : null}
      {rec.recommended_mode && (
        <p className="muted text-sm">
          Recommended production mode:{" "}
          <strong>{rec.recommended_mode}</strong>
        </p>
      )}
    </section>
  );
}

export default function ResultsDashboard({ run }) {
  if (!run) return null;

  // Pick the most recent *resolved* season for the scoring and lineup
  // verification panels. Falling back to the raw-first season would
  // hide both panels whenever the earliest season in the chain is
  // missing (a common case when one league's chain doesn't reach the
  // default 2022 back-stop).
  const seasonKeysDesc = Object.keys(run.per_season || {}).sort(
    (a, b) => Number(b) - Number(a),
  );
  const verificationSeason =
    seasonKeysDesc.find((k) => run.per_season?.[k]?.resolved) ||
    seasonKeysDesc[0];
  const scoringEntry = run.per_season?.[verificationSeason] || {};

  return (
    <div className="idp-lab-dashboard">
      <section className="card idp-lab-section">
        <h2>League verification</h2>
        <div className="idp-lab-chain-grid">
          <ChainBlock label="Test league" chain={run.chains?.test} />
          <ChainBlock label="My league" chain={run.chains?.mine} />
        </div>
        {scoringEntry?.test_scoring && (
          <>
            <p className="muted text-sm">
              Scoring and lineup are taken from each league&rsquo;s{" "}
              <strong>current input season</strong> and applied to every
              historical year&rsquo;s stats &mdash; so this calibration
              answers &ldquo;what would these players be worth under
              today&rsquo;s rules?&rdquo; Sampled from season{" "}
              <strong>{verificationSeason}</strong>
              {scoringEntry.resolved === false && " (unresolved)"}.
            </p>
            <div className="idp-lab-scoring-grid">
              <ScoringSummary label="Test scoring" summary={scoringEntry.test_scoring} />
              <ScoringSummary label="My scoring" summary={scoringEntry.my_scoring} />
            </div>
          </>
        )}
        {scoringEntry?.test_lineup && (
          <div className="idp-lab-lineup-grid">
            <LineupSummary label="Test lineup" lineup={scoringEntry.test_lineup} />
            <LineupSummary label="My lineup" lineup={scoringEntry.my_lineup} />
          </div>
        )}
      </section>

      <SectionBuckets run={run} />
      <SectionMultipliers run={run} />
      <SectionAnchors run={run} />
      <SectionRecommendation run={run} />
    </div>
  );
}
