from procurement_agent.policy.corpus import generate_policy_pdfs


if __name__ == "__main__":
    for path in generate_policy_pdfs():
        print(path)
