"""LangGraph orchestration of the newsroom.

Each agent is a graph node over :class:`GraphState`. Two conditional edges carry
the control flow that used to be a Python loop:

* ``editor -> writer`` while drafts need revision (bounded by ``MAX_REVISIONS``),
  otherwise ``editor -> publisher``;
* ``finalize -> human_review`` when drafts await approval (``AUTO_PUBLISH=false``).

``human_review`` calls :func:`langgraph.types.interrupt`, so a run *pauses* there with
its state checkpointed to SQLite (one thread per run, ``thread_id = run_id``). The
admin page or ``python -m touchline_takes.review`` resumes it with decisions such as
``{"<draft id>": {"action": "approve"}}``. The node loops until nothing is pending.

Print the graph as Mermaid with ``python -m touchline_takes.graph``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt

from touchline_takes.state import NewsroomState

if TYPE_CHECKING:  # pragma: no cover
    from touchline_takes.pipeline import Newsroom

# Our own state classes are the only custom types allowed in checkpoints.
STATE_TYPES = [("touchline_takes.state", name)
               for name in ("NewsroomState", "Story", "Draft", "Evidence", "LogEntry")]
AGENT_NODES = ("ingest", "classifier", "photo_tagger", "research", "analyst", "writer",
               "factcheck", "editor", "publisher")


class GraphState(TypedDict):
    """LangGraph state: the newsroom state object plus the revision-round counter."""

    newsroom: NewsroomState
    rounds: int


def serializer() -> JsonPlusSerializer:
    """Checkpoint serializer that only reconstructs our state classes."""
    return JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)


def make_checkpointer(path: str | None):
    """SQLite checkpointer at ``path`` (``None`` keeps checkpoints in memory)."""
    if not path:
        return InMemorySaver(serde=serializer())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False), serde=serializer())


def _agent_node(room: "Newsroom", name: str,
                func: Callable[[NewsroomState], NewsroomState]) -> Callable[[GraphState], dict]:
    """Wrap an agent's ``run`` as a node (timed and failure-isolated by the newsroom)."""
    def node(state: GraphState) -> dict:
        update: dict[str, Any] = {"newsroom": room.step(name, func, state["newsroom"])}
        if name == "writer":
            update["rounds"] = state.get("rounds", 0) + 1
        return update
    node.__name__ = name
    return node


def build_graph(room: "Newsroom") -> StateGraph:
    """The newsroom as an (uncompiled) LangGraph ``StateGraph``."""
    funcs = {"ingest": room.ingest.run, "classifier": room.classifier.run,
             "photo_tagger": room.photo_tagger.run,
             "research": room.index_research, "analyst": room.analyst.run,
             "writer": room.writer.run, "factcheck": room.factcheck.run,
             "editor": room.editor.run, "publisher": room.publisher.run}
    graph = StateGraph(GraphState)
    for name in AGENT_NODES:
        graph.add_node(name, _agent_node(room, name, funcs[name]))

    def finalize(state: GraphState) -> dict:
        return {"newsroom": room.finalize(state["newsroom"], state.get("rounds", 0))}

    def human_review(state: GraphState) -> dict:
        newsroom = state["newsroom"]
        pending = room.pending_in_run(newsroom)
        decisions = interrupt({
            "run_id": newsroom.run_id,
            "pending": [{"id": d.id, "title": d.title, "type": d.article_type}
                        for d in pending]})
        room.apply_decisions(newsroom, decisions or {})
        return {"newsroom": newsroom}

    def after_editor(state: GraphState) -> str:
        newsroom = state["newsroom"]
        if newsroom.drafts_with_status("needs_revision") and \
                state.get("rounds", 0) <= room.settings.max_revisions:
            return "writer"
        return "publisher"

    def needs_review(state: GraphState) -> str:
        return "human_review" if room.pending_in_run(state["newsroom"]) else END

    graph.add_node("finalize", finalize)
    graph.add_node("human_review", human_review)
    graph.add_edge(START, "ingest")
    for current, nxt in zip(AGENT_NODES[:-2], AGENT_NODES[1:-1]):
        graph.add_edge(current, nxt)
    graph.add_conditional_edges("editor", after_editor, ["writer", "publisher"])
    graph.add_edge("publisher", "finalize")
    graph.add_conditional_edges("finalize", needs_review, ["human_review", END])
    graph.add_conditional_edges("human_review", needs_review, ["human_review", END])
    return graph


def compile_graph(room: "Newsroom", checkpointer=None) -> CompiledStateGraph:
    """Compile with a checkpointer (persistence + interrupts)."""
    return build_graph(room).compile(checkpointer=checkpointer or InMemorySaver(
        serde=serializer()))


def thread_config(run_id: str) -> dict:
    """LangGraph config for a run's thread."""
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 60}


def paused_for_review(app: CompiledStateGraph, run_id: str) -> bool:
    """True if this run's thread is waiting at ``human_review``."""
    snapshot = app.get_state(thread_config(run_id))
    return "human_review" in (snapshot.next or ()) and bool(snapshot.interrupts)


def resume(app: CompiledStateGraph, run_id: str, decisions: dict[str, dict]) -> NewsroomState:
    """Resume a paused run with human decisions."""
    result = app.invoke(Command(resume=decisions), thread_config(run_id))
    return result["newsroom"]


def mermaid() -> str:
    """Mermaid diagram of the graph (no network or API keys needed)."""
    from touchline_takes.config import Settings  # pylint: disable=import-outside-toplevel
    from touchline_takes.pipeline import Newsroom  # pylint: disable=import-outside-toplevel
    from touchline_takes.db import Database  # pylint: disable=import-outside-toplevel

    settings = Settings(offline=True, vector_store="memory", checkpoint_path="")
    room = Newsroom.build(settings, db=Database(":memory:"))
    return room.app.get_graph().draw_mermaid()


if __name__ == "__main__":
    print(mermaid())
