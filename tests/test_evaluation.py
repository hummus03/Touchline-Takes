"""The evaluation harness runs offline and enforces the guardrail."""

from touchline_takes.evaluation import evaluate, main, to_markdown


def test_evaluation_report(tmp_path):
    """All required metrics are present and the guardrail holds."""
    report = evaluate()
    assert report["guardrail_ok"] and report["predictor"]["beats_baseline"]
    llm = report["configs"]["scripted_llm_writer"]["scores"]
    assert llm["unsupported_claims_caught"] > 0 and llm["factcheck_bounces"] > 0
    assert llm["claims_with_source_share_published"] == 1.0
    assert llm["contradictions_caught"] > 0
    checks = report["claim_checks"]
    assert checks["relation_aware/heldout"]["recall"] > checks["token_only/heldout"]["recall"]
    assert checks["relation_aware/heldout"]["false_positive_rate"] == 0.0
    for key in ("editor_rejection_rate", "retries_total", "cost_usd_per_article",
                "agent_latency_s_per_article"):
        assert key in llm
    assert "Beats baseline" in to_markdown(report)
    assert main(["--out", str(tmp_path)]) == 0
    assert (tmp_path / "evaluation.md").exists()
