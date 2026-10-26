/**
 * "Their trade history" disclosure on a generated-trade card.
 *
 * Renders the backend's `managerEvidence` block (owner
 * `src/intel/manager_scout.py::offer_evidence`) through
 * `offerEvidenceLines`. Descriptive counts only: no fit grade, no label,
 * no acceptance likelihood. A non-measured block shows one line saying why.
 *
 * ``defaultOpen``: a caller that renders this only after the user explicitly
 * asked for it (the /trade "Show … trade history" button) opens it, so the
 * answer is not hidden behind a second click. Generated-trade cards keep it
 * collapsed.
 */
import { offerEvidenceLines } from "@/lib/manager-evidence";
import styles from "./manager-evidence.module.css";

export default function ManagerEvidence({
  evidence,
  team,
  defaultOpen = false,
}) {
  const { available, lines, note } = offerEvidenceLines(evidence);
  if (!available) return <p className={styles.note}>{note}</p>;
  return (
    <details className={styles.evidence} open={defaultOpen || undefined}>
      <summary>
        {team ? `${team}: trade history` : "Their trade history"}
      </summary>
      <ul>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <p className={styles.note}>{note}</p>
    </details>
  );
}
