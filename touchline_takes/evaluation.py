"""Offline evaluation of the whole newsroom against fixture stories with known expectations.

Run with ``python scripts/evaluate.py`` (or ``python -m touchline_takes.evaluation``).
It reports, per writer configuration:

* share of claims with a source (first drafts, and in published articles),
* Editor and Fact-checker rejection rates and retry counts,
* expectation checks (which fixture stories should publish or be spiked),
* cost and latency per article,

plus classifier accuracy against labelled expectations and the Analyst's
match-outcome metrics versus baselines. No network or API keys are used:
the "LLM" configuration uses the scripted fake writer, which hallucinates on
purpose for flagged stories so the fact-check -> revise loop is exercised.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from statistics import mean
from typing import Any
from xml.sax.saxutils import escape

from touchline_takes.agents.factcheck import check_draft
from touchline_takes.config import DATA_DIR, PROJECT_ROOT, Settings
from touchline_takes.pipeline import Newsroom
from touchline_takes.state import Draft
from touchline_takes.tools.llm import DEFAULT_MODELS, LLMClient, ScriptedWriterLLM, estimate_cost

FIXTURE_PATH = DATA_DIR / "eval" / "fixture_stories.json"
REPORT_DIR = PROJECT_ROOT / "reports"


def load_fixtures(path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    """Fixture stories with expectations."""
    return json.loads(path.read_text(encoding="utf-8"))["stories"]


def write_feed(stories: list[dict[str, Any]], directory: Path) -> None:
    """Write fixture stories as an RSS file so they flow through the real Ingest agent."""
    items = "".join(
        f"<item><title>{escape(s['title'])}</title><link>{escape(s['url'])}</link>"
        f"<description>{escape(s['summary'])}</description><guid>{escape(s['url'])}</guid>"
        "</item>" for s in stories)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "eval.xml").write_text(
        f"<?xml version=\"1.0\"?><rss version=\"2.0\"><channel><title>Eval Wire</title>"
        f"{items}</channel></rss>", encoding="utf-8")


def classifier_scores(newsroom: Newsroom, stories: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-field accuracy of the classifier against the fixture labels."""
    by_url = {s.url: s for s in newsroom.db.all_stories()}
    fields = {"league": 0, "topic": 0, "sentiment": 0, "teams": 0}
    errors = []
    for fixture in stories:
        story = by_url[fixture["url"]]
        expected = fixture["expected"]
        got = {"league": story.league, "topic": story.topic, "sentiment": story.sentiment,
               "teams": story.teams}
        for key in fields:
            ok = (set(got[key]) == set(expected[key])) if key == "teams" else (
                got[key] == expected[key])
            fields[key] += ok
            if not ok:
                errors.append(f"{fixture['title'][:40]}: {key} expected {expected[key]!r}, "
                              f"got {got[key]!r}")
    n = len(stories)
    return {"n": n, "accuracy": {k: round(v / n, 3) for k, v in fields.items()},
            "errors": errors}


def draft_scores(drafts: list[Draft], duration: float) -> dict[str, Any]:
    """Sourcing, rejection, retry and cost/latency metrics over a run's drafts."""
    published = [d for d in drafts if d.status == "published"]
    checked = sum(d.metrics.get("claims_checked", 0) for d in drafts)
    unsupported = sum(d.metrics.get("claims_unsupported", 0) for d in drafts)
    pub_claims = [c for d in published for c in check_draft(d) if c.is_claim]
    editor_reviews = sum(d.metrics.get("editor_reviews", 0) for d in drafts)
    editor_rejections = sum(d.metrics.get("editor_rejections", 0) for d in drafts)
    fc_bounces = sum(1 for d in drafts for r in d.rejection_history if r["agent"] == "factcheck")
    revisions = [d.revision for d in drafts]
    count = max(len(drafts), 1)
    return {
        "drafts": len(drafts), "published": len(published),
        "rejected": sum(d.status == "rejected" for d in drafts),
        "claims_with_source_share_first_pass": round(1 - unsupported / checked, 3)
        if checked else None,
        "claims_with_source_share_published": round(
            sum(c.supported for c in pub_claims) / len(pub_claims), 3) if pub_claims else None,
        "unsupported_claims_caught": unsupported,
        "factcheck_bounces": fc_bounces,
        "editor_reviews": editor_reviews,
        "editor_rejection_rate": round(editor_rejections / editor_reviews, 3)
        if editor_reviews else None,
        "retries_total": sum(revisions), "retries_mean": round(sum(revisions) / count, 3),
        "retries_max": max(revisions, default=0),
        "llm_calls_per_article": round(sum(d.metrics.get("llm_calls", 0) for d in drafts)
                                       / count, 3),
        "cost_usd_per_article": round(sum(d.metrics.get("cost_usd", 0.0) for d in drafts)
                                      / count, 6),
        "projected_cost_usd_per_article_" + DEFAULT_MODELS["anthropic"].replace("-", "_"):
        round(sum(estimate_cost(DEFAULT_MODELS["anthropic"], d.metrics.get("tokens_in", 0),
                                d.metrics.get("tokens_out", 0)) for d in drafts) / count, 6),
        "tokens_per_article": round(sum(d.metrics.get("tokens_in", 0) + d.metrics.get(
            "tokens_out", 0) for d in drafts) / count, 1),
        "agent_latency_s_per_article": round(mean(d.metrics.get("latency_s", 0.0)
                                                  for d in drafts), 4) if drafts else None,
        "pipeline_s_per_article": round(duration / count, 4),
    }


def expectation_checks(drafts: list[Draft], newsroom: Newsroom,
                       stories: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare publish/reject outcomes with the fixture expectations."""
    by_url = {s.url: s.id for s in newsroom.db.all_stories()}
    outcome = {sid: d.status for d in drafts for sid in d.story_ids}
    results, passed = [], 0
    for fixture in stories:
        if "expect_outcome" not in fixture:
            continue
        got = outcome.get(by_url[fixture["url"]], "not drafted")
        ok = got == fixture["expect_outcome"]
        passed += ok
        results.append({"story": fixture["title"], "expected": fixture["expect_outcome"],
                        "got": got, "ok": ok})
    return {"passed": passed, "total": len(results), "results": results}


def run_config(name: str, llm: LLMClient | None, stories: list[dict[str, Any]],
               workdir: Path) -> dict[str, Any]:
    """Run the pipeline once in an isolated workspace."""
    base = workdir / name
    write_feed(stories, base / "feeds")
    settings = Settings(
        database_path=str(base / "eval.db"), sample_feed_dir=str(base / "feeds"), offline=True,
        vector_store="memory", model_path=str(base / "model.joblib"), auto_publish=True,
        max_articles_per_run=len(stories) + 2, llm_max_calls_per_run=100)
    newsroom = Newsroom.build(settings, llm=llm)
    start = time.perf_counter()
    state = newsroom.run_once()
    duration = time.perf_counter() - start
    return {
        "config": name, "newsroom": newsroom, "state": state,
        "scores": draft_scores(state.drafts, duration),
        "expectations": expectation_checks(state.drafts, newsroom, stories),
        "rejection_reasons": [{"draft": d.title, **r} for d in state.drafts
                              for r in d.rejection_history],
    }


def evaluate() -> dict[str, Any]:
    """Run every configuration and assemble the report."""
    stories = load_fixtures()
    flagged = tuple(s["title"] for s in stories if s.get("inject_hallucination"))
    with tempfile.TemporaryDirectory() as tmp:
        runs = [run_config("template_writer", None, stories, Path(tmp)),
                run_config("scripted_llm_writer", ScriptedWriterLLM(flagged), stories,
                           Path(tmp))]
        classifier = classifier_scores(runs[0]["newsroom"], stories)
        model = runs[0]["newsroom"].analyst.ensure_model().report
        for run in runs:
            run["newsroom"].db.close()
    model_summary = {
        "model": model["metrics"], "baselines": model["baselines"],
        "n_train": model["n_train"], "n_test": model["n_test"],
        "test_period": model["test_period"],
        "beats_baseline": model["metrics"]["accuracy"] > model["baselines"][
            "majority_class"]["accuracy"] and model["metrics"]["roc_auc_ovr"] > 0.5,
    }
    report = {
        "fixture_stories": len(stories), "classifier": classifier, "predictor": model_summary,
        "configs": {r["config"]: {"scores": r["scores"], "expectations": r["expectations"],
                                  "rejection_reasons": r["rejection_reasons"]} for r in runs},
    }
    report["guardrail_ok"] = all(
        r["scores"]["claims_with_source_share_published"] in (None, 1.0) for r in runs)
    return report


def to_markdown(report: dict[str, Any]) -> str:
    """Human-readable report."""
    lines = ["# Touchline Takes evaluation report", "",
             f"Fixture stories: {report['fixture_stories']} · guardrail (every published "
             f"claim sourced): **{'PASS' if report['guardrail_ok'] else 'FAIL'}**", "",
             "## Newsroom quality per writer configuration", "",
             "| Metric | " + " | ".join(report["configs"]) + " |",
             "|---|" + "---|" * len(report["configs"])]
    keys = next(iter(report["configs"].values()))["scores"].keys()
    for key in keys:
        lines.append(f"| {key} | " + " | ".join(
            str(c["scores"][key]) for c in report["configs"].values()) + " |")
    lines.append("| expectations passed | " + " | ".join(
        f"{c['expectations']['passed']}/{c['expectations']['total']}"
        for c in report["configs"].values()) + " |")
    for name, cfg in report["configs"].items():
        lines += ["", f"### Rejections logged: {name}", ""]
        if not cfg["rejection_reasons"]:
            lines.append("None.")
        for rej in cfg["rejection_reasons"]:
            reasons = "; ".join(rej["reasons"])
            lines.append(f"- **{rej['agent']}** (rev {rej['revision']}) on "
                         f"*{rej['draft']}*: {reasons[:220]}")
        failed = [r for r in cfg["expectations"]["results"] if not r["ok"]]
        if failed:
            lines += ["", "Expectation mismatches:"]
            lines += [f"- {r['story']}: expected {r['expected']}, got {r['got']}"
                      for r in failed]
    clf = report["classifier"]
    lines += ["", "## Classifier (lexicon) vs labelled fixtures", "",
              "| Field | Accuracy |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in clf["accuracy"].items()]
    if clf["errors"]:
        lines += ["", "Misses:"] + [f"- {e}" for e in clf["errors"]]
    pred = report["predictor"]
    lines += ["", "## Analyst match-outcome model vs baselines", "",
              f"Chronological split: {pred['n_train']} train / {pred['n_test']} test matches "
              f"(test period {pred['test_period'][0]} to {pred['test_period'][1]}).", "",
              "| Metric | Logistic regression | Majority class | Class prior |",
              "|---|---|---|---|"]
    for key in ("accuracy", "precision_macro", "recall_macro", "f1_macro", "roc_auc_ovr",
                "log_loss"):
        lines.append(f"| {key} | {pred['model'][key]} | "
                     f"{pred['baselines']['majority_class'][key]} | "
                     f"{pred['baselines']['class_prior'][key]} |")
    matrix = pred["model"]["confusion_matrix"]
    lines += ["", "Confusion matrix (rows = actual, cols = predicted, order H/D/A):", ""]
    lines += ["    " + "  ".join(f"{v:>4}" for v in row) for row in matrix["matrix"]]
    lines += ["", f"Beats baseline: **{'yes' if pred['beats_baseline'] else 'no'}**", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; non-zero exit if the guardrail or the model check fails."""
    parser = argparse.ArgumentParser(description="Evaluate the Touchline Takes newsroom.")
    parser.add_argument("--out", default=str(REPORT_DIR), help="report directory")
    args = parser.parse_args(argv)
    report = evaluate()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown = to_markdown(report)
    (out / "evaluation.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    return 0 if report["guardrail_ok"] and report["predictor"]["beats_baseline"] else 1


if __name__ == "__main__":
    sys.exit(main())
