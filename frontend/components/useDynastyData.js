"use client";

import { useEffect, useMemo, useState } from "react";
import { buildRows, fetchDynastyData, getSiteKeys } from "@/lib/dynasty-data";

export function useDynastyData() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [source, setSource] = useState("");
  const [rawData, setRawData] = useState(null);

  useEffect(() => {
    let active = true;
    async function run() {
      try {
        setLoading(true);
        setError("");
        const payload = await fetchDynastyData();
        if (!active) return;
        setRawData(payload?.data || null);
        setSource(String(payload?.source || ""));
      } catch (err) {
        if (!active) return;
        setError(err?.message || "Failed to load data");
      } finally {
        if (active) setLoading(false);
      }
    }
    run();
    return () => {
      active = false;
    };
  }, []);

  const rows = useMemo(() => buildRows(rawData || {}), [rawData]);
  const siteKeys = useMemo(() => getSiteKeys(rawData || {}), [rawData]);

  return {
    loading,
    error,
    source,
    rawData,
    rows,
    siteKeys,
  };
}
