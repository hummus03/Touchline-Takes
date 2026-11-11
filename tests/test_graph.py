"""LangGraph orchestration: graph shape, checkpoints, human-in-the-loop resume, parity."""
# pylint: disable=redefined-outer-name

import logging

from touchline_takes import graph as newsroom_graph
from touchline_takes.pipeline import Newsroom
from touchline_takes.review import main as review_main
from touchline_takes.tools.llm import ScriptedWriterLLM


def statuses(state):
    """Draft id -> status."""
    return {d.id: d.status for d in state.drafts}


def test_graph_shape():
    """Every agent is a node; revision and review are conditional edges."""
    diagram = newsroom_graph.mermaid()
    for node in newsroom_graph.AGENT_NODES + ("finalize", "human_review"):
        assert node in diagram
    assert "editor -.-> writer" in diagram and "finalize -.-> human_review" in diagram


def test_run_pauses_at_human_review_and_resumes_elsewhere(settings, caplog):
    """A run pauses with its state checkpointed; another process can resume it."""
    room = Newsroom.build(settings)
    state = room.run_once()
    pending = [d.id for d in state.drafts if d.status == "pending_review"]
    assert pending and state.metrics["orchestrator"] == "langgraph"
    snapshot = room.app.get_state(newsroom_graph.thread_config(state.run_id))
    assert snapshot.next == ("human_review",)
    assert {p["id"] for p in snapshot.interrupts[0].value["pending"]} == set(pending)

    # A fresh Newsroom (e.g. the web process) shares only the DB and checkpoint files.
    with caplog.at_level(logging.WARNING):
        other = Newsroom.build(settings)
        approved = other.review(pending[0], "approve")
        rejected = other.review(pending[1], "reject", "not sharp enough")
    assert "unregistered type" not in caplog.text
    assert approved.status == "published" and rejected.status == "rejected_by_editor"
    assert other.db.list_articles()[0]["draft_id"] == pending[0]
    snapshot = other.app.get_state(newsroom_graph.thread_config(state.run_id))
    assert snapshot.next == ("human_review",)  # still waiting for the rest
    for draft_id in pending[2:]:
        other.review(draft_id, "approve")
    snapshot = other.app.get_state(newsroom_graph.thread_config(state.run_id))
    assert snapshot.next == ()  # thread finished
    actions = {(log["agent"], log["action"]) for log in other.db.recent_logs(200)}
    assert ("publisher", "published") in actions and ("human", "rejected") in actions
    assert other.review(pending[0], "approve") is None  # no longer pending


def test_auto_publish_does_not_pause(settings):
    """With AUTO_PUBLISH the graph runs straight to the end."""
    room = Newsroom.build(settings.with_overrides(auto_publish=True))
    state = room.run_once()
    assert state.published
    assert room.app.get_state(newsroom_graph.thread_config(state.run_id)).next == ()


def test_parity_with_sequential(settings, tmp_path):
    """LangGraph and the plain loop make the same editorial decisions."""
    graph_state = Newsroom.build(settings).run_once()
    seq_settings = settings.with_overrides(
        orchestrator="sequential", database_path=str(tmp_path / "seq.db"),
        checkpoint_path=str(tmp_path / "seq_ckpt.db"))
    seq_state = Newsroom.build(seq_settings).run_once()
    assert statuses(graph_state) == statuses(seq_state)
    assert graph_state.metrics["rounds"] == seq_state.metrics["rounds"]
    assert graph_state.metrics["drafts"] == seq_state.metrics["drafts"]


def test_revision_loop_is_a_conditional_edge(settings):
    """The editor/fact-check loop back to the writer runs inside the graph, bounded."""
    settings = settings.with_overrides(auto_publish=True, max_articles_per_run=12)
    room = Newsroom.build(settings, llm=ScriptedWriterLLM(hallucinate_on=("Arsenal beat",)))
    state = room.run_once()
    revised = [d for d in state.drafts if d.revision]
    assert revised and state.metrics["rounds"] >= 2
    assert state.metrics["rounds"] <= settings.max_revisions + 1
    assert all(d.status in {"published", "rejected"} for d in state.drafts)


def test_sequential_drafts_are_reviewed_directly(settings):
    """Drafts without a paused thread are still reviewable."""
    room = Newsroom.build(settings.with_overrides(orchestrator="sequential"))
    state = room.run_once()
    draft_id = next(d.id for d in state.drafts if d.status == "pending_review")
    assert room.review(draft_id, "approve").status == "published"
    assert room.review("missing", "approve") is None


def test_review_cli(settings, monkeypatch, capsys):
    """``python -m touchline_takes.review`` lists and approves pending drafts."""
    state = Newsroom.build(settings).run_once()
    draft_id = next(d.id for d in state.drafts if d.status == "pending_review")
    monkeypatch.setattr("touchline_takes.review.Settings.from_env", lambda: settings)
    assert review_main(["list"]) == 0
    assert draft_id in capsys.readouterr().out
    assert review_main(["approve", draft_id]) == 0
    assert "published" in capsys.readouterr().out
    assert review_main(["approve", draft_id]) == 1
