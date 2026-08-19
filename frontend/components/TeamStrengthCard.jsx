"use client";

/**
 * TeamStrengthCard — the canonical Team Strength surface.
 *
 * Renders `GET /api/roster/intelligence`. It computes nothing: every
 * number on screen was produced by `src/roster_intel/strength.py`, the
 * canonical owner (feature inventory row 1.1). This component replaced
 * `scoreTeamTiers`, a frontend team-score formula that lived in
 * `lib/league-analysis.js` and published a second, contradictory
 * ranking of the same twelve teams.
 *
 * Two labelling rules are load-bearing rather than cosmetic, because
 * `V1-35` says the named team quantities must stay distinct:
 *
 *   • Team Strength (`total`) is the MEANINGFUL CORE. The words
 *     "Team Strength" appear against that number and no other.
 *   • Full-roster portfolio (`fullRosterValue`) is the whole-roster sum
 *     and is always labelled as a portfolio. On a deep best-ball roster
 *     the two are far apart by construction.
 *
 * And one refusal rule: when the backend says `available: false`, or
 * gives a `null` rank, this renders the reason or "Not measured". It
 * never falls back to a locally computed score — a fallback is a second
 * owner that only runs when nobody is looking.
 */

import { InfoTip } from "@/components/ds";
import { EmptyState, LoadingState } from "@/components/ui";
import {
  NOT_MEASURED,
  formatStrengthValue,
  strengthCaveats,
  teamStrengthDetail,
  teamStrengthLadder,
} from "@/lib/roster-intelligence";

/** Each refusal gets its own sentence. "Sign in", "pick a team" and
 *  "the engine is down" are three different situations and a user can
 *  act on two of them. */
function StrengthFailure({ failure }) {
  if (!failure) return null;
  const { kind, message } = failure;
  if (kind === "auth") {
    return <EmptyState title="Sign in to see Team Strength" message={message} />;
  }
  if (kind === "team_required") {
    return (
      <EmptyState
        title="Choose a team"
        message={
          message ||
          "Team Strength is measured for one team against the rest of the league. Pick a team above."
        }
      />
    );
  }
  if (kind === "team_not_found") {
    return (
      <EmptyState
        title="That team is not in this league"
        message={message || "Pick a different team above."}
      />
    );
  }
  if (kind === "not_ready") {
    return (
      <EmptyState
        title="Team Strength is not ready yet"
        message={
          message ||
          "The league's rosters have not been loaded on this server yet. Nothing is wrong with the roster — this measurement simply cannot be made until they are."
        }
      />
    );
  }
  if (kind === "league") {
    return <EmptyState title="League unavailable" message={message} />;
  }
  if (kind === "unavailable") {
    return (
      <EmptyState
        title="Team Strength is unavailable"
        message={message || "The roster intelligence service did not respond."}
      />
    );
  }
  return (
    <EmptyState
      title="Team Strength could not be measured"
      message={message || "An unexpected error occurred."}
    />
  );
}

export default function TeamStrengthCard({ loading, data, failure }) {
  if (loading) return <LoadingState message="Measuring Team Strength..." />;
  if (failure) {
    return (
      <div className="card team-strength-card" style={{ marginTop: "var(--space-md)" }}>
        <StrengthHeading />
        <StrengthFailure failure={failure} />
      </div>
    );
  }

  const detail = teamStrengthDetail(data);
  const ladder = teamStrengthLadder(data, { myOwnerId: detail?.ownerId || "" });

  if (!detail && !ladder.length) {
    return (
      <div className="card team-strength-card" style={{ marginTop: "var(--space-md)" }}>
        <StrengthHeading />
        <EmptyState
          title="No Team Strength for this league"
          message="The server returned no team and no league context."
        />
      </div>
    );
  }

  const caveats = strengthCaveats(detail);

  return (
    <div className="card team-strength-card" style={{ marginTop: "var(--space-md)" }}>
      <StrengthHeading />

      {detail && !detail.available && (
        <p className="team-strength-unavailable" role="note">
          <strong>Team Strength is unavailable for {detail.teamName || "this team"}.</strong>{" "}
          {detail.unavailableReason
            ? `Reason: ${detail.unavailableReason}.`
            : "The backend did not give a reason."}{" "}
          This is not a strength of zero — it means the lineup could not be read.
        </p>
      )}

      {detail && detail.available && (
        <div className="team-strength-summary">
          <div className="team-strength-headline">
            <span className="team-strength-headline-label">
              Team Strength
              <span className="team-strength-headline-scope"> — meaningful core</span>
            </span>
            <span className="team-strength-headline-value" data-testid="team-strength-total">
              {formatStrengthValue(detail.total)}
            </span>
            <span className="team-strength-headline-rank">
              {detail.rank === null ? (
                <span title="This team was excluded from the ranking population, so it has no rank. It is not last.">
                  {NOT_MEASURED}
                </span>
              ) : (
                <>
                  {detail.rankLabel} of {ladder.length || "?"}
                </>
              )}
            </span>
          </div>

          <dl className="team-strength-facets">
            <div>
              <dt>Starters</dt>
              <dd>{formatStrengthValue(detail.starterValue)}</dd>
            </div>
            <div>
              <dt>Reserves</dt>
              <dd>{formatStrengthValue(detail.reserveValue)}</dd>
            </div>
            {/* Published only when the backend supplies it.  The live
                endpoint does not today (`build_league_roster_intelligence`
                calls `build_team_strength(core)` with no
                `full_roster_values`), so rather than print a permanent
                em-dash under a heading, the facet appears when the number
                does.  The portfolio quantity the page DOES have is the
                roster-value table below, which is labelled as such. */}
            {detail.fullRosterValue !== null && (
              <div>
                <dt>
                  Full roster portfolio
                  <InfoTip label="the full roster portfolio">
                    <p>
                      The sum of every asset on the roster. It is{" "}
                      <strong>not</strong> Team Strength: a deep roster books its
                      40th player at full market value, which says something about
                      capital rather than about how strong the team is.
                    </p>
                  </InfoTip>
                </dt>
                <dd data-testid="team-strength-full-roster">
                  {formatStrengthValue(detail.fullRosterValue)}
                </dd>
              </div>
            )}
          </dl>

          {caveats.length > 0 && (
            <ul className="team-strength-caveats" role="note">
              {caveats.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}

          {detail.positions.length > 0 && (
            <div className="table-wrap">
              <table className="team-strength-positions">
                <caption className="ds-visually-hidden">
                  {detail.teamName} Team Strength by position group
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Position</th>
                    <th scope="col" style={{ textAlign: "right" }}>
                      Strength
                    </th>
                    <th scope="col" style={{ textAlign: "right" }}>
                      Starters
                    </th>
                    <th scope="col" style={{ textAlign: "right" }}>
                      Reserves
                    </th>
                    <th scope="col" style={{ textAlign: "right" }}>
                      League
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {detail.positions.map((p) => (
                    <tr key={p.position}>
                      <th scope="row">{p.position}</th>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                        {formatStrengthValue(p.value)}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                        {formatStrengthValue(p.starterValue)}
                        {/* The count is omitted when the payload did not
                            carry one. `(0)` is a real statement — no
                            starters at this position — so it may not
                            stand in for a missing field. */}
                        {p.starterCount === null ? null : ` (${p.starterCount})`}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                        {formatStrengthValue(p.reserveValue)}
                        {p.reserveCount === null ? null : ` (${p.reserveCount})`}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                        {p.rankLabel}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {ladder.length > 0 && (
        <div className="team-strength-ladder">
          <h3 className="team-strength-subtitle">League Team Strength</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col" style={{ width: 40 }}>
                    Rank
                  </th>
                  <th scope="col">Team</th>
                  <th scope="col" style={{ textAlign: "right", width: 110 }}>
                    Team Strength
                  </th>
                </tr>
              </thead>
              <tbody>
                {ladder.map((t) => (
                  <tr
                    key={t.ownerId || t.teamName}
                    className={t.isMe ? "team-strength-me" : undefined}
                  >
                    <td
                      style={{ fontFamily: "var(--mono)", fontWeight: 700 }}
                      className={t.measured ? undefined : "team-strength-unranked"}
                    >
                      {t.measured ? t.rankLabel : "—"}
                    </td>
                    <td style={{ fontWeight: 700 }}>
                      {t.teamName}
                      {!t.measured && (
                        <span className="team-strength-unranked-note"> {NOT_MEASURED}</span>
                      )}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                      {formatStrengthValue(t.strengthTotal)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function StrengthHeading() {
  return (
    <div className="team-strength-title">
      Team Strength
      <InfoTip label="Team Strength">
        <p>
          Dynasty roster strength over the <strong>meaningful core</strong> — the
          players who fill this league&rsquo;s starting lineup plus its reserve
          depth — measured by the canonical backend owner and read here verbatim.
        </p>
        <p>
          It is deliberately not the same number as the full-roster portfolio
          below, not rest-of-season production, and not playoff or championship
          odds. Those are separate questions with separate answers.
        </p>
        <p>
          A team with no rank was excluded from the ranking population because
          its lineup could not be read. That is &ldquo;not measured&rdquo;, not
          &ldquo;last&rdquo;.
        </p>
      </InfoTip>
    </div>
  );
}
