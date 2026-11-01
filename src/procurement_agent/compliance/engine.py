"""Explicit deterministic evaluators for the accepted approval and contract rules."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from procurement_agent.compliance.models import ApprovalFact, ComplianceResult, ComplianceStatus, ContractFact, PolicyRule, PurchaseOrderFacts, RuleResult
from procurement_agent.compliance.policy_loader import load_policy_rules
from procurement_agent.database.connection import sqlite_engine
from procurement_agent.database.models import Approval, Category, Contract, PurchaseOrder


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "generated" / "procurement.sqlite"


class ComplianceAuditError(ValueError):
    pass


def load_po_compliance_facts(engine: Engine, po_number: str) -> PurchaseOrderFacts:
    """Load one PO's audit facts from SQLite; ground-truth artifacts are never consulted."""
    with Session(engine) as session:
        po = session.get(PurchaseOrder, po_number)
        if po is None:
            raise ComplianceAuditError(f"Unknown purchase order: {po_number}")
        category = session.get(Category, po.category_id)
        if category is None:
            raise ComplianceAuditError(f"{po_number}: category is unresolved")
        contract_row = session.get(Contract, po.contract_id) if po.contract_id else None
        approvals = tuple(
            ApprovalFact(row.approval_type, row.status, row.approver_id, row.approver_role, row.approved_at)
            for row in session.scalars(select(Approval).where(Approval.po_number == po_number).order_by(Approval.approval_id))
        )
        contract = None if contract_row is None else ContractFact(
            contract_row.contract_id, contract_row.supplier_id, contract_row.category_id, contract_row.status,
            contract_row.effective_date, contract_row.expiration_date, contract_row.termination_date,
        )
        return PurchaseOrderFacts(
            po_number=po.po_number, supplier_id=po.supplier_id, category_id=po.category_id, category_name=category.name,
            contract_required=category.contract_required, order_date=po.order_date, status=po.status,
            total_amount_usd=Decimal(po.total_amount_usd), contract_reference=po.contract_reference or "", contract_id=po.contract_id,
            approval_evidence_status=po.approval_evidence_status, contract_evidence_status=po.contract_evidence_status,
            contract=contract, approvals=approvals,
        )


def _result(rule: PolicyRule, applicable: bool, status: ComplianceStatus | None, reasons: tuple[str, ...], observed: dict, required: dict) -> RuleResult:
    return RuleResult(rule.rule_code, rule.rule_type, applicable, status, reasons, observed, required, rule.provenance)


def evaluate_approval_rule(rule: PolicyRule, facts: PurchaseOrderFacts) -> RuleResult:
    threshold = Decimal(str(rule.parameters["amount_usd"]))
    applicable = facts.total_amount_usd > threshold
    required = {"amount_operator": rule.parameters["amount_operator"], "amount_usd": threshold, "minimum_distinct_purchase_approvals": rule.parameters["minimum_distinct_purchase_approvals"], "requires_director": bool(rule.parameters["requires_director"])}
    observed = {"total_amount_usd": facts.total_amount_usd, "approval_evidence_status": facts.approval_evidence_status}
    if not applicable:
        return _result(rule, False, None, ("RULE_NOT_APPLICABLE",), observed, required)
    if facts.approval_evidence_status != "COMPLETE":
        return _result(rule, True, "REVIEW", ("APPROVAL_EVIDENCE_UNAVAILABLE",), observed, required)
    valid = [approval for approval in facts.approvals if approval.approval_type == "PURCHASE" and approval.status == "APPROVED" and approval.approved_at and approval.approved_at.date() <= facts.order_date]
    approvers = {approval.approver_id for approval in valid}
    has_director = any(approval.approver_role == "DIRECTOR" for approval in valid)
    observed.update({"valid_purchase_approval_count": len(approvers), "valid_purchase_approver_ids": sorted(approvers), "valid_director_approval": has_director})
    reasons: list[str] = []
    if len(approvers) < int(rule.parameters["minimum_distinct_purchase_approvals"]):
        reasons.append("INSUFFICIENT_VALID_APPROVAL_COUNT")
    if bool(rule.parameters["requires_director"]) and not has_director:
        reasons.append("DIRECTOR_APPROVAL_MISSING")
    return _result(rule, True, "FAIL" if reasons else "PASS", tuple(reasons), observed, required)


def _valid_exception(facts: PurchaseOrderFacts) -> bool:
    return any(
        approval.approval_type == "CONTRACT_EXCEPTION" and approval.status == "APPROVED"
        and approval.approver_role == "DIRECTOR" and approval.approved_at and approval.approved_at.date() <= facts.order_date
        for approval in facts.approvals
    )


def _contract_failure_reason(facts: PurchaseOrderFacts) -> str | None:
    contract = facts.contract
    if contract is None:
        return "CONTRACT_MISSING"
    if contract.effective_date > facts.order_date or facts.order_date > contract.expiration_date:
        return "CONTRACT_EXPIRED"
    if contract.supplier_id != facts.supplier_id:
        return "CONTRACT_SUPPLIER_MISMATCH"
    if contract.category_id != facts.category_id:
        return "CONTRACT_CATEGORY_MISMATCH"
    if contract.termination_date is not None and contract.termination_date <= facts.order_date:
        return "CONTRACT_TERMINATED"
    if contract.status not in {"EXECUTED", "TERMINATED"}:
        return "CONTRACT_INVALID"
    return None


def evaluate_contract_rule(rule: PolicyRule, facts: PurchaseOrderFacts) -> RuleResult:
    applicable = facts.contract_required
    required = {"contract_required_categories": rule.parameters["contract_required_categories"], "valid_exception": rule.parameters["valid_exception"]}
    observed = {"category_name": facts.category_name, "contract_required": facts.contract_required, "contract_evidence_status": facts.contract_evidence_status, "approval_evidence_status": facts.approval_evidence_status, "contract_reference": facts.contract_reference, "contract_id": facts.contract_id}
    if not applicable:
        return _result(rule, False, None, ("RULE_NOT_APPLICABLE",), observed, required)
    if facts.contract_evidence_status != "COMPLETE":
        return _result(rule, True, "REVIEW", ("CONTRACT_EVIDENCE_UNAVAILABLE",), observed, required)
    contract_reason = _contract_failure_reason(facts)
    if contract_reason is None:
        return _result(rule, True, "PASS", (), observed, required)
    if facts.approval_evidence_status != "COMPLETE":
        return _result(rule, True, "REVIEW", ("APPROVAL_EVIDENCE_UNAVAILABLE",), observed, required)
    if _valid_exception(facts):
        return _result(rule, True, "PASS", ("VALID_EXCEPTION",), observed, required)
    if facts.contract is None and facts.contract_reference:
        return _result(rule, True, "REVIEW", ("CONTRACT_REFERENCE_UNRESOLVED",), observed, required)
    return _result(rule, True, "FAIL", (contract_reason,), observed, required)


class ComplianceEngine:
    def __init__(self, engine: Engine, rules: tuple[PolicyRule, ...] | None = None) -> None:
        self.engine = engine
        self.rules = load_policy_rules() if rules is None else rules

    def audit(self, po_number: str) -> ComplianceResult:
        facts = load_po_compliance_facts(self.engine, po_number)
        return self.evaluate_facts(facts)

    def evaluate_facts(self, facts: PurchaseOrderFacts) -> ComplianceResult:
        if facts.status == "CANCELLED":
            raise ComplianceAuditError(f"{facts.po_number}: CANCELLED purchase orders are outside audit scope")
        if facts.status not in {"ISSUED", "CLOSED"}:
            raise ComplianceAuditError(f"{facts.po_number}: unsupported audit status {facts.status}")
        available = [rule for rule in self.rules if rule.applies_on(facts.order_date)]
        evidence = {"approval_evidence_status": facts.approval_evidence_status, "contract_evidence_status": facts.contract_evidence_status}
        if not available:
            return ComplianceResult(facts.po_number, facts.order_date, "REVIEW", 0, (), (), evidence,
                                    "No executable PolicyRule covers the PO order date.", ("EXECUTABLE_POLICY_RULE_UNAVAILABLE_FOR_DATE",))
        evaluations = [evaluate_approval_rule(rule, facts) if rule.rule_type == "approval_requirement" else evaluate_contract_rule(rule, facts) for rule in available]
        applicable = tuple(item for item in evaluations if item.applicable)
        skipped = tuple(item for item in evaluations if not item.applicable)
        statuses = {item.status for item in applicable}
        overall: ComplianceStatus = "FAIL" if "FAIL" in statuses else "REVIEW" if "REVIEW" in statuses else "PASS"
        return ComplianceResult(facts.po_number, facts.order_date, overall, len(applicable), applicable, skipped, evidence)


def audit_purchase_order(po_number: str, database_path: Path = DEFAULT_DATABASE_PATH) -> ComplianceResult:
    engine = sqlite_engine(database_path)
    try:
        return ComplianceEngine(engine).audit(po_number)
    finally:
        engine.dispose()
