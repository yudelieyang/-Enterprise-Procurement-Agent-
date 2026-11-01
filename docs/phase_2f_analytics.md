# Phase 2F — Deterministic Procurement Analytics

## Purpose and boundary

Phase 2F provides three small, typed analytics functions over SQLite/SQLAlchemy facts. They do not choose tools, query policy PDFs, call the Compliance Engine, create recommendations, forecast, or execute arbitrary Python.

SQL remains the first choice for ordinary `SUM`, `COUNT`, grouping, filtering, ranking, window functions, and Pareto. Analytics is reserved for deterministic spend-driver decomposition, robust comparable-item price analysis, and single-source risk calculation.

## Spend growth and drivers

`analyze_spend_growth()` compares two explicit date windows for one supplier, considering only `ISSUED` and `CLOSED` POs. It returns Decimal-safe spend, counts, average PO values, absolute/percentage change, category change contributions, and the largest current-period POs.

For a nonzero comparison base, percentage change is `(current - comparison) / comparison * 100`. If the comparison base is zero, percentage change is `null`; `growth_basis` distinguishes `ZERO_BASE_CURRENT_SPEND` from `ZERO_BASE_NO_SPEND`. The result describes record-level factors only, never business causation.

For SUP-042, H1 2025 to H1 2026 is USD 120,000 to USD 390,000: USD 270,000 / 225% growth, three to seven POs, and average PO value USD 40,000 to USD 55,714.29. Category changes reconcile to the total: IT Services +USD 170,000 and Software Licenses +USD 100,000. The top current POs are `PO-2026-1843`, `PO-2026-1842`, and `PO-2026-1861`.

## Price outliers

`analyze_price_outliers()` draws eligible USD line-item facts from SQLite and groups only equal `item_code` and `unit_of_measure` values. A group needs at least eight rows. Its deterministic robust-z formula is:

```text
robust_z = 0.6745 × (unit_price - median_price) / MAD
outlier when abs(robust_z) > 3.5
```

All money and median/MAD calculations remain `Decimal`; no binary floating-point conversion is required. Groups below eight observations return `INSUFFICIENT_PEER_GROUP`; a zero MAD returns `ZERO_VARIANCE`. Different UOMs are never pooled and no unit conversion occurs. A result is a price outlier candidate, never fraud, overcharge, or compliance status.

## Concentration and risk

`analyze_supplier_concentration()` returns category spend, supplier shares/ranks, and the count of `QUALIFIED` suppliers for an explicit window. `analyze_single_source_risk()` applies the accepted risk predicate:

```text
critical category
AND top supplier share >= 0.80
AND qualified supplier count <= 1
```

The result is `risk_finding` and `mitigation_review_required`, not compliance FAIL. For H1 2026, CAT-PRO / SUP-017 is the positive case: 90.91% share, one qualified supplier, risk true. CAT-OFF is high-concentration but noncritical; CAT-PRD has three qualified suppliers. Both counterexamples remain risk false.

## Commands and benchmark

```powershell
.\.venv\Scripts\python.exe scripts/analyze_procurement.py spend SUP-042
.\.venv\Scripts\python.exe scripts/analyze_procurement.py price PRICE-OFF-001
.\.venv\Scripts\python.exe scripts/analyze_procurement.py concentration CAT-PRO
.\.venv\Scripts\python.exe scripts/evaluate_analytics.py
```

The 10-case benchmark is stored in `evals/analytics_cases.json` and writes `evals/results/analytics_metrics.json`. It covers canonical growth, zero base, reconciled drivers, two planted outliers, two insufficient-evidence groups, the positive concentration case, and both counterexamples. Actual result: 10/10 passed.

## Limitations

There is no forecasting, ML anomaly model, unit conversion, external price source, or natural-language interpretation. Scenario #4 Pareto remains demonstrably SQL-capable through the existing SQL foundation.
