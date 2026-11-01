# requirements_v2_1 Focused 5-Case Live Calibration

Configuration: `gpt-5.6-luna`, reasoning effort `none`, prompt `agent_v2`, orchestration `guardrails_v1`, requirements `requirements_v2_1`, max model turns `7`.
Generated: `2026-09-10T14:43:10.980789+00:00`.

## Per-case results

| Case | Requirements decision | Expected decision | Policy support | Requirements match | Tool trajectory | Guard event | Outcome | Deterministic result | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-009 | SUFFICIENT | SUFFICIENT | EXPLAINABLE_POLICY_EVIDENCE | True | retrieve_procurement_policy | None | ANSWERED | True | None |
| TASK-010 | SUFFICIENT | SUFFICIENT | EXPLAINABLE_POLICY_EVIDENCE | True | retrieve_procurement_policy | None | ANSWERED | True | None |
| TASK-025 | SUFFICIENT | SUFFICIENT | EXPLAINABLE_POLICY_EVIDENCE | True | check_policy_compliance → retrieve_procurement_policy | None | ANSWERED | True | None |
| TASK-035 | MISSING_REQUIRED_SCOPE | SUFFICIENT | EXPLAINABLE_POLICY_EVIDENCE | False | No tool | None | CLARIFICATION_REQUIRED | False | requirements_decision_mismatch, response_outcome_mismatch, tool_evaluation_failure |
| TASK-033 | MISSING_REQUIRED_CRITERIA | MISSING_REQUIRED_CRITERIA | NONE | True | No tool | None | CLARIFICATION_REQUIRED | True | None |

## Requirements metrics

```json
{
  "case_count": 5,
  "decision_definition_accuracy": 0.8,
  "clarification_precision": 0.5,
  "clarification_recall": 1.0,
  "clarification_false_positive_count": 1,
  "clarification_false_negative_count": 0,
  "policy_support_classification_accuracy": 1.0,
  "explainable_policy_evidence_precision": 1.0,
  "explainable_policy_evidence_recall": 1.0
}
```

## Downstream metrics (SUFFICIENT cases only)

```json
{
  "sufficient_case_count": 3,
  "deterministic_case_pass_count": 3,
  "tool_selection_precision": 1.0,
  "tool_selection_recall": 1.0,
  "required_tool_coverage": 1.0,
  "trajectory_success_rate": 1,
  "citation_correctness": 1.0,
  "evidence_coverage": 1.0
}
```

Total API model requests: `12`; total tokens: `19905`.

This artifact records one execution per approved case and excludes TASK-030 and all other cases.
