from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


PROJECT_ROOT = Path(__file__).resolve().parents[3]
POLICY_DIR = PROJECT_ROOT / "data" / "policies"
SOURCE_DIR = POLICY_DIR / "source"
MANIFEST_PATH = POLICY_DIR / "policy_manifest.json"
RULES_PATH = POLICY_DIR / "policy_rules.json"
PAGE_BREAK = "<!-- PAGE BREAK -->"


class PolicyValidationError(ValueError):
    """Raised when a corpus asset cannot provide stable policy provenance."""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return load_json(path)


def document_applies_on(document: dict[str, Any], as_of: date) -> bool:
    effective = date.fromisoformat(document["effective_date"])
    expiration = document["expiration_date"]
    return as_of >= effective and (expiration is None or as_of <= date.fromisoformat(expiration))


def applicable_documents(manifest: dict[str, Any], document_type: str, as_of: date) -> list[dict[str, Any]]:
    return [
        document
        for document in manifest["documents"]
        if document["document_type"] == document_type and document_applies_on(document, as_of)
    ]


def _clean_markdown(text: str) -> str:
    text = text.replace("**", "")
    return re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text).strip()


def markdown_pages(source_path: Path) -> list[list[tuple[str, str]]]:
    raw_pages = source_path.read_text(encoding="utf-8").split(PAGE_BREAK)
    pages: list[list[tuple[str, str]]] = []
    for raw_page in raw_pages:
        blocks: list[tuple[str, str]] = []
        for line in raw_page.splitlines():
            line = line.strip()
            if not line or line.startswith("<!--"):
                continue
            if line.startswith("# "):
                blocks.append(("title", _clean_markdown(line[2:])))
            elif line.startswith("## "):
                blocks.append(("heading", _clean_markdown(line[3:])))
            elif line.startswith("- "):
                blocks.append(("bullet", _clean_markdown(line[2:])))
            else:
                blocks.append(("body", _clean_markdown(line)))
        pages.append(blocks)
    return pages


def _styles() -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("PolicyTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=19, leading=23, spaceAfter=18, textColor=colors.HexColor("#17365D")),
        "heading": ParagraphStyle("PolicyHeading", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, spaceBefore=8, spaceAfter=7, textColor=colors.HexColor("#17365D")),
        "body": ParagraphStyle("PolicyBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=10, leading=14, spaceAfter=8, textColor=colors.HexColor("#202020")),
        "bullet": ParagraphStyle("PolicyBullet", parent=styles["BodyText"], fontName="Helvetica", fontSize=10, leading=14, leftIndent=14, firstLineIndent=-9, spaceAfter=6, bulletIndent=4),
    }


def _flowables(pages: list[list[tuple[str, str]]]) -> list[Any]:
    styles = _styles()
    flowables: list[Any] = []
    for page_index, blocks in enumerate(pages):
        for kind, text in blocks:
            if kind == "bullet":
                flowables.append(Paragraph(text, styles[kind], bulletText="•"))
            else:
                flowables.append(Paragraph(text, styles[kind]))
            if kind == "title":
                flowables.append(Spacer(1, 0.10 * inch))
        if page_index < len(pages) - 1:
            flowables.append(PageBreak())
    return flowables


def _page_decorator(document: dict[str, Any]):
    def decorate(canvas: Any, doc: Any) -> None:
        width, height = LETTER
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#9FBAD0"))
        canvas.line(0.62 * inch, height - 0.53 * inch, width - 0.62 * inch, height - 0.53 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#4A6075"))
        canvas.drawString(0.62 * inch, height - 0.42 * inch, f"{document['title']} | Version {document['version']}")
        canvas.drawRightString(width - 0.62 * inch, height - 0.42 * inch, document["document_id"])
        canvas.line(0.62 * inch, 0.48 * inch, width - 0.62 * inch, 0.48 * inch)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(0.62 * inch, 0.34 * inch, "Synthetic policy corpus - Enterprise Procurement Intelligence Agent")
        canvas.drawRightString(width - 0.62 * inch, 0.34 * inch, f"Page {doc.page}")
        canvas.restoreState()

    return decorate


def generate_policy_pdfs(
    source_dir: Path = SOURCE_DIR,
    output_dir: Path = POLICY_DIR,
    manifest_path: Path = MANIFEST_PATH,
) -> list[Path]:
    """Render the checked Markdown policy sources to fixed-page PDFs."""
    manifest = load_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    for document in manifest["documents"]:
        pages = markdown_pages(source_dir / document["source_filename"])
        expected_page_count = max(section["expected_page"] for section in document["sections"])
        if len(pages) != expected_page_count:
            raise PolicyValidationError(f"{document['document_id']} source has {len(pages)} pages; expected {expected_page_count}.")
        pdf_path = output_dir / document["pdf_filename"]
        pdf = SimpleDocTemplate(
            str(pdf_path), pagesize=LETTER, leftMargin=0.62 * inch, rightMargin=0.62 * inch,
            topMargin=1.00 * inch, bottomMargin=0.68 * inch, title=document["title"], author="Enterprise Procurement Intelligence Agent",
        )
        pdf.build(_flowables(pages), onFirstPage=_page_decorator(document), onLaterPages=_page_decorator(document))
        if len(PdfReader(str(pdf_path)).pages) != expected_page_count:
            raise PolicyValidationError(f"{pdf_path.name} did not render to the expected {expected_page_count} pages.")
        created.append(pdf_path)
    return created


def _page_text(pdf_path: Path, page_number: int) -> str:
    reader = PdfReader(str(pdf_path))
    return reader.pages[page_number - 1].extract_text() or ""


def _normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _validate_intervals(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for document in manifest["documents"]:
        by_type.setdefault(document["document_type"], []).append(document)
        if document["expiration_date"] and document["effective_date"] > document["expiration_date"]:
            errors.append(f"{document['document_id']}: invalid effective interval")
    for document_type, documents in by_type.items():
        ordered = sorted(documents, key=lambda item: item["effective_date"])
        for current, following in zip(ordered, ordered[1:]):
            if current["expiration_date"] is None or current["expiration_date"] >= following["effective_date"]:
                errors.append(f"{document_type}: overlapping policy intervals")
    return errors


def validate_policy_corpus(
    policy_dir: Path = POLICY_DIR,
    manifest_path: Path = MANIFEST_PATH,
    rules_path: Path = RULES_PATH,
) -> list[str]:
    """Return deterministic validation errors for document, citation, temporal, and rule provenance checks."""
    manifest = load_manifest(manifest_path)
    errors = _validate_intervals(manifest)
    documents = {document["document_id"]: document for document in manifest["documents"]}
    required_doc_fields = {"document_id", "title", "document_type", "version", "effective_date", "expiration_date", "source_filename", "pdf_filename", "sections"}
    for document in manifest["documents"]:
        missing = required_doc_fields - set(document)
        if missing:
            errors.append(f"{document.get('document_id', 'unknown')}: missing fields {sorted(missing)}")
            continue
        pdf_path = policy_dir / document["pdf_filename"]
        source_path = manifest_path.parent / "source" / document["source_filename"]
        if not source_path.is_file():
            errors.append(f"{document['document_id']}: missing source Markdown")
        if not pdf_path.is_file():
            errors.append(f"{document['document_id']}: missing PDF")
            continue
        reader = PdfReader(str(pdf_path))
        expected_page_count = max(section["expected_page"] for section in document["sections"])
        if len(reader.pages) != expected_page_count:
            errors.append(f"{document['document_id']}: expected {expected_page_count} pages, found {len(reader.pages)}")
        extracted = [page.extract_text() or "" for page in reader.pages]
        if document["title"] not in extracted[0] or f"Version {document['version']}" not in extracted[0]:
            errors.append(f"{document['document_id']}: first page missing title or version")
        for section in document["sections"]:
            page_number = section["expected_page"]
            if page_number > len(extracted) or section["label"] not in extracted[page_number - 1] or section["title"] not in extracted[page_number - 1]:
                errors.append(f"{document['document_id']}: unstable citation location for {section['label']}")

    rules = load_json(rules_path).get("rules", [])
    required_rule_fields = {"rule_code", "rule_type", "human_readable_meaning", "applicability", "parameters", "source_document_id", "source_version", "source_section", "source_page", "canonical_source_phrase"}
    for rule in rules:
        missing = required_rule_fields - set(rule)
        if missing:
            errors.append(f"{rule.get('rule_code', 'unknown')}: missing fields {sorted(missing)}")
            continue
        document = documents.get(rule["source_document_id"])
        if document is None:
            errors.append(f"{rule['rule_code']}: source document does not exist")
            continue
        if document["version"] != rule["source_version"]:
            errors.append(f"{rule['rule_code']}: source version does not match document")
        matching_sections = [section for section in document["sections"] if section["label"] == rule["source_section"]]
        if not matching_sections or matching_sections[0]["expected_page"] != rule["source_page"]:
            errors.append(f"{rule['rule_code']}: source section/page does not match manifest")
            continue
        pdf_path = policy_dir / document["pdf_filename"]
        if pdf_path.is_file() and _normalized_text(rule["canonical_source_phrase"]) not in _normalized_text(_page_text(pdf_path, rule["source_page"])):
            errors.append(f"{rule['rule_code']}: canonical source phrase missing from cited PDF page")

    temporal_expectations = [("2025-06-30", "2025.1"), ("2026-06-30", "2026.1")]
    for document_type in {document["document_type"] for document in manifest["documents"]}:
        for raw_date, expected_version in temporal_expectations:
            applicable = applicable_documents(manifest, document_type, date.fromisoformat(raw_date))
            if applicable and {document["version"] for document in applicable} != {expected_version}:
                errors.append(f"{document_type}: incorrect version for {raw_date}")
        if applicable_documents(manifest, document_type, date(2024, 6, 30)):
            errors.append(f"{document_type}: unexpectedly covers 2024")
    return errors
