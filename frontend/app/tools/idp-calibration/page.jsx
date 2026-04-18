"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { PageHeader } from "@/components/ui";
import { useAuthContext } from "@/app/AppShellWrapper";
import LeagueInputForm from "./LeagueInputForm";
import AdvancedSettingsDrawer from "./AdvancedSettingsDrawer";
import ResultsDashboard from "./ResultsDashboard";
import SavedRunsList from "./SavedRunsList";
import ProductionConfigPanel from "./ProductionConfigPanel";
import { useCalibration } from "./useCalibration";
import {
  downloadAnchorCsv,
  downloadBucketCsv,
  downloadRunJson,
} from "./exports";

export default function IdpCalibrationLabPage() {
  const router = useRouter();
  const { authenticated, checking } = useAuthContext();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState(null);

  const {
    status,
    runs,
    production,
    currentRun,
    loading,
    error,
    refreshStatus,
    refreshRuns,
    refreshProduction,
    analyze,
    loadRun,
    promote,
  } = useCalibration();

  useEffect(() => {
    if (checking) return;
    if (authenticated === false) {
      router.push("/login?next=/tools/idp-calibration");
    }
  }, [checking, authenticated, router]);

  useEffect(() => {
    if (authenticated) {
      refreshStatus();
      refreshRuns();
      refreshProduction();
    }
  }, [authenticated, refreshStatus, refreshRuns, refreshProduction]);

  const warnings = useMemo(() => currentRun?.warnings || [], [currentRun]);

  if (checking || authenticated == null) {
    return (
      <div className="idp-lab-page">
        <PageHeader title="IDP Calibration Lab" subtitle="Checking session…" />
      </div>
    );
  }
  if (authenticated === false) {
    return null;
  }

  return (
    <div className="idp-lab-page">
      <PageHeader
        title="IDP Calibration Lab"
        subtitle="Internal tooling. Analyses are never promoted until you explicitly click Promote to production."
        actions={
          <div className="idp-lab-header-actions">
            {status?.production_present && (
              <span className="badge">production: active</span>
            )}
            {status?.latest_run_id && (
              <span className="muted text-sm">
                latest run{" "}
                <code className="text-sm">{status.latest_run_id}</code>
              </span>
            )}
          </div>
        }
      />

      <LeagueInputForm
        onAnalyze={({ testLeagueId, myLeagueId }) =>
          analyze({ testLeagueId, myLeagueId, settings })
        }
        onOpenSettings={() => setSettingsOpen(true)}
        loading={loading.analyze}
      />

      <AdvancedSettingsDrawer
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        initial={settings || currentRun?.settings}
        onSave={setSettings}
      />

      {(error.analyze || error.runs || error.production || error.promote) && (
        <div className="card idp-lab-error">
          {error.analyze && <p>Analyze: {error.analyze}</p>}
          {error.runs && <p>Runs: {error.runs}</p>}
          {error.production && <p>Production: {error.production}</p>}
          {error.promote && <p>Promote: {error.promote}</p>}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="card idp-lab-warning">
          <strong>Warnings ({warnings.length})</strong>
          <ul>
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {currentRun && (
        <div className="idp-lab-toolbar">
          <button
            type="button"
            className="button"
            onClick={() => downloadRunJson(currentRun)}
          >
            Export run JSON
          </button>
          <button
            type="button"
            className="button"
            onClick={() => downloadBucketCsv(currentRun)}
          >
            Export buckets CSV
          </button>
          <button
            type="button"
            className="button"
            onClick={() => downloadAnchorCsv(currentRun)}
          >
            Export anchors CSV
          </button>
        </div>
      )}

      <ResultsDashboard run={currentRun} />

      <ProductionConfigPanel
        production={production}
        currentRun={currentRun}
        onPromote={promote}
        loading={loading.promote}
        error={error.promote}
      />

      <SavedRunsList
        runs={runs}
        currentRunId={currentRun?.run_id}
        onOpen={(runId) => loadRun(runId)}
      />
    </div>
  );
}
