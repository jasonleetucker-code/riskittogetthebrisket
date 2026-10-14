"use client";

/**
 * trade-ktc-import.jsx — the "Import KTC" URL row.
 *
 * Split out of ./trade-sections.jsx so /trade can load it on demand
 * (React.lazy in app/trade/page.jsx): it renders only after the user presses Import KTC.
 * Pure presentation, moved verbatim — no trade math lives here.
 */

import { Banner, Button, Input, Panel } from "@/components/ds";
import styles from "./trade.module.css";

// ── KTC import ────────────────────────────────────────────────────────

export function KtcImportPanel({
  url,
  onUrlChange,
  busy,
  error,
  onSubmit,
  onCancel,
}) {
  return (
    <Panel
      title="Import from KeepTradeCut"
      headingLevel={2}
      subtitle="Replaces sides A and B; extra sides (3+ team trades) are left untouched."
    >
      <div className={styles.importRow}>
        <Input
          className={styles.importInput}
          type="text"
          placeholder="https://keeptradecut.com/trade-calculator?teamOne=…&teamTwo=…"
          value={url}
          onChange={(e) => onUrlChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !busy) onSubmit();
            if (e.key === "Escape") onCancel();
          }}
          disabled={busy}
          aria-label="KeepTradeCut trade-calculator URL"
          autoFocus
        />
        <Button
          variant="primary"
          onClick={onSubmit}
          disabled={busy || !url.trim()}
          loading={busy}
        >
          Load trade
        </Button>
        <Button onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
      <p className={styles.suggestMeta} style={{ marginTop: "var(--space-2)" }}>
        Unknown KTC IDs and players we can&apos;t match by name are reported here.
      </p>
      {error ? (
        <Banner tone="negative" title="Import failed">
          {error}
        </Banner>
      ) : null}
    </Panel>
  );
}
