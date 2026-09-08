"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Banner, Panel, PageHeader, StatTile } from "@/components/ds";
import { LoadingState } from "@/components/ui";
import { apiErrorMessage } from "@/lib/api-error";

export default function SharpPersonPage({ params }) {
  const [personId, setPersonId] = useState(null);
  const [person, setPerson] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.resolve(params).then((resolved) => setPersonId(resolved.personId));
  }, [params]);

  useEffect(() => {
    if (!personId) return;
    fetch(`/api/sharp/people/${encodeURIComponent(personId)}`, { cache: "no-store" })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(apiErrorMessage(body, response.status));
        setPerson(body);
      })
      .catch((err) => setError(apiErrorMessage(err)));
  }, [personId]);

  if (error) {
    return (
      <section>
        <PageHeader title="Sharp profile" />
        <Banner tone="negative" title="Profile unavailable">
          {error}
        </Banner>
      </section>
    );
  }
  if (!person) return <LoadingState message="Loading Sharp profile…" />;

  return (
    <section>
      <PageHeader
        title={person.public_display_name || person.canonical_name}
        description={[person.primary_public_handle, person.current_affiliation]
          .filter(Boolean)
          .join(" · ")}
      />
      <div style={{ marginBottom: 10 }}>
        <Link href="/market/sharp-people">← All Sharp people</Link>
      </div>

      <Panel>
        <div style={{ display: "flex", gap: 22, flexWrap: "wrap" }}>
          <StatTile label="Membership" value={person.membership_state || "—"} bare />
          <StatTile
            label="Curated expertise"
            value={person.curated_expertise_score ?? "—"}
            bare
          />
          <StatTile label="Trackability" value={person.trackability_score ?? "—"} bare />
          <StatTile
            label="Data completeness"
            value={
              person.performanceMetrics?.[0]?.data_completeness == null
                ? "Unknown"
                : `${Math.round(person.performanceMetrics[0].data_completeness * 100)}%`
            }
            bare
          />
        </div>
        <p className="muted" style={{ lineHeight: 1.55, marginTop: 12 }}>
          {person.why_included || person.evidence_of_skill || person.candidate_status}
        </p>
      </Panel>

      <Panel title="Verified public identities">
        {(person.verifiedPlatformIdentities || []).length ? (
          <div style={{ display: "grid", gap: 8 }}>
            {person.verifiedPlatformIdentities.map((account) => (
              <div key={account.account_id}>
                <strong>{String(account.platform).toUpperCase()}</strong> ·{" "}
                {account.username || account.display_name || account.platform_user_id}
                <div className="muted" style={{ fontSize: "0.68rem" }}>
                  {account.verification_method} · confidence{" "}
                  {Math.round((account.verification_confidence || 0) * 100)}%
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="muted">
            No verified fantasy-platform identity. Curated membership is still retained.
          </div>
        )}
      </Panel>

      <Panel title="Empirical dynasty performance">
        {(person.performanceMetrics || []).length ? (
          person.performanceMetrics.map((metric) => (
            <div key={metric.metric_id} style={{ marginBottom: 8 }}>
              {metric.league_type} · {metric.seasons_observed ?? "?"} seasons · win rate{" "}
              {metric.winning_percentage == null
                ? "unknown"
                : `${(metric.winning_percentage * 100).toFixed(1)}%`}{" "}
              · championships {metric.championships ?? "unknown"}
            </div>
          ))
        ) : (
          <div className="muted">
            No measurable platform history is linked. No neutral win rate or synthetic championship record is assigned.
          </div>
        )}
      </Panel>

      <Panel title="Public evidence">
        <div style={{ display: "grid", gap: 8 }}>
          {(person.evidence || []).map((evidence, index) => (
            <div key={`${evidence.source_url || "evidence"}-${index}`}>
              {evidence.source_url ? (
                <a href={evidence.source_url} target="_blank" rel="noreferrer">
                  {evidence.description || evidence.source_url}
                </a>
              ) : (
                evidence.description
              )}
              <div className="muted" style={{ fontSize: "0.68rem" }}>
                {evidence.evidence_type}
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </section>
  );
}
