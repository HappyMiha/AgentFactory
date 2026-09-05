"""Configured role/model eligibility; synthetic tests are not live qualification."""
from copy import deepcopy
import json
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from agent_factory.models import Agent, ExecutionApproval, ProviderCapabilities, WorkItem
from agent_factory.providers import CLIProvider
from agent_factory.software_roles import AUTONOMOUS_PLANNING_ROLE_IDS
from agent_factory.autonomous_authorization import AuthorizationOutcome
from tests import test_autonomous_planning as planning_fixture
from tests import test_autonomous_authorization as authorization_fixture
from tests import test_autonomous_backlog_approval as approval_fixture

CATALOG = Path(__file__).resolve().parents[1] / "src/agent_factory/defaults/providers.json"


class ProviderRoleQualificationTests(unittest.TestCase):
    def setUp(self):
        self.profiles = json.loads(CATALOG.read_text(encoding="utf-8"))["providers"]
        self.ollama = deepcopy(next(p for p in self.profiles if p["id"] == "ollama"))
        self.model = "local:qwen2.5-coder:7b"

    def fixture(self, cls):
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture

    def test_shipped_profiles_by_autonomous_role_matrix(self):
        roles = (*AUTONOMOUS_PLANNING_ROLE_IDS, "Environment Bootstrap", "Developer")
        for profile in self.profiles:
            capability = ProviderCapabilities.from_config(profile)
            for role in roles:
                with self.subTest(provider=profile["id"], role=role):
                    available = capability.autonomous_local_eligible and capability.role_model_error(role, self.model) is None
                    self.assertEqual(available, profile["id"] == "ollama")
        self.assertFalse(self.ollama["capabilities"]["tool_calls"])

    def test_disabled_wrong_role_and_wrong_model_are_not_eligible(self):
        for field, value in (("enabled", False), ("allow_execution", False), ("allowed_roles", []), ("model_ids", []), ("args", ["run"])):
            with self.subTest(field=field):
                profile = {**self.ollama, field: value}
                self.assertIsNotNone(ProviderCapabilities.from_config(profile).role_model_error("mission_analyst", self.model))
        capability = ProviderCapabilities.from_config(self.ollama)
        self.assertIn("configured roles:", capability.role_model_error("shell_administrator", self.model))
        self.assertIn("configured models:", capability.role_model_error("mission_analyst", "local:unknown"))

    def test_rejected_pairs_never_spawn_even_with_otherwise_enabled_cli(self):
        capability = ProviderCapabilities.from_config(self.ollama)
        supervisor = Mock()
        provider = CLIProvider("ollama", "unused", self.ollama["args"], model_namespace="local",
                               model_ids=self.ollama["model_ids"], allow_execution=True,
                               capabilities=capability, supervisor=supervisor)
        item = WorkItem(id=1, project_id=1, title="Fixture", description="Read only")
        for role, model in [("shell_administrator", self.model), ("mission_analyst", "local:unknown")]:
            agent = Agent(id="fixture", name="Fixture", role=role, provider="ollama", model=model, enabled=True, instructions="Read only")
            with patch.object(provider, "_executable_paths") as paths:
                result = provider.execute(agent, item, {})
                self.assertFalse(result.ok)
                self.assertIn("Provider profile", result.error)
                paths.assert_not_called()
        supervisor.spawn.assert_not_called()

    def test_planning_rejects_profile_before_manifest_is_saved(self):
        fixture = self.fixture(planning_fixture.AutonomousPlanningTests)
        denied = {**self.ollama, "allowed_roles": ["Developer"]}
        fixture.planning.provider_capabilities["local-one"] = ProviderCapabilities.from_config(denied)
        with self.assertRaisesRegex(PermissionError, "mission_analyst.*configured roles"):
            fixture.manifest(default_model=self.model)
        self.assertEqual(fixture.storage.db.execute("SELECT count(*) FROM autonomous_planning_manifests").fetchone()[0], 0)

    def test_planning_accepts_explicit_role_model_pair(self):
        fixture = self.fixture(planning_fixture.AutonomousPlanningTests)
        fixture.planning.provider_capabilities["local-one"] = ProviderCapabilities.from_config(self.ollama)
        bindings = {role: {"provider_id": "local-one", "model": self.model} for role in AUTONOMOUS_PLANNING_ROLE_IDS}
        manifest = fixture.manifest(role_models=bindings)
        self.assertEqual(len(manifest.assignments), 5)
        self.assertTrue(all(a.model == self.model for a in manifest.assignments))

    def test_execution_denies_newly_incompatible_profile(self):
        fixture = self.fixture(authorization_fixture.AutonomousAuthorizationTests)
        denied = {**self.ollama, "allowed_roles": ["mission_analyst"]}
        fixture.authorizations.provider_capabilities["local-provider"] = ProviderCapabilities.from_config(denied)
        result = fixture.authorizations.resolve(fixture.execution_request())
        self.assertEqual(result.outcome, AuthorizationOutcome.DENY)
        self.assertIn("does not allow role", result.reason)

    def test_atomic_approval_rejects_incompatible_execution_roles(self):
        fixture = self.fixture(approval_fixture.AutonomousBacklogApprovalTests)
        before = fixture.counts()
        fixture.approvals.authorizations.provider_capabilities["local"] = ProviderCapabilities.from_config({**self.ollama, "allowed_roles": ["mission_analyst"]})
        with self.assertRaisesRegex(PermissionError, "No configured provider supports role"):
            fixture.approvals.approve_and_start(fixture.report.id, **fixture.approval_arguments())
        self.assertEqual(fixture.counts(), before)

    def test_profile_changes_are_part_of_authority_snapshot(self):
        first = ProviderCapabilities.from_config(self.ollama).to_dict()
        changed = ProviderCapabilities.from_config({**self.ollama, "allowed_roles": ["Developer"]}).to_dict()
        self.assertNotEqual(first, changed)
        self.assertEqual(first["profile_models"], ["local:qwen2.5-coder:7b", "local:qwen2.5-coder:14b"])

    def test_explicit_profiles_invoke_native_read_only_fixture_for_each_role(self):
        roles = (*AUTONOMOUS_PLANNING_ROLE_IDS, "Environment Bootstrap", "Developer")
        args = ["-c", "import sys; sys.stdin.read(); print('READ_ONLY_FIXTURE_OK')", "{model}"]
        profile = {**self.ollama, "args": args, "model_namespace": "fixture", "model_ids": ["small"]}
        with tempfile.TemporaryDirectory() as folder:
            provider = CLIProvider("fixture", sys.executable, args, allow_execution=True,
                                   model_namespace="fixture", model_ids=["small"],
                                   capabilities=ProviderCapabilities.from_config(profile),
                                   workspace=Path(folder), max_timeout=10, max_output_chars=1024)
            for index, role in enumerate(roles, 1):
                with self.subTest(role=role):
                    agent = Agent(id=f"role-{index}", name="Fixture", role=role, provider="fixture",
                                  model="fixture:small", enabled=True, instructions="Read only")
                    item = WorkItem(id=index, project_id=1, title="Fixture", description="Read-only contract smoke")
                    approval = ExecutionApproval(index, "fixture", agent.id, item.id)
                    result = provider.execute(agent, item, {}, approval)
                    self.assertTrue(result.ok, result.error)
                    self.assertEqual(result.content.strip(), "READ_ONLY_FIXTURE_OK")
                    self.assertEqual(result.metadata["effective_model"], "fixture:small")
