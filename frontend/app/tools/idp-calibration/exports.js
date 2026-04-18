"use client";

function triggerDownload(blob, filename) {
  if (typeof window === "undefined") return;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function downloadRunJson(run) {
  if (!run) return;
  const blob = new Blob([JSON.stringify(run, null, 2)], {
    type: "application/json",
  });
  triggerDownload(blob, `idp-calibration-${run.run_id || "run"}.json`);
}

function csvEscape(value) {
  if (value == null) return "";
  const s = String(value);
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export function downloadBucketCsv(run) {
  if (!run) return;
  const lines = [
    [
      "position",
      "bucket",
      "count",
      "intrinsic",
      "market",
      "final",
    ].join(","),
  ];
  const multipliers = run.multipliers || {};
  for (const pos of ["DL", "LB", "DB"]) {
    const posBlock = multipliers[pos];
    if (!posBlock?.buckets) continue;
    for (const b of posBlock.buckets) {
      lines.push(
        [
          pos,
          b.label,
          b.count ?? 0,
          b.intrinsic ?? 0,
          b.market ?? 0,
          b.final ?? 0,
        ]
          .map(csvEscape)
          .join(","),
      );
    }
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  triggerDownload(blob, `idp-calibration-buckets-${run.run_id || "run"}.csv`);
}

export function downloadAnchorCsv(run) {
  if (!run) return;
  const lines = [
    ["kind", "position", "rank", "value"].join(","),
  ];
  const anchors = run.anchors || {};
  for (const kind of ["intrinsic", "market", "final"]) {
    const kindBlock = anchors[kind] || {};
    for (const pos of ["DL", "LB", "DB"]) {
      const points = kindBlock[pos];
      if (!Array.isArray(points)) continue;
      for (const p of points) {
        lines.push(
          [kind, pos, p.rank, p.value].map(csvEscape).join(","),
        );
      }
    }
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  triggerDownload(blob, `idp-calibration-anchors-${run.run_id || "run"}.csv`);
}
