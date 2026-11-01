"""Fixed, auditable analytics functions; no arbitrary Python execution."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from statistics import median

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from procurement_agent.analytics.models import CategoryContribution, LargestPurchaseOrder, PriceGroupResult, PriceObservation, PriceOutlier, SingleSourceRiskResult, SpendGrowthResult, SupplierConcentrationResult, SupplierSpend
from procurement_agent.database.models import Category, PurchaseOrder, PurchaseOrderItem, Supplier, SupplierCategoryEligibility


ELIGIBLE_PO_STATUSES = ("ISSUED", "CLOSED")
MINIMUM_PRICE_PEER_GROUP = 8
ROBUST_Z_THRESHOLD = Decimal("3.5")
ROBUST_Z_CONSTANT = Decimal("0.6745")


def _period_rows(engine: Engine, supplier_id: str, start: date, end: date):
    with Session(engine) as session:
        return session.execute(
            select(PurchaseOrder, Category.category_id, Category.name)
            .join(Category, Category.category_id == PurchaseOrder.category_id)
            .where(PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.status.in_(ELIGIBLE_PO_STATUSES), PurchaseOrder.order_date.between(start, end))
            .order_by(PurchaseOrder.po_number)
        ).all()


def _sum_amount(rows) -> Decimal:
    return sum((Decimal(row[0].total_amount_usd) for row in rows), Decimal("0.00"))


def analyze_spend_growth(engine: Engine, supplier_id: str, comparison_period_start: date, comparison_period_end: date, current_period_start: date, current_period_end: date, top_n: int = 3) -> SpendGrowthResult:
    """Compare explicit windows and expose observable spend drivers without causal inference."""
    comparison = _period_rows(engine, supplier_id, comparison_period_start, comparison_period_end)
    current = _period_rows(engine, supplier_id, current_period_start, current_period_end)
    comparison_spend, current_spend = _sum_amount(comparison), _sum_amount(current)
    change = current_spend - comparison_spend
    if comparison_spend:
        percentage_change, growth_basis = (change / comparison_spend * Decimal("100")).quantize(Decimal("0.01")), "STANDARD"
    else:
        percentage_change = None
        growth_basis = "ZERO_BASE_CURRENT_SPEND" if current_spend else "ZERO_BASE_NO_SPEND"
    comparison_average = (comparison_spend / len(comparison)).quantize(Decimal("0.01")) if comparison else None
    current_average = (current_spend / len(current)).quantize(Decimal("0.01")) if current else None
    category_totals: dict[tuple[str, str], list[Decimal]] = defaultdict(lambda: [Decimal("0.00"), Decimal("0.00")])
    for rows, index in ((comparison, 0), (current, 1)):
        for po, category_id, category_name in rows:
            category_totals[(category_id, category_name)][index] += Decimal(po.total_amount_usd)
    contributions = tuple(
        CategoryContribution(category_id, category_name, totals[0], totals[1], totals[1] - totals[0], ((totals[1] - totals[0]) / change).quantize(Decimal("0.0001")) if change else None)
        for (category_id, category_name), totals in sorted(category_totals.items())
    )
    largest = tuple(
        LargestPurchaseOrder(po.po_number, Decimal(po.total_amount_usd), category_id, category_name)
        for po, category_id, category_name in sorted(current, key=lambda row: (-Decimal(row[0].total_amount_usd), row[0].po_number))[:top_n]
    )
    return SpendGrowthResult(supplier_id, comparison_period_start, comparison_period_end, current_period_start, current_period_end, comparison_spend, current_spend, change, percentage_change, growth_basis, len(comparison), len(current), comparison_average, current_average, len(current) - len(comparison), (current_average - comparison_average).quantize(Decimal("0.01")) if comparison_average is not None and current_average is not None else None, contributions, largest)


def analyze_price_observations(observations: list[PriceObservation]) -> tuple[PriceGroupResult, ...]:
    grouped: dict[tuple[str, str], list[PriceObservation]] = defaultdict(list)
    for observation in observations:
        grouped[(observation.item_code, observation.unit_of_measure)].append(observation)
    results: list[PriceGroupResult] = []
    for (item_code, uom), rows in sorted(grouped.items()):
        prices = [row.unit_price_usd for row in rows]
        if len(rows) < MINIMUM_PRICE_PEER_GROUP:
            results.append(PriceGroupResult(item_code, uom, len(rows), None, None, "INSUFFICIENT_PEER_GROUP", ()))
            continue
        center = median(prices)
        mad = median([abs(price - center) for price in prices])
        if mad == 0:
            results.append(PriceGroupResult(item_code, uom, len(rows), center, mad, "ZERO_VARIANCE", ()))
            continue
        outliers = tuple(
            PriceOutlier(row.purchase_order_item_id, row.po_number, row.supplier_id, row.unit_price_usd, (ROBUST_Z_CONSTANT * (row.unit_price_usd - center) / mad).quantize(Decimal("0.0001")))
            for row in rows
            if abs(ROBUST_Z_CONSTANT * (row.unit_price_usd - center) / mad) > ROBUST_Z_THRESHOLD
        )
        results.append(PriceGroupResult(item_code, uom, len(rows), center, mad, "ANALYZED", outliers))
    return tuple(results)


def analyze_price_outliers(engine: Engine, item_code: str | None = None) -> tuple[PriceGroupResult, ...]:
    with Session(engine) as session:
        statement = (
            select(PurchaseOrderItem, PurchaseOrder, Supplier)
            .join(PurchaseOrder, PurchaseOrder.po_number == PurchaseOrderItem.po_number)
            .join(Supplier, Supplier.supplier_id == PurchaseOrder.supplier_id)
            .where(PurchaseOrder.status.in_(ELIGIBLE_PO_STATUSES), PurchaseOrder.currency == "USD")
            .order_by(PurchaseOrderItem.item_code, PurchaseOrderItem.unit_of_measure, PurchaseOrderItem.purchase_order_item_id)
        )
        if item_code is not None:
            statement = statement.where(PurchaseOrderItem.item_code == item_code)
        rows = session.execute(statement).all()
    return analyze_price_observations([
        PriceObservation(item.purchase_order_item_id, po.po_number, supplier.supplier_id, item.item_code, item.unit_of_measure, Decimal(item.unit_price_usd))
        for item, po, supplier in rows
    ])


def analyze_supplier_concentration(engine: Engine, category_id: str, period_start: date, period_end: date) -> SupplierConcentrationResult:
    with Session(engine) as session:
        category = session.get(Category, category_id)
        if category is None:
            raise ValueError(f"Unknown category: {category_id}")
        rows = session.execute(
            select(PurchaseOrder.supplier_id, func.sum(PurchaseOrder.total_amount_usd))
            .where(PurchaseOrder.category_id == category_id, PurchaseOrder.status.in_(ELIGIBLE_PO_STATUSES), PurchaseOrder.order_date.between(period_start, period_end))
            .group_by(PurchaseOrder.supplier_id)
        ).all()
        qualified = session.scalar(select(func.count()).select_from(SupplierCategoryEligibility).where(SupplierCategoryEligibility.category_id == category_id, SupplierCategoryEligibility.qualification_status == "QUALIFIED")) or 0
    total = sum((Decimal(amount) for _, amount in rows), Decimal("0.00"))
    ordered = sorted(((supplier_id, Decimal(amount)) for supplier_id, amount in rows), key=lambda item: (-item[1], item[0]))
    suppliers = tuple(SupplierSpend(supplier_id, amount, (amount / total).quantize(Decimal("0.0001")) if total else Decimal("0.0000"), rank) for rank, (supplier_id, amount) in enumerate(ordered, start=1))
    return SupplierConcentrationResult(category.category_id, category.name, category.is_critical, period_start, period_end, total, suppliers, int(qualified))


def analyze_single_source_risk(engine: Engine, category_id: str, period_start: date, period_end: date) -> SingleSourceRiskResult:
    concentration = analyze_supplier_concentration(engine, category_id, period_start, period_end)
    top = concentration.supplier_spend[0] if concentration.supplier_spend else None
    risk = bool(top and concentration.is_critical and top.spend_share >= Decimal("0.80") and concentration.qualified_supplier_count <= 1)
    return SingleSourceRiskResult(concentration, top.supplier_id if top else None, top.spend_share if top else Decimal("0.0000"), risk, risk)
