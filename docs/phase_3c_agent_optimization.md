# Phase 3C — Targeted Agent Failure Analysis and `agent_v2`

## Scope

Phase 3C changes only the single Agent's routing and finalization instructions. It preserves the four Phase 3A tool interfaces, the LangGraph loop, retrieval corpus and rankings, executable compliance rules, structured-data ground truth, and the untouched `agent_v1` live baseline.

The analysis below uses observable evaluation inputs, tool trajectories, final outcomes, and deterministic evaluation findings only. It does not infer or retain model hidden reasoning.

## `agent_v1` failure analysis

| Baseline case | User intent / required logical capability | Actual observable behavior | Missing or unnecessary action | Final outcome | Observable prompt/tool-description cause | Issue type |
| --- | --- | --- | --- | --- | --- | --- |
| `TASK-002` | Return an ordinary structured top-N/ranking fact. This is a SQL `GROUP BY` / ranking query, not a domain analytic calculation. | `Analytics → SQL` | Analytics was unnecessary; SQL was required and eventually used. | `ANSWERED` | v1 says to use Analytics for its supported calculations but does not explicitly distinguish ordinary ranking/comparison from spend-growth, concentration, or price-outlier analysis. | `UNNECESSARY_TOOL_CALL` |
| `TASK-025` | Determine a PO's deterministic compliance status and provide human-auditable policy evidence for the conclusion. | `Compliance` | Policy Retrieval was missing, so the run lacked the required human-readable evidence and citations. | `ANSWERED` | v1 separates Compliance (determination) from Retrieval (policy requirements/evidence), but does not explicitly require Retrieval before finalizing an explainable or audit-ready compliance answer. | `MISSING_POLICY_EVIDENCE` |
| `TASK-033` | Resolve an undefined business concept before making a supplier claim. The correct capability is clarification, not data lookup. | `SQL` | SQL was unnecessary; the response should have requested the missing criterion without calling a tool. | `INSUFFICIENT_EVIDENCE` | v1 allows clarification for an “essential entity, scope, or criterion” but does not direct the model to test whether the decision criterion itself is defined before tool selection. | `CLARIFICATION_BEFORE_TOOLS` |
| `TASK-030` | Perform a multi-step investigation: calculate an explicit growth metric, assess identified records with deterministic compliance, and provide policy basis for the requested review. | `Analytics → Analytics → Compliance → Compliance → Compliance` | Retrieval was missing; repeated compliance calls did not supply human-readable policy evidence or citations. | `ANSWERED` | v1 contains no multi-step final checklist linking a requested policy explanation/review to policy evidence, and no instruction to avoid duplicate calls unless arguments materially differ or a prior call failed. | `MULTI_EVIDENCE_MISS` |

## `agent_v2` design

`agent_v2` is a prompt-only routing refinement, selected explicitly through Agent configuration. It adds the following general constraints without case IDs, golden answers, or a keyword-based router:

- choose the smallest sufficient tool set;
- use SQL for ordinary filters, joins, aggregates, ranks, top-N comparisons, and window queries;
- reserve Analytics for its bounded growth/driver, MAD price-outlier, and concentration/risk operations;
- request clarification before tools when the decision criterion itself is undefined;
- pair deterministic Compliance with Retrieval when the user needs policy basis, explanation, audit evidence, or citations;
- before finalizing, check whether the requested calculation, compliance conclusion, policy evidence, analytic operation, and clarification need have each been addressed; and
- avoid duplicate calls unless arguments materially differ, another entity is involved, or the earlier call failed.

Retrieval remains responsible for returned canonical policy evidence; Compliance remains responsible for deterministic `PASS` / `FAIL` / `REVIEW`. This phase adds no LLM classifier, hidden evaluator, component-specific routing code, or new Agent.

## Validation plan

API-free scripted tests lock down five representative observable trajectories: SQL-only ranking, Analytics-only supported analysis, clarification with zero tools, explainable compliance with Compliance plus Retrieval, and a compliance run that continues to Retrieval before finalizing when policy evidence is required. The same fixed ten-case smoke set is then run once with `agent_v2`, `gpt-5.6-luna`, and reasoning effort `none`, with separate report artifacts for A/B comparison.

## `agent_v2` live A/B result

The single candidate run completed on 2026-08-30 with `gpt-5.6-luna`, reasoning effort `none`, and `chat.completions.parse`. It used the same ten cases, component artifacts, and deterministic evaluators as the preserved v1 baseline. Generated-answer facts remain `NOT_AUTOMATICALLY_SCORED`.

| Measure | `agent_v1` baseline | `agent_v2` candidate |
| --- | ---: | ---: |
| Completed cases | 10 / 10 | 10 / 10 |
| Deterministic checks passed | 6 / 10 | 7 / 10 |
| Tool-selection precision | 0.8500 | 0.9000 |
| Tool-selection recall / required coverage | 0.9167 | 0.9167 |
| Unnecessary tool-call rate | 0.1500 | 0.1000 |
| Trajectory success rate | 0.6000 | 0.7000 |
| Response-outcome accuracy | 0.9000 | 0.9000 |
| Citation correctness / evidence coverage | 0.8000 | 0.8000 |
| Model requests | 27 | 25 |
| Total tokens | 56,839 | 58,387 |
| Local latency mean / median | 6,863.597 / 5,345.104 ms | 6,573.541 / 5,258.619 ms |

| Case | `agent_v1` trajectory / finding | `agent_v2` trajectory / finding |
| --- | --- | --- |
| `TASK-001` | SQL → SQL; pass | SQL → SQL; pass |
| `TASK-002` | Analytics → SQL; unnecessary Analytics | SQL; pass |
| `TASK-009` | Retrieval; pass | Retrieval; pass |
| `TASK-010` | Retrieval; pass | Retrieval; pass |
| `TASK-014` | Analytics; pass | Analytics; pass |
| `TASK-020` | Compliance; pass | Compliance; pass |
| `TASK-025` | Compliance; missing Retrieval/citations | Compliance; unchanged missing Retrieval/citations |
| `TASK-033` | SQL; wrong outcome and unnecessary tool | SQL → SQL; wrong outcome and unnecessary tools |
| `TASK-035` | Retrieval → Retrieval; pass | Retrieval; pass |
| `TASK-030` | Analytics → Analytics → Compliance ×3; missing Retrieval/citations | Analytics → Compliance ×3; missing Retrieval/citations |

The prompt refinement demonstrably corrected the ordinary-ranking overuse and reduced two redundant calls, but it did not reliably make the model retrieve policy evidence for explainable compliance or clarify an undefined decision criterion. The v2 prompt is also longer, so lower request count did not lower total token usage.

Artifacts: `evals/results/agent_smoke_v1_live_baseline.json` and `.md` remain untouched. The candidate results are `evals/results/agent_smoke_v2_live.json` and `.md`.

## Decision at the Phase 3C gate

Do not run the full 38-case live evaluation yet. The unresolved failures include the canonical explainable-compliance and ambiguous-criterion reliability paths, so a broader run would measure known gaps rather than validate readiness. No `agent_v3` or additional live tuning was performed in this phase.

## `guardrails_v1` — deterministic completion enforcement

The v2 result separates a tool-selection mistake from a completion invariant. The ordinary-ranking mistake in `TASK-002` responded to prompt guidance because SQL and Analytics are substitutable choices. The remaining explainable-compliance and clarification failures were different: the Agent could select useful tools yet prematurely finalize, or inspect data before resolving an undefined decision criterion. More prompt text did not create a runtime boundary at either point.

`guardrails_v1` is separately versioned from `prompt_version`; it preserves the frozen `agent_v2` text. Before business tools are exposed, the same configured model receives a small structured preflight and returns `RequestRequirements` only:

- `action`: `PROCEED` or `CLARIFY`;
- `clarification_question`: a focused question or `null`;
- `requires_explainable_policy_evidence`: boolean.

This has no rationale, hidden reasoning, expected tools, benchmark identifier, or expected answer. Semantic recognition remains model-driven. The deterministic runtime only enforces the returned contract: `CLARIFY` produces `CLARIFICATION_REQUIRED` with zero business-tool calls; `PROCEED` enters the unchanged bounded single-Agent loop.

At finalization, the evidence invariant applies only when the preflight declared explainable policy evidence, a Compliance call succeeded, and the trusted run-local Retrieval evidence inventory contains no Retrieval evidence. Tool success alone is deliberately insufficient because Retrieval can return no applicable evidence. Compliance rule provenance remains valid decision traceability, but it is not PDF Retrieval evidence and cannot satisfy this condition.

The first violation is recorded as an observable guardrail event and sends a short generic internal instruction back to the same Agent. The runtime never calls Retrieval itself. Exactly one remediation is allowed; a later finalization without applicable Retrieval evidence returns `INSUFFICIENT_EVIDENCE` with termination reason `POLICY_EVIDENCE_GUARD_UNSATISFIED`. This preserves bounded execution and makes failure visible rather than accepting an uncited compliance explanation.

Preflight is an additional real API request. It contributes to total `usage.request_count`, its own `preflight_turns` token data when provided by the SDK, and `preflight_duration_ms`; `model_turn_count` continues to mean only Agent-loop turns so existing v1/v2 trace interpretation remains intact. Future evaluation artifacts must record both versions and the preflight/guardrail trace fields. No live evaluation was run for this implementation.

## Requirements-contract calibration: `requirements_v2`

The three live guardrails sanity cases verified the deterministic enforcement path but exposed two semantic classification errors: the undefined-preferred-supplier request was allowed to proceed, while an explicitly deterministic status-only compliance request was classified as needing explainable policy evidence. The latter caused a valid guardrail remediation, but unnecessary Retrieval and added request cost. These are contract-calibration failures, not defects in the one-remediation enforcement invariant.

| Live sanity case | Preflight result | Observable result | Interpretation |
| --- | --- | --- | --- |
| Undefined preferred supplier | `SUFFICIENT` / `NONE` under the prior boolean contract | SQL then `INSUFFICIENT_EVIDENCE` | Semantic clarification false negative |
| Explainable PO compliance | Proceed / explainable evidence required | Compliance → Retrieval → `ANSWERED` | Correct classification and behavior |
| Explicit deterministic status-only audit | Proceed / explainable evidence required | Compliance → guard → Retrieval → `ANSWERED` | Semantic evidence-requirement false positive; guard enforcement correct |

`requirements_v2` is independently recorded alongside the frozen `agent_v2` prompt and `guardrails_v1` orchestration. It replaces the compressed action/boolean contract with only two enums:

- `decision_definition`: `SUFFICIENT`, `MISSING_REQUIRED_CRITERIA`, `AMBIGUOUS_ENTITY`, or `MISSING_REQUIRED_SCOPE`;
- `policy_support_requirement`: `NONE`, `STATUS_ONLY`, or `EXPLAINABLE_POLICY_EVIDENCE`.

The taxonomy deliberately separates the two different costs observed live. A decision-definition false negative may trigger unnecessary or misleading data inspection; an evidence-requirement false positive may add Retrieval, tokens, and latency. The runtime remains mechanical: any non-sufficient decision definition returns `CLARIFICATION_REQUIRED` before tools; only `EXPLAINABLE_POLICY_EVIDENCE` participates in the unchanged evidence-completeness invariant after successful Compliance. `STATUS_ONLY` permits Compliance-only completion, while RAG-only policy questions never force Compliance.

`evals/requirements/requirements_v2_fixture.json` is a runtime-isolated, twelve-case semantic fixture covering ordinary SQL, Analytics, status-only and explainable compliance, RAG policy questions, each clarification state, and a broad but answerable request. Its evaluator reports separate decision-definition, clarification precision/recall and false counts, policy-support accuracy, explainable-evidence precision/recall and false counts. The model-free script is explicitly an oracle self-check of fixture and metric wiring; it is not presented as a live model-quality result. No live request was made for this calibration implementation.

## Controlled orchestration A/B

The fixed ten-case treatment held `agent_v2` prompt text, `gpt-5.6-luna`, and reasoning effort `none` constant while adding `guardrails_v1` with `requirements_v2`. The frozen control is `evals/results/agent_smoke_v2_live.json`; treatment artifacts are `evals/results/agent_smoke_v2_guardrails_v1_requirements_v2_live.json` and `.md`. These are single live samples, not production measurements.

| Metric | `agent_v2` control | Guardrails treatment | Absolute change |
| --- | ---: | ---: | ---: |
| Deterministic checks passed | 7 / 10 | 5 / 10 | -2 |
| Tool-selection precision | 0.9000 | 1.0000 | +0.1000 |
| Tool-selection recall / required coverage | 0.9167 | 0.6000 | -0.3167 |
| Unnecessary tool-call rate | 0.1000 | 0.0000 | -0.1000 |
| Trajectory success rate | 0.7000 | 0.6000 | -0.1000 |
| Response-outcome accuracy | 0.9000 | 0.5000 | -0.4000 |
| Citation correctness / evidence coverage | 0.8000 | 0.6000 | -0.2000 |
| Total API requests | 25 | 26 | +1 |
| Total tokens | 58,387 | 49,031 | -9,356 |
| Local live latency mean / median (ms) | 6,573.541 / 5,258.619 | 5,472.587 / 3,074.230 | -1,100.954 / -2,184.389 |

`requirements_v2` corrected the canonical clarification path: `TASK-033` returned `MISSING_REQUIRED_CRITERIA`, made zero tool calls, and correctly returned `CLARIFICATION_REQUIRED`. On the six treatment requests with exact fixture labels, decision-definition accuracy was 0.6667; clarification precision/recall were 0.3333 / 1.0000, with two false-positive clarifications (`TASK-009`, `TASK-025`). Policy-support classification was 1.0000 on that labeled subset, including `STATUS_ONLY` for `TASK-020` and explainable evidence for `TASK-025`.

The guard triggered once, in `TASK-030`. It correctly prevented acceptance of an explainable compliance answer without Retrieval evidence, then the Agent made two Retrieval calls after remediation. It did not complete before the existing seven-turn limit, producing `MODEL_TURN_LIMIT` / `INSUFFICIENT_EVIDENCE`; this is bounded remediation behavior, not acceptance of incomplete evidence. No guard triggered for `STATUS_ONLY` `TASK-020`; its treatment trajectory was Compliance-only. The treatment nevertheless over-clarified policy questions in `TASK-009`, `TASK-010`, `TASK-025`, and `TASK-035`, which reduced required-tool coverage, outcome accuracy, and citation/evidence coverage.

Per-case outcome: `TASK-001`, `TASK-002`, `TASK-014`, and `TASK-020` were unchanged passes; `TASK-033` improved; `TASK-009`, `TASK-010`, `TASK-025`, and `TASK-035` regressed through clarification; `TASK-030` replaced a premature uncited answer with bounded insufficient evidence after guard intervention. The treatment's preflight added ten model requests, but early clarification suppressed enough Agent-loop work that net requests rose by only one and total tokens/latency fell in this sample. The reliability trade-off is therefore mixed, not a readiness signal for the 38-case benchmark.
