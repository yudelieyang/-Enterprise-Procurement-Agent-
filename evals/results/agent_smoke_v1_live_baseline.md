# Phase 3B.5 Untouched Live Smoke Baseline

Configuration: `gpt-5.6-luna`, reasoning effort `none`, `chat.completions.parse`, ten independent runs, prompt `agent_v1`.

The first execution reached all model calls but failed while serializing a report-only Pydantic citation-validation record. It is retained as `agent_smoke_v1_live_invalidated_serialization.json`; the JSON baseline beside this file is the valid untouched run.

## Aggregate results

| Measure | Value |
| --- | ---: |
| Completed cases | 10 / 10 |
| Deterministic trace/citation/outcome checks passed | 6 / 10 |
| Tool selection precision | 0.8500 |
| Tool selection recall / required coverage | 0.9167 |
| Unnecessary tool-call rate | 0.1500 |
| Trajectory success rate | 0.6000 |
| Response outcome accuracy | 0.9000 |
| Citation correctness / evidence coverage | 0.8000 |
| Model requests | 27 |
| Input / cached input tokens | 53,140 / 42,980 |
| Output / reasoning tokens | 3,699 / 0 |
| Total tokens | 56,839 |
| Local latency mean / median | 6,863.597 ms / 5,345.104 ms |
| Local latency min / max | 3,213.188 ms / 17,066.190 ms |

Final-answer fact extraction is `NOT_AUTOMATICALLY_SCORED` for every case. These are local live smoke measurements, not production latency or a composite Agent score.

## Observable trajectories

| Case | Tool trajectory | Outcome | Dominant finding |
| --- | --- | --- | --- |
| TASK-001 | SQL → SQL | ANSWERED | Deterministic checks passed |
| TASK-002 | Analytics → SQL | ANSWERED | Unnecessary Analytics call |
| TASK-009 | Retrieval | ANSWERED | Deterministic checks passed |
| TASK-010 | Retrieval | ANSWERED | Deterministic checks passed |
| TASK-014 | Analytics | ANSWERED | Deterministic checks passed |
| TASK-020 | Compliance | ANSWERED | Deterministic checks passed |
| TASK-025 | Compliance | ANSWERED | Missing Retrieval and required policy citations |
| TASK-033 | SQL | INSUFFICIENT_EVIDENCE | Expected clarification; SQL was unnecessary |
| TASK-035 | Retrieval → Retrieval | INSUFFICIENT_EVIDENCE | Deterministic checks passed |
| TASK-030 | Analytics → Analytics → Compliance → Compliance → Compliance | ANSWERED | Missing Retrieval and required policy citations |

Failure counts: `CITATION_ERROR=2`, `INCORRECT_RESPONSE_OUTCOME=1`, `UNNECESSARY_TOOL_CALL=1`. They are preserved baseline findings for Phase 3C, not changes made during this run.
