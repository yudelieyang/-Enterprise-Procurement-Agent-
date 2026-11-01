# agent_v2 Live Smoke Evaluation

Configuration: `gpt-5.6-luna`, reasoning effort `none`, `chat.completions.parse`.

## Aggregate results

| Measure | Value |
| --- | ---: |
| Completed cases | 10 / 10 |
| Deterministic trace/citation/outcome checks passed | 7 / 10 |
| tool_selection_precision | 0.9000 |
| tool_selection_recall | 0.9167 |
| required_tool_coverage | 0.9167 |
| unnecessary_tool_call_rate | 0.1000 |
| trajectory_success_rate | 0.7000 |
| response_outcome_accuracy | 0.9000 |
| citation_correctness | 0.8000 |
| evidence_coverage | 0.8000 |

## Observable trajectories

| Case | Tool trajectory | Outcome | Failure category |
| --- | --- | --- | --- |
| TASK-001 | query_procurement_database → query_procurement_database | ANSWERED | None |
| TASK-002 | query_procurement_database | ANSWERED | None |
| TASK-009 | retrieve_procurement_policy | ANSWERED | None |
| TASK-010 | retrieve_procurement_policy | ANSWERED | None |
| TASK-014 | analyze_procurement_data | ANSWERED | None |
| TASK-020 | check_policy_compliance | ANSWERED | None |
| TASK-025 | check_policy_compliance | ANSWERED | CITATION_ERROR |
| TASK-033 | query_procurement_database → query_procurement_database | INSUFFICIENT_EVIDENCE | INCORRECT_RESPONSE_OUTCOME |
| TASK-035 | retrieve_procurement_policy | INSUFFICIENT_EVIDENCE | None |
| TASK-030 | analyze_procurement_data → check_policy_compliance → check_policy_compliance → check_policy_compliance | ANSWERED | CITATION_ERROR |

Final-answer fact extraction is `NOT_AUTOMATICALLY_SCORED`; this report records deterministic trace, citation, and outcome checks only.
