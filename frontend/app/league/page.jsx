"use client";

import { useState } from "react";
import { SubNav, PageHeader, EmptyState } from "@/components/ui";

/**
 * League Hub — multi-sub-tab league analysis page.
 * Sub-tabs: Power Rankings, Team Breakdown, Comparison, Trade DB, Waiver DB, Draft Capital.
 * Each sub-tab will be implemented in Phase 2.
 */
const SUB_TABS = [
  { key: "power", label: "Power Rankings" },
  { key: "breakdown", label: "Team Breakdown" },
  { key: "compare", label: "Comparison" },
  { key: "tradeDb", label: "Trade DB" },
  { key: "waiverDb", label: "Waiver DB" },
  { key: "capital", label: "Draft Capital" },
];

const PLACEHOLDERS = {
  power: { title: "Power Rankings", message: "Positional heatmap showing team strength across all positions." },
  breakdown: { title: "Team Breakdown", message: "Detailed roster breakdown by position group with value bars." },
  compare: { title: "Team Comparison", message: "Head-to-head comparison of two teams across every position." },
  tradeDb: { title: "KTC Trade Database", message: "Crowdsourced trade results searchable by player name." },
  waiverDb: { title: "KTC Waiver Database", message: "Crowdsourced waiver pickups searchable by player name." },
  capital: { title: "Draft Capital", message: "Auction-dollar pick values with ownership from Sleeper." },
};

export default function LeaguePage() {
  const [activeTab, setActiveTab] = useState("power");
  const placeholder = PLACEHOLDERS[activeTab] || PLACEHOLDERS.power;

  return (
    <section>
      <div className="card">
        <PageHeader
          title="League"
          subtitle="League-wide analysis — power rankings, team breakdowns, comparisons, and draft capital."
        />
        <SubNav items={SUB_TABS} active={activeTab} onChange={setActiveTab} />
        <EmptyState
          title={placeholder.title}
          message={`${placeholder.message} Coming soon in Phase 2 migration.`}
        />
      </div>
    </section>
  );
}
