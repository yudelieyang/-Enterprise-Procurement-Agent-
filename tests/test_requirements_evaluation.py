from procurement_agent.agent.models import RequestRequirementsV2
from procurement_agent.agent.prompts import requirements_preflight_prompt
from procurement_agent.evaluation.requirements import evaluate_requirements, fixture_distribution, fixture_oracle_predictions, load_requirements_fixture


def test_requirements_fixture_has_the_required_semantic_coverage():
    cases = load_requirements_fixture()
    distribution = fixture_distribution(cases)
    assert len(cases) == 12
    assert distribution["decision_definition"] == {"AMBIGUOUS_ENTITY": 1, "MISSING_REQUIRED_CRITERIA": 1, "MISSING_REQUIRED_SCOPE": 1, "SUFFICIENT": 9}
    assert distribution["policy_support_requirement"] == {"EXPLAINABLE_POLICY_EVIDENCE": 4, "NONE": 7, "STATUS_ONLY": 1}


def test_requirements_metrics_keep_clarification_and_evidence_errors_separate():
    cases = load_requirements_fixture()
    predictions = fixture_oracle_predictions(cases)
    predictions["undefined_decision_criterion"] = RequestRequirementsV2(decision_definition="SUFFICIENT", clarification_question=None, policy_support_requirement="NONE")
    predictions["broad_but_answerable"] = RequestRequirementsV2(decision_definition="MISSING_REQUIRED_SCOPE", clarification_question="What period should I use?", policy_support_requirement="NONE")
    predictions["explainable_compliance"] = RequestRequirementsV2(decision_definition="SUFFICIENT", clarification_question=None, policy_support_requirement="STATUS_ONLY")
    predictions["status_only_compliance"] = RequestRequirementsV2(decision_definition="SUFFICIENT", clarification_question=None, policy_support_requirement="EXPLAINABLE_POLICY_EVIDENCE")
    metrics = evaluate_requirements(cases, predictions)
    assert metrics["clarification_false_negative_count"] == 1
    assert metrics["clarification_false_positive_count"] == 1
    assert metrics["evidence_requirement_false_negative_count"] == 1
    assert metrics["evidence_requirement_false_positive_count"] == 1


def test_requirements_v2_1_fixture_covers_sanctioned_scope_resolution_and_regressions():
    cases = load_requirements_fixture("requirements_v2_1")
    expected = {case.case_key: (case.decision_definition, case.policy_support_requirement) for case in cases}
    assert expected == {
        "explicit_historical_policy_scope": ("SUFFICIENT", "EXPLAINABLE_POLICY_EVIDENCE"),
        "relative_temporal_scope": ("SUFFICIENT", "EXPLAINABLE_POLICY_EVIDENCE"),
        "default_current_policy_scope": ("SUFFICIENT", "EXPLAINABLE_POLICY_EVIDENCE"),
        "po_policy_scope": ("SUFFICIENT", "EXPLAINABLE_POLICY_EVIDENCE"),
        "unavailable_historical_policy": ("SUFFICIENT", "EXPLAINABLE_POLICY_EVIDENCE"),
        "unresolved_historical_policy_scope": ("MISSING_REQUIRED_SCOPE", "EXPLAINABLE_POLICY_EVIDENCE"),
        "undefined_decision_criterion": ("MISSING_REQUIRED_CRITERIA", "NONE"),
        "ambiguous_entity": ("AMBIGUOUS_ENTITY", "NONE"),
    }
    assert evaluate_requirements(cases, fixture_oracle_predictions(cases))["decision_definition_accuracy"] == 1.0


def test_requirements_v2_1_preflight_prompt_adds_only_sanctioned_scope_context():
    v2 = requirements_preflight_prompt("requirements_v2")
    v2_1 = requirements_preflight_prompt("requirements_v2_1")
    assert "EVAL_AS_OF_DATE" not in v2
    assert "EVAL_AS_OF_DATE is 2026-06-30" in v2_1
    assert "TASK-" not in v2_1


def test_requirements_v2_1_prompt_distinguishes_resolved_historical_scope_from_missing_scope():
    prompt = requirements_preflight_prompt("requirements_v2_1")
    assert "historical year or date is sufficient temporal scope" in prompt
    assert "do not ask for an organization or jurisdiction" in prompt
    assert "let Retrieval establish the evidence gap" in prompt
    assert "only when a necessary time period, entity, or other scope remains unresolved" in prompt
