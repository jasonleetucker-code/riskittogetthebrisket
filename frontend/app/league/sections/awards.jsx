"use client";

// AwardsSection — public /league tab view.
//
// Shows the featured season's awards (Champion + Manager of the Year
// pinned first by the backend).  Tap any award to open its full
// multi-season history.  Season rollover is automatic — the backend
// picks the featured season and keeps last season featured until the
// next one is underway.

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { EmptyState, PlayerImage } from "@/components/ui";
import { Avatar, Card, EmptyCard, renderAwardValue } from "../shared.jsx";
import { TradeCard } from "./activity.jsx";

// Award keys whose ``value`` payload carries a player — render the
// headshot next to the manager's avatar.
const PLAYER_AWARD_KEYS = new Set([
  "top_qb", "top_rb", "top_wr", "top_te", "top_k",
  "top_dl", "top_lb", "top_db",
  "league_mvp", "off_mvp", "def_mvp", "playoff_mvp", "off_roy", "def_roy",
]);

function AwardWinner({ a, managers, size = 24 }) {
  const isPlayer = PLAYER_AWARD_KEYS.has(a.key) && a.value?.playerId;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
      {isPlayer && (
        <PlayerImage
          playerId={a.value.playerId}
          team={a.value.team}
          position={a.value.position}
          name={a.value.playerName}
          size={size + 8}
        />
      )}
      {a.ownerId && <Avatar managers={managers} ownerId={a.ownerId} size={size} />}
      <div style={{ minWidth: 0 }}>
        {isPlayer && a.value?.playerName ? (
          <>
            <div style={{ fontWeight: 700, fontSize: "0.98rem" }}>
              {a.value.playerName}
              {a.value.position && (
                <span style={{ color: "var(--subtext)", fontSize: "0.7rem", marginLeft: 6 }}>
                  ({a.value.position})
                </span>
              )}
            </div>
            {a.displayName && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>{a.displayName}</div>
            )}
          </>
        ) : (
          <>
            <div style={{ fontWeight: 700, fontSize: "0.98rem" }}>{a.displayName || "—"}</div>
            {a.teamName && a.teamName !== a.displayName && (
              <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>{a.teamName}</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function AwardHistoryModal({ awardKey, label, description, history, managers, onNavigate, onClose }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(2, 6, 18, 0.72)",
        display: "flex", alignItems: "flex-start", justifyContent: "center",
        padding: "5vh 12px", overflowY: "auto",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(560px, 100%)",
          background: "var(--card)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-lg, 14px)",
          padding: 16,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <div>
            <div style={{ fontSize: "1.1rem", fontWeight: 800 }}>{label}</div>
            {description && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 4, lineHeight: 1.45 }}>
                {description}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Close award history"
            style={{
              background: "transparent", border: "1px solid var(--border)",
              borderRadius: 8, color: "var(--text)", cursor: "pointer",
              fontSize: "1rem", lineHeight: 1, padding: "4px 9px",
            }}
          >
            ✕
          </button>
        </div>

        <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em", margin: "14px 0 8px" }}>
          History
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {history.length === 0 && (
            <div style={{ fontSize: "0.78rem", color: "var(--subtext)" }}>
              No prior winners on record yet.
            </div>
          )}
          {history.map(({ season, award }) => (
            <div
              key={season}
              style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}
            >
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}>
                {season}
              </div>
              <AwardWinner a={award} managers={managers} size={22} />
              {award.value && (
                <div style={{ fontFamily: "var(--mono)", fontSize: "0.76rem", color: "var(--cyan)", marginTop: 6 }}>
                  {renderAwardValue(award.key, award.value)}
                </div>
              )}
              {award.key === "best_trade_of_the_year" && award.value?.trade && (
                <div style={{ marginTop: 8 }}>
                  <TradeCard trade={award.value.trade} managers={managers} onNavigate={onNavigate} />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function AwardsSection({ managers, data, onNavigate }) {
  const seasons = data?.bySeason || [];
  const races = data?.awardRaces || [];
  const [openKey, setOpenKey] = useState(null);

  // History per award key across every season (bySeason is newest-first).
  const historyByKey = useMemo(() => {
    const map = new Map();
    for (const s of seasons) {
      for (const a of s.awards || []) {
        if (!map.has(a.key)) map.set(a.key, []);
        map.get(a.key).push({ season: s.season, award: a });
      }
    }
    return map;
  }, [seasons]);

  if (!seasons.length && !races.length) return <EmptyCard label="Awards" />;

  const featuredName = data?.featuredSeason || data?.currentSeason || seasons[0]?.season;
  const featured = seasons.find((s) => s.season === featuredName) || seasons[0] || null;
  const upcoming = data?.upcomingSeason;

  const openHistory = openKey ? historyByKey.get(openKey) || [] : [];
  const openMeta = openHistory[0]?.award;

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
                      key={leader.ownerId || leader.value?.playerId || `${race.key}-${leader.rank}`}
                      style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.78rem", gap: 6 }}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
                        <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", minWidth: 16 }}>
                          {leader.rank}.
                        </span>
                        {PLAYER_AWARD_KEYS.has(race.key) && leader.value?.playerId && (
                          <PlayerImage
                            playerId={leader.value.playerId}
                            team={leader.value.team}
                            position={leader.value.position}
                            name={leader.value.playerName}
                            size={18}
                          />
                        )}
                        {leader.ownerId && (
                          <Avatar managers={managers} ownerId={leader.ownerId} size={18} />
                        )}
                        <span
                          style={{ cursor: leader.ownerId ? "pointer" : "default", color: leader.ownerId ? "var(--cyan)" : "var(--text)", overflow: "hidden", textOverflow: "ellipsis" }}
                          onClick={leader.ownerId ? () => onNavigate("franchise", { owner: leader.ownerId }) : undefined}
                        >
                          {PLAYER_AWARD_KEYS.has(race.key) && leader.value?.playerName
                            ? leader.value.playerName
                            : leader.displayName}
                        </span>
                      </span>
                      <span style={{ fontFamily: "var(--mono)", color: "var(--text)", flexShrink: 0 }}>
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

      {featured && (
        <Card
          title={`${featured.season} awards`}
          subtitle={
            (featured.isComplete ? "Season complete" : "Season in progress") +
            " · tap an award for its full history" +
            (upcoming ? ` · ${upcoming} hasn't started yet` : "")
          }
        >
          {featured.hasPlayerScoring === false && (
            <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginBottom: 8 }}>
              Trader / Waiver / MVP / Rookie awards depend on per-player scoring that
              Sleeper didn't surface for this season — some awards may be skipped.
            </div>
          )}
          {(featured.awards || []).length === 0 ? (
            <EmptyState
              title="No awards yet"
              message="Awards will appear once the season has enough games / transactions / trades on record."
            />
          ) : (() => {
            const _all = featured.awards || [];
            const _players = _all.filter((a) => PLAYER_AWARD_KEYS.has(a.key));
            const _mgr = _all.filter((a) => !PLAYER_AWARD_KEYS.has(a.key));
            const _lbl = { fontSize: "0.7rem", fontWeight: 700, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--subtext)", margin: "2px 0 8px" };
            const _renderCard = (a) => {
                const histCount = (historyByKey.get(a.key) || []).length;
                const isBestTrade = a.key === "best_trade_of_the_year" && a.value?.trade;
                return (
                  <div
                    key={a.key}
                    role="button"
                    tabIndex={0}
                    onClick={() => setOpenKey(a.key)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setOpenKey(a.key);
                      }
                    }}
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius)",
                      padding: 12,
                      background: "rgba(15, 28, 59, 0.45)",
                      cursor: "pointer",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
                      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                        {a.label}
                      </div>
                      {histCount > 1 && (
                        <div style={{ fontSize: "0.58rem", color: "var(--subtext)" }}>
                          {histCount} yrs →
                        </div>
                      )}
                    </div>
                    <AwardWinner a={a} managers={managers} />
                    {a.value && (
                      <div style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--cyan)", marginTop: 6 }}>
                        {renderAwardValue(a.key, a.value)}
                      </div>
                    )}
                    {isBestTrade && (
                      <div style={{ marginTop: 8 }} onClick={(e) => e.stopPropagation()}>
                        <TradeCard trade={a.value.trade} managers={managers} onNavigate={onNavigate} />
                      </div>
                    )}
                    {a.description && (
                      <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 8, lineHeight: 1.4 }}>
                        {a.description}
                      </div>
                    )}
                    <div style={{ marginTop: 8, fontSize: "0.72rem", color: "var(--cyan)", fontWeight: 600 }}>
                      Award history →
                    </div>
                  </div>
                );
            };
            const _grid = (list) => (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 }}>
                {list.map(_renderCard)}
              </div>
            );
            return (
              <>
                {_mgr.length > 0 && (
                  <div style={{ marginBottom: _players.length > 0 ? 18 : 0 }}>
                    <div style={_lbl}>Manager &amp; Team Awards</div>
                    {_grid(_mgr)}
                  </div>
                )}
                {_players.length > 0 && (
                  <div>
                    <div style={_lbl}>Player Awards</div>
                    {_grid(_players)}
                  </div>
                )}
              </>
            );
          })()}
        </Card>
      )}

      {openKey && openMeta && typeof document !== "undefined" &&
        createPortal(
          <AwardHistoryModal
            awardKey={openKey}
            label={openMeta.label}
            description={openMeta.description}
            history={openHistory}
            managers={managers}
            onNavigate={onNavigate}
            onClose={() => setOpenKey(null)}
          />,
          document.body,
        )}
    </>
  );
}

export default AwardsSection;
