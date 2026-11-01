# Phase 2G — Unified Evaluation Foundation

## Purpose and boundary

Phase 2G adds the task-level contract that a future Agent must satisfy. It does not create an Agent, prompt, LLM call, tool wrapper, answer chain, UI, or LLM-as-judge. Existing component benchmarks remain independent: SQL/database regression proves structured facts and query safety; PDF retrieval measures evidence ranking; Compliance measures executable-rule correctness; Analytics measures the three bounded calculations.

The new benchmark defines realistic user tasks before orchestration exists:

```text
GoldenTask + future ToolTrace + future citations
       ↓
deterministic tool / trajectory / evidence checks
       ↓
interpretable per-dimension metrics
```

## Dataset and vocabulary

`evals/tasks/golden_tasks.json` contains 38 concrete cases. The framework-neutral logical capabilities are `query_procurement_database`, `retrieve_procurement_policy`, `analyze_procurement_data`, and `check_policy_compliance`.

A case separates required, optional, and explicitly unnecessary tools. `allowed_trajectories` contains accepted routes; by default a route is an order-preserving required subsequence rather than one rigid trace. `ordering_constraints` express real dependencies such as SQL facts before Analytics or Compliance. An `exact_trajectory` option exists for a future case that genuinely needs strict order.

`ANSWERED`, `CLARIFICATION_REQUIRED`, and `INSUFFICIENT_EVIDENCE` are response outcomes. They remain separate from `PASS`, `FAIL`, and `REVIEW`, which appear only in `expected_compliance` for a real PO audit.

## Deterministic contracts

`src/procurement_agent/evaluation/tasks.py` provides framework-neutral `GoldenTask`, `ToolCall`, `ToolTrace`, `Citation`, and result models.

For an observed trace, the evaluator reports:

- tool-selection precision: permitted (`required` or `optional`) calls divided by calls made;
- tool-selection recall / required-tool coverage: distinct required capabilities invoked divided by required capabilities;
- unnecessary-tool-call rate: explicitly unnecessary calls divided by calls made; and
- trajectory success: required coverage, no unnecessary/unknown calls, satisfied dependencies, and an accepted route.

This deliberately does not collapse performance into a weighted “Agent score.” A correct answer with needless calls remains visibly inefficient.

The citation evaluator checks chunk existence, temporal applicability, and each curated document/version/section/page target. It reports citation correctness and evidence coverage separately. It does not attempt semantic LLM claim extraction; Phase 3 can build Citation Support Rate, Unsupported Claim Rate, and Evidence Coverage from these authored mappings.

## Data consistency validation

Run after component artifacts exist:

```powershell
.\.venv\Scripts\python.exe scripts\validate_golden_tasks.py
```

The validator rejects duplicate IDs, unknown/overlapping tool contracts, invalid trajectories, invalid dates, invoice/payment scope expansion, and incorrect clarification contracts. It validates entities against SQLite; policy evidence against the PDF-derived canonical chunk registry and temporal applicability; structured facts through reference SQL; analytics through the Analytics component; and PO status through the Compliance Engine. It also verifies explicit no-policy-coverage cases.

It writes `evals/results/golden_task_validation.json` and `evals/results/golden_task_summary.md`. These are benchmark-definition artifacts, not fabricated future-Agent results.

## Benchmark composition

The accepted corpus has 7 SQL-only, 6 RAG-only, 6 SQL+Analytics, 5 SQL+Compliance, 6 SQL+RAG+Compliance, 2 full SQL+Analytics+RAG+Compliance, and 6 reliability cases. It includes SQL/RAG restraint, PASS/FAIL/REVIEW, historical policy and executable-rule boundaries, missing PO evidence, and clarification-first cases.

Phase 3A resolves the concrete domain-tool interfaces. `tool_interface_overrides` in the dataset is applied when loading cases: domain Analytics and Compliance now load their own bounded facts, so tasks that had mandated an explicit SQL precursor now evaluate the smaller literal tool trajectory. This retains the original task families and factual ground truth while correctly measuring unnecessary SQL calls.

The portfolio-priority canonical tasks are:

- `TASK-030`: SUP-042 H1 investigation — SQL facts, record-level drivers, three PO compliance outcomes, and policy provenance.
- `TASK-025`: PO-2026-1842 explainability audit — structured facts, approval FAIL / contract PASS / overall FAIL, and both human-readable policy sources.

## Limitations and next gate

There is no Agent trace production yet, so task success, answer-fact extraction, citation support for generated prose, correct-clarification rate, latency, and token cost are only defined contracts. Phase 3 may connect its traces and responses to this fixed benchmark; it must not rewrite the benchmark merely to fit a chosen framework or prompt.
