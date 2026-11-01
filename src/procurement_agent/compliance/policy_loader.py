"""Small, validated loader for the two accepted executable policy rules."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from procurement_agent.compliance.models import PolicyProvenance, PolicyRule
from procurement_agent.policy.corpus import MANIFEST_PATH, RULES_PATH, load_json, validate_policy_corpus


KNOWN_RULE_TYPES = {"approval_requirement", "contract_requirement"}


class PolicyRuleValidationError(ValueError):
    pass


def load_policy_rules(rules_path: Path = RULES_PATH, manifest_path: Path = MANIFEST_PATH) -> tuple[PolicyRule, ...]:
    errors = validate_policy_corpus(manifest_path=manifest_path, rules_path=rules_path)
    if errors:
        raise PolicyRuleValidationError("; ".join(errors))
    documents = {document["document_id"]: document for document in load_json(manifest_path)["documents"]}
    rules: list[PolicyRule] = []
    seen_codes: set[str] = set()
    for raw_rule in load_json(rules_path).get("rules", []):
        rule_code = raw_rule.get("rule_code")
        if not isinstance(rule_code, str) or rule_code in seen_codes:
            raise PolicyRuleValidationError("Policy rules need unique rule_code values")
        seen_codes.add(rule_code)
        rule_type = raw_rule.get("rule_type")
        if rule_type not in KNOWN_RULE_TYPES:
            raise PolicyRuleValidationError(f"{rule_code}: unknown rule type")
        parameters = raw_rule.get("parameters")
        if not isinstance(parameters, dict):
            raise PolicyRuleValidationError(f"{rule_code}: parameters must be an object")
        document = documents.get(raw_rule.get("source_document_id"))
        if document is None or document["version"] != raw_rule.get("source_version"):
            raise PolicyRuleValidationError(f"{rule_code}: source provenance is invalid")
        rules.append(PolicyRule(
            rule_code=rule_code,
            rule_type=rule_type,
            parameters=parameters,
            effective_date=date.fromisoformat(document["effective_date"]),
            expiration_date=date.fromisoformat(document["expiration_date"]) if document["expiration_date"] else None,
            provenance=PolicyProvenance(
                source_document_id=document["document_id"], title=document["title"], version=document["version"],
                section=raw_rule["source_section"], page=int(raw_rule["source_page"]),
            ),
        ))
    if {rule.rule_code for rule in rules} != {"APPROVAL_OVER_50000_2026", "CONTRACT_REQUIRED_CATEGORIES_2026"}:
        raise PolicyRuleValidationError("Executable rule set does not match the accepted MVP scope")
    return tuple(rules)
