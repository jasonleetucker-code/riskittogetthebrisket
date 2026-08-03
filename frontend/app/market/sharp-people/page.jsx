"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { apiErrorMessage } from "@/lib/api-error";

const MEMBERSHIPS = [
  ["all", "All researched people"],
  ["curated", "Curated Industry Sharps"],
  ["performance", "Algorithmically Qualified"],
  ["super", "Super Sharps"],
  ["both", "Curated + performance"],
  ["research", "Research candidates"],
];
const SPECIALTIES = [
  ["all", "All specialties"],
  ["idp", "IDP"],
  ["devy", "Devy / C2C"],
  ["high_stakes", "High stakes"],
  ["analyst", "Analysts / rankers"],
];
const IDENTITIES = [
  ["all", "All identity states"],
  ["verified", "Verified fantasy identity"],
  ["trackable", "Publicly trackable"],
  ["untrackable", "No verified fantasy identity"],
  ["review", "Needs identity review"],
];

function Badge({ children }) {
  return (
    <span
      style={{
        border: "1px solid var(--border-default)",
        borderRadius: 999,
        padding: "2px 7px",
        fontSize: "0.62rem",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function Score({ label, value }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: "0.62rem", textTransform: "uppercase" }}>
        {label}
      </div>
      <strong>{value == null ? "—" : Number(value).toFixed(0)}</strong>
    </div>
  );
}

export default function SharpPeoplePage() {
  const [membership, setMembership] = useState("curated");
  const [platform, setPlatform] = useState("all");
  const [specialty, setSpecialty] = useState("all");
  const [identity, setIdentity] = useState("all");
  const [search, setSearch] = useState("");
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        membership,
        platform,
        specialty,
        identity,
        search,
        limit: "500",
      });
      const response = await fetch(`/api/sharp/people?${params}`, { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiErrorMessage(body, response.status));
      setPayload(body);
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [identity, membership, platform, search, specialty]);

  useEffect(() => {
    const timer = window.setTimeout(load, 180);
    return () => window.clearTimeout(timer);
  }, [load]);

  const summary = payload?.summary?.membership || {};
  const people = payload?.people || [];
  const headline = useMemo(
    () => [
      ["Curated", summary.curated_people],
      ["Super Sharps", summary.super_sharps],
      ["Performance", summary.performance_qualified_people],
      ["Both", summary.both],
    ],
    [summary],
  );

  return (
    <section>
      <PageHeader
        title="Sharp People"
        subtitle="The researched dynasty-industry universe, independently labeled by curation, measured performance, and public trackability."
      />

      <div className="card" style={{ display: "flex", gap: 28, flexWrap: "wrap", marginBottom: 12 }}>
        {headline.map(([label, value]) => (
          <div key={label}>
            <div className="muted" style={{ fontSize: "0.64rem", textTransform: "uppercase" }}>
              {label}
            </div>
            <div style={{ fontSize: "1.35rem", fontWeight: 700 }}>{value ?? "—"}</div>
          </div>
        ))}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          <Link href="/market/sharp-tracker">Market signals</Link>
          <Link href="/admin/sharp-identities">Identity review</Link>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "end" }}>
          <label>
            Population<br />
            <select value={membership} onChange={(event) => setMembership(event.target.value)}>
              {MEMBERSHIPS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            Platform<br />
            <select value={platform} onChange={(event) => setPlatform(event.target.value)}>
              <option value="all">All platforms</option>
              <option value="sleeper">Sleeper verified</option>
              <option value="ffpc">FFPC verified</option>
              <option value="x">Public X handle</option>
            </select>
          </label>
          <label>
            Specialty<br />
            <select value={specialty} onChange={(event) => setSpecialty(event.target.value)}>
              {SPECIALTIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            Identity<br />
            <select value={identity} onChange={(event) => setIdentity(event.target.value)}>
              {IDENTITIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label style={{ minWidth: 220, flex: 1 }}>
            Search<br />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name, handle, affiliation…"
              style={{ width: "100%" }}
            />
          </label>
          <button type="button" onClick={load} disabled={loading}>
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {loading && !payload ? <LoadingState message="Loading researched Sharp people…" /> : null}
      {error && !payload ? <div className="card"><EmptyState title="Sharp people unavailable" message={error} /></div> : null}
      {!loading && !error && !people.length ? <div className="card"><EmptyState title="No people match these filters" /></div> : null}

      <div style={{ display: "grid", gap: 10 }}>
        {people.map((person) => {
          const membershipState = person.membership_state || person.membershipState;
          const verifiedFantasy = (person.verifiedPlatformIdentities || []).filter((account) =>
            ["sleeper", "ffpc"].includes(account.platform),
          );
          return (
            <article key={person.person_id} className="card">
              <div style={{ display: "flex", gap: 12, justifyContent: "space-between", flexWrap: "wrap" }}>
                <div style={{ minWidth: 220, flex: 1 }}>
                  <Link href={`/market/sharp-people/${encodeURIComponent(person.person_id)}`}>
                    <strong style={{ fontSize: "0.95rem" }}>{person.public_display_name || person.canonical_name}</strong>
                  </Link>
                  <div className="muted" style={{ fontSize: "0.68rem", marginTop: 3 }}>
                    {person.primary_public_handle || "No verified social handle"}
                    {person.current_affiliation ? ` · ${person.current_affiliation}` : ""}
                  </div>
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 8 }}>
                    {person.curated_industry_sharp ? <Badge>Curated Industry</Badge> : null}
                    {person.algorithmically_qualified_sharp ? <Badge>Performance-qualified</Badge> : null}
                    {person.verified_super_sharp ? <Badge>Super Sharp</Badge> : null}
                    {person.idp_specialist ? <Badge>IDP</Badge> : null}
                    {person.devy_c2c_specialist ? <Badge>Devy / C2C</Badge> : null}
                    {person.high_stakes_specialist ? <Badge>High stakes</Badge> : null}
                    {verifiedFantasy.map((account) => (
                      <Badge key={account.account_id}>{account.platform.toUpperCase()} verified</Badge>
                    ))}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 22 }}>
                  <Score label="Curated" value={person.curated_expertise_score} />
                  <Score label="Trackability" value={person.trackability_score} />
                  <Score label="Influence" value={person.combined_influence == null ? null : person.combined_influence * 100} />
                </div>
              </div>
              <div className="muted" style={{ marginTop: 9, fontSize: "0.7rem", lineHeight: 1.5 }}>
                <strong style={{ color: "var(--text-primary)" }}>{membershipState || person.candidate_status}</strong>
                {person.why_included ? ` · ${person.why_included}` : ""}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
