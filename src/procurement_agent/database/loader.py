from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from procurement_agent.data.validation import load_generated_dataset, validate_dataset

from .connection import sqlite_engine
from .models import Approval, Base, BusinessUnit, Category, Contract, PurchaseOrder, PurchaseOrderItem, Supplier, SupplierCategoryEligibility


MODEL_TABLES = {
    "business_units": BusinessUnit,
    "categories": Category,
    "suppliers": Supplier,
    "purchase_orders": PurchaseOrder,
    "purchase_order_items": PurchaseOrderItem,
    "contracts": Contract,
    "approvals": Approval,
    "supplier_category_eligibility": SupplierCategoryEligibility,
}


def build_database(database_path: Path, source_dir: Path) -> dict[str, int]:
    data, manifest = load_generated_dataset(source_dir)
    validate_dataset(data, int(manifest["seed"]))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()
    engine = sqlite_engine(database_path)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(BusinessUnit(**row) for row in data["business_units"])
        session.add_all(Category(**{**row, "is_critical": row["is_critical"] == "true", "contract_required": row["contract_required"] == "true"}) for row in data["categories"])
        session.add_all(Supplier(**row) for row in data["suppliers"])
        session.flush()
        session.add_all(Contract(**{**row, "effective_date": date.fromisoformat(row["effective_date"]), "expiration_date": date.fromisoformat(row["expiration_date"]), "termination_date": date.fromisoformat(row["termination_date"]) if row["termination_date"] else None}) for row in data["contracts"])
        session.flush()
        session.add_all(PurchaseOrder(**{**row, "order_date": date.fromisoformat(row["order_date"]), "total_amount_usd": Decimal(row["total_amount_usd"]), "contract_id": row["contract_id"] or None}) for row in data["purchase_orders"])
        session.flush()
        session.add_all(PurchaseOrderItem(**{**row, "line_number": int(row["line_number"]), "quantity": Decimal(row["quantity"]), "unit_price_usd": Decimal(row["unit_price_usd"]), "line_amount_usd": Decimal(row["line_amount_usd"])}) for row in data["purchase_order_items"])
        session.add_all(Approval(**{**row, "approved_at": datetime.fromisoformat(row["approved_at"]) if row["approved_at"] else None}) for row in data["approvals"])
        session.add_all(SupplierCategoryEligibility(**row) for row in data["supplier_category_eligibility"])
        session.commit()
        counts = {table: session.scalar(select(func.count()).select_from(model)) for table, model in MODEL_TABLES.items()}
    engine.dispose()
    if counts != manifest["row_counts"]:
        raise AssertionError(f"Database row counts differ from source manifest: {counts}")
    return counts
