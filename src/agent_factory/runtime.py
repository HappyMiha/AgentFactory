from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from pathlib import Path
import threading
from typing import Any

from .config import WORKSPACE, config_path_for_workspace, load_yaml
from .models import Agent, ExecutionApproval, ProviderResult, WorkItem
from .providers import CLIProvider, DeterministicProvider, Provider
from .token_failover import result_exhausted_quota


class ExecutionMode(StrEnum):
    SIMULATION = "simulation"
    LIVE = "live"


class AgentRuntime:
    def __init__(
        self,
        providers: dict[str, Provider] | None = None,
        *,
        workspace: Path | None = None,
    ):
        self.workspace = (workspace or WORKSPACE).resolve()
        self.providers = providers or self._from_config()
        self._token_exhausted_providers: set[str] = set()

    def _from_config(self) -> dict[str, Provider]:
        result: dict[str, Provider] = {"deterministic": DeterministicProvider()}
        policy: dict[str, Any] = load_yaml(
            config_path_for_workspace("policy", self.workspace)
        )
        prompt_policy = policy.get("prompt", {})
        execution_policy = policy.get("execution", {})
        provider_document = load_yaml(
            config_path_for_workspace("providers", self.workspace)
        )
        for cfg in provider_document.get("providers", []):
            if not cfg.get("enabled", True):
                continue
            if cfg.get("type") not in {"cli", "health_only_cli"}:
                continue
            health_only = cfg.get("type") == "health_only_cli"
            result[cfg["id"]] = CLIProvider(
                cfg["id"],
                cfg["executable"],
                cfg.get("args", []),
                executable_candidates=cfg.get("executable_candidates"),
                version_args=cfg.get("version_args"),
                prompt_transport=cfg.get("prompt_transport", "stdin"),
                prompt_file_args=cfg.get("prompt_file_args"),
                allow_execution=cfg.get("allow_execution", False) and not health_only,
                max_timeout=cfg.get("max_timeout", execution_policy.get("max_timeout", 180)),
                max_output_chars=cfg.get(
                    "max_output_chars", execution_policy.get("max_output_chars", 100_000)
                ),
                max_prompt_chars=cfg.get(
                    "max_prompt_chars", prompt_policy.get("max_chars", 50_000)
                ),
                allowed_roles=cfg.get("allowed_roles", []),
                allowed_sensitive_env=cfg.get("allowed_sensitive_env", []),
                protected_paths=cfg.get(
                    "protected_paths", prompt_policy.get("protected_paths", [])
                ),
                safety_rules=[
                    *prompt_policy.get("rules", []),
                    *cfg.get("safety_rules", []),
                ],
                workspace=self.workspace,
            )
        return result

    def health(self) -> list[dict]:
        return [provider.health() for provider in self.providers.values()]

    def run(
        self,
        agent: Agent,
        item: WorkItem,
        context: dict[str, Any],
        approval: ExecutionApproval | None = None,
        *,
        allow_fallback: bool = True,
        mode: ExecutionMode | str | None = None,
        cancel_event: threading.Event | None = None,
        token_exhaustion_fallback_agents: tuple[Agent, ...] = (),
    ) -> ProviderResult:
        if mode is not None:
            selected = ExecutionMode(mode)
            allow_fallback = selected is ExecutionMode.SIMULATION
        candidates = tuple(
            dict.fromkeys(
                (agent.id, *(item.id for item in token_exhaustion_fallback_agents))
            )
        )
        by_id = {item.id: item for item in (agent, *token_exhaustion_fallback_agents)}
        errors: list[str] = []
        attempted_agents: list[str] = []
        exhausted: list[dict[str, str]] = []
        simulation_agent = agent
        terminal_error = ""
        terminal_token_exhausted = False
        for agent_id in candidates:
            candidate = by_id[agent_id]
            name = candidate.provider
            if name.casefold() in self._token_exhausted_providers:
                terminal_error = f"{name}: token quota already exhausted"
                terminal_token_exhausted = True
                errors.append(terminal_error)
                continue
            simulation_agent = candidate
            provider = self.providers.get(name)
            if not provider:
                terminal_error = f"{name}: not configured"
                terminal_token_exhausted = False
                errors.append(terminal_error)
                break
            if not candidate.enabled:
                terminal_error = f"{name}: agent {candidate.id} is disabled"
                terminal_token_exhausted = False
                errors.append(terminal_error)
                break
            scoped_approval = (
                approval
                if approval is not None
                and approval.provider == name
                and approval.agent_id == candidate.id
                else None
            )
            candidate_item = replace(item, permissions=list(candidate.permissions))
            attempted_agents.append(candidate.id)
            if cancel_event is not None and isinstance(provider, CLIProvider):
                result = provider.execute(
                    candidate,
                    candidate_item,
                    context,
                    scoped_approval,
                    cancel_event=cancel_event,
                )
            else:
                result = provider.execute(candidate, candidate_item, context, scoped_approval)
            if result.ok:
                result.metadata.update(
                    {
                        "fallback_errors": errors,
                        "attempted_agents": attempted_agents,
                        "selected_agent_id": candidate.id,
                        "token_exhausted_providers": exhausted,
                    }
                )
                return result
            terminal_error = result.error or f"{name} provider failed"
            terminal_token_exhausted = result_exhausted_quota(result)
            errors.append(f"{name}: {terminal_error}")
            if not terminal_token_exhausted:
                break
            self._token_exhausted_providers.add(name.casefold())
            exhausted.append({"provider": name, "agent_id": candidate.id})

        if allow_fallback:
            provider = self.providers.get("deterministic")
            if provider:
                simulation_item = replace(
                    item, permissions=list(simulation_agent.permissions)
                )
                result = provider.execute(
                    simulation_agent, simulation_item, context, None
                )
                if result.ok:
                    result.metadata.update(
                        {
                            "fallback_errors": errors,
                            "attempted_agents": attempted_agents,
                            "selected_agent_id": simulation_agent.id,
                            "token_exhausted_providers": exhausted,
                        }
                    )
                    return result
                errors.append(f"deterministic: {result.error}")
        return ProviderResult(
            False,
            provider="none",
            error=terminal_error or "; ".join(errors),
            metadata={
                "fallback_errors": errors,
                "attempted_agents": attempted_agents,
                "token_exhausted_providers": exhausted,
                "failure_class": "TOKEN_EXHAUSTED" if terminal_token_exhausted else "",
            },
        )
