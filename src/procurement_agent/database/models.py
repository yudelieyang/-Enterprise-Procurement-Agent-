from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BusinessUnit(Base):
    __tablename__ = "business_units"

    business_unit_id: Mapped[str] = mapped_column(String, primary_key=True)
    business_unit_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)


class Category(Base):
    __tablename__ = "categories"

    category_id: Mapped[str] = mapped_column(String, primary_key=True)
    category_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    procurement_class: Mapped[str] = mapped_column(String, nullable=False)
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    contract_required: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (CheckConstraint("procurement_class IN ('DIRECT', 'INDIRECT')"),)


class Supplier(Base):
    __tablename__ = "suppliers"

    supplier_id: Mapped[str] = mapped_column(String, primary_key=True)
    supplier_code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    po_number: Mapped[str] = mapped_column(String, primary_key=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"), nullable=False)
    business_unit_id: Mapped[str] = mapped_column(ForeignKey("business_units.business_unit_id"), nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.category_id"), nullable=False)
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    total_amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    contract_reference: Mapped[str] = mapped_column(String, nullable=False, default="")
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.contract_id"), nullable=True)
    approval_evidence_status: Mapped[str] = mapped_column(String, nullable=False)
    contract_evidence_status: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('ISSUED', 'CLOSED', 'CANCELLED')"),
        CheckConstraint("currency = 'USD'"),
        CheckConstraint("total_amount_usd >= 0"),
        CheckConstraint("approval_evidence_status IN ('COMPLETE', 'UNAVAILABLE')"),
        CheckConstraint("contract_evidence_status IN ('COMPLETE', 'UNAVAILABLE')"),
    )


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    purchase_order_item_id: Mapped[str] = mapped_column(String, primary_key=True)
    po_number: Mapped[str] = mapped_column(ForeignKey("purchase_orders.po_number"), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    item_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String, nullable=False)
    unit_price_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_amount_usd: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    __table_args__ = (
        CheckConstraint("quantity > 0"),
        CheckConstraint("unit_price_usd >= 0"),
        CheckConstraint("line_amount_usd >= 0"),
        UniqueConstraint("po_number", "line_number"),
    )


class Contract(Base):
    __tablename__ = "contracts"

    contract_id: Mapped[str] = mapped_column(String, primary_key=True)
    contract_number: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"), nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.category_id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('EXECUTED', 'TERMINATED')"),
        CheckConstraint("expiration_date >= effective_date"),
    )


class Approval(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String, primary_key=True)
    po_number: Mapped[str] = mapped_column(ForeignKey("purchase_orders.po_number"), nullable=False)
    approval_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    approver_id: Mapped[str] = mapped_column(String, nullable=False)
    approver_role: Mapped[str] = mapped_column(String, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("approval_type IN ('PURCHASE', 'CONTRACT_EXCEPTION')"),
        CheckConstraint("status IN ('APPROVED', 'REJECTED', 'WITHDRAWN', 'PENDING')"),
        UniqueConstraint("po_number", "approval_type", "approver_id"),
    )


class SupplierCategoryEligibility(Base):
    __tablename__ = "supplier_category_eligibility"

    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.supplier_id"), primary_key=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.category_id"), primary_key=True)
    qualification_status: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (CheckConstraint("qualification_status IN ('QUALIFIED', 'NOT_QUALIFIED', 'SUSPENDED')"),)
