# Phase 2A — Synthetic Data Generator

## Generator strategy

The generator uses only the Python standard library. It creates stable master data, injects protected scenario records first, fills the remaining rows with fixed-seed background data, validates the result, then writes CSV tables plus `ground_truth.json`.

Monetary values use `Decimal`; every PO total is derived from its item lines. Stable identifiers such as `SUP-042` and `PO-2026-1842` are never selected from random ordering.

## Planted patterns

- `SUP-042`: H1 2025 spend of $120,000 and H1 2026 spend of $390,000, with record-level category and large-PO drivers.
- Indirect-spend Pareto concentration in H1 2026.
- Contract and approval PASS/FAIL/REVIEW cases, including `PO-2026-1842` (overall FAIL), canonical PASS, and evidence-unavailable REVIEW controls.
- Same-item/same-UOM price groups with MAD robust-z outliers, a non-comparable different-UOM item, and a below-minimum peer group. Generic service lines use PO-scoped item codes so unrelated spend records cannot become accidental price peers.
- `SUP-017` critical-category single-source risk plus two counterexamples.

## Schema amendments accepted in Phase 2A

- `categories.contract_required`: true only for IT Services and Professional Services.
- `contracts.termination_date`: nullable; allows contract validity to be assessed at the PO date even when a contract is currently terminated.
- `purchase_orders.approval_evidence_status` and `contract_evidence_status`: distinguish confirmed absence from unavailable evidence.

## Reproducibility and validation

`DEFAULT_SEED = 20260630`. Protected cases are inserted independently of background random data. Validation checks foreign references, PO/item money totals, date bounds, USD-only scope, evidence semantics, compliance ground truth, concentration, and outlier design.

## How to run

```text
python scripts/generate_data.py
python scripts/validate_data.py
pytest
```

The project uses a `src/` package layout; install development dependencies first with `python -m pip install -e ".[dev]"`.

## Known limitations

This phase creates structured synthetic data only. It does not implement SQL access, policy PDFs, retrieval, an agent, an API, a database, multi-currency, unit conversion, or external integrations.
