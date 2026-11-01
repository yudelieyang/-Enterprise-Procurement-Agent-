# agent_v2 / guardrails_v1 Live Smoke Evaluation

Configuration: `gpt-5.6-luna`, reasoning effort `none`, `chat.completions.parse`, orchestration `guardrails_v1`.

## Aggregate results

| Measure | Value |
| --- | ---: |
| Completed cases | 10 / 10 |
| Deterministic trace/citation/outcome checks passed | 5 / 10 |
| tool_selection_precision | 1.0000 |
| tool_selection_recall | 0.6000 |
| required_tool_coverage | 0.6000 |
| unnecessary_tool_call_rate | 0.0000 |
| trajectory_success_rate | 0.6000 |
| response_outcome_accuracy | 0.5000 |
| citation_correctness | 0.6000 |
| evidence_coverage | 0.6000 |

## Observable trajectories

| Case | Tool trajectory | Outcome | Failure category |
| --- | --- | --- | --- |
| TASK-001 | query_procurement_database → query_procurement_database | ANSWERED | None |
| TASK-002 | query_procurement_database | ANSWERED | None |
| TASK-009 | No tool | CLARIFICATION_REQUIRED | CITATION_ERROR |
| TASK-010 | No tool | CLARIFICATION_REQUIRED | CITATION_ERROR |
| TASK-014 | analyze_procurement_data | ANSWERED | None |
| TASK-020 | check_policy_compliance | ANSWERED | None |
| TASK-025 | No tool | CLARIFICATION_REQUIRED | CITATION_ERROR |
| TASK-033 | No tool | CLARIFICATION_REQUIRED | None |
| TASK-035 | No tool | CLARIFICATION_REQUIRED | INCORRECT_RESPONSE_OUTCOME |
| TASK-030 | analyze_procurement_data → check_policy_compliance → check_policy_compliance → check_policy_compliance → retrieve_procurement_policy → retrieve_procurement_policy | INSUFFICIENT_EVIDENCE | LOOP_LIMIT |

Final-answer fact extraction is `NOT_AUTOMATICALLY_SCORED`; this report records deterministic trace, citation, and outcome checks only.
