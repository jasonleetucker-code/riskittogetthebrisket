// Pick inventory chips — shared by the Draft tab, the Franchise tab and the
// server-rendered franchise page, so all three label a pick the same way.
//
// No hooks: safe in both server and client components.  The backend owns the
// facts (``src/public_league/draft.py::pick_inventory``); this only renders
// them.  Each chip names the pick's ORIGIN ("Own" / "From <manager>") because
// several picks can share a year and round — "2027 R1" alone cannot tell a
// manager's own first from one acquired from someone else.

import {
  PICK_OWNERSHIP_UNAVAILABLE,
  PICK_OWNERSHIP_UNAVAILABLE_LABEL,
  describePickOwnershipReason,
} from "@/lib/pick-ownership";

/** Why a public draft payload's pick ownership is unknown, or ``null``. */
export function draftOwnershipUnavailableReason(payload) {
  if (!payload || payload.pickOwnershipState !== PICK_OWNERSHIP_UNAVAILABLE) return null;
  return payload.pickOwnershipReason || "pick_ownership_unstated";
}

/** Stable React key: the canonical asset id, else the pick's identity. */
export function pickChipKey(p) {
  return p.assetId || `${p.season}-${p.round}-${p.originRosterId ?? p.originalOwnerId ?? ""}`;
}

/** "Own" / "From Kich" — falls back for payloads that predate origin labels. */
export function pickOriginText(p) {
  if (p.originLabel) return p.originLabel;
  return p.isTraded ? "Acquired" : "Own";
}

export function PickChips({ picks, size = "md" }) {
  const small = size === "sm";
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: small ? 4 : 6 }} data-testid="pick-chips">
      {picks.map((p) => (
        <span
          key={pickChipKey(p)}
          data-asset-id={p.assetId || undefined}
          title={`${p.label} — ${pickOriginText(p)}`}
          style={{
            fontFamily: "var(--mono)",
            fontSize: small ? "0.7rem" : "0.72rem",
            border: "1px solid var(--border)",
            padding: small ? "2px 6px" : "3px 8px",
            borderRadius: 4,
            color: p.isTraded ? "var(--amber)" : "var(--text)",
            maxWidth: "100%",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {p.label}
          <span style={{ opacity: 0.75 }}> · {pickOriginText(p)}</span>
        </span>
      ))}
    </div>
  );
}

export function PickChipsLegend({ children }) {
  return (
    <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 6 }}>
      Amber = acquired from another manager; each pick names its original owner.
      {children}
    </div>
  );
}

export function PickOwnershipUnavailableNote({ reason, withheld }) {
  return (
    <div role="status" style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
      <strong style={{ color: "var(--text)" }}>{PICK_OWNERSHIP_UNAVAILABLE_LABEL}.</strong>{" "}
      {describePickOwnershipReason(reason)}{" "}
      {withheld || "Pick counts are withheld rather than shown as if every team held only its own picks."}
    </div>
  );
}
