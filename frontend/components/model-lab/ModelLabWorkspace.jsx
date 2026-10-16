"use client";

/**
 * ModelLabWorkspace — the client half of /admin/model-lab (IC-6).
 *
 * One GET (`useModelLab`), two views: the family list, and one family's
 * detail selected by `?family=<id>` (shareable, back-button friendly).
 *
 * States, each distinct (contract §9 — never collapsed into one another):
 *   loading      skeleton, only while nothing has been shown yet
 *   forbidden    a signed-in non-admin: the backend's 403, rendered by the
 *                shared FailureState — no retry, no crash
 *   auth         signed out (401)
 *   failure      any other refusal, classified by `lib/contract-failure`
 *   refresh fail the failure as a banner ABOVE the content already shown
 *   empty        the Lab answered and lists no family
 *   unknown id   a `?family=` the payload does not contain
 */

import React, { Suspense, lazy } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Panel } from "@/components/ds/Panel";
import { CollapsiblePanel } from "@/components/ds/CollapsiblePanel";
import { Button } from "@/components/ds/Button";
import { Banner } from "@/components/ds/Banner";
import { EmptyState } from "@/components/ds/EmptyState";
import { FailureState } from "@/components/ds/FailureState";
import { SkeletonTable } from "@/components/ds/Skeleton";
import {
  READ_ONLY_NOTE,
  builderErrors,
  familiesOf,
  findFamily,
  isFamilyId,
  notCovered,
} from "@/lib/model-lab";
import { useModelLab } from "./useModelLab";
import { EvidenceValue } from "./EvidenceValue";
import { FamilyList, MODEL_LAB_HREF } from "./FamilyList";
import styles from "./model-lab.module.css";

const FamilyDetail = lazy(() => import("./FamilyDetail"));

function DetailLoading() {
  return (
    <div className={styles.loading} aria-busy="true" aria-label="Loading model family">
      <SkeletonTable rows={6} columns={4} />
    </div>
  );
}

function ContextStrip({ data, loading, onRefresh }) {
  return (
    <div className={styles.contextStrip}>
      <dl className={styles.inlineFacts}>
        <dt>Built</dt>
        <dd>
          <EvidenceValue value={data.generatedAt ?? { state: "unobserved", reason: "no build time in the payload" }} />
        </dd>
        <dt>Schema</dt>
        <dd>
          <code className={styles.code}>{String(data.schema ?? "unstated")}</code>
        </dd>
        <dt>Learning receipts</dt>
        <dd>
          <EvidenceValue value={data.receiptStore ?? { state: "unobserved", reason: "the payload carries no receipt-store block" }} />
        </dd>
      </dl>
      <Button size="sm" variant="secondary" onClick={onRefresh} loading={loading} disabled={loading}>
        Refresh
      </Button>
    </div>
  );
}

function NotCovered({ rows }) {
  if (!rows.length) return null;
  return (
    <CollapsiblePanel title="Not covered by the Lab yet" headingLevel={2} defaultCollapsed>
      <dl className={styles.facts}>
        {rows.map((r, i) => (
          <React.Fragment key={`${r.domain}-${i}`}>
            <dt>{String(r.domain ?? "unnamed domain")}</dt>
            <dd>
              <EvidenceValue value={r.reason} />
            </dd>
          </React.Fragment>
        ))}
      </dl>
    </CollapsiblePanel>
  );
}

function BuilderErrors({ rows }) {
  if (!rows.length) return null;
  return (
    <Banner tone="warning" title="Some model families could not be assembled">
      <ul className={styles.plainList}>
        {rows.map((r) => (
          <li key={r.family}>
            <code className={styles.code}>{r.family}</code>: {r.error}
          </li>
        ))}
      </ul>
    </Banner>
  );
}

export default function ModelLabWorkspace() {
  const params = useSearchParams();
  const requested = params?.get("family") || "";
  const { data, failure, loading, refetch } = useModelLab();

  if (!data) {
    if (failure) {
      return <FailureState failure={failure} onRetry={refetch} variant="block" context="Model Lab" />;
    }
    return (
      <div className={styles.loading} aria-busy="true" aria-label="Loading the Model Lab">
        <SkeletonTable rows={7} columns={5} />
      </div>
    );
  }

  const families = familiesOf(data) || [];
  let body;
  if (requested) {
    const family = isFamilyId(requested) ? findFamily(data, requested) : null;
    body = family ? (
      <Suspense fallback={<DetailLoading />}>
        <FamilyDetail family={family} labStates={data.labStates} />
      </Suspense>
    ) : (
      <EmptyState
        title="No such model family"
        description={`The Model Lab lists no family named “${requested}”.`}
        action={<Link href={MODEL_LAB_HREF}>All model families</Link>}
      />
    );
  } else if (families.length === 0) {
    body = (
      <EmptyState
        title="No model families listed"
        description="The Model Lab answered, but it lists no model families."
      />
    );
  } else {
    body = (
      <>
        <Panel
          title="Model families"
          subtitle="Champion, challengers and the recorded decision for each family. Open a family for its evidence."
          headingLevel={2}
          flush
        >
          <FamilyList payload={data} />
        </Panel>
        <NotCovered rows={notCovered(data)} />
      </>
    );
  }

  return (
    <div className={styles.workspace}>
      <p className={styles.panelNote} data-testid="read-only-banner">
        {READ_ONLY_NOTE}
      </p>
      <ContextStrip data={data} loading={loading} onRefresh={refetch} />
      {failure ? (
        <FailureState failure={failure} onRetry={refetch} variant="banner" context="Model Lab refresh" />
      ) : null}
      <BuilderErrors rows={builderErrors(data)} />
      {body}
    </div>
  );
}
