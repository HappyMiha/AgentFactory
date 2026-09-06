from copy import deepcopy
import unittest

from agent_factory.installation_plan import build_plan, changed_fields, load_catalog, validate_catalog


CONTEXT = {"tenant": "family", "project": "first-game", "host": "worker", "workspace": "project-tools"}


class InstallationPlanTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load_catalog()
        self.editor = self.catalog["packages"]["godot-editor"]

    def plan(self, requested=None, **kwargs):
        return build_plan(["godot-export-templates"] if requested is None else requested,
                          **({"context": CONTEXT, "platform": "windows-x86_64",
                              "catalog": self.catalog, "free_bytes": 20 * 1024**3} | kwargs))

    def observed(self, **kwargs):
        return {"version": self.editor["version"], "sha256": self.editor["sha256"],
                "target": self.editor["target"], "managed": True} | kwargs

    def test_real_catalogue_dependency_order_and_exact_sizes(self):
        document = self.plan().document()
        self.assertEqual([s["package"] for s in document["steps"]],
                         ["godot-editor", "godot-export-templates"])
        self.assertEqual(document["download_required_bytes"], 1367363568)
        self.assertFalse(document["execution_eligible"])
        self.assertFalse(document["disk_budget_is_measured_size"])
        self.assertFalse(document["requires_manual_action"])
        self.assertEqual(document["observation_trust"], "caller_reported_planning_only")
        self.assertNotIn("administrator", document["steps"][0]["permissions"])

    def test_snapshot_is_detached_and_request_order_is_stable(self):
        before = deepcopy(self.catalog)
        a = self.plan(["godot-editor", "godot-export-templates"])
        b = self.plan(["godot-export-templates", "godot-editor", "godot-editor"])
        self.assertEqual(a.digest, b.digest)
        exported = a.document()
        exported["steps"][0]["url"] = "changed"
        self.assertEqual(a.digest, b.digest)
        self.assertEqual(self.catalog, before)
        self.assertEqual(changed_fields(a, b), [])

    def test_disk_budget_covers_coexisting_copies_and_cache_saves_only_download(self):
        online = self.plan(['godot-editor']).document()
        cached = self.plan(['godot-editor'], offline=True,
                           cached_sha256=[self.editor['sha256']]).document()
        step = online['steps'][0]
        expected = 2*self.editor['download_bytes'] + 2*self.editor['extraction_budget_bytes'] + 72*1024**2
        self.assertEqual(online['disk_budget_bytes'], expected)
        self.assertEqual(sum(step['disk_budget_components'].values()), expected)
        self.assertEqual(cached['download_required_bytes'], 0)
        self.assertEqual(cached['disk_budget_bytes'], expected-self.editor['download_bytes'])
        self.assertEqual(cached['steps'][0]['disk_budget_components']['verification_archive_bytes'],
                         self.editor['download_bytes'])
        self.assertEqual(online['download_required_bytes'], self.editor['download_bytes'])

    def test_old_single_copy_capacity_is_rejected_and_exact_new_budget_is_allowed(self):
        old = self.editor['download_bytes'] + self.editor['extraction_budget_bytes']
        insufficient = self.plan(['godot-editor'], free_bytes=old).document()
        self.assertEqual(insufficient['issues'], ['insufficient_disk_budget'])
        self.assertTrue(insufficient['requires_manual_action'])
        enough = self.plan(['godot-editor'], free_bytes=insufficient['disk_budget_bytes']).document()
        self.assertFalse(enough['requires_manual_action'])
        self.assertFalse(enough['execution_eligible'])

    def test_reused_package_has_no_copy_budget_and_package_totals_add_up(self):
        document = self.plan().document()
        self.assertEqual(document['disk_budget_bytes'], sum(s['disk_budget_bytes'] for s in document['steps']))
        reused = self.plan(['godot-editor'], inventory={'godot-editor': self.observed()}, free_bytes=0).document()
        self.assertEqual(reused['disk_budget_bytes'], 0)
        self.assertTrue(all(value == 0 for value in reused['steps'][0]['disk_budget_components'].values()))
        self.assertFalse(reused['requires_manual_action'])

    def test_installed_reuse_install_and_explicit_update(self):
        fixtures = [
            (self.observed(), {}, "already_installed"),
            (self.observed(target="other-tools/editor", managed=False), {}, "reuse"),
            (self.observed(version="4.6-stable", target="old-managed"), {}, "install"),
            (self.observed(version="4.6-stable", target="old-managed"), {"updates": ["godot-editor"]}, "update"),
            (self.observed(version="4.6-stable", target="other-tools/editor", managed=False),
             {"updates": ["godot-editor"]}, "install"),
        ]
        for observed, options, expected in fixtures:
            with self.subTest(expected=expected, observed=observed):
                step = self.plan(["godot-editor"], inventory={"godot-editor": observed}, **options).document()["steps"][0]
                self.assertEqual(step["action"], expected)
                self.assertTrue(step["preserve_existing_installations"])
                if expected in {"reuse", "already_installed"}:
                    self.assertEqual(step["permissions"], [])
                    self.assertEqual(step["disk_budget_bytes"], 0)

    def test_changed_archive_at_existing_target_never_overwrites(self):
        step = self.plan(["godot-editor"], inventory={"godot-editor": self.observed(sha256="0" * 64)},
                         updates=["godot-editor"]).document()["steps"][0]
        self.assertEqual(step["action"], "manual_action")
        self.assertIn("target_conflict", step["reasons"])

    def test_offline_exact_cache_and_dependency_blocking(self):
        offline = self.plan(offline=True).document()
        self.assertTrue(offline["requires_manual_action"])
        self.assertIn("dependency_needs_action", offline["steps"][1]["reasons"])
        cache = [p["sha256"] for p in self.catalog["packages"].values()]
        ready = self.plan(offline=True, cached_sha256=cache).document()
        self.assertEqual(ready["download_required_bytes"], 0)
        self.assertFalse(ready["requires_manual_action"])
        self.assertFalse(ready["execution_eligible"])
        self.assertEqual(ready["steps"][0]["permissions"], ["write_workspace"])
        wrong = self.plan(offline=True, cached_sha256=["0" * 64]).document()
        self.assertIn("offline_archive_missing", wrong["steps"][0]["reasons"])

    def test_no_admin_license_platform_and_disk_require_visible_action(self):
        self.editor["requires_admin"] = True
        self.editor["license_step"] = "manual_acceptance"
        document = self.plan(platform="linux-x86_64", free_bytes=1).document()
        self.assertEqual(set(document["steps"][0]["reasons"]), {
            "unsupported_platform", "administrator_unavailable", "license_acceptance_required"})
        self.assertEqual(document["issues"], ["insufficient_disk_budget"])
        self.assertIn("administrator", document["steps"][0]["permissions"])
        self.assertEqual(self.plan(free_bytes=None).document()["issues"], ["available_disk_space_unknown"])

    def test_any_changed_source_hash_size_permission_or_context_invalidates_review(self):
        original = self.plan()
        original.require_same_reviewed_content(original.digest)
        for field, value in [("url", "https://example.com/changed.zip"), ("sha256", "1" * 64),
                             ("download_bytes", 123), ("extraction_budget_bytes", 456),
                             ("requires_admin", True), ("target", "other/tool"),
                             ("license_step", "manual_acceptance")]:
            with self.subTest(field=field):
                altered = deepcopy(self.catalog)
                altered["packages"]["godot-editor"][field] = value
                new = self.plan(catalog=altered)
                with self.assertRaisesRegex(ValueError, "new decision"):
                    new.require_same_reviewed_content(original.digest)
                self.assertIn(f"steps[0].{field}", changed_fields(original, new))
        for field in CONTEXT:
            new = self.plan(context=CONTEXT | {field: "other"})
            with self.assertRaises(ValueError):
                new.require_same_reviewed_content(original.digest)
        with self.assertRaises(ValueError):
            original.require_same_reviewed_content("yes")

    def test_dependency_conflicts_cycles_and_unknown_packages_fail_closed(self):
        for dependency in ({"missing": "1"}, {"godot-editor": "wrong"}):
            broken = deepcopy(self.catalog)
            broken["packages"]["godot-export-templates"]["dependencies"] = dependency
            with self.assertRaises(ValueError):
                self.plan(catalog=broken)
        self.editor["dependencies"] = {"godot-export-templates": "4.7.2-stable"}
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.plan()
        with self.assertRaises(ValueError):
            build_plan(["unknown"], context=CONTEXT, platform="windows-x86_64")

    def test_invalid_sources_hashes_paths_sizes_and_extra_commands_rejected(self):
        for field, bad in [("url", "http://example.com/a"), ("url", "https://user:pass@example.com/a"),
                           ("url", "https://example.com/a?token=secret"), ("sha256", "latest"),
                           ("target", "../outside"), ("target", "C:/Windows"),
                           ("target", "tools/con.zip"), ("target", "tools/package."),
                           ("version", "latest"),
                           ("download_bytes", True), ("download_bytes", -1),
                           ("extraction_budget_bytes", float("nan")), ("requires_admin", "false"),
                           ("command", "curl | shell")]:
            with self.subTest(field=field, bad=bad):
                broken = deepcopy(self.catalog)
                broken["packages"]["godot-editor"][field] = bad
                with self.assertRaises(ValueError):
                    validate_catalog(broken)
        self.catalog["packages"]["godot-export-templates"]["target"] = self.editor["target"] + "/nested"
        with self.assertRaises(ValueError):
            validate_catalog(self.catalog)

    def test_malformed_catalogue_metadata_and_dependency_record(self):
        for date in ("yesterday", "2026-02-30", "20260906"):
            with self.subTest(date=date), self.assertRaises(ValueError):
                validate_catalog(self.catalog | {"reviewed_on": date})
        self.catalog["packages"]["godot-editor"] = None
        with self.assertRaises(ValueError):
            validate_catalog(self.catalog)

    def test_unrelated_software_is_not_updated_or_included(self):
        original = self.plan()
        other = self.plan(inventory={"unrelated": self.observed(target="unrelated-folder")})
        self.assertEqual(original.digest, other.digest)
        with self.assertRaises(ValueError):
            self.plan(updates=["unrelated"])

    def test_other_package_target_collision_checks_windows_case_and_ancestors(self):
        for target in (self.editor["target"].upper().replace("/", "\\"),
                       "tools/godot-editor", self.editor["target"] + "/child"):
            with self.subTest(target=target):
                document = self.plan(inventory={"another-package": self.observed(target=target)}).document()
                self.assertIn("target_conflict", document["steps"][0]["reasons"])
                self.assertIn("dependency_needs_action", document["steps"][1]["reasons"])

    def test_invalid_or_unbounded_observations_are_not_coerced(self):
        for changes in ({"free_bytes": True}, {"free_bytes": -1}, {"offline": "false"},
                        {"context": {}}, {"inventory": []}, {"cached_sha256": ["x"]},
                        {"inventory": {"godot-editor": self.observed(managed="true")}},
                        {"inventory": {"godot-editor": {}}}, {"cached_sha256": ["0" * 64] * 65}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.plan(**changes)
        for requested in ([], "godot-editor", ["godot-editor"] * 65):
            with self.subTest(requested=requested), self.assertRaises(ValueError):
                self.plan(requested)

    def test_windows_aliases_and_opaque_locations_require_manual_resolution(self):
        targets = ["./tools/godot-editor/4.7.2-stable", "tools//godot-editor//4.7.2-stable",
                   "tools/godot-editor./4.7.2-stable", "tools/godot-editor /4.7.2-stable",
                   "tools/unused/../godot-editor/4.7.2-stable", "tools/godot-editor/4.7.2-stable/",
                   "C:/tools/godot-editor/4.7.2-stable", "//server/share", "tools/GODOT-~1/4.7.2-stable"]
        for target in targets:
            with self.subTest(target=target):
                for key in ("godot-editor", "other"):
                    result = self.plan(inventory={key: self.observed(target=target)}).document()
                    self.assertTrue(result["requires_manual_action"])
                    self.assertEqual(result["steps"][0]["action"], "manual_action")
                    self.assertIn("ambiguous_inventory_location", result["steps"][0]["reasons"])
                    self.assertFalse(result["execution_eligible"])
        result = self.plan(inventory={"other": self.observed(target="external-editor", location_kind="external_label")}).document()
        self.assertTrue(result["requires_manual_action"])


if __name__ == "__main__":
    unittest.main()
