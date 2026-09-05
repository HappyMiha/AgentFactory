"""Opt-in local Ollama role-contract smoke, not end-to-end mission acceptance."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agent_factory.models import Agent, ExecutionApproval, ProviderCapabilities, WorkItem
from agent_factory.providers import CLIProvider
from agent_factory.software_roles import AUTONOMOUS_PLANNING_ROLE_IDS


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Local qualification must not follow redirects")


def bind_local_cli_endpoint():
    """Reject ambient remote/custom daemons before any canary request."""
    host = os.environ.get("OLLAMA_HOST", "")
    if host not in {"", "127.0.0.1:11434", "http://127.0.0.1:11434"}:
        raise ValueError("Canary requires OLLAMA_HOST to be unset or exactly http://127.0.0.1:11434")
    # This standalone process must use the same daemon for CLI and API/digests.
    os.environ["OLLAMA_HOST"] = "http://127.0.0.1:11434"



def validate_cli_json(content, expected, diagnostics):
    """Keep malformed synthetic output a failure with bounded escaped evidence."""
    reason = None
    if len(content) > 1024:
        reason = "JSON content exceeds 1024 characters"
    else:
        try:
            if json.loads(content) != expected:
                reason = "JSON object does not match the requested role contract"
        except json.JSONDecodeError as error:
            reason = f"Invalid JSON at line {error.lineno}, column {error.colno}"
    if reason:
        evidence = {**diagnostics, "synthetic_stdout_prefix": content[:192],
                    "stdout_prefix_truncated": len(content) > 192}
        raise ValueError(f"Configured CLI JSON contract failed for {expected['role']}: {reason}; bounded diagnostics: {json.dumps(evidence, ensure_ascii=True)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", help="Authorize these synthetic local inference requests")
    parser.add_argument("--model", choices=["qwen2.5-coder:7b", "qwen2.5-coder:14b"], default="qwen2.5-coder:7b")
    args = parser.parse_args()
    if not args.run_live:
        parser.error("Live inference requires --run-live; no model download or service start is performed")
    bind_local_cli_endpoint()
    opener = build_opener(ProxyHandler({}), NoRedirect())
    def local(path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request("http://127.0.0.1:11434" + path, data=body,
                          headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=60) as response:
            raw = response.read(131073)
        if len(raw) > 131072:
            raise ValueError("Local API response exceeds 128 KiB bound")
        return json.loads(raw)
    inventory = local("/api/tags")
    model = next((entry for entry in inventory["models"] if entry["name"] == args.model), None)
    if not model or not model.get("digest"):
        raise ValueError("Requested model is not already installed with a reported digest")
    config_bytes = (ROOT / "src/agent_factory/defaults/providers.json").read_bytes()
    config = next(p for p in json.loads(config_bytes)["providers"] if p["id"] == "ollama")
    capability = ProviderCapabilities.from_config(config)
    roles = (*AUTONOMOUS_PLANNING_ROLE_IDS, "Environment Bootstrap", "Developer")
    results = []
    with tempfile.TemporaryDirectory(prefix="af-role-canary-") as folder:
        provider = CLIProvider("ollama", config["executable"], config["args"],
                               model_namespace=config["model_namespace"], model_ids=config["model_ids"],
                               executable_candidates=config.get("executable_candidates"),
                               allowed_roles=config["allowed_roles"], allow_execution=config["allow_execution"],
                               capabilities=capability, workspace=Path(folder),
                               max_timeout=60, max_output_chars=16384)
        for index, role in enumerate(roles, 1):
            expected = {"role": role, "mode": "read_only", "writes": []}
            prompt = "Synthetic role contract smoke. Do not call tools or change files. Return only this JSON object: " + json.dumps(expected)
            error = capability.role_model_error(role, "local:" + args.model)
            if error:
                raise ValueError(error)
            generated = local("/api/generate", {"model": args.model, "prompt": prompt,
                              "format": "json", "stream": False, "keep_alive": 0,
                              "options": {"num_predict": 96, "num_ctx": 2048, "temperature": 0}})
            if (generated.get("model") != args.model or not generated.get("done")
                    or not 0 < generated.get("eval_count", 0) <= 96
                    or json.loads(generated.get("response", "")) != expected):
                raise ValueError(f"Bounded API JSON contract failed for {role}")
            agent = Agent(id=f"canary-{index}", name="Role canary", role=role, enabled=True,
                          provider="ollama", model="local:" + args.model, instructions=prompt)
            item = WorkItem(id=index, project_id=1, title="Read-only role canary", description=prompt)
            approval = ExecutionApproval(index, "ollama", agent.id, item.id, approved_by="Local canary operator")
            result = provider.execute(agent, item, {"synthetic": True}, approval)
            diagnostics = {key: result.metadata.get(key) for key in (
                "elapsed_seconds", "returncode", "output_limit_chars", "retained_output_chars",
                "observed_output_chars", "stdout_retained_chars", "stderr_retained_chars", "stderr_ansi_sequences",
            )}
            if not result.ok:
                raise ValueError(f"Configured CLI contract failed for {role}: {result.error}; bounded diagnostics: {json.dumps(diagnostics)}")
            validate_cli_json(result.content, expected, diagnostics)
            results.append({"role": role, "api_output_tokens": generated["eval_count"],
                            "cli_effective_model": result.metadata.get("effective_model"), "cli_diagnostics": diagnostics, "passed": True})
            print(json.dumps(results[-1]), flush=True)
    final_model = next((entry for entry in local("/api/tags")["models"] if entry["name"] == args.model), None)
    if not final_model or final_model["digest"] != model["digest"]:
        raise ValueError("Installed model identity changed during qualification")
    print(json.dumps({"scope": "local-role-contract-smoke-only", "model_digest": model["digest"],
                      "profile_sha256": hashlib.sha256(config_bytes).hexdigest(), "roles": len(results),
                      "api_limit_tokens": 96, "request_timeout_seconds": 60,
                      "cli_combined_output_limit_chars": 16384, "cli_json_limit_chars": 1024, "cli_hard_token_limit": None}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
