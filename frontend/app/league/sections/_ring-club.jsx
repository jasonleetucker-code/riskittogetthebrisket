"use client";

// RingClubCard — the public History tab's honor roll of NFL players with
// two or more verified Brisket Dynasty championship rings (owner directive
// 2026-11-23, "BUILD THE RING CLUB").
//
// Renders `sections.history.ringClub` exactly as the backend published it:
// members arrive sorted (most rings first, ties alphabetical) with their
// shared `rank` and `tied` flag, `prestige` marks the deeper tier of the
// SAME club, and `emptyState` already carries the right message for "no
// multi-champions", "coverage incomplete" and "no championships yet".
// Nothing here sorts, ranks, counts or picks an empty-state message.
//
// Lives inside the History tab's lazy chunk (imported by history.jsx only),
// so it never reaches the /league page chunk.

import Link from "next/link";
import { PlayerImage } from "@/components/ui";
import { Avatar, Card } from "../shared.jsx";
import {
  RING_CLUB_SUBTITLE,
  RING_CLUB_TITLE,
  coverageNotes,
  playerIdentityParts,
  rankLabel,
  ringCount,
  ringsAriaLabel,
  seasonLabels,
  trophyRun,
} from "@/lib/ring-club";
import styles from "./ring-club.module.css";

function CardTitle({ title }) {
  return (
    <>
      <span aria-hidden="true">🏆</span> {title}
    </>
  );
}

/** The ring count: the number, then one 🏆 per ring, read as one label. */
function RingCount({ rings }) {
  const n = ringCount(rings);
  return (
    <span className={styles.ringCount} role="img" aria-label={ringsAriaLabel(n)}>
      <span className={styles.ringNumber}>{n}</span>
      <span className={styles.trophies}>{trophyRun(n)}</span>
    </span>
  );
}

/** One championship's franchise: season, avatar, team name, manager. */
function FranchiseLabel({ championship, managers }) {
  const c = championship || {};
  return (
    <>
      <span className={styles.franchiseSeason}>{c.season}</span>
      {c.ownerId && managers ? <Avatar managers={managers} ownerId={c.ownerId} size={20} /> : null}
      <span className={styles.franchiseTeam}>{c.teamName || "—"}</span>
      {c.displayName ? <span className={styles.franchiseManager}>{c.displayName}</span> : null}
    </>
  );
}

function Member({ member, managers, onNavigate }) {
  const id = member.playerId == null ? "" : String(member.playerId).trim();
  const name = member.playerName || "Unknown player";
  const parts = playerIdentityParts(member);
  const rank = rankLabel(member);
  const seasons = seasonLabels(member.seasons);
  const championships = Array.isArray(member.championships) ? member.championships : [];
  const prestige = member.prestige === true;
  return (
    <li
      className={prestige ? `${styles.member} ${styles.memberPrestige}` : styles.member}
      data-prestige={prestige ? "true" : undefined}
    >
      <span className={styles.rank} title={member.tied === true ? `Tied for rank ${member.rank}` : undefined}>
        {rank ?? ""}
      </span>
      <PlayerImage
        playerId={id || undefined}
        team={member.nflTeam || undefined}
        position={member.position || undefined}
        name={name}
        size={44}
      />
      <div className={styles.identity}>
        <div className={styles.name}>
          {/* Public hub → the public player journey, never the private
              Player File (#1337).  No id → plain text, never a guess. */}
          {id ? (
            <Link
              href={`/league/player/${encodeURIComponent(id)}`}
              prefetch={false}
              className={`ds-player-name ${styles.nameLink}`}
            >
              {name}
            </Link>
          ) : (
            <span>{name}</span>
          )}
          {parts.map((part) => (
            <span key={part} className={styles.meta}>
              {" — "}
              {part}
            </span>
          ))}
        </div>
        <div className={styles.line}>
          <span className={styles.lineLabel}>Championship Rings: </span>
          <RingCount rings={member.rings} />
        </div>
        {seasons.length > 0 && (
          <div className={styles.line}>
            <span className={styles.lineLabel}>Championship Seasons: </span>
            {seasons.join(", ")}
          </div>
        )}
        {championships.length > 0 && (
          <ul className={styles.franchiseList} aria-label={`${name}'s championship franchises`}>
            {championships.map((c, i) => (
              <li key={`${c.season}-${c.ownerId || i}`} className={styles.franchiseItem}>
                {c.ownerId && typeof onNavigate === "function" ? (
                  <button
                    type="button"
                    className={styles.franchiseButton}
                    onClick={() => onNavigate("franchise", { owner: c.ownerId })}
                  >
                    <FranchiseLabel championship={c} managers={managers} />
                  </button>
                ) : (
                  <span className={styles.franchiseStatic}>
                    <FranchiseLabel championship={c} managers={managers} />
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

export default function RingClubCard({ ringClub, managers, onNavigate }) {
  if (!ringClub || typeof ringClub !== "object") return null;
  const members = Array.isArray(ringClub.members) ? ringClub.members : [];
  const empty = ringClub.emptyState && typeof ringClub.emptyState === "object" ? ringClub.emptyState : null;
  // Members, or the backend's own empty-state message — nothing else to show.
  if (!members.length && !empty) return null;

  const title = ringClub.title || RING_CLUB_TITLE;
  const { verifiedLine, incompleteLine } = coverageNotes(ringClub.coverage);

  return (
    <Card id="ring-club" title={<CardTitle title={title} />} subtitle={ringClub.subtitle || RING_CLUB_SUBTITLE}>
      {ringClub.description && <p className={styles.description}>{ringClub.description}</p>}
      {members.length > 0 ? (
        <ol className={styles.members} aria-label={title}>
          {members.map((m, i) => (
            <Member key={m.playerId || `${m.playerName}-${i}`} member={m} managers={managers} onNavigate={onNavigate} />
          ))}
        </ol>
      ) : (
        <p className={styles.emptyMessage} data-empty-kind={empty?.kind || undefined}>
          {empty?.message}
        </p>
      )}
      {(verifiedLine || incompleteLine) && (
        <div className={styles.coverage}>
          {verifiedLine && <p>{verifiedLine}</p>}
          {incompleteLine && <p>{incompleteLine}</p>}
        </div>
      )}
    </Card>
  );
}
