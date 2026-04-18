"use client";

/**
 * AnchorChart — minimal SVG line chart for a single position.
 *
 * Draws three monotone curves (intrinsic / market / final) over the
 * anchor ranks. Pure SVG — no external chart library so we stay
 * aligned with the repo's vanilla-React / vanilla-CSS convention.
 */
export default function AnchorChart({ position, anchors }) {
  if (!anchors) return null;
  const intrinsic = anchors?.intrinsic?.[position] || [];
  const market = anchors?.market?.[position] || [];
  const final = anchors?.final?.[position] || [];
  const allPoints = [...intrinsic, ...market, ...final];
  if (!allPoints.length) {
    return (
      <div className="card idp-lab-chart-empty muted">
        No anchor data for {position}.
      </div>
    );
  }
  const maxRank = Math.max(1, ...allPoints.map((p) => p.rank));
  const maxValue = Math.max(
    1.0,
    ...allPoints.map((p) => Number(p.value) || 0),
  );
  const width = 320;
  const height = 140;
  const padX = 32;
  const padY = 14;

  function projectX(rank) {
    return padX + ((rank - 1) / Math.max(1, maxRank - 1)) * (width - 2 * padX);
  }
  function projectY(value) {
    const v = Math.max(0, Math.min(maxValue, Number(value) || 0));
    return height - padY - (v / maxValue) * (height - 2 * padY);
  }
  function toPath(points) {
    if (!points.length) return "";
    return points
      .map(
        (p, i) =>
          `${i === 0 ? "M" : "L"} ${projectX(p.rank).toFixed(2)} ${projectY(p.value).toFixed(2)}`,
      )
      .join(" ");
  }

  const series = [
    { name: "intrinsic", points: intrinsic, color: "var(--cyan, #4ec9ff)" },
    { name: "market", points: market, color: "var(--amber, #e4a12e)" },
    { name: "final", points: final, color: "var(--green, #7bd389)" },
  ];

  return (
    <div className="card idp-lab-chart">
      <div className="idp-lab-chart-header">
        <span className="idp-lab-chart-title">{position} anchors</span>
        <div className="idp-lab-chart-legend">
          {series.map((s) => (
            <span key={s.name} className="idp-lab-chart-legend-item">
              <span
                className="idp-lab-chart-legend-swatch"
                style={{ background: s.color }}
              />
              {s.name}
            </span>
          ))}
        </div>
      </div>
      <svg
        role="img"
        aria-label={`${position} anchor curves`}
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
      >
        <line
          x1={padX}
          x2={width - padX}
          y1={projectY(1)}
          y2={projectY(1)}
          stroke="var(--border, #333)"
          strokeDasharray="4 4"
        />
        {series.map((s) => (
          <path
            key={s.name}
            d={toPath(s.points)}
            fill="none"
            stroke={s.color}
            strokeWidth="2"
          />
        ))}
        {series.map((s) =>
          s.points.map((p, i) => (
            <circle
              key={`${s.name}-${i}`}
              cx={projectX(p.rank)}
              cy={projectY(p.value)}
              r="2.5"
              fill={s.color}
            />
          )),
        )}
      </svg>
      <div className="idp-lab-chart-axis">
        <span>rank 1</span>
        <span>rank {maxRank}</span>
      </div>
    </div>
  );
}
