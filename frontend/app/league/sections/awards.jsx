"use client";

// AwardsSection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { EmptyState, PlayerImage } from "@/components/ui";
import { Avatar, Card, EmptyCard, LinkButton, renderAwardValue } from "../shared.jsx";

// Award keys whose ``value`` payload carries a player (top_qb, MVP, etc.).
// We render the player's headshot next to the manager's avatar so the
// player part of the award is visible at a glance.
const PLAYER_AWARD_KEYS = new Set([
  "top_qb", "top_rb", "top_wr", "top_te", "top_k",
  "top_dl", "top_lb", "top_db",
  "league_mvp", "playoff_mvp",
]);

function AwardsSection({ managers, data, onNavigate }) {
  const seasons = data?.bySeason || [];
  const races = data?.awardRaces || [];
  if (!seasons.length && !races.length) return <EmptyCard label="Awards" />;

  return (
    <>
      {races.length > 0 && (
        <Card
          title="Award races · season to date"
          subtitle={`Top 3 for every live race${data.currentSeason ? ` · ${data.currentSeason} in progress` : ""}`}
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
            {races.map((race) => (
              <div
                key={race.key}
                style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 12 }}
              >
                <div style={{ fontWeight: 700 }}>{race.label}</div>
                <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 2, marginBottom: 8, lineHeight: 1.4 }}>
                  {race.description}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {race.leaders.map((leader) => (
                    <div
                      key={leader.ownerId}
                      style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.78rem" }}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", minWidth: 16 }}>
                          {leader.rank}.
                        </span>
                        <Avatar managers={managers} ownerId={leader.ownerId} size={18} />
                        <span
                          style={{ cursor: "pointer", color: "var(--cyan)" }}
                          onClick={() => onNavigate("franchise", { owner: leader.ownerId })}
                        >
                          {leader.displayName}
                        </span>
                      </span>
                      <span style={{ fontFamily: "var(--mono)", color: "var(--text)" }}>
                        {renderAwardValue(race.key, leader.value)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {seasons.map((s) => (
        <Card
          key={s.leagueId}
          title={`${s.season} award winners`}
          subtitle={s.isComplete ? "Season complete" : "Season in progress"}
        >
          {s.hasPlayerScoring === false && (
            <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginBottom: 8 }}>
              Trader / Waiver / Playoff MVP awards depend on per-player scoring that
              Sleeper didn't surface for this season — some awards may be skipped.
            </div>
          )}
          {(s.awards || []).length === 0 ? (
            <EmptyState
              title="No awards yet"
              message="Awards will appear once the season has enough games / transactions / trades on record."
            />
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 }}>
              {(s.awards || []).map((a) => (
                <div
                  key={a.key}
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: 12,
                    background: "rgba(15, 28, 59, 0.45)",
                  }}
                >
                  <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {a.label}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                    {PLAYER_AWARD_KEYS.has(a.key) && a.value?.playerId && (
                      <PlayerImage
                        playerId={a.value.playerId}
                        position={a.value.position}
                        name={a.value.playerName}
                        size={32}
                      />
                    )}
                    {a.ownerId && <Avatar managers={managers} ownerId={a.ownerId} size={24} />}
                    <div style={{ minWidth: 0 }}>
                      {PLAYER_AWARD_KEYS.has(a.key) && a.value?.playerName && (
                        <div style={{ fontWeight: 700, fontSize: "0.98rem" }}>
                          {a.value.playerName}
                          {a.value.position && (
                            <span style={{ color: "var(--subtext)", fontSize: "0.7rem", marginLeft: 6 }}>
                              ({a.value.position})
                            </span>
                          )}
                        </div>
                      )}
                      {(!PLAYER_AWARD_KEYS.has(a.key) || !a.value?.playerName) && (
                        <div style={{ fontWeight: 700, fontSize: "0.98rem" }}>{a.displayName}</div>
                      )}
                      {PLAYER_AWARD_KEYS.has(a.key) && a.value?.playerName && a.displayName && (
                        <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
                          {a.displayName}
                        </div>
                      )}
                      {(!PLAYER_AWARD_KEYS.has(a.key) || !a.value?.playerName) && a.teamName && a.teamName !== a.displayName && (
                        <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>{a.teamName}</div>
                      )}
                    </div>
                  </div>
                  {a.value && (
                    <div style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--cyan)", marginTop: 6 }}>
                      {renderAwardValue(a.key, a.value)}
                    </div>
                  )}
                  {a.description && (
                    <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 8, lineHeight: 1.4 }}>
                      {a.description}
                    </div>
                  )}
                  {a.ownerId && (
                    <div style={{ marginTop: 8 }}>
                      <LinkButton onClick={() => onNavigate("franchise", { owner: a.ownerId })}>
                        Franchise page →
                      </LinkButton>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      ))}
    </>
  );
}

export default AwardsSection;
