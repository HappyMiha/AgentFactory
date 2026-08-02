from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from .config import WORKSPACE, config_path, load_yaml
from .models import Agent, ExecutionApproval, ProviderResult, WorkItem
from .providers import CLIProvider, DeterministicProvider, Provider


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

    def _from_config(self) -> dict[str, Provider]:
        result: dict[str, Provider] = {"deterministic": DeterministicProvider()}
        policy: dict[str, Any] = load_yaml(config_path("policy"))
        prompt_policy = policy.get("prompt", {})
        execution_policy = policy.get("execution", {})
        provider_document = load_yaml(config_path("providers"))
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
        context: dict[str, str],
        approval: ExecutionApproval | None = None,
        *,
        allow_fallback: bool = True,
        mode: ExecutionMode | str | None = None,
    ) -> ProviderResult:
        if mode is not None:
            selected = ExecutionMode(mode)
            allow_fallback = selected is ExecutionMode.SIMULATION
        order = [agent.provider]
        if allow_fallback:
            order.append("deterministic")
        errors: list[str] = []
        for name in dict.fromkeys(order):
            provider = self.providers.get(name)
            if not provider:
                errors.append(f"{name}: not configured")
                continue
            scoped_approval = approval if name == agent.provider else None
            result = provider.execute(agent, item, context, scoped_approval)
            if result.ok:
                result.metadata["fallback_errors"] = errors
                return result
            errors.append(f"{name}: {result.error}")
        return ProviderResult(False, provider="none", error="; ".join(errors))
