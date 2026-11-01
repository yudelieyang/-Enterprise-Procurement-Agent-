from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal


ComplianceStatus = Literal["PASS", "FAIL", "REVIEW"]


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class PolicyProvenance:
    source_document_id: str
    title: str
    version: str
    section: str
    page: int


@dataclass(frozen=True)
class PolicyRule:
    rule_code: str
    rule_type: Literal["approval_requirement", "contract_requirement"]
    parameters: dict[str, Any]
    effective_date: date
    expiration_date: date | None
    provenance: PolicyProvenance

    def applies_on(self, target_date: date) -> bool:
        return target_date >= self.effective_date and (self.expiration_date is None or target_date <= self.expiration_date)


@dataclass(frozen=True)
class ApprovalFact:
    approval_type: str
    status: str
    approver_id: str
    approver_role: str
    approved_at: datetime | None


@dataclass(frozen=True)
class ContractFact:
    contract_id: str
    supplier_id: str
    category_id: str
    status: str
    effective_date: date
    expiration_date: date
    termination_date: date | None


@dataclass(frozen=True)
class PurchaseOrderFacts:
    po_number: str
    supplier_id: str
    category_id: str
    category_name: str
    contract_required: bool
    order_date: date
    status: str
    total_amount_usd: Decimal
    contract_reference: str
    contract_id: str | None
    approval_evidence_status: str
    contract_evidence_status: str
    contract: ContractFact | None
    approvals: tuple[ApprovalFact, ...]


@dataclass(frozen=True)
class RuleResult:
    rule_code: str
    rule_type: str
    applicable: bool
    status: ComplianceStatus | None
    reason_codes: tuple[str, ...]
    observed_facts: dict[str, Any]
    required_facts: dict[str, Any]
    provenance: PolicyProvenance

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class ComplianceResult:
    po_number: str
    policy_target_date: date
    overall_status: ComplianceStatus
    applicable_rule_count: int
    rule_results: tuple[RuleResult, ...]
    skipped_rules: tuple[RuleResult, ...]
    evidence_summary: dict[str, str]
    scope_note: str | None = None
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))
