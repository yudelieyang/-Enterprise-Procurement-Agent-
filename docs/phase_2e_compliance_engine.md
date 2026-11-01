# Phase 2E — Deterministic Compliance Engine

## Purpose and boundary

Phase 2E turns the accepted 2026 `PolicyRule` manifest into a small deterministic compliance component. It audits a single PO using SQLite procurement facts and returns structured `PASS`, `FAIL`, or `REVIEW` results. It contains no Agent, LLM, vector retrieval, natural-language interpretation, generic rule DSL, or workflow engine.

```text
procurement.sqlite + policy_rules.json
              ↓
      explicit rule evaluators
              ↓
 structured result + rule provenance
```

`ground_truth.json` is used only by tests as an evaluation oracle; engine code never reads it.

## Inputs and provenance

`load_po_compliance_facts()` obtains the PO, category, contract, and approvals from SQLAlchemy/SQLite. `load_policy_rules()` validates the existing policy corpus first, then confirms each executable rule has a known type and manifest-backed source document, version, section, and page.

Every applicable `RuleResult` includes that provenance. A future presentation layer can retrieve surrounding PDF evidence, but hard-rule execution never depends on retrieval.

## Rule semantics

`APPROVAL_OVER_50000_2026` is applicable only to POs over USD 50,000 covered by the 2026 rule. It requires two distinct timely approved `PURCHASE` approvers, including a literal `DIRECTOR`. `COMPLETE` approval evidence permits a conclusive FAIL; `UNAVAILABLE` produces REVIEW.

`CONTRACT_REQUIRED_CATEGORIES_2026` is applicable only when the database category has `contract_required = true`. A valid contract must resolve, cover the PO date, match supplier/category, and not be terminated on or before that date. A timely approved `DIRECTOR` contract exception also passes. Confirmed absence or an invalid resolved contract can FAIL; an unresolved reference or unavailable evidence produces REVIEW.

Non-applicable rules are emitted in `skipped_rules` with no compliance status. Overall status over applicable rules is `FAIL > REVIEW > PASS`. A PO outside executable policy coverage returns REVIEW with `EXECUTABLE_POLICY_RULE_UNAVAILABLE_FOR_DATE`; `CANCELLED` POs are rejected as outside audit scope.

## Running it

```powershell
.\.venv\Scripts\python.exe scripts/audit_purchase_order.py PO-2026-1842
.\.venv\Scripts\python.exe scripts/evaluate_compliance.py
```

The audit command prints JSON containing the overall status, per-rule facts/reason codes, and provenance. The benchmark uses 15 database-backed cases: canonical PASS/FAIL/REVIEW controls, contract states, approval variants, the exact threshold, and an unsupported 2025 policy date.

## Measured component results

The deterministic benchmark produced 15/15 correct overall results and 30/30 correct rule outcomes (including explicit non-applicability):

| Metric | Result |
|---|---:|
| Rule-level accuracy | 1.000 |
| Overall compliance accuracy | 1.000 |
| PASS precision / recall | 1.000 / 1.000 |
| FAIL precision / recall | 1.000 / 1.000 |
| REVIEW precision / recall | 1.000 / 1.000 |

`PO-2026-1842` derives contract PASS, approval FAIL, and overall FAIL. `PO-2026-1846` is PASS; `PO-2026-1847` is REVIEW because approval evidence is unavailable. The generated report is `evals/results/compliance_metrics.json`.

## Limitations

Only the accepted 2026 approval and contract rules are executable. Competitive sourcing and supplier concentration remain informational/retrieval or analytics concerns. Human-readable 2025 PDFs remain retrievable, but no historical structured rule coverage is guessed.
