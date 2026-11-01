# Phase 3B — Single-Agent LangGraph Orchestration

## Purpose and boundary

Phase 3B turns the four Phase 3A interfaces into one observable, bounded LangGraph Agent. It is the first user-facing synthesis layer, but it does not introduce a specialist-agent hierarchy, persistent memory, UI, API server, pgvector changes, or new deterministic business logic.

```text
START → model → tools? → model → … → final validation → END
```

The `tools` node executes model requests sequentially through the existing `ToolRegistry`. The only exposed capabilities remain `query_procurement_database`, `retrieve_procurement_policy`, `analyze_procurement_data`, and `check_policy_compliance`.

## Why LangGraph and one Agent

The workflow needs an explicit, inspectable loop: a model can request evidence, see a typed tool result, request additional evidence, or terminate. LangGraph supplies that control flow without forcing the four bounded components to become agents. A supervisor or specialist-agent layer would add handoff and evaluation burden with no retained MVP requirement.

## Model integration and configuration

`LiveOpenAIModelAdapter` calls the official OpenAI Python SDK directly. It uses Chat Completions function calling for tool-selection turns and JSON Schema output for `AgentFinalResponse`. The adapter is intentionally thin; `ScriptedModelAdapter` feeds the same graph deterministic observable turns for ordinary tests.

Configuration is environment-driven:

```text
OPENAI_API_KEY
PROCUREMENT_AGENT_MODEL=gpt-5.6-luna
PROCUREMENT_AGENT_REASONING_EFFORT=low
```

No key is committed or required for the deterministic suite. The prompt artifact is `agent_v1` in `src/procurement_agent/agent/prompts.py`. It contains role/tool/evidence rules and a compact schema reference dynamically derived from SQLAlchemy table metadata; it contains neither rows, policy text, case IDs, nor golden answers.

## State and trace

The graph state contains messages, original query, optional caller-supplied target date, pending tool calls, Phase 3A `ToolCallRecord`s, evidence references, repeated-call counters, model/tool counts, final response, termination reason, and API usage metadata. It never stores a database, an embedding array, or model hidden reasoning.

`AgentRunTrace` records the run ID, optional case ID, model, prompt version, timestamps/duration, observable tool actions/arguments/outcomes, evidence references, final outcome, termination reason, and provider usage fields when returned. It deliberately does not request or save chain-of-thought.

## Grounding and citations

The final typed contract is `AgentFinalResponse`:

```text
response_outcome: ANSWERED | CLARIFICATION_REQUIRED | INSUFFICIENT_EVIDENCE
answer
citations
tool_call_ids
evidence_summary
limitations
```

Retrieval evidence registers chunk/document/version/section/page metadata. Compliance registers executable-rule provenance with the same document/version/section/page shape. A model may select a returned Retrieval `chunk_id`; final validation then materializes every displayed citation field from that run-local evidence record. Without a chunk ID, the model must provide a complete exact metadata match to run-local Retrieval or Compliance evidence. Fabricated citations and unknown tool-call IDs are removed and flagged in `limitations`; `citation_validation` preserves the model selector and a safe acceptance/rejection reason.

`REVIEW` remains a deterministic compliance status, not an Agent response outcome. An answer explaining a `REVIEW` can therefore be `ANSWERED`. When a policy date has no applicable evidence, the Agent should use `INSUFFICIENT_EVIDENCE` rather than fall forward to another version. Essential ambiguity should produce `CLARIFICATION_REQUIRED` without decorative tool calls.

### OpenAI parse compatibility and safe diagnostics

The OpenAI-facing function schemas are strict: every function has `strict: true`, `additionalProperties: false`, and a complete `required` property list. Arguments that are optional at the framework-neutral Phase 3A boundary are nullable in the strict schema, preserving the existing adapter defaults and validation. This is required by `chat.completions.parse`; it does not alter any Phase 3A business interface.

If the SDK/provider boundary fails, `AgentRunTrace.model_diagnostics` records only the stage, exception class, and a sanitized, length-bounded message. The user-facing final response remains safe and structured. API-key and authorization-like fragments are redacted; no request headers, key values, or hidden model reasoning are recorded.

## Reliability controls

`AgentConfig` defaults to seven model turns, ten total tool calls, and two identical calls for any normalized `(tool, arguments)` pair. The controls are enforced in graph code, not merely stated in the prompt:

- a model-turn limit yields a safe insufficient-evidence response;
- a total-tool-call limit yields a structured blocked call and safe termination;
- repeated identical calls are blocked;
- tool errors remain structured messages for a subsequent model turn;
- only registry names can execute; and
- final citations and tool-call IDs are validated against the observed run.

Tool results passed to the model are compacted by bounded list/text limits. Complete typed tool results remain in the runtime record; no LLM summarizer is introduced.

## Commands and verification

```powershell
.\.venv\Scripts\python.exe scripts\run_agent.py "Is PO-2026-1842 compliant with procurement policy?"
.\.venv\Scripts\python.exe scripts\evaluate_agent_smoke.py
.\.venv\Scripts\python.exe -m pytest tests/test_agent_orchestration.py
```

`scripts/evaluate_agent_smoke.py` loads only ten selected Phase 2G cases and writes `evals/results/agent_smoke_v1.json`. It uses deterministic trajectory/citation checks and clearly records answer-fact scoring as not yet automatic. If `OPENAI_API_KEY` is absent, it writes `skipped` and makes no network request.

The initial workspace had no configured OpenAI key, so Phase 3B's live smoke report is honestly `skipped`. Scripted tests verify multi-step Registry execution, a clarification without tools, no-evidence handling, SQL safety error propagation, invalid citation rejection, provenance citations, repeated-call blocking, model-turn limits, and total-tool limits. The separately marked live test is additionally opt-in through `RUN_LIVE_AGENT_TESTS=1`, so ordinary `pytest` never spends API credits.

Actual verification in this workspace is updated after each deterministic regression; live smoke measurements are recorded only after a real API run. The live-test skip is deliberate opt-in behavior, not a deterministic failure.

## Limitations and next gate

This establishes orchestration correctness, not a full Agent quality score. A configured account must still run the selected live smoke set before Phase 3C can analyze generated answer quality. Phase 3B does not tune against all 38 tasks, calculate API cost, use an LLM-as-judge, add persistence, or make a production API.

## Untouched Live Smoke Baseline

The preserved live baseline is `evals/results/agent_smoke_v1_live_baseline.json`. It used `gpt-5.6-luna`, reasoning effort `none`, the official `chat.completions.parse` adapter, and independent single-request runs for the fixed ten selected cases. No prompt, tool, retrieval, analytics, compliance, or golden-task changes occurred during the run.

All ten cases completed with 27 model requests. Deterministic trace/citation/outcome checks passed for 6/10 cases: tool-selection precision was 0.85, recall and required-tool coverage were 0.9167, unnecessary-tool-call rate was 0.15, trajectory-success rate was 0.60, response-outcome accuracy was 0.90, and citation correctness/evidence coverage were both 0.80. Generated-answer fact checks are explicitly `NOT_AUTOMATICALLY_SCORED`.

Measured usage was 53,140 input tokens (42,980 cached), 3,699 output tokens, zero reported reasoning tokens, and 56,839 total tokens. Local live smoke latency was mean 6,863.597 ms, median 5,345.104 ms, minimum 3,213.188 ms, and maximum 17,066.190 ms; this is not a production-latency claim.

Observed behavior findings were retained without tuning: `TASK-002` made an unnecessary Analytics call; `TASK-025` omitted required policy retrieval/citations; `TASK-033` made a SQL call and returned `INSUFFICIENT_EVIDENCE` instead of clarification; and `TASK-030` omitted policy retrieval/citations. The previous execution reached all model calls but failed while serializing report-only citation diagnostics; it is retained as `agent_smoke_v1_live_invalidated_serialization.json` and is not a behavioral baseline.
