"use client";

// AwardsSection — public /league tab view.
//
// Shows the featured season's awards (Champion + Manager of the Year
// pinned first by the backend).  Tap any award to open its full
// multi-season history.  Season rollover is automatic — the backend
// picks the featured season and keeps last season featured until the
// next one is underway.

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ds";
import { EmptyState, PlayerImage } from "@/components/ui";
import { captureElementImage } from "@/lib/capture-element-image";
import {
  Avatar,
  Card,
  EmptyCard,
  fmtNumber,
  fmtPercent,
  fmtPoints,
  renderAwardValue,
} from "../shared.jsx";
import { TradeCard } from "./activity.jsx";
import styles from "./awards.module.css";

// Award keys whose ``value`` payload carries a player. Player awards render
// one headshot; roster ownership is text so player/team identities never stack.
const PLAYER_AWARD_KEYS = new Set([
  "top_qb", "top_rb", "top_wr", "top_te", "top_k",
  "top_dl", "top_lb", "top_db",
  "league_mvp", "off_mvp", "def_mvp", "playoff_mvp", "off_roy", "def_roy",
]);

const PLAYER_AWARD_ORDER = [
  "league_mvp",
  "off_mvp",
  "def_mvp",
  "off_roy",
  "def_roy",
  "top_qb",
  "top_rb",
  "top_wr",
  "top_te",
  "top_dl",
  "top_lb",
  "top_db",
  "top_k",
];

const MANAGER_AWARD_ORDER = [
  "manager_of_the_year",
  "regular_season_crown",
  "points_king",
  "top_offense",
  "top_defense",
  "top_nfl_team",
  "weekly_hammer",
  "trader_of_the_year",
  "best_trade_of_the_year",
  "waiver_king",
  "mr_consistent",
  "silent_assassin",
  "bad_beat",
  "highest_single_week",
  "lowest_single_week",
  "best_rebuild",
  "rivalry_of_the_year",
  "champion",
];

const POSTSEASON_AWARD_KEYS = new Set(["playoff_mvp"]);
function ordered(items, order) {
  const position = new Map(order.map((key, index) => [key, index]));
  return [...items].sort(
    (a, b) =>
      (position.get(a.key) ?? order.length) -
      (position.get(b.key) ?? order.length),
  );
}

export function groupAwards(items = []) {
  return {
    players: ordered(
      items.filter(
        (item) =>
          PLAYER_AWARD_KEYS.has(item.key) &&
          !POSTSEASON_AWARD_KEYS.has(item.key),
      ),
      PLAYER_AWARD_ORDER,
    ),
    managers: ordered(
      items.filter((item) => !PLAYER_AWARD_KEYS.has(item.key)),
      MANAGER_AWARD_ORDER,
    ),
    postseason: ordered(
      items.filter((item) => POSTSEASON_AWARD_KEYS.has(item.key)),
      ["playoff_mvp"],
    ),
  };
}

function raceMetric(awardKey, value = {}) {
  switch (awardKey) {
    case "league_mvp":
    case "off_mvp":
    case "def_mvp":
    case "off_roy":
    case "def_roy":
    case "playoff_mvp":
      return `${fmtPoints(value.vorp)} VORP`;
    case "top_qb":
    case "top_rb":
    case "top_wr":
    case "top_te":
    case "top_k":
    case "top_dl":
    case "top_lb":
    case "top_db":
      return `${fmtPoints(value.starterPoints)} pts`;
    case "manager_of_the_year":
      return `${fmtNumber(value.compositeScore, 3)} score`;
    case "top_offense":
      return `${fmtNumber(value.offensePoints, 1)} pts`;
    case "top_defense":
      return `${fmtNumber(value.defensePoints, 1)} pts`;
    case "top_nfl_team":
      return `${fmtNumber(value.points, 1)} pts`;
    case "trader_of_the_year":
    case "waiver_king":
      return `+${fmtPoints(value.pointsGained)} pts`;
    case "weekly_hammer":
      return `${value.highScoreFinishes || 0} ${value.highScoreFinishes === 1 ? "wk" : "wks"}`;
    case "silent_assassin":
      return fmtPercent(value.winPct);
    case "bad_beat":
      return `${fmtPoints(value.points)} pts`;
    case "mr_consistent":
      return `CV ${fmtNumber(value.cv, 3)}`;
    default:
      return renderAwardValue(awardKey, value);
  }
}

function initialsFor(value) {
  return String(value || "")
    .split(/\s+/)
    .map((part) => part[0] || "")
    .join("")
    .slice(0, 2)
    .toUpperCase() || "?";
}

function RaceVisual({ isPlayer, leader, managers, size }) {
  const identity =
    (isPlayer && leader.value?.playerName) || leader.displayName || "";
  return (
    <span className={styles.leaderVisual}>
      <span className={styles.captureFallback} aria-hidden="true">
        {initialsFor(identity)}
      </span>
      <span className={styles.liveImage} data-html2canvas-ignore>
        {isPlayer ? (
          <PlayerImage
            playerId={leader.value?.playerId}
            team={leader.value?.team}
            position={leader.value?.position}
            name={leader.value?.playerName}
            size={size}
            showTeamFallback={false}
          />
        ) : leader.ownerId ? (
          <Avatar managers={managers} ownerId={leader.ownerId} size={size} />
        ) : null}
      </span>
    </span>
  );
}

// One ranked row in a race / finalists list.  Shared by the live
// "Award races" card and the per-year finalists in the history modal so
// both render an identical ranked board.
function LeaderRow({ awardKey, leader, managers, onNavigate, compact = false }) {
  const isPlayer = PLAYER_AWARD_KEYS.has(awardKey);
  const playerName = leader.value?.playerName;
  const identity = isPlayer && playerName ? playerName : leader.displayName;
  return (
    <li className={styles.leaderRow}>
      <span
        className={`${styles.leaderRank} ${leader.rank === 1 ? styles.leaderRankFirst : ""}`}
      >
        {leader.rank}
      </span>
      <RaceVisual
        isPlayer={isPlayer}
        leader={leader}
        managers={managers}
        size={compact ? 26 : 30}
      />
      <span className={styles.leaderIdentity}>
        {leader.ownerId && !isPlayer ? (
          <button
            type="button"
            className={styles.ownerLink}
            onClick={() => onNavigate("franchise", { owner: leader.ownerId })}
          >
            {identity}
          </button>
        ) : (
          <span className={styles.leaderName}>{identity}</span>
        )}
        {isPlayer && leader.displayName && (
          <span className={styles.ownerMeta}>Rostered by {leader.displayName}</span>
        )}
      </span>
      <span
        className={`${styles.metric} ${leader.rank === 1 ? styles.metricFirst : ""}`}
      >
        {raceMetric(awardKey, leader.value)}
      </span>
    </li>
  );
}

function AwardWinner({ a, managers, size = 24 }) {
  const isPlayer = PLAYER_AWARD_KEYS.has(a.key) && a.value?.playerId;
  return (
    <div className={styles.winner}>
      {isPlayer ? (
        <PlayerImage
          playerId={a.value.playerId}
          team={a.value.team}
          position={a.value.position}
          name={a.value.playerName}
          size={size + 8}
          showTeamFallback={false}
        />
      ) : a.ownerId ? (
        <Avatar managers={managers} ownerId={a.ownerId} size={size + 4} />
      ) : (
        <span />
      )}
      <div className={styles.winnerIdentity}>
        {isPlayer && a.value?.playerName ? (
          <>
            <div className={styles.winnerName}>
              {a.value.playerName}
              {a.value.position && (
                <span className={styles.winnerPosition}>
                  ({a.value.position})
                </span>
              )}
            </div>
            {a.displayName && (
              <div className={styles.winnerOwner}>Rostered by {a.displayName}</div>
            )}
          </>
        ) : (
          <>
            <div className={styles.winnerName}>{a.displayName || "—"}</div>
            {a.teamName && a.teamName !== a.displayName && (
              <div className={styles.winnerOwner}>{a.teamName}</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function AwardHistoryModal({ awardKey, label, description, history, managers, onNavigate, onClose }) {
  const [expanded, setExpanded] = useState(() => new Set());
  const toggle = (season) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(season)) next.delete(season);
      else next.add(season);
      return next;
    });

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
          {history.map(({ season, award, finalists }) => {
            const fin = finalists || [];
            const hasFinalists = fin.length > 1;
            const isOpen = expanded.has(season);
            return (
              <div
                key={season}
                style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}
              >
                <div
                  role={hasFinalists ? "button" : undefined}
                  tabIndex={hasFinalists ? 0 : undefined}
                  onClick={hasFinalists ? () => toggle(season) : undefined}
                  onKeyDown={
                    hasFinalists
                      ? (e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            toggle(season);
                          }
                        }
                      : undefined
                  }
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 8,
                    cursor: hasFinalists ? "pointer" : "default",
                  }}
                >
                  <div style={{ fontSize: "0.66rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}>
                    {season}
                  </div>
                  {hasFinalists && (
                    <div style={{ fontSize: "0.62rem", color: "var(--cyan)", fontWeight: 600 }}>
                      {isOpen ? "Hide finalists ▴" : `Finalists (${fin.length}) ▾`}
                    </div>
                  )}
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
                {hasFinalists && isOpen && (
                  <div
                    style={{
                      marginTop: 10,
                      borderTop: "1px solid var(--border)",
                      paddingTop: 10,
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                    }}
                  >
                    <div style={{ fontSize: "0.58rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                      {season} finalists
                    </div>
                    {fin.map((leader) => (
                      <LeaderRow
                        key={leader.ownerId || leader.value?.playerId || `${award.key}-${leader.rank}`}
                        awardKey={award.key}
                        leader={leader}
                        managers={managers}
                        onNavigate={onNavigate}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function RaceCard({ race, managers, onNavigate, featured = false }) {
  return (
    <article
      className={`${styles.raceCard} ${featured ? styles.featuredRace : ""}`}
      data-award-key={race.key}
    >
      <div className={styles.raceHeader}>
        <h4 className={styles.raceTitle}>{race.label}</h4>
        {featured && <span className={styles.liveMark}>Live</span>}
      </div>
      <ol className={styles.leaderList}>
        {race.leaders.slice(0, 3).map((leader) => (
          <LeaderRow
            key={leader.ownerId || leader.value?.playerId || `${race.key}-${leader.rank}`}
            awardKey={race.key}
            leader={leader}
            managers={managers}
            onNavigate={onNavigate}
            compact
          />
        ))}
      </ol>
    </article>
  );
}

function RaceGroup({ title, kicker, note, races, managers, onNavigate }) {
  if (!races.length) return null;
  return (
    <section className={styles.raceSection} aria-labelledby={`race-${kicker}`}>
      <div className={styles.sectionHeading}>
        <div>
          <div className={styles.sectionKicker}>{kicker}</div>
          <h3 className={styles.sectionTitle} id={`race-${kicker}`}>
            {title}
          </h3>
        </div>
        {note && <span className={styles.sectionNote}>{note}</span>}
      </div>
      <div className={styles.raceGrid}>
        {races.map((race) => (
          <RaceCard
            key={race.key}
            race={race}
            managers={managers}
            onNavigate={onNavigate}
            featured={race.key === "league_mvp"}
          />
        ))}
      </div>
    </section>
  );
}

function SavePreview({ url, onClose }) {
  if (!url) return null;
  return (
    <div
      className="screenshot-preview-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="Awards race snapshot preview"
      tabIndex={-1}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
      data-html2canvas-ignore
    >
      <div className="screenshot-preview-inner">
        <p className="screenshot-preview-hint">
          Hold the image &rarr; &ldquo;Save to Photos&rdquo;
        </p>
        <img
          src={url}
          alt="Awards race snapshot"
          className="screenshot-preview-img"
        />
        <button
          type="button"
          className="screenshot-preview-close"
          onClick={onClose}
        >
          Done
        </button>
      </div>
    </div>
  );
}

function AwardGroup({ kicker, title, meta, awards, renderAward, later = false }) {
  if (!awards.length) return null;
  return (
    <section className={`${styles.awardSection} ${later ? styles.laterSection : ""}`}>
      <div className={styles.awardSectionHeader}>
        <div>
          <div className={styles.sectionKicker}>{kicker}</div>
          <h3 className={styles.awardSectionTitle}>{title}</h3>
        </div>
        {meta && <span className={styles.awardSectionMeta}>{meta}</span>}
      </div>
      <div className={styles.awardGrid}>{awards.map(renderAward)}</div>
    </section>
  );
}

function AwardsSection({ managers, data, onNavigate }) {
  const seasons = data?.bySeason || [];
  const races = data?.awardRaces || [];
  const [openKey, setOpenKey] = useState(null);
  const [capturing, setCapturing] = useState(false);
  const [captureError, setCaptureError] = useState("");
  const [previewUrl, setPreviewUrl] = useState(null);
  const snapshotRef = useRef(null);

  useEffect(() => {
    document.body.classList.add("awards-snapshot-page");
    return () => document.body.classList.remove("awards-snapshot-page");
  }, []);

  // History per award key across every season (bySeason is newest-first).
  const historyByKey = useMemo(() => {
    const map = new Map();
    for (const s of seasons) {
      for (const a of s.awards || []) {
        if (!map.has(a.key)) map.set(a.key, []);
        map.get(a.key).push({
          season: s.season,
          award: a,
          finalists: s.finalists?.[a.key] || [],
        });
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
  const groupedRaces = groupAwards(races);

  function closePreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
  }

  async function saveSnapshot() {
    if (capturing || !snapshotRef.current) return;
    setCapturing(true);
    setCaptureError("");
    try {
      const season = data?.currentSeason || featuredName || "season";
      const result = await captureElementImage(snapshotRef.current, {
        filename: `chase-upside-awards-${season}-${new Date().toISOString().slice(0, 10)}.png`,
        title: `Chase Upside ${season} Awards Race Snapshot`,
      });
      if (result.kind === "preview") setPreviewUrl(result.url);
    } catch (error) {
      console.error("Awards snapshot failed:", error);
      setCaptureError("Could not save the snapshot. Please try again.");
    } finally {
      setCapturing(false);
    }
  }

  return (
    <>
      {races.length > 0 && (
        <Card
          title="Awards race snapshot"
          subtitle="The weekly leaderboard: player races first, manager and team honors below."
        >
          <div className={styles.toolbar} data-html2canvas-ignore>
            <p className={styles.toolbarCopy}>
              Save this board after each scoring week to keep a clean visual history of every race.
            </p>
            <Button
              className={styles.saveButton}
              variant="primary"
              size="sm"
              loading={capturing}
              onClick={saveSnapshot}
              icon={
                <span className={styles.saveIcon} aria-hidden="true">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M7 3h10l1.5 2H21v15H3V5h2.5L7 3Zm5 5.2a4.8 4.8 0 1 0 0 9.6 4.8 4.8 0 0 0 0-9.6Zm0 2a2.8 2.8 0 1 1 0 5.6 2.8 2.8 0 0 1 0-5.6Z" />
                  </svg>
                </span>
              }
            >
              Save weekly snapshot
            </Button>
          </div>
          {captureError && (
            <p className={styles.captureError} role="alert" data-html2canvas-ignore>
              {captureError}
            </p>
          )}
          <div className={styles.snapshot} ref={snapshotRef} data-awards-snapshot>
            <header className={styles.snapshotHeader}>
              <div>
                <div className={styles.eyebrow}>Chase Upside League</div>
                <h2 className={styles.snapshotTitle}>Awards Race</h2>
              </div>
              <div className={styles.snapshotMeta}>
                {data.currentSeason || featuredName} · season to date
              </div>
            </header>

            <RaceGroup
              kicker="01"
              title="Player Awards"
              note="Top three · realized starter value"
              races={groupedRaces.players}
              managers={managers}
              onNavigate={onNavigate}
            />
            <RaceGroup
              kicker="02"
              title="Manager & Team Awards"
              note="League performance and front-office honors"
              races={groupedRaces.managers}
              managers={managers}
              onNavigate={onNavigate}
            />
            <RaceGroup
              kicker="03"
              title="Later This Season"
              note="Postseason races stay out of the way until they matter"
              races={groupedRaces.postseason}
              managers={managers}
              onNavigate={onNavigate}
            />

            <footer className={styles.snapshotFooter}>
              <span>Top 3 in each active race</span>
              <span>chaseupside.com</span>
            </footer>
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
            const groups = groupAwards(featured.awards || []);
            const renderCard = (a) => {
                const histCount = (historyByKey.get(a.key) || []).length;
                const isBestTrade = a.key === "best_trade_of_the_year" && a.value?.trade;
                const isPlayer = PLAYER_AWARD_KEYS.has(a.key);
                return (
                  <div
                    key={a.key}
                    className={styles.awardCard}
                    role="button"
                    tabIndex={0}
                    onClick={() => setOpenKey(a.key)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setOpenKey(a.key);
                      }
                    }}
                  >
                    <div className={styles.awardCardTop}>
                      <div className={styles.awardLabel}>{a.label}</div>
                      {histCount > 1 && (
                        <div className={styles.historyCount}>
                          {histCount} yrs →
                        </div>
                      )}
                    </div>
                    <AwardWinner a={a} managers={managers} />
                    {a.value && (
                      <div className={styles.awardValue}>
                        {isPlayer ? raceMetric(a.key, a.value) : renderAwardValue(a.key, a.value)}
                      </div>
                    )}
                    {isBestTrade && (
                      <div style={{ marginTop: 8 }} onClick={(e) => e.stopPropagation()}>
                        <TradeCard trade={a.value.trade} managers={managers} onNavigate={onNavigate} />
                      </div>
                    )}
                    {a.description && (
                      <div className={styles.awardDescription}>
                        {a.description}
                      </div>
                    )}
                    <div className={styles.historyLink}>
                      Award history →
                    </div>
                  </div>
                );
            };
            return (
              <>
                <p className={styles.awardsIntro}>
                  Player honors lead the board. Open any award to see every winner and finalist by season.
                </p>
                <AwardGroup
                  kicker="First team"
                  title="Player Awards"
                  meta="MVPs → rookies → positions"
                  awards={groups.players}
                  renderAward={renderCard}
                />
                <AwardGroup
                  kicker="League honors"
                  title="Manager & Team Awards"
                  meta="Season performance and front-office results"
                  awards={groups.managers}
                  renderAward={renderCard}
                />
                <AwardGroup
                  kicker="Postseason"
                  title="Later This Season"
                  meta="Playoff honors stay secondary until the bracket begins"
                  awards={groups.postseason}
                  renderAward={renderCard}
                  later
                />
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
      <SavePreview url={previewUrl} onClose={closePreview} />
    </>
  );
}

export default AwardsSection;
