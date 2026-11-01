# Phase 1D — Synthetic Procurement Dataset & Policy Corpus Specification

This is a design specification, not a generator, database definition, PDF corpus, or evaluation implementation.

## 1. Dataset Scale & Time Range

The dataset covers **2025-01-01 through 2026-06-30**. `EVAL_AS_OF_DATE` is fixed at **2026-06-30**.

Target scale is deliberately small enough for local iteration while large enough for meaningful ranking, concentration, and peer analysis:

| Entity | Target count | Rationale |
|---|---:|---|
| Business units | 4 | Enough for #1 comparisons without creating an org hierarchy. |
| Categories | 6 | Covers direct/indirect, critical, IT, and contract-required categories. |
| Suppliers | 25 | Provides realistic ranking and price-comparison peer groups, including stable `SUP-042`. |
| Purchase orders | 480 | About 27 POs/month over 18 months; sufficient for period comparisons. |
| PO items | 820–900 | 1–3 lines per PO, permitting item-level analysis. |
| Contracts | 12–14 | Enough valid, expired, and absent-link patterns. |
| Approvals | about 180 | Enough approved, rejected, late, exception, and planted edge cases. |
| Supplier-category eligibility records | about 42 | Sparse qualification evidence without a vendor-lifecycle system. |

All transaction amounts are USD. There is no FX table, conversion, or currency-normalization evaluation.

## 2. Master Data Specification

### Business units

Use four compact operating units: `CORP_IT`, `OPERATIONS`, `FACILITIES`, and `R_AND_D`. They exist to make spend segmentation meaningful; no budgets, cost centers, or hierarchy are generated.

### Categories

| Category | Procurement class | Critical | Contract policy role |
|---|---|---:|---|
| Software Licenses | INDIRECT | Yes | Not contract-required by MVP rule |
| IT Services | INDIRECT | Yes | Contract-required |
| Professional Services | INDIRECT | Yes | Contract-required in 2025 and 2026 |
| Office Supplies | INDIRECT | No | Not contract-required by MVP rule |
| Facilities Maintenance | INDIRECT | No | Not contract-required by MVP rule |
| Production Materials | DIRECT | Yes | Used as a direct-procurement counterexample |

### Suppliers and item codes

Create 24 named suppliers with stable IDs `SUP-001` through `SUP-024`. Reserve:

- `SUP-017` for the critical single-source risk pattern.
- `SUP-042` as the spend-growth subject; it is added to the 24 background supplier identifiers for 25 suppliers total.

Item codes use a small, stable convention such as `SWL-001` for software licences, `ITS-001` for IT services, `PRO-001` for professional-services deliverables, `OFF-001` for office consumables, `FAC-001` for maintenance parts, and `PRD-001` for production materials. Item codes are not an Item Master.

For #10, multiple suppliers must sell the same `item_code` under the same `unit_of_measure`; only those rows form a comparable peer group. At least one same-item, different-UOM record is deliberately excluded from comparison rather than converted.

## 3. Planted Business Pattern Matrix

| Pattern | Protected facts and expected ground truth | Scenario use |
|---|---|---|
| SUP-042 H1 growth | H1 2025 spend = $120,000 across 3 POs; H1 2026 spend = $390,000 across 7 POs. Increase = $270,000 / 225%. 2025 category mix: IT Services $70,000, Software $50,000. 2026: IT Services $240,000, Software $150,000. PO count rises 3→7; average PO value rises $40,000→about $55,714. Two 2026 POs exceed $70,000. | #3, #7 |
| Pareto indirect spend | In H1 2026, a protected set of five suppliers contributes roughly 80–85% of valid indirect spend. The exact generated percentage is post-generation validated and recorded for golden cases. | #4 |
| Off-contract outcomes | Include valid contract, confirmed no contract, unresolved contract reference, expired/invalid contract, and valid Director-approved exception cases. | #8, #12 |
| Approval outcomes | Include valid two approvals including Director; one valid approval; two valid approvals with no Director; rejected-only additional record; late approval; confirmed zero approvals; and evidence unavailable. | #7, #9, #12 |
| Price outliers | For at least two same-code, same-UOM peer groups, create normal observations plus meaningful high and low outliers. Include one same code with a different UOM labelled non-comparable. | #10 |
| Single-source risk | In one critical category, `SUP-017` has spend share >=80% and qualified supplier count <=1. Add counterexamples: high concentration in a noncritical category, and high concentration with multiple qualified alternatives. | #11 |
| Temporal policy corpus | Current and historical versions have distinct effective intervals and semantic differences; no document covers 2024. | #5, #6, #15 |

Background records may be randomized within controlled ranges, but none may alter protected pattern records or their expected results.

## 4. Canonical Ground-truth Cases

### PO-2026-1842 — canonical explainability demo

`PO-2026-1842` is an ISSUED IT Services PO dated in H1 2026 with total amount greater than $50,000. It has:

- a resolved, active, supplier/category-matching contract covering its `order_date`;
- `approval_evidence_status = COMPLETE`;
- exactly one valid `PURCHASE` approval; and
- no need for a contract exception.

Expected rule-level result:

```text
Contract rule: PASS
Approval rule: FAIL
Overall compliance: FAIL
```

It must include line items whose sum exactly equals the PO total and an executable-rule provenance link to the 2026 Approval Authority Matrix and Contract Compliance Policy.

### Comparable controls

Create two similarly scoped, higher-value 2026 POs:

- **PASS control:** valid contract plus two timely distinct PURCHASE approvals, at least one from a DIRECTOR.
- **REVIEW control:** approval or contract evidence status is `UNAVAILABLE`, so a required fact cannot be confirmed. It must not be labelled FAIL merely because a record is absent.

### Off-contract control set

Reserve stable PO identifiers for:

| PO | Contract fact | Expected contract-rule result |
|---|---|---|
| `PO-2026-1837` | Complete evidence; no contract reference and no valid exception | FAIL |
| `PO-2026-1838` | Contract reference exists but cannot resolve to a contract record | REVIEW |
| `PO-2026-1839` | Resolved contract expired before PO date; no valid exception | FAIL |
| `PO-2026-1840` | No valid contract but timely DIRECTOR contract exception | PASS |

Their approval-rule results may vary only when deliberately needed for a separate test; the contract ground truth remains protected.

### Approval-case semantics

| Evidence condition for a >$50k PO | Expected approval result |
|---|---|
| Two timely, distinct APPROVED purchase approvals, including DIRECTOR | PASS |
| One timely valid purchase approval | FAIL |
| Two timely approvals, neither DIRECTOR | FAIL |
| Rejected approval record does not fill a missing required approval | FAIL when evidence is COMPLETE |
| Approval occurs after `order_date` | FAIL when evidence is COMPLETE |
| No approval records and evidence is COMPLETE | confirmed zero → FAIL |
| Required approval evidence is UNAVAILABLE | REVIEW |
| Duplicate `(PO, PURCHASE, approver_id)` insert attempt | reject as integrity failure; never persist it as normal data |

## 5. Missing Evidence Strategy

Confirmed absence and unavailable evidence must be represented differently.

### Minimal schema amendment

Add two required PurchaseOrder evidence-status fields to the Phase 1C design:

| Field | Values | Why it is needed |
|---|---|---|
| `approval_evidence_status` | `COMPLETE`, `UNAVAILABLE` | Distinguishes confirmed zero approvals from missing approval evidence. |
| `contract_evidence_status` | `COMPLETE`, `UNAVAILABLE` | Distinguishes confirmed no linked contract from unavailable contract evidence. |

Interpretation:

- `COMPLETE` + no relevant record is a confirmed absence and may support `FAIL`.
- `UNAVAILABLE` means the compliance assessment lacks necessary evidence and must return `REVIEW` when that evidence is required.
- A non-null unresolved `contract_reference` is separately meaningful: a reference exists, but no authoritative record was resolved; this is `REVIEW`.

Policy evidence uses a different response-layer rule: no policy document whose validity interval covers the requested date produces `INSUFFICIENT_EVIDENCE`, not compliance `REVIEW`.

## 6. Policy Corpus Specification

The minimum corpus has seven PDF versions. PDFs are not generated in this phase.

| Title | Version / interval | Major sections | Scenarios and retrieval targets | Executable sections |
|---|---|---|---|---|
| Corporate Procurement Policy | 2025.1; 2025-01-01 to 2025-12-31 | scope, purchase governance, competitive sourcing guidance, exceptions | #5 historical/general policy questions | None |
| Corporate Procurement Policy | 2026.1; 2026-01-01 onward | scope, purchase governance, updated sourcing guidance, exceptions | #5, #7, #12 explanation | None |
| Approval Authority Matrix | 2025.1; 2025-01-01 to 2025-12-31 | approval tiers, authorized roles, timing | temporal approval retrieval | Approval threshold section |
| Approval Authority Matrix | 2026.1; 2026-01-01 onward | approval tiers, two approvals over $50k, Director requirement | #6, #7, #9, #12 | §4.2 approval rule |
| Contract Compliance Policy | 2025.1; 2025-01-01 to 2025-12-31 | contract-required categories, exceptions, evidence | #15 historical contract question | contract requirement / exception section |
| Contract Compliance Policy | 2026.1; 2026-01-01 onward | IT and Professional Services requirements, Director exception, unresolved evidence handling | #8, #12 | contract requirement / exception section |
| Supplier Selection Policy | 2026.1; 2026-01-01 onward | qualified suppliers, single-source mitigation, critical categories | #11 | None; risk guidance only |

### Temporal differences

Versions must not be identical text with different labels:

- **Approval:** 2025.1 requires two approvals including a Director above $75,000; 2026.1 lowers the threshold to $50,000. This gives historical retrieval an observable semantic difference.
- **Contract:** both versions require contracts for IT Services and Professional Services. 2026.1 clarifies that only a timely Director-approved exception can substitute for a valid contract and that an unresolved contract reference requires review rather than an assumed violation.
- **Corporate policy:** 2026.1 updates explanatory sourcing guidance, but competitive sourcing remains non-executable in the MVP.

There is intentionally no policy version covering 2024. A 2025 Supplier Selection Policy is also intentionally absent. These support `INSUFFICIENT_EVIDENCE` cases without multiplying documents.

## 7. Executable PolicyRule Specification

Only the following rules are structured. Every rule links to its canonical source PolicyChunk and therefore inherits the source document version and validity interval.

| Rule code | Meaning and applicability | Required facts | PASS | FAIL | REVIEW | Source |
|---|---|---|---|---|---|---|
| `APPROVAL_2025_OVER_75000` | In 2025, PO amount >$75k requires two valid PURCHASE approvals and one DIRECTOR. | PO amount/date/status; approval evidence status; approval records | Count and Director requirement met | Evidence COMPLETE and requirement unmet | Evidence UNAVAILABLE or applicable policy cannot be resolved | Approval Matrix 2025.1, approval tier section |
| `APPROVAL_2026_OVER_50000` | In 2026, PO amount >$50k requires two valid PURCHASE approvals and one DIRECTOR. | Same as above | Count and Director requirement met | Evidence COMPLETE and requirement unmet | Evidence UNAVAILABLE or policy conflict | Approval Matrix 2026.1 §4.2 |
| `CONTRACT_2025_REQUIRED_CATEGORY` | In 2025, IT Services and Professional Services require a valid contract or timely Director exception. | PO category/date/supplier; contract evidence status/reference; contract facts; exception approvals | Valid contract or valid exception | Evidence COMPLETE and neither exists | Evidence unavailable, unresolved reference, or policy applicability unresolved | Contract Policy 2025.1, contract/exception section |
| `CONTRACT_2026_REQUIRED_CATEGORY` | In 2026, IT Services and Professional Services require a valid contract or timely Director exception. | Same as above | Valid contract or valid exception | Evidence COMPLETE and neither exists | Evidence unavailable, unresolved reference, or conflict | Contract Policy 2026.1, contract/exception section |

Single-source, price outlier, supplier concentration, competitive sourcing, and general policy guidance remain non-executable in MVP. They may inform an explanation, risk finding, or recommendation for review; they do not produce automatic compliance FAIL.

## 8. Data Generation Invariants

### Hard data invariants

- Every foreign key resolves.
- Every PO has one supplier, business unit, category, status, and USD amount.
- `PurchaseOrder.total_amount_usd = SUM(PurchaseOrderItem.line_amount_usd)` exactly.
- Quantity is positive; unit price and amounts are non-negative.
- Contract expiration is on or after effective date.
- A resolved PO contract matches its supplier and category.
- A completed approval has a timestamp; duplicate `(PO, approval_type, approver_id)` records are rejected.
- Policy version intervals for a given policy type do not overlap.
- Every PolicyRule has exactly one canonical source PolicyChunk, whose document has a valid version interval.

### Intentionally planted business violations

The following are valid domain data, not corruption, and must survive validation:

- insufficient valid approvals;
- missing contract with complete evidence;
- expired contract;
- timely approved contract exception;
- unresolved contract reference;
- unavailable approval or contract evidence;
- price outliers;
- supplier concentration risk.

## 9. Reproducibility Strategy

Use one fixed random seed once implementation begins, but do not rely on a seed alone.

1. Generate background master data and noncanonical transactions from deterministic seeded ranges.
2. Insert protected master records and planted PO/approval/contract cases with stable identifiers after background generation.
3. Prevent random generation from using protected identifiers or overwriting protected records.
4. Run post-generation validation for invariants and every planted ground truth.
5. Record the seed, specification version, counts, and validation summary alongside the generated dataset.

The intended result is:

```text
same seed + same specification → same dataset → same golden answers
```

## 10. Golden Evaluation Expansion Plan

The 14 scenario families expand into 36–44 concrete golden cases, not one case each.

| Case family | Target count | Coverage |
|---|---:|---|
| SQL-only | 7–8 | spend by BU, supplier rankings, period growth, status/date boundaries |
| RAG-only | 5–6 | current policy, historical policy, citation and version selection |
| Analytics | 5–6 | Pareto, spend-driver decomposition, comparable price outliers, non-comparable UOM |
| Multi-tool compliance | 9–10 | approval/contract PASS, FAIL, REVIEW, rule provenance |
| Risk and policy synthesis | 3–4 | #7 and #11 without equating risk to violation |
| Clarification / insufficient evidence | 4–5 | ambiguous supplier preference, absent historical policy, missing definition |
| Tool overuse / failure / adversarial | 4–5 | unnecessary RAG, invalid date range, unresolved contract, duplicate-approval input, irrelevant retrieval |

Trajectory evaluation accepts semantically equivalent minimal paths. For example, #3 may be `SQL` or `SQL → Analytics` only if Analytics contributes a reusable, deterministic decomposition; #4 requires SQL and may optionally use Analytics; #9's decision-critical path is `SQL → Compliance`, with RAG optional for explanation.

## 11. Scope Audit

This specification does not add invoices, payments, receipts, three-way matching, RFQ systems, warehouses, inventory, external APIs, multi-currency, full IAM, external supplier risk, an ERP write interface, policy DSLs, or a multi-agent architecture.

It also does not generate CSVs, PDFs, database DDL, code, prompts, retrieval implementation, or evaluation files.

## 12. Remaining Risks

1. The synthetic policy wording must match every structured rule exactly enough that rule provenance is credible.
2. Contract-required category scope must stay intentionally small; adding more categories without scenarios would create fake enterprise complexity.
3. Price-outlier thresholds and peer-group sizes must be fixed before implementation, so results are not tuned after seeing outputs.
4. The final H1 spend-driver decomposition should report observed record factors—PO count, average value, category contribution, large-order contribution—not unsupported business causality.
5. A later implementation must enforce evidence-status semantics before it evaluates missing records; otherwise confirmed absence and unavailable evidence could be conflated.
