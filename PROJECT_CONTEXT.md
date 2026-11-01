# Enterprise Procurement Intelligence Agent — Project Context

## Project

Enterprise Procurement Intelligence Agent is a small but technically complete AI-engineering portfolio project for 2026 recruiting. It models an internal enterprise procurement analyst, rather than a generic chatbot.

Representative questions include:

- For `SUP-042`, how much did procurement spend increase in H1 2026 versus H1 2025, what do procurement records show drove it, and which related POs require policy review?
- Is `PO-2026-1842` compliant with procurement policy?

## MVP architecture

```text
User
  ↓
Single Agent Orchestrator
  ↓ dynamic tool selection
SQL Tool · Policy RAG Tool · Analytics Tool · Compliance Tool
  ↓
Evidence / Reliability Gate
  ↓
Grounded Answer | Clarification | Insufficient Evidence
```

There is one real agent. SQL, retrieval, analytics, and compliance are ordinary bounded tools; do not introduce a procurement multi-agent department.

LangGraph is the current orchestration direction, used with ordinary Python tools rather than LangChain everywhere. It may later be compared with OpenAI Agents SDK or PydanticAI only if implementation evidence warrants it.

## Domain scope

The minimal domain model is:

```text
BusinessUnit, Category, Supplier, PurchaseOrder, PurchaseOrderItem,
Contract, Approval, SupplierCategoryEligibility,
PolicyDocument, PolicyChunk, PolicyRule
```

Out of scope: invoices, receipts, payments, inventory, warehouses, shipments, RFQ systems, external supplier-risk APIs, full ERP behavior, and write operations.

## Dual-layer policy architecture

PDF policy evidence supports retrieval, citation, explanation, provenance, and auditability. Structured `PolicyRule` data supports deterministic approval, contract, and approved-exception checks.

Every executable rule must be traceable:

```text
PolicyRule → canonical PolicyChunk → PolicyDocument → version / section / page
```

The LLM may select tools, find evidence, explain results, and compose an answer. It must not invent hard compliance decisions.

## Status semantics

`PASS`, `FAIL`, and `REVIEW` are **compliance statuses** only for a business object that is actually assessed.

- `PASS`: complete facts and applicable rules establish compliance.
- `FAIL`: complete facts and applicable rules establish a violation.
- `REVIEW`: an assessment is in scope but required facts, rule applicability, or evidence is unresolved.

Agent response outcomes are separate: `ANSWERED`, `CLARIFICATION_REQUIRED`, and `INSUFFICIENT_EVIDENCE`. For example, no policy version covering a historical question is `INSUFFICIENT_EVIDENCE`, not compliance `REVIEW`.

## Fixed evaluation semantics

```text
EVAL_AS_OF_DATE = 2026-06-30
past six months = 2026-01-01 through 2026-06-30
this quarter = 2026 Q2
H1 2026 = 2026-01-01 through 2026-06-30
H1 2025 = 2025-01-01 through 2025-06-30
currency = USD only
```

Golden answers must never depend on the runtime date.

## Current structured-data backend

Phase 2B uses **SQLite via SQLAlchemy** as the local deterministic development and test backend. Generated CSV files remain the source artifact; `data/generated/procurement.sqlite` is rebuilt from them and ignored by Git. PostgreSQL plus pgvector remains the intended later deployment/retrieval direction.

The database layer exposes metadata-derived table inspection and a bounded read-only query interface. It accepts one `SELECT` or `WITH ... SELECT` statement, returns structured `columns / rows / row_count`, rejects mutation keywords and multi-statement input, and raises explicitly above its 100-row default limit. It retrieves facts and aggregates; it does not decide compliance status.

The only PO lifecycle states are `ISSUED`, `CLOSED`, and `CANCELLED`. `order_date` is the formal issuance/commitment date. Spend and compliance audits include `ISSUED` and `CLOSED` only; cancelled POs are excluded.

`PurchaseOrder.total_amount_usd` is derived from, and must equal, the sum of its line amounts.

## Policy corpus assets

Phase 2C stores an editable synthetic policy corpus under `data/policies/source/` and deterministically renders seven versioned PDFs under `data/policies/`. `policy_manifest.json` is the document/section/page source of citation stability. `policy_rules.json` is intentionally a small executable-rule manifest, not a policy DSL or compliance engine.

For the current 2026 rule set, each structured rule records canonical PDF provenance: document ID, version, stable section, page, and an expected source phrase. A later `PolicyChunk` record will be generated from that canonical source location; it must not become a detached second source of truth.

## Policy retrieval foundation

Phase 2D ingests the generated policy PDFs with `pypdf`, not their Markdown authoring sources. It builds page-bounded, section-aware canonical `PolicyChunk` records with deterministic IDs, then applies policy validity filtering before lexical, exact dense, or hybrid ranking. The default target date is the fixed `EVAL_AS_OF_DATE` of `2026-06-30`.

The local dense baseline is CPU-only exact search with `sentence-transformers/multi-qa-MiniLM-L6-cos-v1`; BM25 and reciprocal-rank fusion are evaluated against the same chunk registry. There is no ANN index, pgvector, LLM retrieval step, answer generation, or policy-type classifier in this phase.

## pgvector retrieval integration

Phase 2D.5 keeps the Phase 2D exact CPU implementation as the ranking oracle while adding a dedicated PostgreSQL `policy_chunks_pgvector` table for the same canonical chunks and persisted normalized 384-dimensional embeddings. The existing SQLite procurement database remains unchanged. PostgreSQL applies effective/expiration-date filtering in SQL before exact cosine ordering (`embedding <=> query_vector`) with `chunk_id` as the deterministic tie-breaker. No ANN index is created.

The integration requires a separately configured PostgreSQL instance with the `vector` extension. The repository supplies a minimal local Docker Compose target and opt-in integration tests; no password or generated vectors are committed.

## Deterministic compliance engine

Phase 2E evaluates executable `PolicyRule` records against facts loaded from the SQLite procurement database. It does not consult `ground_truth.json`, retrieval, or an LLM. Applicable rule results contain manifest-validated PDF provenance; non-applicable rules are explicitly skipped rather than reported as PASS.

For eligible `ISSUED` and `CLOSED` POs, overall status follows `FAIL > REVIEW > PASS`. A missing executable rule for a PO date returns `REVIEW` with `EXECUTABLE_POLICY_RULE_UNAVAILABLE_FOR_DATE`; current 2026 rules are never applied to 2025 POs. `CANCELLED` POs are outside audit scope and raise an engine-level error rather than receiving a compliance status.

## Deterministic procurement analytics

Phase 2F adds only three bounded functions over SQLite facts: explicit-window supplier spend growth and record-level drivers, MAD robust-z comparable-item price outliers, and category supplier concentration/single-source risk. SQL remains preferred for ordinary aggregation, ranking, filtering, and Pareto analysis.

Analytics returns typed facts only: it neither queries policy evidence nor calls Compliance automatically. Spend uses `ISSUED`/`CLOSED` POs and `Decimal`; a zero comparison base returns `percentage_change = null` with an explicit growth basis. Price comparisons require equal item code/UOM, USD, at least eight observations, and `abs(0.6745 * (price - median) / MAD) > 3.5`. Single-source risk is a non-compliance finding requiring a critical category, top supplier share at least 80%, and no more than one qualified supplier.

## MVP hard rules

Approval rule:

```text
IF total_amount_usd > 50,000
THEN at least two valid PURCHASE approvals
AND at least one valid approval with DIRECTOR role
```

A valid approval has `approval_type = PURCHASE`, `status = APPROVED`, `approved_at <= PO.order_date`, and a distinct `approver_id`. Rejected, pending, withdrawn, late, or duplicate approvals do not count. There is no role hierarchy.

A PO-time valid contract is resolved, has not been terminated on or before the PO date, covers the PO date, and matches the PO supplier and category. Contracts therefore carry a nullable `termination_date` alongside their administrative `EXECUTED` / `TERMINATED` status. A valid contract exception is a `CONTRACT_EXCEPTION` approval that is `APPROVED`, given by a `DIRECTOR`, and timestamped no later than the PO date.

For evidence completeness, POs will carry minimal `approval_evidence_status` and `contract_evidence_status` fields. `COMPLETE` makes an empty approval set a confirmed zero; `UNAVAILABLE` requires compliance `REVIEW` where that evidence is needed.

Only the INDIRECT `IT Services` and `Professional Services` categories have `contract_required = true`. This category boolean is deliberately the full MVP applicability model; other categories do not fail contract compliance solely because no contract exists.

## Key demos and risk logic

The canonical explainability demo is `PO-2026-1842`: valid contract, failed approval rule, overall `FAIL`, with rule-level provenance.

Single-source dependency is not an automatic compliance violation. It is a risk/mitigation finding when:

```text
category.is_critical = true
AND supplier spend share >= 80%
AND qualified supplier count <= 1
```

## Unified evaluation foundation

Phase 2G preserves independent SQL, retrieval, compliance, and analytics component benchmarks while adding 38 task-level golden cases under `evals/tasks/`. These are framework-neutral future-Agent contracts, not an Agent implementation. A case records required, optional, and unnecessary logical capabilities; acceptable trajectories and dependency constraints; machine-verifiable facts; policy-citation metadata; compliance results; and the response outcome.

The frozen logical capability vocabulary is `query_procurement_database`, `retrieve_procurement_policy`, `analyze_procurement_data`, and `check_policy_compliance`. The deterministic pre-Agent evaluator measures tool-selection precision/recall, required coverage, unnecessary-tool-call rate, trajectory success, and citation correctness/evidence coverage. It deliberately creates no composite Agent score and no LLM-as-judge metric. `scripts/validate_golden_tasks.py` checks the task corpus against SQLite, current component results, and the PDF-derived chunk registry before future orchestration is allowed.

## Agent-facing tool interfaces

Phase 3A exposes the same four logical capabilities through typed, framework-neutral Python adapters in `procurement_agent.tools`. Tool execution returns structured component results or normalized errors plus a runtime call ID, UTC timing, success flag, and backend; it never returns generated prose or a raw traceback. SQL remains the general read-only facts tool, while Analytics and Compliance accept domain parameters and internally load their safe SQLite facts. Policy retrieval defaults to the measured local hybrid RRF path and accurately reports its local PDF-chunk backend; pgvector dense retrieval remains a separately validated deployment integration.

This interface decision updates the resolved Phase 2G tool contracts: a direct Analytics or Compliance call is sufficient when its existing structured result contains all facts needed by that task. Explicit SQL remains required only for ad-hoc structured-data cases, rather than being forced ahead of every domain tool.

## Single-Agent orchestration

Phase 3B implements the accepted one-Agent design as an explicit LangGraph loop over the four Phase 3A registry tools. A thin official-OpenAI adapter is environment-configured and isolated from the graph; a scripted adapter powers deterministic tests without API calls. The graph records observable messages, tool calls, run-local PDF/rule provenance, bounded model/tool counts, final response, termination, and returned usage metadata, but never chain-of-thought.

Agent execution is bounded by configurable model-turn, total-tool, and repeated-identical-call limits. Every final citation is validated against Retrieval evidence or Compliance provenance returned during that same run, and unknown tool-call IDs are rejected. `ANSWERED`, `CLARIFICATION_REQUIRED`, and `INSUFFICIENT_EVIDENCE` remain user-response outcomes separate from Compliance `PASS`, `FAIL`, and `REVIEW`. There is no persistence, memory, multi-agent layer, or full 38-case optimization in this phase.

The OpenAI `chat.completions.parse` adapter receives strict function schemas (`strict: true`, no extra properties, complete required fields; Phase 3A-optional values are nullable). SDK/model failures retain a sanitized stage/class/message diagnostic in the run trace while keeping the user-facing response safe; secrets and headers are never logged.

Phase 3B.5 has one preserved untouched ten-case live baseline using `gpt-5.6-luna` with reasoning effort `none`: all cases completed, with 6/10 deterministic trace/citation/outcome checks passing. The measured baseline is intentionally not tuned in place; its tool-selection, citation, clarification, and multi-tool omissions are retained for Phase 3C evaluation work. The result records actual API usage and local latency but no estimated dollar cost or automatically parsed final-answer-fact score.

Phase 3C preserves `agent_v1` and adds a configurable `agent_v2` prompt-only routing candidate. Its one fixed ten-case live A/B run improved deterministic checks from 6/10 to 7/10, tool-selection precision from 0.85 to 0.90, unnecessary-tool-call rate from 0.15 to 0.10, and trajectory success from 0.60 to 0.70; recall, outcome accuracy, and citation/evidence metrics did not improve. The candidate still omitted Retrieval for explainable compliance and failed to clarify an undefined decision criterion, so it is not yet ready for the full 38-case live run. The preserved v1 artifacts and separate v2 artifacts document the comparison; no Agent v3 was started.

Phase 3C then adds `guardrails_v1`, an independently recorded orchestration version; `agent_v2` prompt text remains frozen. Guardrails use one additional structured preflight request to the same configured model, producing only `RequestRequirements(action, clarification_question, requires_explainable_policy_evidence)`. The model continues to recognize semantic ambiguity and evidence need; the runtime does not keyword-route user text. A declared `CLARIFY` exits before exposing any business tool. For a declared evidence requirement, a successful Compliance call without a non-empty run-local Retrieval evidence inventory blocks finalization once and returns control to the same Agent with a generic evidence-remediation instruction. Retrieval is never auto-called. A second incomplete finalization terminates safely with `POLICY_EVIDENCE_GUARD_UNSATISFIED`. Compliance provenance remains valid decision traceability but cannot satisfy this PDF Retrieval evidence invariant. Run traces record the request contract, guardrail events, remediation count, orchestration version, and preflight request/usage/latency separately from Agent-loop model turns. This remains one bounded Agent with four business tools and no second model, router, planner, or benchmark-specific logic.

The live `guardrails_v1` sanity runs confirmed enforcement, but the original boolean RequestRequirements contract made opposite semantic errors: it missed an undefined “preferred supplier” decision criterion and added unnecessary policy evidence to an explicitly deterministic status-only audit. `requirements_v2` therefore versions the semantic contract independently from the frozen prompt and orchestration. It records a four-state `decision_definition` (`SUFFICIENT`, missing criteria, ambiguous entity, or missing scope) and a three-state `policy_support_requirement` (`NONE`, `STATUS_ONLY`, or `EXPLAINABLE_POLICY_EVIDENCE`). The runtime uses no keyword routing: every non-sufficient state terminates as clarification before tools, and only explainable evidence activates the existing unchanged post-Compliance guard. A separate offline fixture/evaluator measures these semantic axes independently, including precision, recall, and false-positive/false-negative counts. Its model-free oracle self-check validates fixtures and metrics, not live model quality. No live calibration evaluation or broader benchmark has been run.

The controlled ten-case `agent_v2 + guardrails_v1 + requirements_v2` treatment is preserved separately from the frozen v2 control. It fixed the canonical clarification task and kept status-only Compliance free of guardrail-forced Retrieval, but over-clarified several policy questions and ended the guarded multi-tool investigation at the configured model-turn limit. Relative to the v2 control, deterministic checks fell from 7/10 to 5/10, required coverage from 0.9167 to 0.6000, outcome accuracy from 0.9000 to 0.5000, and citation/evidence coverage from 0.8000 to 0.6000. Precision improved to 1.0000 and the unnecessary-tool-call rate fell to zero; total API requests rose from 25 to 26, while total tokens and local smoke latency declined in this single run. The outcome is a mixed reliability/cost result and does not justify the 38-case live evaluation without a separate design decision.

## Evaluation philosophy

Target 30–50 golden cases across SQL-only, RAG-only, analytics, multi-tool, PASS/FAIL/REVIEW, clarification, insufficient evidence, temporal policy retrieval, tool overuse, and failure/adversarial cases.

Future metrics include SQL execution/result correctness; Hit@k, Recall@k, MRR; tool-selection and trajectory correctness; task success, citation correctness, evidence coverage, unsupported claim rate; abstention/clarification correctness; latency and cost.

## Engineering rule

```text
Business Tasks → Required Evidence → Required Data → Required Tools → Agent Architecture
```

Do not reverse this order or expand scope merely for resume keywords.
