"""Offline scoring for the versioned requirements-classification fixture."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from procurement_agent.agent.models import RequestRequirementsV2


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATHS = {
    "requirements_v2": PROJECT_ROOT / "evals" / "requirements" / "requirements_v2_fixture.json",
    "requirements_v2_1": PROJECT_ROOT / "evals" / "requirements" / "requirements_v2_1_fixture.json",
}


@dataclass(frozen=True)
class RequirementsFixtureCase:
    case_key: str
    user_query: str
    decision_definition: str
    policy_support_requirement: str


def load_requirements_fixture(requirements_version: str = "requirements_v2") -> list[RequirementsFixtureCase]:
    if requirements_version not in FIXTURE_PATHS:
        raise ValueError("Unsupported requirements fixture version")
    path = FIXTURE_PATHS[requirements_version]
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("requirements_version") != requirements_version:
        raise ValueError("Unsupported requirements fixture version")
    return [RequirementsFixtureCase(**case) for case in data["cases"]]


def fixture_oracle_predictions(cases: list[RequirementsFixtureCase]) -> dict[str, RequestRequirementsV2]:
    return {
        case.case_key: RequestRequirementsV2(
            decision_definition=case.decision_definition,
            clarification_question=None,
            policy_support_requirement=case.policy_support_requirement,
        )
        for case in cases
    }


def evaluate_requirements(cases: list[RequirementsFixtureCase], predictions: dict[str, RequestRequirementsV2]) -> dict[str, float | int]:
    expected_keys = {case.case_key for case in cases}
    if set(predictions) != expected_keys:
        raise ValueError("Predictions must contain exactly the fixture case keys")
    expected_clarify = {case.case_key for case in cases if case.decision_definition != "SUFFICIENT"}
    predicted_clarify = {key for key, value in predictions.items() if value.decision_definition != "SUFFICIENT"}
    expected_evidence = {case.case_key for case in cases if case.policy_support_requirement == "EXPLAINABLE_POLICY_EVIDENCE"}
    predicted_evidence = {key for key, value in predictions.items() if value.policy_support_requirement == "EXPLAINABLE_POLICY_EVIDENCE"}
    decision_correct = sum(predictions[case.case_key].decision_definition == case.decision_definition for case in cases)
    policy_correct = sum(predictions[case.case_key].policy_support_requirement == case.policy_support_requirement for case in cases)
    true_positive_clarify = len(expected_clarify & predicted_clarify)
    true_positive_evidence = len(expected_evidence & predicted_evidence)
    return {
        "case_count": len(cases),
        "decision_definition_accuracy": decision_correct / len(cases),
        "clarification_precision": true_positive_clarify / len(predicted_clarify) if predicted_clarify else 1.0,
        "clarification_recall": true_positive_clarify / len(expected_clarify) if expected_clarify else 1.0,
        "clarification_false_negative_count": len(expected_clarify - predicted_clarify),
        "clarification_false_positive_count": len(predicted_clarify - expected_clarify),
        "policy_support_classification_accuracy": policy_correct / len(cases),
        "explainable_policy_evidence_precision": true_positive_evidence / len(predicted_evidence) if predicted_evidence else 1.0,
        "explainable_policy_evidence_recall": true_positive_evidence / len(expected_evidence) if expected_evidence else 1.0,
        "evidence_requirement_false_positive_count": len(predicted_evidence - expected_evidence),
        "evidence_requirement_false_negative_count": len(expected_evidence - predicted_evidence),
    }


def fixture_distribution(cases: list[RequirementsFixtureCase]) -> dict[str, dict[str, int]]:
    return {
        "decision_definition": dict(sorted(Counter(case.decision_definition for case in cases).items())),
        "policy_support_requirement": dict(sorted(Counter(case.policy_support_requirement for case in cases).items())),
    }
