"""Command-line interface for the standalone Agent Factory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .backlog import BacklogProposal, diff_issues, issue_operations, load_backlog
from .github import GitHubClient
from .models import ExecutionApproval, WorkItem
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


def _seed_example(storage: SQLiteStorage) -> tuple[int, int]:
    name = "Agent Factory Demo"
    project = storage.find_project(name)
    project_id = (
        int(project["id"])
        if project
        else storage.create_project(
            name,
            "A neutral example that demonstrates a complete evidence and approval chain.",
        )
    )
    existing = storage.db.execute(
        "SELECT id FROM work_items WHERE project_id=? AND title=?",
        (project_id, "Deliver the first reviewable capability"),
    ).fetchone()
    if existing:
        return project_id, int(existing["id"])
    item = WorkItem(
        title="Deliver the first reviewable capability",
        description=(
            "Produce a bounded implementation proposal, validate it against explicit criteria, "
            "and stop for a human decision."
        ),
        project_id=project_id,
        kind="epic",
        inputs={"example": True},
        expected_outputs=[
            "policy precheck",
            "implementation artifact",
            "validation evidence",
            "policy postcheck",
        ],
        acceptance_criteria=[
            "Every stage produces a typed artifact",
            "Every acceptance criterion has evidence",
            "The workflow stops before final acceptance",
        ],
    )
    return project_id, storage.create_task(item)


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
    gate = storage.db.execute(
        "SELECT * FROM approval_gates WHERE run_id=?", (run_id,)
    ).fetchone()
    if gate:
        print(f"\nSTOPPED AT HUMAN APPROVAL: gate {gate['id']} is {gate['status']}")


def _existing_local_items(storage: SQLiteStorage, project_id: int) -> dict[str, int]:
    result: dict[str, int] = {}
    rows = storage.db.execute(
        "SELECT id,payload FROM work_items WHERE project_id=?", (project_id,)
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload"])
            stable_id = payload.get("inputs", {}).get("stable_id")
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(stable_id, str) and stable_id:
            result[stable_id] = int(row["id"])
    return result


def _import_backlog(
    storage: SQLiteStorage, proposal: BacklogProposal, project_id: int
) -> dict[str, Any]:
    if not storage.db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        raise KeyError(f"Unknown project: {project_id}")
    known = _existing_local_items(storage, project_id)
    remaining = {item.stable_id: item for item in proposal.items}
    created: list[dict[str, Any]] = []
    skipped: list[str] = []
    for stable_id in list(remaining):
        if stable_id in known:
            skipped.append(stable_id)
            remaining.pop(stable_id)
    while remaining:
        ready = [
            item
            for item in remaining.values()
            if all(
                reference in known
                for reference in (
                    *item.dependencies,
                    *([item.parent_id] if item.parent_id else []),
                )
            )
        ]
        if not ready:
            raise RuntimeError("Validated backlog could not be ordered for local import")
        for item in ready:
            task = WorkItem(
                title=item.title,
                description=item.description,
                project_id=project_id,
                kind=item.kind,
                dependencies=[known[value] for value in item.dependencies],
                inputs={
                    "stable_id": item.stable_id,
                    "parent_stable_id": item.parent_id,
                    "source_path": proposal.source_path,
                    "source_sha256": proposal.source_sha256,
                    "source_references": list(item.source_references),
                    "review_notes": list(item.review_notes),
                },
                acceptance_criteria=list(item.acceptance_criteria),
                expected_outputs=["reviewable delivery artifact", "acceptance evidence"],
            )
            task_id = storage.create_task(task)
            known[item.stable_id] = task_id
            created.append({"stable_id": item.stable_id, "task_id": task_id})
            remaining.pop(item.stable_id)
    return {"created": created, "skipped": sorted(skipped), "source_sha256": proposal.source_sha256}


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _provider_snapshot_hashes(
    provider: str, agent: Any, item: WorkItem
) -> tuple[str, str]:
    """Bind an approval to canonical request and effective policy definitions."""

    from .config import config_path, load_yaml

    request = {
        "provider": provider,
        "agent": asdict(agent),
        "task": item.to_dict(),
    }
    definitions = {
        "providers": load_yaml(config_path("providers")),
        "policy": load_yaml(config_path("policy")),
    }
    return _canonical_hash(request), _canonical_hash(definitions)


def _provider_invoke(storage: SQLiteStorage, registry: Any, gate_id: int) -> int:
    from .runtime import AgentRuntime

    gate = storage.db.execute(
        "SELECT * FROM provider_execution_gates WHERE id=?", (gate_id,)
    ).fetchone()
    if not gate:
        raise KeyError(f"Unknown provider gate: {gate_id}")
    agent = registry.get(gate["agent_id"])
    item = storage.get_task(int(gate["task_id"]))
    request_hash, definition_hash = _provider_snapshot_hashes(
        str(gate["provider"]), agent, item
    )
    attempt = storage.claim_provider_execution(
        gate_id,
        request_hash,
        definition_hash,
    )
    approval = ExecutionApproval(
        int(gate["id"]), gate["provider"], gate["agent_id"], int(gate["task_id"])
    )
    storage.mark_provider_attempt_running(int(attempt["id"]))
    try:
        if agent.provider != gate["provider"]:
            raise ValueError("Agent provider changed after approval; request a new gate")
        result = AgentRuntime().run(
            agent,
            item,
            {"source": "one-time human-approved invocation"},
            approval,
            allow_fallback=False,
        )
    except Exception as exc:  # Persist a terminal attempt even for launcher failures.
        from .models import ProviderResult

        result = ProviderResult(
            False,
            provider=str(gate["provider"]),
            error=str(exc)[:4000],
            metadata={"exception": type(exc).__name__},
        )
    metadata = {"ok": result.ok, "error": (result.error or "")[:4000], **result.metadata}
    metadata["content_sha256"] = hashlib.sha256(result.content.encode()).hexdigest()
    artifact_id = storage.finish_provider_attempt(
        int(attempt["id"]),
        "succeeded" if result.ok else "failed",
        result.content if result.ok else (result.error or "provider failed"),
        metadata,
    )
    print(
        json.dumps(
            {
                "ok": result.ok,
                "provider": result.provider,
                "artifact_id": artifact_id,
                "content": result.content,
                "error": result.error,
                "metadata": result.metadata,
            },
            indent=2,
        )
    )
    return 0 if result.ok else 3


def _execute(args: argparse.Namespace) -> int:
    workspace, db_path = _paths(args)
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["AGENT_FACTORY_WORKSPACE"] = str(workspace)

    # These imports intentionally happen after workspace selection because configuration
    # supports independent state and overrides for every workspace.
    from .environment import as_json
    from .registry import AgentRegistry
    from .runtime import AgentRuntime, ExecutionMode
    from .workflow import WorkflowEngine

    storage = SQLiteStorage(db_path)
    registry = AgentRegistry()
    try:
        if args.command in {"init", "bootstrap"}:
            project_id, task_id = _seed_example(storage)
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
                existing = storage.find_project(args.name)
                project_id = (
                    int(existing["id"])
                    if existing
                    else storage.create_project(args.name, args.description)
                )
                print(json.dumps({"project_id": project_id, "created": existing is None}))
            else:
                rows = storage.db.execute("SELECT * FROM projects ORDER BY id").fetchall()
                print(json.dumps([dict(row) for row in rows], indent=2))
        elif args.command == "work-item":
            if args.action == "create":
                if not storage.db.execute(
                    "SELECT 1 FROM projects WHERE id=?", (args.project_id,)
                ).fetchone():
                    raise KeyError(f"Unknown project: {args.project_id}")
                item = WorkItem(
                    title=args.title,
                    description=args.description,
                    project_id=args.project_id,
                    kind=args.kind,
                    acceptance_criteria=args.acceptance,
                )
                print(json.dumps({"task_id": storage.create_task(item)}))
            elif args.action == "show":
                print(json.dumps(storage.get_task(args.task_id).to_dict(), indent=2, default=str))
            else:
                query = "SELECT id,project_id,title,description,status,payload FROM work_items"
                parameters: tuple[Any, ...] = ()
                if args.project_id is not None:
                    query += " WHERE project_id=?"
                    parameters = (args.project_id,)
                query += " ORDER BY id"
                rows = storage.db.execute(query, parameters).fetchall()
                print(
                    json.dumps(
                        [
                            {
                                "id": row["id"],
                                "project_id": row["project_id"],
                                "title": row["title"],
                                "description": row["description"],
                                "status": row["status"],
                                "kind": json.loads(row["payload"]).get("kind", "task"),
                            }
                            for row in rows
                        ],
                        indent=2,
                    )
                )
        elif args.command == "providers":
            if args.provider_action == "status":
                print(json.dumps(AgentRuntime().health(), indent=2))
            elif args.provider_action == "gates":
                print(
                    json.dumps(
                        [dict(row) for row in storage.provider_execution_gates()], indent=2
                    )
                )
            elif args.provider_action == "reconcile":
                print(
                    json.dumps(
                        {
                            "reconciled": storage.reconcile_provider_attempts(),
                            "retry_requires_new_gate": True,
                        },
                        indent=2,
                    )
                )
            elif args.provider_action == "request":
                agent = registry.get(args.agent)
                if not agent.enabled:
                    raise RuntimeError(f"Agent is disabled: {agent.id}")
                if agent.provider != args.provider:
                    raise ValueError(
                        f"Agent {agent.id} uses {agent.provider}, not {args.provider}"
                    )
                item = storage.get_task(args.task_id)
                request_hash, definition_hash = _provider_snapshot_hashes(
                    args.provider, agent, item
                )
                gate_id = storage.request_provider_execution(
                    args.provider,
                    agent.id,
                    args.task_id,
                    request_hash,
                    definition_hash,
                )
                print(
                    f"Provider execution gate {gate_id} is pending human approval."
                )
            elif args.provider_action in {"approve", "reject", "cancel"}:
                if args.provider_action == "cancel":
                    storage.cancel_provider_execution(args.gate_id, args.note)
                    decision = "cancelled"
                else:
                    decision = (
                        "approved" if args.provider_action == "approve" else "rejected"
                    )
                    storage.decide_provider_execution(args.gate_id, decision, args.note)
                print(f"Provider execution gate {args.gate_id} {decision} by Human.")
            else:
                return _provider_invoke(storage, registry, args.gate_id)
        elif args.command == "agents":
            if args.action == "list":
                print(
                    json.dumps(
                        [
                            {
                                "id": agent.id,
                                "name": agent.name,
                                "role": agent.role,
                                "enabled": agent.enabled,
                                "provider": agent.provider,
                            }
                            for agent in registry.list()
                        ],
                        indent=2,
                    )
                )
            elif args.action == "replace":
                agent = registry.replace_provider(args.agent_id, args.provider)
                storage.event(
                    "agent.provider.replaced",
                    "agent",
                    agent.id,
                    {"provider": agent.provider},
                )
                print(json.dumps({"agent_id": agent.id, "provider": agent.provider}))
            else:
                agent = registry.set_enabled(args.agent_id, args.action == "enable")
                storage.event(
                    "agent.enabled" if agent.enabled else "agent.disabled",
                    "agent",
                    agent.id,
                    {"enabled": agent.enabled},
                )
                print(json.dumps({"agent_id": agent.id, "enabled": agent.enabled}))
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
                        _import_backlog(
                            storage, load_backlog(Path(args.path)), args.project_id
                        ),
                        indent=2,
                    )
                )
            elif args.action == "gates":
                print(json.dumps([dict(row) for row in storage.github_gates()], indent=2))
            elif args.action in {"approve", "reject"}:
                decision = "approved" if args.action == "approve" else "rejected"
                storage.decide_github_gate(args.gate_id, decision, args.note)
                print(f"GitHub gate {args.gate_id} {decision} by Human.")
            elif args.apply:
                if args.plan_id is None or args.gate_id is None:
                    raise ValueError("--apply requires --plan-id and --gate-id")
                plan = storage.github_plan(args.plan_id)
                operations = json.loads(plan["plan_json"])["operations"]
                storage.claim_github_gate(
                    args.gate_id,
                    args.plan_id,
                    plan["repo"],
                    plan["plan_hash"],
                )
                client = GitHubClient(repo=plan["repo"], dry_run=False)
                result = client.apply(
                    operations, storage.github_completed_keys(plan["repo"])
                )
                report_id = storage.finish_github_apply(
                    args.gate_id, args.plan_id, result
                )
                print(json.dumps({"report_id": report_id, **result}, indent=2))
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
                    plan_id, plan_hash = storage.create_github_plan(args.repo, operations)
                    gate = storage.db.execute(
                        """SELECT * FROM github_mutation_gates
                             WHERE plan_id=? AND status IN ('pending','approved')
                             ORDER BY id DESC LIMIT 1""",
                        (plan_id,),
                    ).fetchone()
                    gate_id = int(gate["id"]) if gate else storage.request_github_gate(plan_id)
                    output.update(
                        {
                            "plan_id": plan_id,
                            "plan_hash": plan_hash,
                            "gate_id": gate_id,
                            "gate_status": str(gate["status"]) if gate else "pending",
                            "preview": client.apply(operations),
                        }
                    )
                print(json.dumps(output, indent=2))
        elif args.command == "task":
            item = storage.get_task(args.task_id)
            if args.action == "claim":
                agent = registry.get(args.agent)
                if not agent.enabled:
                    raise RuntimeError(f"Agent is disabled: {agent.id}")
                storage.event(
                    "task.claimed", "task", item.id or 0, {"worker": agent.id}
                )
                print(json.dumps({"task_id": item.id, "worker": agent.id}))
            elif args.action == "run":
                print("Execution mode: simulation")
                _show_run(
                    storage,
                    WorkflowEngine(storage).run(
                        args.workflow, item, ExecutionMode.SIMULATION
                    ),
                )
            elif args.artifact_id is not None or args.decision is not None:
                if args.artifact_id is None or args.decision is None:
                    raise ValueError("artifact review requires --artifact-id and --decision")
                row = storage.db.execute(
                    """SELECT a.id FROM artifacts a JOIN workflow_runs r ON r.id=a.run_id
                         WHERE a.id=? AND r.task_id=?""",
                    (args.artifact_id, args.task_id),
                ).fetchone()
                if not row:
                    raise ValueError("Artifact does not belong to the requested work item")
                storage.review_artifact(args.artifact_id, args.decision, args.note)
                print(
                    json.dumps(
                        {"artifact_id": args.artifact_id, "decision": args.decision}
                    )
                )
            else:
                rows = storage.db.execute(
                    """SELECT a.* FROM artifacts a JOIN workflow_runs r ON r.id=a.run_id
                         WHERE r.task_id=? ORDER BY a.id""",
                    (args.task_id,),
                ).fetchall()
                print(json.dumps([dict(row) for row in rows], indent=2))
        elif args.command == "workflow":
            mode = ExecutionMode(args.mode)
            print(
                f"Execution mode: {mode.value} "
                f"({'offline fallback permitted' if mode is ExecutionMode.SIMULATION else 'offline fallback prohibited'})"
            )
            _show_run(
                storage,
                WorkflowEngine(storage).run(
                    args.workflow, storage.get_task(args.task_id), mode
                ),
            )
        elif args.command == "approvals":
            if args.action == "list":
                print(json.dumps([dict(row) for row in storage.approvals()], indent=2))
            else:
                decision = "approved" if args.action == "approve" else "rejected"
                storage.decide_approval(args.gate_id, decision, args.note)
                print(f"Approval {args.gate_id} {decision} by Human.")
        elif args.command == "audit":
            if args.limit < 1 or args.limit > 10_000:
                raise ValueError("--limit must be between 1 and 10000")
            rows = storage.db.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (args.limit,)
            ).fetchall()
            print(json.dumps([dict(row) for row in rows], indent=2))
        elif args.command == "state":
            if args.action == "check":
                print(json.dumps(storage.integrity_check(), indent=2))
            elif args.action == "backup":
                print(json.dumps({"backup": str(storage.online_backup(Path(args.to)))}, indent=2))
            else:
                print(
                    json.dumps(
                        {
                            "workflow_runs": [dict(row) for row in storage.stale_workflow_runs(args.older_than)],
                            "provider_attempts": [dict(row) for row in storage.stale_provider_attempts(args.older_than)],
                        },
                        indent=2,
                    )
                )
        elif args.command == "demo":
            _, task_id = _seed_example(storage)
            print("Execution mode: simulation (live providers are never invoked implicitly)")
            active = storage.db.execute(
                """SELECT id FROM workflow_runs
                     WHERE task_id=? AND workflow_id='delivery'
                       AND status IN ('running','awaiting_approval')
                     ORDER BY id DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
            run_id = (
                int(active["id"])
                if active
                else WorkflowEngine(storage).run(
                    "delivery", storage.get_task(task_id), ExecutionMode.SIMULATION
                )
            )
            _show_run(storage, run_id)
        return 0
    finally:
        storage.close()


def main(argv: list[str] | None = None) -> int:
    try:
        return _execute(parser().parse_args(argv))
    except (KeyError, ValueError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
