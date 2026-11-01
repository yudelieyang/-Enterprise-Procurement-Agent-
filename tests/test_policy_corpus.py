from datetime import date
from pathlib import Path

from pypdf import PdfReader

from procurement_agent.policy.corpus import applicable_documents, generate_policy_pdfs, load_manifest, validate_policy_corpus


PROJECT_ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = PROJECT_ROOT / "data" / "policies"


def test_policy_pdf_generation_is_semantically_reproducible(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest_path = POLICY_DIR / "policy_manifest.json"
    generate_policy_pdfs(POLICY_DIR / "source", first, manifest_path)
    generate_policy_pdfs(POLICY_DIR / "source", second, manifest_path)
    for document in load_manifest(manifest_path)["documents"]:
        first_text = [page.extract_text() for page in PdfReader(str(first / document["pdf_filename"])).pages]
        second_text = [page.extract_text() for page in PdfReader(str(second / document["pdf_filename"])).pages]
        assert first_text == second_text


def test_policy_manifest_pdf_content_and_provenance_validate(tmp_path: Path):
    output = tmp_path / "policies"
    generate_policy_pdfs(POLICY_DIR / "source", output, POLICY_DIR / "policy_manifest.json")
    assert validate_policy_corpus(output, POLICY_DIR / "policy_manifest.json", POLICY_DIR / "policy_rules.json") == []


def test_temporal_version_resolution_has_no_2024_coverage():
    manifest = load_manifest(POLICY_DIR / "policy_manifest.json")
    for document_type in {document["document_type"] for document in manifest["documents"]}:
        current = applicable_documents(manifest, document_type, date(2026, 6, 30))
        historical = applicable_documents(manifest, document_type, date(2025, 6, 30))
        assert {document["version"] for document in current} <= {"2026.1"}
        assert {document["version"] for document in historical} <= {"2025.1"}
        assert applicable_documents(manifest, document_type, date(2024, 6, 30)) == []


def test_current_rules_trace_to_complete_canonical_pdf_passages(tmp_path: Path):
    output = tmp_path / "policies"
    generate_policy_pdfs(POLICY_DIR / "source", output, POLICY_DIR / "policy_manifest.json")
    rules = __import__("json").loads((POLICY_DIR / "policy_rules.json").read_text(encoding="utf-8"))["rules"]
    assert {rule["rule_code"] for rule in rules} == {"APPROVAL_OVER_50000_2026", "CONTRACT_REQUIRED_CATEGORIES_2026"}
    assert validate_policy_corpus(output, POLICY_DIR / "policy_manifest.json", POLICY_DIR / "policy_rules.json") == []
