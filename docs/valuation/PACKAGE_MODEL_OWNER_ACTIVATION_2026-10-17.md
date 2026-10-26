# Package Value Adjustment activation — owner decision 2026-10-17

**Decision:** The owner explicitly approved activating the new geometric Value Adjustment method after the sitewide integration and model comparison. Promote `geom_q078_v1` with fixed `q = 0.78` as the default package-equity model. Retain `ktc_2026_04` as a reversible shadow comparator/rollback.

**Evidence limitation acknowledged:** The challenger passes the reported 530,000-case package benchmark and structural tests (monotonicity, symmetry, scaling). It moderates the ordinary 1–4-piece star-side tendency, but remains strongly stud-biased in deep stud-for-depth packages. The point-in-time own-league completed-trade residuals (15 KTC-priced and 21 IDPTC-priced trades) split by price source; the larger box-local Sharp/KTC archive remains an uncompleted independent validation. This is an **owner-authorized promotion despite incomplete independent evidence**, not a claim that the geometric method is proved most accurate.

**Implementation:** `config/trade/package_model.json` and `frontend/lib/trade-logic.js::ACTIVE_PACKAGE_MODEL_ID` change together. Python and JS receipts must identify the geometric model, while explicit `model_id=ktc_2026_04` continues to reproduce historical KTC results. Existing `packageModel` stamps preserve model provenance; trade-history aging must refuse to compare cross-model snapshots.

**Release safety:** Do not merge on a red gate. Validate affected KTC-default fixtures, all package verdict consumers, public league grades, Second Opinions, Trade History, cross-model aging, and desktop/mobile UI before deployment. Revisit the 3% fairness band, the provisional ±200 aging band, finder thresholds and explanatory copy that were calibrated under KTC. If any fail, repair or label unvalidated; do not silently alter unrelated valuation models.

**After deploy:** Verify live `packageModel.id` and matched JS client output are `geom_q078_v1`, and test positive-only VA examples on both front and back ends. Monitor discrepancies and keep rollback one scoped change back to `ktc_2026_04`. Continue independent held-out trade evaluation of q=0.78 vs q=0.80–0.85 and the hybrid challenger; neither is auto-promoted.

**Scope:** Package comparison math only; do not change standalone dynasty values, KTC Market's native comparison lens, or roster utility/availability.
