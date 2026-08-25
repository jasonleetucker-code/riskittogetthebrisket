"use client";

// League Conduct Board — current Sleeper rosters joined to the backend's
// reviewed, source-backed conduct registry. This component never infers a
// legal outcome: it renders the exact status, disposition, denial/response,
// discipline, and source links supplied by src/public_league/conduct.py.

import { Avatar, nameFor } from "../shared.jsx";
import styles from "../conduct.module.css";

const BASIS_LABELS = {
  credibleAllegation: "Alleged",
  formalLegalAction: "Arrested / charged",
  convictionOrPlea: "Convicted / pleaded",
  violenceRelatedDiscipline: "Violence discipline",
};

const UNAVAILABLE_MESSAGES = {
  noCurrentSeason:
    "The current Sleeper season is unavailable, so no roster tally can be built.",
  noRosters:
    "Sleeper has not returned current rosters, so no roster tally can be built.",
  registryUnavailable:
    "The reviewed evidence registry could not be read. The board is withheld rather than showing a false zero.",
  registryInvalid:
    "The evidence registry failed validation. The board is withheld rather than publishing malformed or unsourced records.",
};

function plural(value, singular, pluralLabel = `${singular}s`) {
  return Number(value) === 1 ? singular : pluralLabel;
}

function formatScore(value) {
  if (value === null || value === undefined || value === "") return "—";
  const score = Number(value);
  if (!Number.isFinite(score)) return "—";
  return Number.isInteger(score) ? String(score) : score.toFixed(1);
}

function hasNumericScore(value) {
  return (
    value !== null &&
    value !== undefined &&
    value !== "" &&
    Number.isFinite(Number(value))
  );
}

function hasCompleteScoreContract(data) {
  if (!data?.scoring?.version || !hasNumericScore(data?.totals?.score)) {
    return false;
  }
  const teams = Array.isArray(data.teams) ? data.teams : [];
  return teams.every((team) => {
    if (!hasNumericScore(team.score)) return false;
    const players = Array.isArray(team.players) ? team.players : [];
    return players.every((player) => {
      if (!hasNumericScore(player.score)) return false;
      const incidents = Array.isArray(player.incidents) ? player.incidents : [];
      return incidents.every(
        (incident) =>
          hasNumericScore(incident.score) &&
          hasNumericScore(incident.scoreBreakdown?.severityPoints) &&
          hasNumericScore(incident.scoreBreakdown?.outcomeMultiplier) &&
          hasNumericScore(incident.scoreBreakdown?.disciplineBonus),
      );
    });
  });
}

function statusTone(status) {
  if (["pleaded", "convicted", "leagueFinding"].includes(status)) {
    return styles.statusFinding;
  }
  if (
    [
      "prosecutionDeclined",
      "noBilled",
      "dismissed",
      "acquitted",
      "leagueNoFinding",
    ].includes(status)
  ) {
    return styles.statusResolved;
  }
  if (
    ["arrestedInvestigationOpen", "chargedPending", "pretrialDiversion"].includes(
      status,
    )
  ) {
    return styles.statusPending;
  }
  return styles.statusAllegation;
}

function ScoreFormula({ scoring = {} }) {
  if (!scoring.formula) return null;
  return (
    <div className={styles.scoreFormula} aria-label="Ranking score formula">
      <div>
        <strong>Ranking formula</strong>
        <span>{scoring.formula}</span>
      </div>
      <div className={styles.formulaBonuses}>
        <span>
          <strong>+{formatScore(scoring.disciplineBonus)}</strong> qualifying discipline
        </span>
        <span>
          <strong>up to +{formatScore(scoring.repeatIncidentBonus)}</strong> each repeat incident
        </span>
      </div>
    </div>
  );
}

function Breakdown({ breakdown = {}, compact = false }) {
  return (
    <div className={compact ? styles.breakdownCompact : styles.breakdown}>
      {Object.entries(BASIS_LABELS).map(([key, label]) => (
        <div className={styles.breakdownItem} key={key}>
          <strong>{Number(breakdown[key]) || 0}</strong>
          <span>{label}</span>
        </div>
      ))}
    </div>
  );
}

function Incident({ incident }) {
  const sources = Array.isArray(incident.sources) ? incident.sources : [];
  const score = incident.scoreBreakdown || {};
  return (
    <article className={styles.incident}>
      <div className={styles.incidentTopline}>
        <span className={`${styles.status} ${statusTone(incident.status)}`}>
          {incident.statusLabel}
        </span>
        <span className={styles.incidentMeta}>
          {incident.categoryLabel} · {incident.dateLabel}
        </span>
      </div>

      <p className={styles.summary}>{incident.summary}</p>

      <div className={styles.incidentScore}>
        <strong>+{formatScore(incident.score)} pts</strong>
        <span>
          {formatScore(score.severityPoints)} severity × {Number(score.outcomeMultiplier) || 0}
          {Number(score.disciplineBonus)
            ? ` + ${formatScore(score.disciplineBonus)} discipline`
            : ""}
        </span>
      </div>

      <div className={styles.factGrid}>
        <div>
          <span className={styles.factLabel}>Disposition / current status</span>
          <p>{incident.disposition}</p>
        </div>
        {incident.denial ? (
          <div>
            <span className={styles.factLabel}>Response / denial</span>
            <p>{incident.denial}</p>
          </div>
        ) : null}
        {incident.discipline ? (
          <div>
            <span className={styles.factLabel}>Organization discipline</span>
            <p>
              {incident.discipline.organization}: {incident.discipline.description}
            </p>
          </div>
        ) : null}
      </div>

      <div className={styles.sourceRow} aria-label="Incident sources">
        <span className={styles.factLabel}>Sources</span>
        {sources.map((source) => (
          <a
            href={source.url}
            key={`${incident.incidentId}-${source.url}`}
            target="_blank"
            rel="noreferrer"
          >
            {source.label}
          </a>
        ))}
      </div>
      <div className={styles.verified}>Status checked {incident.lastVerified}</div>
    </article>
  );
}

function PlayerRecord({ player }) {
  const incidents = Array.isArray(player.incidents) ? player.incidents : [];
  const meta = [player.position, player.nflTeam].filter(Boolean).join(" · ");
  return (
    <details className={styles.playerRecord}>
      <summary>
        <span className={styles.playerIdentity}>
          <strong>{player.playerName}</strong>
          {meta ? <span>{meta}</span> : null}
        </span>
        <span className={styles.playerCount}>
          <strong>{formatScore(player.score)} pts</strong>
          <span>
            {incidents.length} {plural(incidents.length, "record")}
            {Number(player.repeatIncidentBonus)
              ? ` · +${formatScore(player.repeatIncidentBonus)} repeat`
              : ""}
          </span>
        </span>
      </summary>
      <div className={styles.playerBody}>
        <div className={styles.basisRow}>
          {(player.qualifyingBasis || []).map((basis) => (
            <span key={basis}>{BASIS_LABELS[basis] || basis}</span>
          ))}
        </div>
        {incidents.map((incident) => (
          <Incident incident={incident} key={incident.incidentId} />
        ))}
      </div>
    </details>
  );
}

function TeamCard({ team, managers }) {
  const players = Array.isArray(team.players) ? team.players : [];
  const displayName = nameFor(managers, team.ownerId) || team.displayName;
  const isClear = Number(team.flaggedPlayerCount) === 0;

  return (
    <details className={`${styles.teamCard} ${isClear ? styles.teamCardClear : ""}`}>
      <summary>
        <span className={styles.rank}>{team.rank}</span>
        <span className={styles.managerBlock}>
          <Avatar managers={managers} ownerId={team.ownerId} size={34} />
          <span>
            <strong>{displayName}</strong>
            <small>{team.teamName || `Roster ${team.rosterId}`}</small>
          </span>
        </span>
        <span className={styles.teamTally}>
          <strong>{formatScore(team.score)}</strong>
          <span>
            ranking points · {Number(team.flaggedPlayerCount) || 0} flagged{" "}
            {plural(team.flaggedPlayerCount, "player")} · {Number(team.incidentCount) || 0}{" "}
            {plural(team.incidentCount, "record")}
          </span>
        </span>
        <span className={styles.caret} aria-hidden="true" />
      </summary>

      <div className={styles.teamBody}>
        <Breakdown breakdown={team.breakdown} compact />
        <div className={styles.rosterScope}>
          {team.rosteredPlayerCount} current roster IDs reviewed
        </div>
        {players.length ? (
          <div className={styles.playerList}>
            {players.map((player) => (
              <PlayerRecord player={player} key={player.playerId} />
            ))}
          </div>
        ) : (
          <p className={styles.zeroNote}>
            No current roster IDs matched this reviewed registry. That is not a
            background-check result or a claim that no incident exists.
          </p>
        )}
      </div>
    </details>
  );
}

function Methodology({ methodology = {}, scoring = {}, dataQuality = {} }) {
  const rejected =
    (Number(dataQuality.rejectedPlayerCount) || 0) +
    (Number(dataQuality.rejectedIncidentCount) || 0);
  return (
    <details className={styles.methodology}>
      <summary>Methodology, scope, and exclusions</summary>
      <div className={styles.methodBody}>
        <p>{methodology.mainTally}</p>
        <p>{methodology.breakdownCounts}</p>
        <p>{methodology.rosterScope}</p>
        <p>{methodology.sourceRule}</p>
        {scoring.caveat ? <p className={styles.scoreCaveat}>{scoring.caveat}</p> : null}
        <div className={styles.formulaTables}>
          <div>
            <h3>Category severity points</h3>
            <ul className={styles.formulaRows}>
              {(scoring.severityWeights || []).map((item) => (
                <li key={item.category}>
                  <span>{item.label}</span>
                  <strong>{formatScore(item.points)}</strong>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3>Current-status multipliers</h3>
            <ul className={styles.formulaRows}>
              {(scoring.outcomeMultipliers || []).map((item) => (
                <li key={item.status}>
                  <span>{item.label}</span>
                  <strong>×{Number(item.multiplier) || 0}</strong>
                </li>
              ))}
            </ul>
          </div>
        </div>
        {scoring.repeatDefinition ? <p>{scoring.repeatDefinition}</p> : null}
        <div className={styles.methodColumns}>
          <div>
            <h3>Included</h3>
            <ul>
              {(methodology.included || []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3>Excluded</h3>
            <ul>
              {(methodology.excluded || []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
        {rejected ? (
          <p className={styles.rejected}>
            Validation withheld {rejected} malformed or unsourced registry {plural(rejected, "entry", "entries")}.
          </p>
        ) : null}
      </div>
    </details>
  );
}

export default function ConductSection({ data, managers }) {
  if (!data) {
    return (
      <div className={`card ${styles.unavailable}`}>
        <h2>Piece of Shit Rankings</h2>
        <p>The section has not loaded. Refresh the page to retry.</p>
      </div>
    );
  }

  if (data.available === false) {
    return (
      <div className={`card ${styles.unavailable}`}>
        <h2>Piece of Shit Rankings unavailable</h2>
        <p>
          {UNAVAILABLE_MESSAGES[data.unavailableReason] ||
            "The board cannot be built from the current reviewed data."}
        </p>
      </div>
    );
  }

  if (!hasCompleteScoreContract(data)) {
    return (
      <div className={`card ${styles.unavailable}`}>
        <h2>Piece of Shit Rankings updating</h2>
        <p>
          A cached response from before formula scoring was detected. The board
          is withheld rather than showing missing scores as zero; refresh once
          to load the current rankings.
        </p>
      </div>
    );
  }

  const teams = Array.isArray(data.teams) ? data.teams : [];
  const totals = data.totals || {};

  return (
    <div className={styles.board}>
      <header className={`card ${styles.hero}`}>
        <div className={styles.eyebrow}>Current roster · source-backed</div>
        <div className={styles.heroCopy}>
          <div>
            <h2>Piece of Shit Rankings</h2>
            <p>
              A formula-based roster ranking of qualifying public-record incidents.
              Severity, documented outcome, discipline, and repeat incidents all
              affect the score; allegations never score like convictions.
            </p>
          </div>
          <div className={styles.reviewStamp}>
            Registry reviewed <strong>{data.registryLastReviewed || "—"}</strong>
          </div>
        </div>

        <div className={styles.totals} aria-label="Piece of Shit Rankings totals">
          <div className={styles.primaryTotal}>
            <strong>{formatScore(totals.score)}</strong>
            <span>league ranking points</span>
          </div>
          <div>
            <strong>{Number(totals.flaggedPlayers) || 0}</strong>
            <span>unique flagged players</span>
          </div>
          <div>
            <strong>{Number(totals.incidents) || 0}</strong>
            <span>documented records</span>
          </div>
          <div>
            <strong>{Number(totals.teams) || 0}</strong>
            <span>fantasy teams</span>
          </div>
        </div>

        <ScoreFormula scoring={data.scoring} />

        <Breakdown breakdown={totals.breakdown} />

        <div className={styles.caution} role="note">
          <strong>A flag is not a finding of guilt.</strong>
          <span>{data.methodology?.caveat}</span>
        </div>
      </header>

      <Methodology
        methodology={data.methodology}
        scoring={data.scoring}
        dataQuality={data.dataQuality}
      />

      <section
        className={styles.teamList}
        aria-label="Piece of Shit Rankings by fantasy team"
      >
        {teams.length ? (
          teams.map((team) => (
            <TeamCard team={team} managers={managers} key={`${team.ownerId}-${team.rosterId}`} />
          ))
        ) : (
          <div className={`card ${styles.unavailable}`}>
            <h2>No current teams</h2>
            <p>The section is healthy, but Sleeper returned no fantasy teams.</p>
          </div>
        )}
      </section>
    </div>
  );
}
