"use client";

/**
 * DesignGallery — every token ramp and component state, rendered live.
 * Composed exclusively from @/components/ds primitives + tokens; if
 * something can't be built cleanly here, the system is missing a piece.
 */
import React, { useState } from "react";
import {
  Badge,
  Banner,
  Button,
  DataTable,
  Drawer,
  EmptyState,
  Field,
  Icon,
  Input,
  Meter,
  Modal,
  Movement,
  Confidence,
  PageHeader,
  Panel,
  SegmentedControl,
  Select,
  Skeleton,
  SkeletonStat,
  SkeletonTable,
  Sparkline,
  StatTile,
  StatusIndicator,
  Tabs,
  tabId,
  tabPanelId,
  Tooltip,
} from "@/components/ds";
import styles from "./design.module.css";

/* ── sample data (display only) ── */
const SAMPLE_ROWS = [
  { id: 1, rank: 1, name: "Justin Jefferson", pos: "WR", team: "MIN", value: 9541, delta: 128, trend: [92, 93, 95, 94, 96, 97] },
  { id: 2, rank: 2, name: "Ja'Marr Chase", pos: "WR", team: "CIN", value: 9430, delta: -64, trend: [97, 96, 95, 95, 94, 94] },
  { id: 3, rank: 3, name: "Bijan Robinson", pos: "RB", team: "ATL", value: 9155, delta: 212, trend: [88, 90, 91, 93, 94, 95] },
  { id: 4, rank: 4, name: "CeeDee Lamb", pos: "WR", team: "DAL", value: 8890, delta: 0, trend: [91, 91, 92, 91, 91, 91] },
  { id: 5, rank: 5, name: "Jahmyr Gibbs", pos: "RB", team: "DET", value: 8720, delta: 305, trend: [84, 86, 88, 90, 92, 93] },
];

const SURFACES = [
  ["--surface-0", "page background"],
  ["--surface-1", "panel"],
  ["--surface-2", "nested / inputs"],
  ["--surface-3", "overlay"],
];
const TEXTS = [
  ["--text-primary", "primary · 15.7:1"],
  ["--text-secondary", "secondary · 8.4:1"],
  ["--text-tertiary", "tertiary · 5.9:1"],
  ["--text-disabled", "disabled · decorative"],
];
const ACCENTS = [
  ["--accent", "accent (franchise gold)"],
  ["--accent-hover", "hover"],
  ["--accent-pressed", "pressed"],
  ["--accent-muted", "muted wash"],
];
const SEMANTIC = [
  ["--positive", "positive"],
  ["--negative", "negative"],
  ["--warning", "warning"],
  ["--info", "info"],
];
const CHARTS = [1, 2, 3, 4, 5, 6];

const TYPE_SCALE = [
  ["2xs", "11px · micro labels"],
  ["xs", "12px · captions, badges"],
  ["sm", "13px · dense tables"],
  ["md", "14px · body"],
  ["lg", "16px · emphasized"],
  ["xl", "18px · panel headline"],
  ["2xl", "22px · page title"],
  ["3xl", "28px · hero stat"],
];

function Swatch({ token, note, height = 56 }) {
  return (
    <div className={styles.swatch}>
      <div
        className={styles.swatchChip}
        style={{ background: `var(${token})`, height }}
      />
      <div className={styles.swatchMeta}>
        <span className={styles.swatchName}>{token}</span>
        <span className={styles.swatchNote}>{note}</span>
      </div>
    </div>
  );
}

export default function DesignGallery() {
  const [segment, setSegment] = useState("7d");
  const [tab, setTab] = useState("tokens");
  const [density, setDensity] = useState("regular");
  const [modalOpen, setModalOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Design system"
        title="Design system"
        description="Premium Sports Intelligence: near-black cool neutrals, ONE franchise-gold accent reserved for interactive and identity roles, market direction on a CVD-validated blue/orange pair, near-zero radii, data in a tabular mono face. Every ramp and component state on this page is the live system — if it renders here, it is what ships."
        actions={<Badge tone="outline">docs/DESIGN-SYSTEM.md</Badge>}
      />

      {/* ── Color ─────────────────────────────────────────────────── */}
      <Panel
        title="Color"
        subtitle="Semantic aliases only — components never touch the neutral ramp or raw hex."
      >
        <div className={styles.stack}>
          <div>
            <p className={styles.demoLabel}>Surfaces (elevation by lightness)</p>
            <div className={`${styles.grid} ${styles.cols4}`}>
              {SURFACES.map(([t, n]) => (
                <Swatch key={t} token={t} note={n} />
              ))}
            </div>
          </div>
          <div>
            <p className={styles.demoLabel}>Text (contrast on --surface-1)</p>
            <div className={`${styles.grid} ${styles.cols4}`}>
              {TEXTS.map(([t, n]) => (
                <Swatch key={t} token={t} note={n} />
              ))}
            </div>
          </div>
          <div>
            <p className={styles.demoLabel}>The one accent</p>
            <div className={`${styles.grid} ${styles.cols4}`}>
              {ACCENTS.map(([t, n]) => (
                <Swatch key={t} token={t} note={n} />
              ))}
            </div>
          </div>
          <div>
            <p className={styles.demoLabel}>
              Market / state semantics (terminal-restrained, never neon)
            </p>
            <div className={`${styles.grid} ${styles.cols4}`}>
              {SEMANTIC.map(([t, n]) => (
                <Swatch key={t} token={t} note={n} />
              ))}
            </div>
          </div>
          <div>
            <p className={styles.demoLabel}>
              Chart series — CVD-validated fixed order, never cycled
            </p>
            <div className={`${styles.grid} ${styles.cols3}`}>
              {CHARTS.map((i) => (
                <Swatch key={i} token={`--chart-${i}`} note={`slot ${i}`} height={36} />
              ))}
            </div>
          </div>
        </div>
      </Panel>

      {/* ── Typography ────────────────────────────────────────────── */}
      <Panel
        title="Typography"
        subtitle="JetBrains Mono throughout, via next/font. Inter survives only inside .ds-prose — see the prose exception in tokens.css. Eight sizes, there is no ninth."
      >
        <div className={styles.stack}>
          {TYPE_SCALE.map(([size, note]) => (
            <div key={size} className={styles.typeRow}>
              <span className={styles.typeTag}>
                --font-size-{size} · {note.split(" · ")[0]}
              </span>
              <span
                style={{
                  fontSize: `var(--font-size-${size})`,
                  lineHeight: "var(--line-height-tight)",
                }}
              >
                {note.split(" · ")[1]} — the quick brown fox
              </span>
            </div>
          ))}
          <div className={styles.typeRow}>
            <span className={styles.typeTag}>--font-data + tabular</span>
            <span className="ds-mono" style={{ fontSize: "var(--font-size-sm)" }}>
              9,541 · 8,890 · 1,024.5 · −64 (columns align)
            </span>
          </div>
        </div>
      </Panel>

      {/* ── Space / radius / shadow ───────────────────────────────── */}
      <Panel
        title="Space, radius, elevation"
        subtitle="4px grid · four radii · three shadows. Motion: 120/180/280ms, zeroed under prefers-reduced-motion."
      >
        <div className={styles.stack}>
          <div>
            <p className={styles.demoLabel}>Spacing scale</p>
            <div className={styles.stack} style={{ gap: "var(--space-1)" }}>
              {[1, 2, 3, 4, 6, 8, 10].map((s) => (
                <div key={s} className={styles.row} style={{ gap: "var(--space-3)" }}>
                  <span className={styles.typeTag}>--space-{s}</span>
                  <span className={styles.spaceChip} style={{ width: `var(--space-${s})` }} />
                </div>
              ))}
            </div>
          </div>
          <div className={styles.row} style={{ gap: "var(--space-6)" }}>
            {["1", "2", "3", "full"].map((r) => (
              <div key={r} className={styles.stack} style={{ gap: "var(--space-1)", alignItems: "center" }}>
                <span className={styles.radiusChip} style={{ borderRadius: `var(--radius-${r})` }} />
                <span className={styles.swatchNote}>--radius-{r}</span>
              </div>
            ))}
            {["1", "2", "3"].map((s) => (
              <div key={s} className={styles.stack} style={{ gap: "var(--space-1)", alignItems: "center" }}>
                <span className={styles.shadowChip} style={{ boxShadow: `var(--shadow-${s})` }}>
                  shadow-{s}
                </span>
              </div>
            ))}
          </div>
        </div>
      </Panel>

      {/* ── Buttons + form ────────────────────────────────────────── */}
      <div className={`${styles.grid} ${styles.cols2}`}>
        <Panel title="Buttons" subtitle="One primary per view region.">
          <div className={styles.stack}>
            <div className={styles.row}>
              <Button variant="primary">Propose trade</Button>
              <Button variant="secondary">Export</Button>
              <Button variant="ghost">Reset</Button>
              <Button variant="danger">Delete board</Button>
            </div>
            <div className={styles.row}>
              <Button variant="primary" size="sm">Primary sm</Button>
              <Button variant="secondary" size="sm" icon={<Icon name="search" size={12} />}>
                With icon
              </Button>
              <Button variant="secondary" loading>Saving</Button>
              <Button variant="primary" disabled>Disabled</Button>
            </div>
          </div>
        </Panel>

        <Panel title="Form controls" subtitle="Field wires label, hint, error, aria.">
          <div className={styles.stack}>
            <Field label="Search players" hint="Name or team">
              <Input placeholder="e.g. Jefferson" />
            </Field>
            <Field label="FAAB bid" error="Must be a number">
              <Input defaultValue="forty" data-numeric="" />
            </Field>
            <Field label="Position">
              <Select
                defaultValue="WR"
                options={[
                  { value: "QB" },
                  { value: "RB" },
                  { value: "WR" },
                  { value: "TE" },
                ]}
              />
            </Field>
            <div>
              <p className={styles.demoLabel}>SegmentedControl (radiogroup, arrow keys)</p>
              <SegmentedControl
                label="Window"
                value={segment}
                onChange={setSegment}
                options={[{ value: "1d" }, { value: "7d" }, { value: "30d" }]}
              />
            </div>
          </div>
        </Panel>
      </div>

      {/* ── Signals ───────────────────────────────────────────────── */}
      <Panel
        title="Signals"
        subtitle="Movement = direction + magnitude + confidence. Direction is never color alone."
      >
        <div className={styles.stack}>
          <div className={styles.row}>
            <Badge>WR</Badge>
            <Badge tone="accent">Tier 1</Badge>
            <Badge tone="positive">Buy</Badge>
            <Badge tone="negative">Sell</Badge>
            <Badge tone="warning">Volatile</Badge>
            <Badge tone="info">Rookie</Badge>
            <Badge tone="outline">KTC</Badge>
          </div>
          <div className={styles.row}>
            <StatusIndicator status="positive">All sources fresh</StatusIndicator>
            <StatusIndicator status="warning">DLF stale (26h)</StatusIndicator>
            <StatusIndicator status="negative">Scrape failed</StatusIndicator>
            <StatusIndicator status="neutral">KTC stub</StatusIndicator>
          </div>
          <div className={styles.row} style={{ gap: "var(--space-6)" }}>
            <Movement delta={340} confidence={0.9} />
            <Movement delta={-128} confidence={0.5} />
            <Movement delta={62} confidence={0.15} />
            <Movement delta={0} />
            <Movement delta={12.5} />
          </div>
          <div className={styles.row} style={{ gap: "var(--space-6)" }}>
            {/* Confidence annotates values that have no DIRECTION. Note
                the first pair: a confident value renders NOTHING, which
                is the point — the marker's presence is the signal, so a
                healthy page stays quiet. */}
            <span>
              9,541 <Confidence confidence={0.95} />
            </span>
            <span>
              4,120 <Confidence confidence={0.5} limitedBy="role" />
            </span>
            <span>
              ~800 <Confidence confidence={0.12} limitedBy="sample size" />
            </span>
            <span>
              9,541 <Confidence confidence={0.95} showWhen="always" />
            </span>
          </div>
        </div>
      </Panel>

      {/* ── Stat tiles ────────────────────────────────────────────── */}
      <Panel title="Stat tiles" subtitle="One KPI primitive; values in the data face.">
        <div className={`${styles.grid} ${styles.cols4}`}>
          <StatTile
            label="Roster value"
            value="48,210"
            movement={<Movement delta={340} confidence={0.8} />}
            meta="7d"
          />
          <StatTile label="League rank" value="#2" meta="of 12" />
          <StatTile
            label="Draft capital"
            value="6,120"
            movement={<Movement delta={-95} confidence={0.4} />}
            meta="7d"
          />
          <StatTile label="Open trades" value="3" />
        </div>
      </Panel>

      {/* ── DataTable ─────────────────────────────────────────────── */}
      <Panel
        flush
        title="DataTable"
        subtitle="Sortable (aria-sort), sticky header, density modes, tabular numerics."
        actions={
          <SegmentedControl
            label="Density"
            value={density}
            onChange={setDensity}
            options={[
              { value: "regular", label: "Regular" },
              { value: "compact", label: "Compact" },
            ]}
          />
        }
      >
        <DataTable
          caption="Sample value board: rank, player, position, value, 7-day movement and trend"
          density={density}
          defaultSort={{ key: "value", direction: "desc" }}
          rows={SAMPLE_ROWS}
          columns={[
            { key: "rank", header: "Rk", numeric: true, sortable: true, width: 48 },
            { key: "name", header: "Player", sortable: true },
            {
              key: "pos",
              header: "Pos",
              render: (r) => <Badge>{r.pos}</Badge>,
            },
            { key: "team", header: "Team" },
            { key: "value", header: "Value", numeric: true, sortable: true,
              render: (r) => r.value.toLocaleString("en-US") },
            {
              key: "delta",
              header: "7d",
              numeric: true,
              sortable: true,
              render: (r) => <Movement delta={r.delta} />,
            },
            {
              key: "trend",
              header: "Trend",
              render: (r) => (
                <Sparkline values={r.trend} label={`${r.name} 6-week trend`} series={1} />
              ),
            },
          ]}
        />
      </Panel>

      {/* ── Tabs ──────────────────────────────────────────────────── */}
      <Panel title="Tabs" subtitle="Tablist semantics, roving focus, overflow scrolls.">
        <Tabs
          idPrefix="gallery"
          label="Gallery sections"
          active={tab}
          onChange={setTab}
          tabs={[
            { id: "tokens", label: "Tokens" },
            { id: "market", label: "Market" },
            { id: "rosters", label: "Rosters" },
            { id: "history", label: "History" },
          ]}
        />
        <div
          role="tabpanel"
          id={tabPanelId("gallery", tab)}
          aria-labelledby={tabId("gallery", tab)}
          style={{ paddingTop: "var(--space-4)", color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}
        >
          Active panel: {tab}
        </div>
      </Panel>

      {/* ── Overlays / loading / empty / banners ──────────────────── */}
      <div className={`${styles.grid} ${styles.cols2}`}>
        <Panel title="Overlays" subtitle="Focus trap, Escape, restore-on-close.">
          <div className={styles.row}>
            <Button variant="secondary" onClick={() => setModalOpen(true)}>
              Open modal
            </Button>
            <Button variant="secondary" onClick={() => setDrawerOpen(true)}>
              Open drawer
            </Button>
            <Tooltip content="Blended value across all enabled sources, 0–9999 scale.">
              <Button variant="ghost" icon={<Icon name="info" size={14} />}>
                Tooltip (hover / focus)
              </Button>
            </Tooltip>
          </div>
        </Panel>

        <Panel title="Skeletons" subtitle="Px-sized to content — zero layout shift.">
          <div className={styles.stack}>
            <div className={styles.row}>
              <Skeleton width={140} height={16} />
              <Skeleton width={64} height={16} />
            </div>
            <div className={`${styles.grid} ${styles.cols2}`}>
              <SkeletonStat />
              <SkeletonStat />
            </div>
          </div>
        </Panel>
      </div>

      <Panel flush title="Table loading state">
        <SkeletonTable rows={4} columns={6} />
      </Panel>

      <div className={`${styles.grid} ${styles.cols2}`}>
        <Panel flush title="Empty state">
          <EmptyState
            title="No arbitrage found"
            description="When board value and market value disagree by enough to act on, opportunities appear here."
            action={<Button variant="secondary" size="sm">Adjust thresholds</Button>}
          />
        </Panel>
        <Panel title="Banners" subtitle="warning/negative announce as alerts.">
          <div className={styles.stack}>
            <Banner tone="info" title="Scrape scheduled">
              Next refresh at 04:00 UTC.
            </Banner>
            <Banner tone="warning" title="Data is stale">
              Last successful scrape finished 26 hours ago.
            </Banner>
            <Banner tone="negative" onDismiss={() => {}}>
              KTC fetch failed — serving last snapshot.
            </Banner>
            <Banner tone="positive">Board exported.</Banner>
          </div>
        </Panel>
      </div>

      {/* ── Small charts ──────────────────────────────────────────── */}
      <Panel
        title="Small charts"
        subtitle="Sparkline + Meter. Larger charts compose lib/chart-primitives with the --chart-* slots."
      >
        <div className={styles.stack}>
          <div className={styles.row} style={{ gap: "var(--space-6)" }}>
            <Sparkline values={[20, 24, 22, 30, 34, 33, 40]} label="Value trend, rising" width={140} height={32} />
            <Sparkline values={[40, 38, 39, 31, 28, 26, 22]} label="Value trend, falling" series={3} width={140} height={32} />
            <Sparkline values={[10, 14, 8, 16, 12, 18, 13]} label="Volatile trend with zero baseline" series={2} width={140} height={32} baseline={12} />
          </div>
          <div className={styles.stack} style={{ maxWidth: 420 }}>
            <Meter value={9541} max={10000} label="Jefferson value" />
            <Meter value={6120} max={10000} label="Draft capital" series={2} />
            <Meter value={2870} max={10000} label="Bench depth" series={4} />
          </div>
        </div>
      </Panel>

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Confirm trade proposal">
        <div className={styles.stack}>
          <p style={{ margin: 0, color: "var(--text-secondary)", fontSize: "var(--font-size-sm)" }}>
            Send Jefferson + 2027 2nd for Chase + 2026 1st? This posts the offer to your league.
          </p>
          <div className={styles.row} style={{ justifyContent: "flex-end" }}>
            <Button variant="ghost" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => setModalOpen(false)}>Send offer</Button>
          </div>
        </div>
      </Modal>

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title="Justin Jefferson">
        <div className={styles.stack}>
          <div className={`${styles.grid} ${styles.cols2}`}>
            <StatTile bare label="Value" value="9,541" movement={<Movement delta={128} confidence={0.9} />} />
            <StatTile bare label="Overall" value="#1" meta="WR1" />
          </div>
          <Sparkline values={[88, 90, 91, 93, 96, 97]} label="Jefferson 6-week value trend" width={360} height={48} />
          <Banner tone="info">Drawer replaces PlayerPopup in R2.</Banner>
        </div>
      </Drawer>
    </div>
  );
}
