# Phase 3A — Agent Tool Interface Layer

## Purpose and boundary

Phase 3A exposes the four accepted procurement capabilities as small, typed, framework-neutral Python adapters. It adds no LangGraph, LLM call, prompt, answer generation, planner, memory, API, or UI.

```text
future framework adapter
        ↓
typed tool input → validated component call → structured result / normalized error
```

Each adapter returns `ToolResponse`: typed `result` or `ToolError`, plus a UUID runtime call ID, UTC start/end timestamps, duration in milliseconds, success flag, and actual backend. `to_dict()` serializes dates, datetimes, Decimals, dataclasses, tuples, and enums into JSON-compatible values. Runtime call IDs are deliberately not stable identifiers.

`ToolResponse.to_call_record(arguments)` creates the framework-neutral `ToolCallRecord` used by a future orchestrator: call ID, tool name, JSON-safe arguments, timings, success, result type summary, and normalized error. It records an interface execution without introducing an Agent trace store.

## Four contracts

| Tool | Input | Result | Backend / boundary |
|---|---|---|---|
| `query_procurement_database` | `sql`, optional `max_rows` (1–100) | columns, rows, row count, truncation flag, limit | SQLite + existing SELECT-only query layer |
| `retrieve_procurement_policy` | query, explicit/defaulted target date, top-k (1–10), lexical/dense/hybrid mode | ranked PDF-derived evidence with chunk/document/version/effective interval/section/page/content/score | local canonical chunk registry; hybrid is local BM25 + exact dense RRF |
| `analyze_procurement_data` | explicit bounded operation and its domain arguments | existing typed spend, price, or concentration/risk result | SQLite; no arbitrary code |
| `check_policy_compliance` | PO number | existing `ComplianceResult`, rule results, reasons, observations, provenance, and skipped rules | SQLite facts + structured PolicyRules; never Retrieval |

Hybrid is the default retrieval mode because it is the current best measured baseline. The tool truthfully reports `local_pdf_chunk_registry`: it does not claim that hybrid executes in pgvector. The validated pgvector dense retriever remains a separate deployment integration and future backend option.

## Error semantics

`ToolError` contains a compact code, safe message, retryability flag, and optional structured details. No raw traceback crosses a tool boundary. Known examples are `VALIDATION_ERROR`, `SQL_SAFETY_VIOLATION`, `SQL_EXECUTION_ERROR`, `ROW_LIMIT_EXCEEDED`, `ENTITY_NOT_FOUND`, and component execution errors.

A successful tool call can still return insufficient business evidence. In particular, a 2024 policy query returns `success=true`, zero evidence, and `NO_APPLICABLE_POLICY_EVIDENCE`; insufficient price peers remain a successful Analytics result; and a 2025 executable-rule gap remains a successful Compliance result with `REVIEW`.

## Internal fact loading and evaluation alignment

Analytics and Compliance adopt domain-level inputs and load their own SQLite facts. This avoids unsafe LLM-mediated row shuttling, repeated SQL calls, and malformed fact assembly. General SQL remains the tool for ad-hoc facts, joins, rankings, and aggregations.

The Phase 2G dataset records Phase 3A interface overrides in `tool_interface_overrides`. The resolved contract changes 21 cases:

- `TASK-014`–`TASK-019`: Analytics alone is required.
- `TASK-020`–`TASK-024`, `TASK-037`, and `TASK-038`: Compliance alone is required.
- `TASK-025`–`TASK-029` and `TASK-031`: Compliance + policy retrieval are required.
- `TASK-030` and `TASK-032`: Analytics + Compliance + policy retrieval are required.

Their earlier explicit SQL calls are now unnecessary, not merely optional, because the direct domain result already contains the required audited or analytical facts. SQL-only and RAG-only restraint cases are unchanged. Ground-truth values, policy evidence targets, compliance statuses, and response outcomes are unchanged.

## Readiness benchmark

Run:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_tool_readiness.py
```

The 14 deterministic calls cover SQL success, rejection, and syntax error; current and unsupported policy retrieval; all accepted Analytics operations including insufficient peers; Compliance PASS/FAIL/REVIEW; and an unknown PO error. The machine-readable output is `evals/results/tool_readiness.json`.

## Limitations and next gate

The registry is plain Python and intentionally has no framework decorator. It provides stable lookup, descriptions, input types, execution, and lifecycle cleanup only. A later Agent phase may aggregate the already-defined `ToolCallRecord` traces through a LangGraph or SDK adapter; it must not duplicate component logic or alter tool semantics.
