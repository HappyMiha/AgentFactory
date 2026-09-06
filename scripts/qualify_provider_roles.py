"""Opt-in local Ollama role-contract smoke; implementation is shared with readiness."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent_factory.local_role_qualification import bind_local_cli_endpoint, validate_cli_json, main

if __name__ == "__main__":
    raise SystemExit(main())
