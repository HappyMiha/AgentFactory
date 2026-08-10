from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .config import config_path, load_yaml, save_yaml, writable_config_path
from .models import Agent


class AgentRegistry:
    def __init__(self, path: Path | None = None):
        self.path = path or config_path("agents")
        self._custom_path = path is not None

    def list(self, enabled_only: bool = False) -> list[Agent]:
        agents = [Agent(**item) for item in load_yaml(self.path)["agents"]]
        return [a for a in agents if a.enabled] if enabled_only else agents

    def get(self, agent_id: str) -> Agent:
        for agent in self.list():
            if agent.id == agent_id:
                return agent
        raise KeyError(f"Unknown agent: {agent_id}")

    def set_enabled(self, agent_id: str, enabled: bool) -> Agent:
        agent = self.get(agent_id)
        agent.enabled = enabled
        self.replace(agent)
        return agent

    def add(self, agent: Agent, replace: bool = False) -> None:
        agents = self.list()
        existing = next((i for i, item in enumerate(agents) if item.id == agent.id), None)
        if existing is not None and not replace:
            raise ValueError(f"Agent already exists: {agent.id}")
        if existing is None:
            agents.append(agent)
        else:
            agents[existing] = agent
        if not self._custom_path:
            self.path = writable_config_path("agents")
        save_yaml(self.path, {"agents": [asdict(a) for a in agents]})

    def replace(self, agent: Agent) -> None:
        self.add(agent, replace=True)

    def replace_provider(self, agent_id: str, provider: str, model: str = "") -> Agent:
        agent = self.get(agent_id)
        agent.provider = provider
        agent.model = model
        self.replace(agent)
        return agent
