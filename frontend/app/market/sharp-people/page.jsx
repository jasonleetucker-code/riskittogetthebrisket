"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  Field,
  Input,
  Panel,
  PageHeader,
  Select,
  StatTile,
} from "@/components/ds";
import { LoadingState } from "@/components/ui";
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
        description="The researched dynasty-industry universe, independently labeled by curation, measured performance, and public trackability."
      />

      <Panel dense>
        <div style={{ display: "flex", gap: 28, flexWrap: "wrap", alignItems: "center" }}>
          {headline.map(([label, value]) => (
            <StatTile key={label} label={label} value={value ?? "—"} bare />
          ))}
          <div style={{ marginLeft: "auto", display: "flex", gap: 14, alignItems: "center" }}>
            <Link href="/market/sharp-tracker">Market signals</Link>
            <Link href="/admin/sharp-identities">Identity review</Link>
          </div>
        </div>
      </Panel>

      <Panel title="Filters" dense>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "end" }}>
          <Field label="Population">
            <Select
              value={membership}
              onChange={(event) => setMembership(event.target.value)}
              options={MEMBERSHIPS.map(([value, label]) => ({ value, label }))}
            />
          </Field>
          <Field label="Platform">
            <Select
              value={platform}
              onChange={(event) => setPlatform(event.target.value)}
              options={[
                ["all", "All platforms"],
                ["sleeper", "Sleeper verified"],
                ["ffpc", "FFPC verified"],
                ["x", "Public X handle"],
              ].map(([value, label]) => ({ value, label }))}
            />
          </Field>
          <Field label="Specialty">
            <Select
              value={specialty}
              onChange={(event) => setSpecialty(event.target.value)}
              options={SPECIALTIES.map(([value, label]) => ({ value, label }))}
            />
          </Field>
          <Field label="Identity">
            <Select
              value={identity}
              onChange={(event) => setIdentity(event.target.value)}
              options={IDENTITIES.map(([value, label]) => ({ value, label }))}
            />
          </Field>
          <Field label="Search" hint="Name, handle, affiliation…">
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search"
              style={{ minWidth: 220 }}
            />
          </Field>
          <Button type="button" variant="secondary" size="sm" loading={loading} onClick={load}>
            Refresh
          </Button>
        </div>
      </Panel>

      {loading && !payload ? <LoadingState message="Loading researched Sharp people…" /> : null}
      {error && !payload ? (
        <Banner tone="negative" title="Sharp people unavailable">
          {error}
        </Banner>
      ) : null}
      {!loading && !error && !people.length ? (
        <Banner tone="info" title="No people match these filters" />
      ) : null}

      <div style={{ display: "grid", gap: 10 }}>
        {people.map((person) => {
          const membershipState = person.membership_state || person.membershipState;
          const verifiedFantasy = (person.verifiedPlatformIdentities || []).filter((account) =>
            ["sleeper", "ffpc"].includes(account.platform),
          );
          return (
            <Panel key={person.person_id}>
              <div style={{ display: "flex", gap: 12, justifyContent: "space-between", flexWrap: "wrap" }}>
                <div style={{ minWidth: 220, flex: 1 }}>
                  <Link href={`/market/sharp-people/${encodeURIComponent(person.person_id)}`}>
                    <strong style={{ fontSize: "0.95rem" }}>
                      {person.public_display_name || person.canonical_name}
                    </strong>
                  </Link>
                  <div className="muted" style={{ fontSize: "0.68rem", marginTop: 3 }}>
                    {person.primary_public_handle || "No verified social handle"}
                    {person.current_affiliation ? ` · ${person.current_affiliation}` : ""}
                  </div>
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 8 }}>
                    {person.curated_industry_sharp ? <Badge tone="outline">Curated Industry</Badge> : null}
                    {person.algorithmically_qualified_sharp ? (
                      <Badge tone="outline">Performance-qualified</Badge>
                    ) : null}
                    {person.verified_super_sharp ? <Badge tone="accent">Super Sharp</Badge> : null}
                    {person.idp_specialist ? <Badge tone="outline">IDP</Badge> : null}
                    {person.devy_c2c_specialist ? <Badge tone="outline">Devy / C2C</Badge> : null}
                    {person.high_stakes_specialist ? <Badge tone="outline">High stakes</Badge> : null}
                    {verifiedFantasy.map((account) => (
                      <Badge key={account.account_id} tone="neutral">
                        {account.platform.toUpperCase()} verified
                      </Badge>
                    ))}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 22 }}>
                  <StatTile
                    label="Curated"
                    value={person.curated_expertise_score == null ? "—" : Number(person.curated_expertise_score).toFixed(0)}
                    bare
                  />
                  <StatTile
                    label="Trackability"
                    value={person.trackability_score == null ? "—" : Number(person.trackability_score).toFixed(0)}
                    bare
                  />
                  <StatTile
                    label="Influence"
                    value={
                      person.combined_influence == null
                        ? "—"
                        : Number(person.combined_influence * 100).toFixed(0)
                    }
                    bare
                  />
                </div>
              </div>
              <div className="muted" style={{ marginTop: 9, fontSize: "0.7rem", lineHeight: 1.5 }}>
                <strong style={{ color: "var(--text-primary)" }}>
                  {membershipState || person.candidate_status}
                </strong>
                {person.why_included ? ` · ${person.why_included}` : ""}
              </div>
            </Panel>
          );
        })}
      </div>
    </section>
  );
}
