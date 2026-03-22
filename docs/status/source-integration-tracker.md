# Source Integration Tracker

_Updated: 2026-03-22 (scarcity tuned to 0.20 + founder review packet)_

## Pipeline

```
Source CSVs → Adapter → Identity Resolution (initial collapsing + suffix cleanup)
  → Canonical Blend (14 sources, weight v4)
  → Position Enrichment (legacy + nickname + supplemental + IDP infer = 82.0%)
  → Scarcity Adjustment (dampened 20% VAR, 1003 assets)
  → Player Calibration (offense=8500, IDP=5000, K≤600)
  → Pick Calibration (legacy curve)
  → Canonical Snapshot
```

## Key Metrics

| Metric | Value | Int-Primary | Pub-Primary |
|--------|-------|-------------|-------------|
| Sources | 14 | ✓ (≥4) | ✓ (≥6) |
| Assets | 1239 | — | — |
| Position coverage | 82.0% | — | — |
| Scarcity-adjusted | 1003 | — | — |
| Multi-source blend | **61%** | ✓ (≥40) | ✓ (≥60) |
| Off players top-50 | **80%** | ✓ (≥70) | ✓ (≥80) |
| Off players top-100 | **81%** | ✓ (≥65) | ✓ (≥75) |
| Off players tier | **50.5%** | ✓ (≥50) | ✗ (≥65) |
| Off players delta | **1071** | ✓ (≤1500) | ✗ (≤800) |
| **Internal-primary** | **9/10** | ✓ | — |
| **Public-primary** | **8/12** | — | ✗ |
