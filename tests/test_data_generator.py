from decimal import Decimal
from pathlib import Path

from procurement_agent.data.generator import DEFAULT_SEED, build_dataset, ground_truth, outlier_summary, write_dataset
from procurement_agent.data.validation import validate_dataset


def test_generation_is_seed_reproducible():
    assert ground_truth(build_dataset(DEFAULT_SEED), DEFAULT_SEED) == ground_truth(build_dataset(DEFAULT_SEED), DEFAULT_SEED)


def test_purchase_order_totals_equal_line_amounts():
    validate_dataset(build_dataset(DEFAULT_SEED), DEFAULT_SEED)


def test_sup_042_h1_growth_ground_truth():
    growth = ground_truth(build_dataset(DEFAULT_SEED), DEFAULT_SEED)["sup_042_growth"]
    assert growth["h1_2025_spend_usd"] == "120000.00"
    assert growth["h1_2026_spend_usd"] == "390000.00"
    assert growth["absolute_increase_usd"] == "270000.00"
    assert growth["growth_pct"] == "225.00"


def test_canonical_compliance_controls_preserve_fail_pass_review():
    compliance = ground_truth(build_dataset(DEFAULT_SEED), DEFAULT_SEED)["canonical_compliance"]
    assert compliance["PO-2026-1842"] == {"approval": "FAIL", "contract": "PASS", "overall": "FAIL"}
    assert compliance["PO-2026-1846"]["overall"] == "PASS"
    assert compliance["PO-2026-1847"]["overall"] == "REVIEW"


def test_single_source_pattern_and_counterexamples():
    cases = ground_truth(build_dataset(DEFAULT_SEED), DEFAULT_SEED)["single_source"]
    assert Decimal(cases["positive"]["spend_share"]) >= Decimal("0.80")
    assert cases["positive"]["qualified_supplier_count"] == 1
    assert cases["multiple_qualified_counterexample"]["qualified_supplier_count"] > 1


def test_price_outlier_and_insufficient_peer_groups():
    result = outlier_summary(build_dataset(DEFAULT_SEED))
    assert "PO-2025-1910-L01" in result["outlier_item_ids"]
    assert "PO-2025-2009-L01" in result["outlier_item_ids"]
    assert any(group["item_code"] == "PRICE-OFF-001" and group["unit_of_measure"] == "BOX" for group in result["insufficient_groups"])
    assert any(group["item_code"] == "PRICE-PRD-001" for group in result["insufficient_groups"])


def test_written_files_are_byte_reproducible(tmp_path: Path):
    first, second = tmp_path / "first", tmp_path / "second"
    write_dataset(first, DEFAULT_SEED)
    write_dataset(second, DEFAULT_SEED)
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {path.name: path.read_bytes() for path in second.iterdir()}
