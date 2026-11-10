"""The minimal agent interface shared by every newsroom agent."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from touchline_takes.state import NewsroomState


class Agent(ABC):
    """An agent is a named, side-effect-aware function over :class:`NewsroomState`.

    Moving to LangGraph later is mechanical: each ``agent.run`` becomes a node
    (``graph.add_node(agent.name, agent.run)``) and the revision loop becomes a
    conditional edge from the editor back to the writer.
    """

    name = "agent"

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"touchline_takes.{self.name}")

    @abstractmethod
    def run(self, state: NewsroomState) -> NewsroomState:
        """Process ``state`` and return it updated."""

    def __call__(self, state: NewsroomState) -> NewsroomState:
        return self.run(state)

    def log(self, state: NewsroomState, action: str, detail: str = "",
            story_id: str | None = None) -> None:
        """Log to both the run state and the Python logger."""
        state.log(self.name, action, detail, story_id)
        self.logger.info("%s %s %s", action, story_id or "-", detail)
