"""Command-line interface for the standalone Agent Factory."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .backlog import BacklogProposal, diff_issues, issue_operations, load_backlog
from .github import GitHubClient
from .storage import SQLiteStorage


def _version() -> str:
    try:
        return version("agent-factory-orchestrator")
    except ImportError:  # The source checkout has no installed distribution metadata.
        return "0.1.0"


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        prog="agent-factory",
        description="Provider-neutral orchestration for traceable, human-approved agent delivery.",
    )
    command.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    command.add_argument(
        "--workspace",
        default=os.getenv("AGENT_FACTORY_WORKSPACE", "."),
        help="Project workspace used for state and configuration (default: current directory).",
    )
    command.add_argument(
        "--db",
        default=os.getenv("AGENT_FACTORY_DB"),
        help="SQLite path (default: WORKSPACE/.agent-factory/state.db).",
    )
    sub = command.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create the generic example project and work item.")
    sub.add_parser("bootstrap", help="Alias for init.")
    sub.add_parser("demo", help="Run the offline deterministic delivery demo.")
    web = sub.add_parser("web", help="Start the loopback-only Local Control Center API.")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", default=8765, type=int)
    web.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        help="Open the Local Control Center in the default browser after startup.",
    )

    project = sub.add_parser("project").add_subparsers(dest="action", required=True)
    project_init = project.add_parser("init")
    project_init.add_argument("--name", required=True)
    project_init.add_argument("--description", default="")
    project.add_parser("list")

    work_item = sub.add_parser("work-item").add_subparsers(dest="action", required=True)
    create_item = work_item.add_parser("create")
    create_item.add_argument("--project-id", required=True, type=int)
    create_item.add_argument("--title", required=True)
    create_item.add_argument("--description", required=True)
    create_item.add_argument("--kind", default="task")
    create_item.add_argument("--acceptance", action="append", required=True)
    list_items = work_item.add_parser("list")
    list_items.add_argument("--project-id", type=int)
    show_item = work_item.add_parser("show")
    show_item.add_argument("task_id", type=int)

    providers = sub.add_parser("providers").add_subparsers(
        dest="provider_action", required=True
    )
    providers.add_parser("status")
    providers.add_parser("gates")
    providers.add_parser("reconcile")
    request = providers.add_parser("request")
    request.add_argument("provider")
    request.add_argument("--agent", required=True)
    request.add_argument("--task-id", required=True, type=int)
    for action in ("approve", "reject", "cancel"):
        gate = providers.add_parser(action)
        gate.add_argument("gate_id", type=int)
        gate.add_argument("--note", default="")
    invoke = providers.add_parser("invoke")
    invoke.add_argument("gate_id", type=int)

    env = sub.add_parser("env").add_subparsers(dest="action", required=True)
    env.add_parser("check")

    agents = sub.add_parser("agents").add_subparsers(dest="action", required=True)
    agents.add_parser("list")
    for action in ("enable", "disable"):
        agent = agents.add_parser(action)
        agent.add_argument("agent_id")
    replace = agents.add_parser("replace")
    replace.add_argument("agent_id")
    replace.add_argument("--provider", required=True)
    replace.add_argument(
        "--model",
        default="",
        help="Stable model identity used by independent-review routing.",
    )

    reviews = sub.add_parser("reviews").add_subparsers(
        dest="review_action", required=True
    )
    review_list = reviews.add_parser("list")
    review_list.add_argument("--run-id", type=int)
    review_list.add_argument("--limit", type=int, default=100)

    backlog = sub.add_parser("backlog").add_subparsers(dest="action", required=True)
    validate = backlog.add_parser("validate")
    validate.add_argument("--path", required=True)
    import_items = backlog.add_parser("import")
    import_items.add_argument("--path", required=True)
    import_items.add_argument("--project-id", required=True, type=int)
    sync = backlog.add_parser("sync")
    sync.add_argument("--path")
    sync.add_argument("--repo")
    sync.add_argument("--existing-json")
    sync.add_argument("--apply", action="store_true")
    sync.add_argument("--plan-id", type=int)
    sync.add_argument("--gate-id", type=int)
    backlog.add_parser("gates")
    for action in ("approve", "reject"):
        gate = backlog.add_parser(action)
        gate.add_argument("gate_id", type=int)
        gate.add_argument("--note", default="")

    task = sub.add_parser("task").add_subparsers(dest="action", required=True)
    claim = task.add_parser("claim")
    claim.add_argument("task_id", type=int)
    claim.add_argument("--agent", default="coding-worker-codex")
    run_task = task.add_parser("run")
    run_task.add_argument("task_id", type=int)
    run_task.add_argument("--workflow", default="delivery")
    review = task.add_parser("review")
    review.add_argument("task_id", type=int)
    review.add_argument("--artifact-id", type=int)
    review.add_argument("--decision", choices=["approved", "rejected"])
    review.add_argument("--note", default="")

    workflow = sub.add_parser("workflow").add_subparsers(dest="action", required=True)
    workflow_run = workflow.add_parser("run")
    workflow_run.add_argument("--task-id", type=int, required=True)
    workflow_run.add_argument("--workflow", default="delivery")
    workflow_run.add_argument("--mode", choices=["simulation", "live"], default="simulation")

    approvals = sub.add_parser("approvals").add_subparsers(dest="action", required=True)
    approvals.add_parser("list")
    for action in ("approve", "reject"):
        gate = approvals.add_parser(action)
        gate.add_argument("gate_id", type=int)
        gate.add_argument("--note", default="")

    audit = sub.add_parser("audit").add_subparsers(dest="action", required=True)
    audit_list = audit.add_parser("list")
    audit_list.add_argument("--limit", type=int, default=100)

    state = sub.add_parser("state").add_subparsers(dest="action", required=True)
    state.add_parser("check")
    backup = state.add_parser("backup")
    backup.add_argument("--to", required=True)
    stale = state.add_parser("stale")
    stale.add_argument("--older-than", type=int, default=3600)
    return command


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    workspace = Path(args.workspace).expanduser().resolve()
    db = Path(args.db).expanduser() if args.db else Path(".agent-factory/state.db")
    if not db.is_absolute():
        db = workspace / db
    return workspace, db.resolve()


def _control_center_url(host: str, port: int) -> str:
    display_host = f"[{host}]" if ":" in host else host
    return f"http://{display_host}:{port}/"


def _schedule_browser_open(
    url: str, *, delay: float = 0.75, opener: Any | None = None
) -> threading.Timer:
    callback = opener or webbrowser.open
    timer = threading.Timer(delay, callback, args=(url,))
    timer.daemon = True
    timer.start()
    return timer


def _workflow_approval_output(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "run_id": item.target_id,
        "status": item.status,
        "decision_note": item.decision_note,
        "created_at": item.created_at,
        "decided_at": item.decided_at,
    }


def _provider_approval_output(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "provider": item.metadata["provider"],
        "agent_id": item.metadata["agent_id"],
        "task_id": item.metadata["task_id"],
        "status": item.status,
        "decision_note": item.decision_note,
        "created_at": item.created_at,
        "decided_at": item.decided_at,
        "consumed_at": item.metadata["consumed_at"],
        "request_hash": item.metadata["request_hash"],
        "definition_hash": item.metadata["definition_hash"],
    }


def _github_approval_output(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "plan_id": item.target_id,
        "repo": item.metadata["repo"],
        "plan_hash": item.metadata["plan_hash"],
        "status": item.status,
        "decision_note": item.decision_note,
        "created_at": item.created_at,
        "decided_at": item.decided_at,
        "consumed_at": item.metadata["consumed_at"],
    }


def _review_output(item: Any) -> dict[str, Any]:
    result = asdict(item)
    for field in (
        "reviewed_stages",
        "reviewed_artifact_ids",
        "producer_agents",
        "excluded_models",
        "excluded_candidates",
    ):
        result[field] = json.dumps(result[field], sort_keys=True)
    return result


def _seed_example(storage: SQLiteStorage) -> tuple[int, int]:
    from .application import AgentFactoryService

    return AgentFactoryService(storage).seed_example()


def _show_run(storage: SQLiteStorage, run_id: int) -> None:
    run = storage.db.execute(
        "SELECT * FROM workflow_runs WHERE id=?", (run_id,)
    ).fetchone()
    if not run:
        raise KeyError(f"Unknown run: {run_id}")
    print(f"Run {run_id}: {run['workflow_id']} - {run['status']}")
    for row in storage.artifacts(run_id):
        print(
            f"\n--- {row['stage']} | {row['agent_id']} | {row['provider']} ---\n"
            f"{row['content']}"
        )
    for assignment in storage.reviewer_assignments(run_id):
        print(
            "\nREVIEW ROUTING: "
            f"{assignment['stage']} -> {assignment['reviewer_agent_id']} "
            f"({assignment['reviewer_model']})"
        )
    gate = storage.db.execute(
        "SELECT * FROM approval_gates WHERE run_id=?", (run_id,)
    ).fetchone()
    if gate:
        print(f"\nSTOPPED AT HUMAN APPROVAL: gate {gate['id']} is {gate['status']}")


def _import_backlog(
    storage: SQLiteStorage, proposal: BacklogProposal, project_id: int
) -> dict[str, Any]:
    from .application import AgentFactoryService

    return asdict(AgentFactoryService(storage).import_backlog(proposal, project_id))


def _canonical_hash(value: Any) -> str:
    from .application import canonical_hash

    return canonical_hash(value)


def _provider_snapshot_hashes(
    provider: str, agent: Any, item: Any
) -> tuple[str, str]:
    from .application import provider_snapshot_hashes

    return provider_snapshot_hashes(provider, agent, item)


def _provider_invoke(storage: SQLiteStorage, registry: Any, gate_id: int) -> int:
    from .application import AgentFactoryService

    result = AgentFactoryService(storage, registry).invoke_provider(gate_id)
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.ok else 3


def _execute(args: argparse.Namespace) -> int:
    workspace, db_path = _paths(args)
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["AGENT_FACTORY_WORKSPACE"] = str(workspace)

    # These imports intentionally happen after workspace selection because configuration
    # supports independent state and overrides for every workspace.
    from .application import AgentFactoryService
    from .environment import as_json
    from .registry import AgentRegistry
    from .runtime import AgentRuntime, ExecutionMode

    if args.command == "web":
        try:
            import uvicorn

            from .web import create_app, validate_loopback_host
        except ImportError as exc:
            raise RuntimeError(
                'Local Control Center dependencies are missing; install with pip install -e ".[web]"'
            ) from exc
        host = validate_loopback_host(args.host)
        if args.port < 1 or args.port > 65_535:
            raise ValueError("--port must be between 1 and 65535")
        if args.open_browser:
            url = _control_center_url(host, args.port)
            print(f"Opening Local Control Center at {url}")
            _schedule_browser_open(url)
        uvicorn.run(create_app(workspace, db_path), host=host, port=args.port)
        return 0

    storage = SQLiteStorage(db_path)
    registry = AgentRegistry()
    runtime = AgentRuntime(workspace=workspace)
    service = AgentFactoryService(
        storage, registry, runtime, workspace=workspace
    )
    try:
        if args.command in {"init", "bootstrap"}:
            project_id, task_id = service.seed_example()
            print(
                json.dumps(
                    {"workspace": str(workspace), "database": str(db_path), "project_id": project_id, "task_id": task_id},
                    indent=2,
                )
            )
        elif args.command == "env":
            print(json.dumps(as_json(), indent=2))
        elif args.command == "project":
            if args.action == "init":
                print(
                    json.dumps(
                        asdict(service.create_project(args.name, args.description))
                    )
                )
            else:
                print(json.dumps([asdict(item) for item in service.projects()], indent=2))
        elif args.command == "work-item":
            if args.action == "create":
                item = service.create_work_item(
                    project_id=args.project_id,
                    title=args.title,
                    description=args.description,
                    kind=args.kind,
                    acceptance_criteria=args.acceptance,
                )
                print(json.dumps({"task_id": item.id}))
            elif args.action == "show":
                output = asdict(service.work_item(args.task_id))
                output.pop("created_at")
                output.pop("priority")
                output.pop("assignee")
                print(json.dumps(output, indent=2))
            else:
                items = service.work_items(args.project_id)
                print(
                    json.dumps(
                        [
                            {
                                "id": item.id,
                                "project_id": item.project_id,
                                "title": item.title,
                                "description": item.description,
                                "status": item.status,
                                "kind": item.kind,
                            }
                            for item in items
                        ],
                        indent=2,
                    )
                )
        elif args.command == "providers":
            if args.provider_action == "status":
                print(
                    json.dumps(
                        [
                            item.health_details
                            for item in service.providers()
                            if item.id in service.runtime.providers
                        ],
                        indent=2,
                    )
                )
            elif args.provider_action == "gates":
                print(
                    json.dumps(
                        [
                            _provider_approval_output(item)
                            for item in service.approvals()
                            if item.kind == "provider"
                        ],
                        indent=2,
                    )
                )
            elif args.provider_action == "reconcile":
                print(
                    json.dumps(
                        {
                            "reconciled": service.reconcile_provider_attempts(),
                            "retry_requires_new_gate": True,
                        },
                        indent=2,
                    )
                )
            elif args.provider_action == "request":
                gate_id = service.request_provider_execution(
                    args.provider, args.agent, args.task_id
                )
                print(
                    f"Provider execution gate {gate_id} is pending human approval."
                )
            elif args.provider_action in {"approve", "reject", "cancel"}:
                decision = (
                    "cancelled"
                    if args.provider_action == "cancel"
                    else "approved" if args.provider_action == "approve" else "rejected"
                )
                service.decide_provider_execution(args.gate_id, decision, args.note)
                print(f"Provider execution gate {args.gate_id} {decision} by Human.")
            else:
                result = service.invoke_provider(args.gate_id)
                print(json.dumps(asdict(result), indent=2))
                return 0 if result.ok else 3
        elif args.command == "agents":
            if args.action == "list":
                print(
                    json.dumps(
                        [
                            {
                                "id": item.id,
                                "name": item.name,
                                "role": item.role,
                                "enabled": item.enabled,
                                "provider": item.provider,
                                "model": item.model,
                            }
                            for item in service.agents()
                        ],
                        indent=2,
                    )
                )
            elif args.action == "replace":
                agent = service.replace_agent_provider(
                    args.agent_id, args.provider, args.model
                )
                print(
                    json.dumps(
                        {
                            "agent_id": agent.id,
                            "provider": agent.provider,
                            "model": agent.model,
                        }
                    )
                )
            else:
                agent = service.set_agent_enabled(
                    args.agent_id, args.action == "enable"
                )
                print(json.dumps({"agent_id": agent.id, "enabled": agent.enabled}))
        elif args.command == "reviews":
            print(
                json.dumps(
                    [_review_output(item) for item in service.reviews(args.run_id, limit=args.limit)],
                    indent=2,
                )
            )
        elif args.command == "backlog":
            if args.action == "validate":
                proposal = load_backlog(Path(args.path))
                print(
                    json.dumps(
                        {
                            "valid": True,
                            "source_sha256": proposal.source_sha256,
                            "item_count": len(proposal.items),
                            "stable_ids": [item.stable_id for item in proposal.items],
                        },
                        indent=2,
                    )
                )
            elif args.action == "import":
                print(
                    json.dumps(
                        asdict(
                            service.import_backlog(
                                load_backlog(Path(args.path)), args.project_id
                            )
                        ),
                        indent=2,
                    )
                )
            elif args.action == "gates":
                print(
                    json.dumps(
                        [
                            _github_approval_output(item)
                            for item in service.approvals()
                            if item.kind == "github"
                        ],
                        indent=2,
                    )
                )
            elif args.action in {"approve", "reject"}:
                decision = "approved" if args.action == "approve" else "rejected"
                service.decide_github_approval(args.gate_id, decision, args.note)
                print(f"GitHub gate {args.gate_id} {decision} by Human.")
            elif args.apply:
                if args.plan_id is None or args.gate_id is None:
                    raise ValueError("--apply requires --plan-id and --gate-id")
                plan = storage.github_plan(args.plan_id)
                client = GitHubClient(repo=plan["repo"], dry_run=False)
                result = service.apply_github_plan(
                    args.plan_id, args.gate_id, client
                )
                print(json.dumps(result, indent=2))
                return 0 if result.get("ok") else 3
            else:
                if not args.path or not args.repo:
                    raise ValueError("backlog sync requires --path and --repo")
                proposal = load_backlog(Path(args.path))
                client = GitHubClient(repo=args.repo, dry_run=True)
                if args.existing_json:
                    existing = json.loads(Path(args.existing_json).read_text(encoding="utf-8"))
                else:
                    response = client.issues()
                    if not response.get("ok"):
                        raise RuntimeError(response.get("error", "Could not read GitHub issues"))
                    existing = response.get("data", [])
                if not isinstance(existing, list):
                    raise ValueError("GitHub issue source must be a list")
                difference = diff_issues(proposal, existing)
                operations = issue_operations(difference)
                output: dict[str, Any] = {"diff": difference, "operations": operations}
                if operations:
                    output.update(
                        service.preview_github_plan(args.repo, operations, client)
                    )
                print(json.dumps(output, indent=2))
        elif args.command == "task":
            if args.action == "claim":
                print(json.dumps(asdict(service.claim_work_item(args.task_id, args.agent))))
            elif args.action == "run":
                print("Execution mode: simulation")
                _show_run(
                    storage,
                    service.run_workflow(
                        args.task_id, args.workflow, ExecutionMode.SIMULATION
                    ).id,
                )
            elif args.artifact_id is not None or args.decision is not None:
                if args.artifact_id is None or args.decision is None:
                    raise ValueError("artifact review requires --artifact-id and --decision")
                service.review_artifact(
                    args.task_id, args.artifact_id, args.decision, args.note
                )
                print(
                    json.dumps(
                        {"artifact_id": args.artifact_id, "decision": args.decision}
                    )
                )
            else:
                print(
                    json.dumps(
                        [asdict(item) for item in service.artifacts(task_id=args.task_id)],
                        indent=2,
                    )
                )
        elif args.command == "workflow":
            mode = ExecutionMode(args.mode)
            print(
                f"Execution mode: {mode.value} "
                f"({'offline fallback permitted' if mode is ExecutionMode.SIMULATION else 'offline fallback prohibited'})"
            )
            _show_run(
                storage,
                service.run_workflow(args.task_id, args.workflow, mode).id,
            )
        elif args.command == "approvals":
            if args.action == "list":
                print(
                    json.dumps(
                        [
                            _workflow_approval_output(item)
                            for item in service.approvals()
                            if item.kind == "workflow"
                        ],
                        indent=2,
                    )
                )
            else:
                decision = "approved" if args.action == "approve" else "rejected"
                service.decide_workflow_approval(args.gate_id, decision, args.note)
                print(f"Approval {args.gate_id} {decision} by Human.")
        elif args.command == "audit":
            print(
                json.dumps(
                    [
                        {
                            **asdict(item),
                            "payload": json.dumps(item.payload),
                        }
                        for item in service.events(limit=args.limit)
                    ],
                    indent=2,
                )
            )
        elif args.command == "state":
            if args.action == "check":
                print(json.dumps(storage.integrity_check(), indent=2))
            elif args.action == "backup":
                print(json.dumps({"backup": str(service.backup(Path(args.to)))}, indent=2))
            else:
                print(json.dumps(service.stale_state(args.older_than), indent=2))
        elif args.command == "demo":
            print("Execution mode: simulation (live providers are never invoked implicitly)")
            _show_run(storage, service.run_demo().id)
        return 0
    finally:
        storage.close()


def main(argv: list[str] | None = None) -> int:
    try:
        return _execute(parser().parse_args(argv))
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
