from procurement_agent.policy.corpus import PolicyValidationError, validate_policy_corpus


if __name__ == "__main__":
    errors = validate_policy_corpus()
    if errors:
        raise PolicyValidationError("\n".join(errors))
    print("Policy corpus validation passed.")
