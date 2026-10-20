"use client";

// One team's side of the trade: what it sends and where each asset goes,
// plus — for 3+ team trades — what it receives and from whom, so the whole
// routing is readable team by team.  Identities and labels only.

import { Panel } from "@/components/ds/Panel";
import { Button } from "@/components/ds/Button";
import { Select } from "@/components/ds/Select";
import { Icon } from "@/components/ds/Icon";
import { slotName, teamLabel } from "@/lib/trade-advisor";
import styles from "./trade-advisor.module.css";

export function AdvisorTeamPanel({
  index,
  team,
  rosterId,
  legs,
  incoming = [],
  slots,
  teams,
  teamCount,
  staleIds,
  onAdd,
  onRemove,
  onRoute,
  focusTargets = null,
}) {
  const name = teamLabel(team) || slotName(index);
  const isYou = index === 0;
  const title = isYou ? "Your team sends" : `${name} sends`;
  const nameOf = (rid) => {
    const t = (teams || []).find((x) => x.rosterId === rid);
    return rid === slots[0] ? "your team" : teamLabel(t) || `Team ${rid}`;
  };
  const destinations = slots
    .filter((rid) => rid != null && rid !== rosterId)
    .map((rid) => {
      const t = (teams || []).find((x) => x.rosterId === rid);
      return { value: String(rid), label: rid === slots[0] ? `${teamLabel(t)} (your team)` : teamLabel(t) };
    });

  return (
    <Panel
      dense
      headingLevel={3}
      title={<span className={styles.panelTitleName}>{title}</span>}
      subtitle={isYou ? name : slotName(index)}
      data-testid={`advisor-panel-${index}`}
    >
      {legs.length === 0 ? (
        <p className={styles.emptyLegs}>Nothing added yet.</p>
      ) : (
        <ul className={styles.legs} aria-label={title}>
          {legs.map((leg) => (
            <li key={leg.id} className={styles.leg}>
              <span className={styles.legLabel}>
                {leg.label}
                {staleIds?.has(leg.id) ? (
                  <span className={styles.legFlag}>No longer on this roster — remove it to continue.</span>
                ) : null}
                {teamCount === 2 && leg.to != null ? (
                  <span className={styles.legMeta}>
                    <Icon name="arrow-right" size={12} /> to {nameOf(leg.to)}
                  </span>
                ) : null}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className={styles.removeBtn}
                onClick={() => onRemove(leg.id)}
                aria-label={`Remove ${leg.label}`}
                ref={(el) => focusTargets?.set(`remove:${leg.id}`, el)}
              >
                Remove
              </Button>
              {teamCount > 2 ? (
                <label className={styles.legRoute}>
                  <span className={styles.label}>Send {leg.label} to</span>
                  <Select
                    value={leg.to == null ? "" : String(leg.to)}
                    onChange={(e) => onRoute(leg.id, e.target.value === "" ? null : Number(e.target.value))}
                    aria-invalid={leg.to == null ? true : undefined}
                    options={[{ value: "", label: "Choose a team", disabled: true }, ...destinations]}
                  />
                </label>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <Button
        className={styles.addBtn}
        onClick={onAdd}
        aria-haspopup="dialog"
        ref={(el) => focusTargets?.set(`add:${rosterId}`, el)}
      >
        + Add player or pick
      </Button>
      {teamCount > 2 ? (
        <div className={styles.incoming}>
          <h4 className={styles.incomingHead}>{isYou ? "Your team receives" : `${name} receives`}</h4>
          {incoming.length === 0 ? (
            <p className={styles.emptyLegs}>Nothing routed here yet.</p>
          ) : (
            <ul className={styles.incomingList}>
              {incoming.map((leg) => (
                <li key={leg.id}>
                  {leg.label} <span className={styles.legMeta}>from {nameOf(leg.from)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </Panel>
  );
}
