from procurement_agent.evaluation.policy_retrieval import evaluate_all_modes, write_evaluation_report
from procurement_agent.retrieval.policy_retrieval import DenseEncoder, PolicyRetriever, build_policy_chunks


if __name__ == "__main__":
    retriever = PolicyRetriever(build_policy_chunks(), DenseEncoder())
    report, failures = evaluate_all_modes(retriever)
    paths = write_evaluation_report(report, failures)
    print({"report": report, "outputs": [str(path) for path in paths]})
