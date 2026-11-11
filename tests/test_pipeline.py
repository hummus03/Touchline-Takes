"""End-to-end pipeline tests (offline, fake LLM)."""
# pylint: disable=redefined-outer-name

from pathlib import Path

from touchline_takes.pipeline import Newsroom, results_label
from touchline_takes.run import main
from touchline_takes.tools.llm import ScriptedWriterLLM


def test_run_once_offline_template(settings):
    """A full offline run ingests, classifies, predicts, writes and queues drafts."""
    newsroom = Newsroom.build(settings)
    state = newsroom.run_once()
    metrics = state.metrics
    assert "errors" not in metrics, metrics
    assert metrics["ingest"]["fallback"] and metrics["ingest"]["duplicates"] == 1
    assert metrics["analyst"]["predicted"] > 0
    assert metrics["drafts"]["pending_review"] > 0  # human approval is the default
    assert metrics["llm"] == {"provider": "offline", "calls": 0}
    assert newsroom.db.recent_runs()[0]["run_id"] == state.run_id
    assert {e.agent for e in state.logs} >= {"ingest", "classifier", "research", "analyst",
                                              "writer", "factcheck", "editor", "publisher"}
    # A second run picks up the stories that did not fit the first run's article budget.
    second = newsroom.run_once()
    assert second.metrics["ingest"]["new"] == 0
    assert second.metrics["writer"]["assignments"] > 0


def test_run_once_with_fake_llm_revision_loop(settings):
    """The scripted LLM hallucinates once; fact-check bounces it and the revision passes."""
    settings = settings.with_overrides(auto_publish=True, max_articles_per_run=12)
    llm = ScriptedWriterLLM(hallucinate_on=("Arsenal beat Chelsea",))
    newsroom = Newsroom.build(settings, llm=llm)
    state = newsroom.run_once()
    arsenal = next(d for d in state.drafts if d.title.startswith("Arsenal v Chelsea"))
    assert arsenal.revision == 1 and arsenal.status == "published"
    assert arsenal.rejection_history[0]["agent"] == "factcheck"
    assert "200 million" not in arsenal.body
    assert state.metrics["llm"]["calls"] >= len(state.drafts)
    assert state.published


def test_budget_cap_falls_back_to_templates(settings):
    """With a budget of one call, the rest of the drafts use templates."""
    settings = settings.with_overrides(llm_max_calls_per_run=1)
    state = Newsroom.build(settings, llm=ScriptedWriterLLM()).run_once()
    modes = [d.mode for d in state.drafts]
    assert modes.count("llm") <= 1 and "template" in modes
    assert state.metrics["llm"]["calls"] == 1


def test_results_label(tmp_path):
    """Synthetic sample data is labelled honestly."""
    (tmp_path / "sample_E0.csv").write_text("x")
    assert results_label(str(tmp_path)) == "synthetic sample results"
    (tmp_path / "E0_2425.csv").write_text("x")
    assert results_label(str(tmp_path)) == "Football-Data.co.uk results"


def test_cli_runs_once(settings, monkeypatch, capsys):
    """``python -m touchline_takes.run --offline`` works end to end."""
    for key, value in {"DATABASE_PATH": settings.database_path,
                       "CHROMA_DIR": settings.chroma_dir, "MODEL_PATH": settings.model_path,
                       "CHECKPOINT_PATH": settings.checkpoint_path,
                       "PHOTO_MODEL_DIR": settings.photo_model_dir,
                       "VECTOR_STORE": "memory", "LLM_PROVIDER": "offline"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("touchline_takes.config.PROJECT_ROOT", Path(settings.database_path).parent)
    assert main(["--offline", "--auto-publish", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert '"published"' in out and "Summary" in out


def test_llm_verifier_is_wired_from_settings(settings):
    """FACTCHECK_VERIFIER=llm attaches the verifier when an LLM is configured."""
    room = Newsroom.build(settings.with_overrides(factcheck_verifier="llm"),
                          llm=ScriptedWriterLLM())
    assert room.factcheck.verifier is not None
    assert Newsroom.build(settings).factcheck.verifier is None
