from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from procurement_agent.compliance.engine import ComplianceAuditError, ComplianceEngine, evaluate_approval_rule, evaluate_contract_rule, load_po_compliance_facts
from procurement_agent.compliance.models import ApprovalFact, ContractFact
from procurement_agent.compliance.policy_loader import load_policy_rules
from procurement_agent.data.generator import DEFAULT_SEED, write_dataset
from procurement_agent.database.connection import sqlite_engine
from procurement_agent.database.loader import build_database
from procurement_agent.evaluation.compliance import evaluate_compliance


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def compliance_engine(tmp_path: Path):
    source_dir = tmp_path / "generated"
    write_dataset(source_dir, DEFAULT_SEED)
    database_path = tmp_path / "procurement.sqlite"
    build_database(database_path, source_dir)
    database = sqlite_engine(database_path)
    yield ComplianceEngine(database)
    database.dispose()


def _rule(engine: ComplianceEngine, rule_type: str):
    return next(rule for rule in engine.rules if rule.rule_type == rule_type)


def _result(engine: ComplianceEngine, po_number: str, rule_type: str):
    result = engine.audit(po_number)
    return next(item for item in result.rule_results if item.rule_type == rule_type)


def test_policy_rule_loader_preserves_manifest_backed_provenance():
    rules = load_policy_rules()
    approval = next(rule for rule in rules if rule.rule_code == "APPROVAL_OVER_50000_2026")
    contract = next(rule for rule in rules if rule.rule_code == "CONTRACT_REQUIRED_CATEGORIES_2026")
    assert (approval.provenance.source_document_id, approval.provenance.version, approval.provenance.section, approval.provenance.page) == ("APPROVAL_MATRIX_2026_1", "2026.1", "Section 4.2", 2)
    assert (contract.provenance.source_document_id, contract.provenance.version, contract.provenance.section, contract.provenance.page) == ("CONTRACT_COMPLIANCE_2026_1", "2026.1", "Section 4.1", 2)


def test_canonical_results_are_derived_from_sqlite_facts_and_match_oracle(compliance_engine: ComplianceEngine):
    expected = json.loads((PROJECT_ROOT / "data" / "generated" / "ground_truth.json").read_text(encoding="utf-8"))["canonical_compliance"]
    for po_number, statuses in expected.items():
        result = compliance_engine.audit(po_number)
        actual = {item.rule_type: item.status for item in result.rule_results}
        assert actual == {"approval_requirement": statuses["approval"], "contract_requirement": statuses["contract"]}
        assert result.overall_status == statuses["overall"]
        assert all(item.provenance.version == "2026.1" for item in result.rule_results)


@pytest.mark.parametrize(("po_number", "expected_reasons"), [
    ("PO-2026-1848", {"DIRECTOR_APPROVAL_MISSING"}),
    ("PO-2026-1849", {"INSUFFICIENT_VALID_APPROVAL_COUNT", "DIRECTOR_APPROVAL_MISSING"}),
    ("PO-2026-1850", {"INSUFFICIENT_VALID_APPROVAL_COUNT", "DIRECTOR_APPROVAL_MISSING"}),
    ("PO-2026-1851", {"INSUFFICIENT_VALID_APPROVAL_COUNT", "DIRECTOR_APPROVAL_MISSING"}),
    ("PO-2026-1852", {"INSUFFICIENT_VALID_APPROVAL_COUNT", "DIRECTOR_APPROVAL_MISSING"}),
    ("PO-2026-1853", {"INSUFFICIENT_VALID_APPROVAL_COUNT", "DIRECTOR_APPROVAL_MISSING"}),
])
def test_approval_variants_are_deterministic(compliance_engine: ComplianceEngine, po_number: str, expected_reasons: set[str]):
    result = _result(compliance_engine, po_number, "approval_requirement")
    assert result.status == "FAIL"
    assert set(result.reason_codes) == expected_reasons


def test_approval_threshold_distinct_approvers_and_unavailable_evidence(compliance_engine: ComplianceEngine):
    exact = compliance_engine.audit("PO-2026-1862")
    assert exact.overall_status == "PASS" and exact.applicable_rule_count == 0
    assert {item.status for item in exact.skipped_rules} == {None}
    facts = load_po_compliance_facts(compliance_engine.engine, "PO-2026-1846")
    duplicate = replace(facts, approvals=(
        ApprovalFact("PURCHASE", "APPROVED", "ONE", "MANAGER", datetime(2026, 4, 14, 8)),
        ApprovalFact("PURCHASE", "APPROVED", "ONE", "DIRECTOR", datetime(2026, 4, 14, 9)),
    ))
    duplicate_result = evaluate_approval_rule(_rule(compliance_engine, "approval_requirement"), duplicate)
    assert duplicate_result.status == "FAIL" and duplicate_result.reason_codes == ("INSUFFICIENT_VALID_APPROVAL_COUNT",)
    unavailable_result = evaluate_approval_rule(_rule(compliance_engine, "approval_requirement"), replace(facts, approval_evidence_status="UNAVAILABLE"))
    assert unavailable_result.status == "REVIEW" and unavailable_result.reason_codes == ("APPROVAL_EVIDENCE_UNAVAILABLE",)


def test_contract_missing_unresolved_expired_and_exception_cases(compliance_engine: ComplianceEngine):
    contract_results = {
        po: _result(compliance_engine, po, "contract_requirement")
        for po in ("PO-2026-1837", "PO-2026-1838", "PO-2026-1839", "PO-2026-1840")
    }
    assert (contract_results["PO-2026-1837"].status, contract_results["PO-2026-1837"].reason_codes) == ("FAIL", ("CONTRACT_MISSING",))
    assert (contract_results["PO-2026-1838"].status, contract_results["PO-2026-1838"].reason_codes) == ("REVIEW", ("CONTRACT_REFERENCE_UNRESOLVED",))
    assert (contract_results["PO-2026-1839"].status, contract_results["PO-2026-1839"].reason_codes) == ("FAIL", ("CONTRACT_EXPIRED",))
    assert (contract_results["PO-2026-1840"].status, contract_results["PO-2026-1840"].reason_codes) == ("PASS", ("VALID_EXCEPTION",))


@pytest.mark.parametrize(("mutator", "reason"), [
    (lambda contract: replace(contract, supplier_id="SUP-OTHER"), "CONTRACT_SUPPLIER_MISMATCH"),
    (lambda contract: replace(contract, category_id="CAT-OTHER"), "CONTRACT_CATEGORY_MISMATCH"),
    (lambda contract: replace(contract, status="TERMINATED", termination_date=date(2026, 4, 14)), "CONTRACT_TERMINATED"),
])
def test_contract_fact_failures_and_evidence_review(compliance_engine: ComplianceEngine, mutator, reason: str):
    facts = load_po_compliance_facts(compliance_engine.engine, "PO-2026-1846")
    result = evaluate_contract_rule(_rule(compliance_engine, "contract_requirement"), replace(facts, contract=mutator(facts.contract)))
    assert result.status == "FAIL" and result.reason_codes == (reason,)
    unavailable = evaluate_contract_rule(_rule(compliance_engine, "contract_requirement"), replace(facts, contract_evidence_status="UNAVAILABLE"))
    assert unavailable.status == "REVIEW" and unavailable.reason_codes == ("CONTRACT_EVIDENCE_UNAVAILABLE",)


def test_engine_aggregation_historical_boundary_and_cancelled_scope(compliance_engine: ComplianceEngine):
    fail_and_review = compliance_engine.evaluate_facts(replace(load_po_compliance_facts(compliance_engine.engine, "PO-2026-1842"), contract_evidence_status="UNAVAILABLE"))
    assert fail_and_review.overall_status == "FAIL"
    assert {item.status for item in fail_and_review.rule_results} == {"FAIL", "REVIEW"}
    historical = compliance_engine.audit("PO-2025-0421")
    assert historical.overall_status == "REVIEW" and historical.reason_codes == ("EXECUTABLE_POLICY_RULE_UNAVAILABLE_FOR_DATE",)
    with pytest.raises(ComplianceAuditError):
        compliance_engine.evaluate_facts(replace(load_po_compliance_facts(compliance_engine.engine, "PO-2026-1846"), status="CANCELLED"))


def test_component_benchmark_is_database_backed_and_fully_correct(compliance_engine: ComplianceEngine):
    report = evaluate_compliance(compliance_engine)
    assert report["metrics"] == {
        "case_count": 15,
        "rule_level_accuracy": 1.0,
        "overall_compliance_accuracy": 1.0,
        "pass": {"precision": 1.0, "recall": 1.0},
        "fail": {"precision": 1.0, "recall": 1.0},
        "review": {"precision": 1.0, "recall": 1.0},
    }
    assert all(record["passed"] for record in report["records"])
