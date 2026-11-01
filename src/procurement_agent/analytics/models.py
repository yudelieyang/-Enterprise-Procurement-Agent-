from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any


def json_value(value: Any) -> Any:
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


class JsonResult:
    def to_dict(self) -> dict[str, Any]:
        return json_value(asdict(self))


@dataclass(frozen=True)
class CategoryContribution(JsonResult):
    category_id: str
    category_name: str
    comparison_spend: Decimal
    current_spend: Decimal
    absolute_change: Decimal
    share_of_total_change: Decimal | None


@dataclass(frozen=True)
class LargestPurchaseOrder(JsonResult):
    po_number: str
    amount_usd: Decimal
    category_id: str
    category_name: str


@dataclass(frozen=True)
class SpendGrowthResult(JsonResult):
    supplier_id: str
    comparison_period_start: date
    comparison_period_end: date
    current_period_start: date
    current_period_end: date
    comparison_spend: Decimal
    current_spend: Decimal
    absolute_change: Decimal
    percentage_change: Decimal | None
    growth_basis: str
    comparison_po_count: int
    current_po_count: int
    comparison_average_po_amount: Decimal | None
    current_average_po_amount: Decimal | None
    po_count_change: int
    average_po_amount_change: Decimal | None
    category_contributions: tuple[CategoryContribution, ...]
    largest_current_period_pos: tuple[LargestPurchaseOrder, ...]


@dataclass(frozen=True)
class PriceObservation(JsonResult):
    purchase_order_item_id: str
    po_number: str
    supplier_id: str
    item_code: str
    unit_of_measure: str
    unit_price_usd: Decimal


@dataclass(frozen=True)
class PriceOutlier(JsonResult):
    purchase_order_item_id: str
    po_number: str
    supplier_id: str
    unit_price_usd: Decimal
    robust_z_score: Decimal


@dataclass(frozen=True)
class PriceGroupResult(JsonResult):
    item_code: str
    unit_of_measure: str
    peer_group_size: int
    median_price: Decimal | None
    mad: Decimal | None
    analysis_status: str
    outliers: tuple[PriceOutlier, ...]


@dataclass(frozen=True)
class SupplierSpend(JsonResult):
    supplier_id: str
    spend_usd: Decimal
    spend_share: Decimal
    rank: int


@dataclass(frozen=True)
class SupplierConcentrationResult(JsonResult):
    category_id: str
    category_name: str
    is_critical: bool
    period_start: date
    period_end: date
    total_category_spend: Decimal
    supplier_spend: tuple[SupplierSpend, ...]
    qualified_supplier_count: int


@dataclass(frozen=True)
class SingleSourceRiskResult(JsonResult):
    concentration: SupplierConcentrationResult
    top_supplier_id: str | None
    top_supplier_share: Decimal
    risk_finding: bool
    mitigation_review_required: bool
