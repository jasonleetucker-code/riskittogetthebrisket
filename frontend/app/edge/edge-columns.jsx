"use client";

/**
 * edge-columns — the shared DataTable column specs for /edge (R3).
 *
 * Every /edge section is the same table with a different column
 * subset, so the specs live here once. Extracted verbatim from the
 * pre-R3 hand-rolled column objects: the same accessors, the same
 * formatting, the same legacy badge/action-label classes (which stay
 * global until the R5 CSS purge, matching the R2 board's call).
 *
 * The only behavioral addition is sortability — these were static
 * tables before, so no sort semantics are being changed, only added.
 */

import { posBadgeClass, confBadgeClass, confBadgeLabel } from "@/lib/display-helpers";
import { actionLabel, cautionLabels } from "@/lib/edge-helpers";
import styles from "./edge.module.css";

const EM_DASH = "—";

export function colRank() {
  return {
    key: "rank",
    header: "#",
    numeric: true,
    sortable: true,
    accessor: (r) => r.rank ?? null,
    render: (r) => r.rank || EM_DASH,
  };
}

export function colPlayer(onPlayerClick) {
  return {
    key: "name",
    header: "Player",
    sortable: true,
    accessor: (r) => r.name || "",
    render: (r) => (
      <button
        type="button"
        className={styles.playerCell}
        onClick={() => onPlayerClick?.(r)}
        title={`Open ${r.name}`}
      >
        {r.name}
        {r.team ? <span className={styles.playerTeam}>{r.team}</span> : null}
      </button>
    ),
  };
}

export function colPos() {
  return {
    key: "pos",
    header: "Pos",
    sortable: true,
    accessor: (r) => r.pos || "",
    render: (r) => <span className={posBadgeClass(r)}>{r.pos}</span>,
  };
}

export function colValue() {
  return {
    key: "value",
    header: "Value",
    numeric: true,
    sortable: true,
    accessor: (r) => Math.round(r.rankDerivedValue || r.values?.full || 0) || null,
    render: (r) => {
      const val = Math.round(r.rankDerivedValue || r.values?.full || 0);
      return val > 0 ? val.toLocaleString() : EM_DASH;
    },
  };
}

export function colSpread() {
  return {
    key: "spread",
    header: "Spread",
    numeric: true,
    sortable: true,
    headerInfo: "How far apart the sources ranked this player (ordinal spread)",
    accessor: (r) => r.sourceRankSpread ?? null,
    render: (r) =>
      r.sourceRankSpread != null ? `±${r.sourceRankSpread}` : EM_DASH,
  };
}

/** IDP gap magnitude — the ordinal distance behind an IDP buy/sell
 *  signal. Pre-R3 this lived only in a title attribute even though it
 *  drove the section's ordering; surfacing it as a real column makes
 *  the sort visible and keeps the default order identical. */
export function colIdpGap() {
  return {
    key: "idpGap",
    header: "Gap",
    numeric: true,
    sortable: true,
    headerInfo: "Ordinal distance between IDPTC and the IDP-expert consensus",
    accessor: (r) => r.__idpGap ?? null,
    render: (r) => (r.__idpGap ? `${r.__idpGap}` : EM_DASH),
  };
}

export function colGapDirection() {
  return {
    key: "gap",
    header: "Higher",
    sortable: true,
    headerInfo: "Which market has this player higher",
    accessor: (r) => r.marketGapDirection || "",
    render: (r) => {
      if (r.marketGapDirection === "retail_premium") return "Sell";
      if (r.marketGapDirection === "consensus_premium") return "Buy";
      return <span className={styles.muted}>{EM_DASH}</span>;
    },
  };
}

export function colConfidence() {
  return {
    key: "conf",
    header: "Conf",
    align: "center",
    sortable: true,
    accessor: (r) => r.confidenceBucket || "",
    render: (r) => (
      <span className={confBadgeClass(r.confidenceBucket)}>
        {confBadgeLabel(r.confidenceBucket)}
      </span>
    ),
  };
}

export function colFlags() {
  return {
    key: "flags",
    header: "Flags",
    accessor: (r) => (r.anomalyFlags || []).join(", "),
    render: (r) => {
      const flags = (r.anomalyFlags || []).slice(0, 2).join(", ");
      return flags ? <span className={styles.flags}>{flags}</span> : EM_DASH;
    },
  };
}

export function colSignal() {
  return {
    key: "signal",
    header: "Signal",
    accessor: (r) => actionLabel(r)?.label || "",
    render: (r) => {
      const action = actionLabel(r);
      const cautions = cautionLabels(r);
      if (!action && cautions.length === 0) {
        return <span className={styles.muted}>{EM_DASH}</span>;
      }
      return (
        <span className={styles.signals}>
          {action && (
            <span className={`action-label ${action.css}`} title={action.title}>
              {action.label}
            </span>
          )}
          {cautions.map((c) => (
            <span key={c.label} className={`action-label ${c.css}`} title={c.title}>
              {c.label}
            </span>
          ))}
        </span>
      );
    },
  };
}
