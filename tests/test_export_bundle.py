"""Packaging a verified build, and keeping publication a separate decision."""

from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from agent_factory.export_bundle import (
    ATTRIBUTION_FILE,
    BUNDLE_MANIFEST,
    LAUNCH_FILE,
    TARGETS,
    ExportBundler,
    ExportRefused,
    ShareGate,
    attributions_from_library,
    excluded,
    scan_payload,
)


@dataclass(frozen=True)
class FakeVersion:
    version_digest: str
    source_commit: str
    artifact_checksum: str
    engine: str = "godot"
    engine_version: str = "4.3.stable.official"


@dataclass(frozen=True)
class FakeRights:
    allowed: bool
    blocking: tuple[tuple[str, str], ...] = ()


class ExportFixture(unittest.TestCase):
    """Shared helpers; no test methods are inherited by the suites below."""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.project = self.root / "game"
        (self.project / "scripts").mkdir(parents=True)
        (self.project / "project.godot").write_text("config_version=5\n", encoding="utf-8")
        (self.project / "scripts/main.gd").write_text("extends Node2D\n", encoding="utf-8")
        self.artifact = self.root / "build" / "game.x86_64"
        self.artifact.parent.mkdir(parents=True)
        self.payload = b"a playable binary"
        self.artifact.write_bytes(self.payload)
        self.version = FakeVersion(
            "v" * 64, "abc1234", hashlib.sha256(self.payload).hexdigest(),
        )
        self.bundler = ExportBundler(self.project)
        self.output = self.root / "out" / "game.zip"

    def preflight(self, target_id="linux-x86_64", **kwargs):
        return self.bundler.preflight(
            target_id=target_id, version=self.version, artifact=self.artifact, **kwargs
        )

    def build(self, preflight=None, **kwargs):
        plan = preflight or self.preflight()
        return self.bundler.build(
            plan, artifact=self.artifact, output=self.output, version=self.version,
            **kwargs,
        )


class TargetTest(ExportFixture):
    def test_unsupported_targets_are_explained_before_building(self) -> None:
        for target_id in ("ios", "console", "web"):
            with self.subTest(target=target_id):
                plan = self.preflight(target_id)
                self.assertFalse(plan.allowed)
                self.assertTrue(plan.refusals[0])
                self.assertEqual(plan.included, ())
                with self.assertRaises(ExportRefused):
                    self.build(plan)
                self.assertFalse(self.output.exists())

    def test_unknown_target_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            self.preflight("playstation-9")

    def test_supported_targets_carry_launch_instructions(self) -> None:
        for target in TARGETS.values():
            if target.supported:
                self.assertTrue(target.launch.strip(), target.target_id)
            else:
                self.assertTrue(target.reason.strip(), target.target_id)


class PreflightTest(ExportFixture):
    def test_a_clean_project_passes(self) -> None:
        plan = self.preflight()
        self.assertTrue(plan.allowed, plan.refusals + tuple(f.rule for f in plan.findings))
        self.assertIn("project.godot", plan.included)
        self.assertIn("scripts/main.gd", plan.included)

    def test_a_missing_artifact_is_refused(self) -> None:
        self.artifact.unlink()
        plan = self.preflight()
        self.assertFalse(plan.allowed)
        self.assertIn("not on disk", plan.refusals[0])

    def test_an_artifact_that_does_not_match_the_version_is_refused(self) -> None:
        self.artifact.write_bytes(b"something else entirely")
        plan = self.preflight()
        self.assertFalse(plan.allowed)
        self.assertIn("does not match the verified version", plan.refusals[0])

    def test_assets_without_rights_block_the_export(self) -> None:
        rights = FakeRights(False, (("art/found.png", "rights are unknown"),))
        plan = self.preflight(rights=rights)
        self.assertFalse(plan.allowed)
        self.assertIn("art/found.png", plan.refusals[0])

    def test_private_files_are_skipped_by_default(self) -> None:
        (self.project / ".env").write_text("TOKEN=abcdefghijkl\n", encoding="utf-8")
        (self.project / "state.db").write_bytes(b"sqlite")
        (self.project / ".lokvetia").mkdir()
        (self.project / ".lokvetia/assets.json").write_text("{}", encoding="utf-8")
        plan = self.preflight()
        skipped = {path for path, _ in plan.skipped}
        self.assertIn(".env", skipped)
        self.assertIn("state.db", skipped)
        self.assertIn(".lokvetia/assets.json", skipped)
        self.assertTrue(plan.allowed, [f.rule for f in plan.findings])

    def test_a_secret_in_an_included_file_refuses_the_package(self) -> None:
        (self.project / "scripts/config.gd").write_text(
            'const API_KEY = "sk_live_9f8a7b6c5d4e3f2a1b"\n', encoding="utf-8",
        )
        plan = self.preflight()
        self.assertFalse(plan.allowed)
        self.assertEqual(plan.findings[0].rule, "credential assignment")
        self.assertNotIn("9f8a7b6c5d4e3f2a1b", plan.findings[0].sample)
        with self.assertRaises(ExportRefused):
            self.build(plan)

    def test_a_local_home_path_refuses_the_package(self) -> None:
        (self.project / "scripts/paths.gd").write_text(
            'const OUT = "/home/miha/projects/game"\n', encoding="utf-8",
        )
        plan = self.preflight()
        self.assertFalse(plan.allowed)
        self.assertEqual(plan.findings[0].rule, "local home path")

    def test_a_secret_inside_the_built_artifact_is_caught(self) -> None:
        self.artifact.write_bytes(b"\x00\x01binary AKIAABCDEFGHIJKLMNOP tail")
        version = FakeVersion(
            "v" * 64, "abc1234",
            hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
        )
        plan = self.bundler.preflight(
            target_id="linux-x86_64", version=version, artifact=self.artifact,
        )
        self.assertFalse(plan.allowed)
        self.assertEqual(plan.findings[0].rule, "aws access key")

    def test_extra_excludes_can_drop_a_flagged_file(self) -> None:
        (self.project / "notes.txt").write_text(
            "password: hunter2hunter2\n", encoding="utf-8",
        )
        self.assertFalse(self.preflight().allowed)
        plan = self.preflight(extra_excludes=("notes.txt",))
        self.assertTrue(plan.allowed)
        self.assertIn("notes.txt", {path for path, _ in plan.skipped})


class ScanTest(unittest.TestCase):
    def test_known_secret_shapes_are_found(self) -> None:
        cases = (
            (b"-----BEGIN RSA PRIVATE KEY-----", "private key block"),
            (b"AKIAABCDEFGHIJKLMNOP", "aws access key"),
            (b"ghp_abcdefghijklmnopqrstuvwxyz012345", "github token"),
            (b"Authorization: Bearer abcdefghijklmnopqrstuvwx", "bearer token"),
            (b'client_secret="abcdefgh12345678"', "credential assignment"),
        )
        for payload, rule in cases:
            with self.subTest(rule=rule):
                findings = scan_payload("f.txt", payload)
                self.assertIn(rule, {item.rule for item in findings})

    def test_ordinary_content_is_not_flagged(self) -> None:
        payload = b"extends Node2D\n\nfunc _ready():\n    print('hello')\n"
        self.assertEqual(scan_payload("main.gd", payload), ())

    def test_samples_are_masked(self) -> None:
        finding = scan_payload("f.txt", b"AKIAABCDEFGHIJKLMNOP")[0]
        self.assertNotIn("ABCDEFGHIJKLMN", finding.sample)
        self.assertIn("...", finding.sample)

    def test_binary_content_is_scanned_without_decoding_errors(self) -> None:
        payload = b"\xff\xfe\x00binary AKIAABCDEFGHIJKLMNOP"
        self.assertTrue(scan_payload("game.bin", payload))

    def test_exclusion_patterns(self) -> None:
        self.assertTrue(excluded(".git/config", (".git/*",)))
        self.assertTrue(excluded("nested/state.db", ("*.db",)))
        self.assertFalse(excluded("scripts/main.gd", ("*.db", ".git/*")))


class BundleTest(ExportFixture):
    def test_the_package_contains_game_source_and_provenance(self) -> None:
        bundle = self.build(game_name="Collector Starter")
        self.assertEqual(len(bundle.checksum), 64)
        self.assertGreater(bundle.size_bytes, 0)
        with zipfile.ZipFile(self.output) as archive:
            names = set(archive.namelist())
            self.assertIn(BUNDLE_MANIFEST, names)
            self.assertIn(LAUNCH_FILE, names)
            self.assertIn(ATTRIBUTION_FILE, names)
            self.assertIn("game/game.x86_64", names)
            self.assertIn("source/project.godot", names)
            manifest = json.loads(archive.read(BUNDLE_MANIFEST))
            launch = archive.read(LAUNCH_FILE).decode("utf-8")
        self.assertEqual(manifest["source_commit"], "abc1234")
        self.assertEqual(manifest["artifact_checksum"], self.version.artifact_checksum)
        self.assertEqual(manifest["engine_version"], "4.3.stable.official")
        self.assertFalse(manifest["published"])
        self.assertIn("Collector Starter", launch)
        self.assertIn(self.version.artifact_checksum, launch)

    def test_attributions_are_written_into_the_package(self) -> None:
        credits = ({
            "asset": "art/hero.png", "licence_id": "CC-BY-4.0",
            "attribution": "A. Artist", "source": "https://example.invalid",
        },)
        plan = self.preflight(attributions=credits)
        self.build(plan)
        with zipfile.ZipFile(self.output) as archive:
            text = archive.read(ATTRIBUTION_FILE).decode("utf-8")
        self.assertIn("A. Artist", text)
        self.assertIn("CC-BY-4.0", text)

    def test_an_asset_library_supplies_the_required_credits(self) -> None:
        from agent_factory.asset_provenance import (
            AssetCandidate, AssetLibrary, AssetProvenance,
        )
        import struct

        def png() -> bytes:
            return (
                b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
                + struct.pack(">II", 8, 8) + b"\x08\x06\x00\x00\x00" + b"\x00" * 16
            )

        library = AssetLibrary(self.root / "assets-project")
        for name, provenance in (
            ("art/credited.png", AssetProvenance.create(
                source="https://example.invalid", licence_id="CC-BY-4.0",
                attribution="A. Artist",
            )),
            ("art/owned.png", AssetProvenance.create(source="in-house", licence_id="owned")),
        ):
            candidate = AssetCandidate(name, png(), provenance)
            library.apply(library.plan([candidate]), [candidate])
        credits = attributions_from_library(library)
        self.assertEqual([item["asset"] for item in credits], ["art/credited.png"])

    def test_no_attribution_says_so_plainly(self) -> None:
        self.build()
        with zipfile.ZipFile(self.output) as archive:
            text = archive.read(ATTRIBUTION_FILE).decode("utf-8")
        self.assertIn("no assets that require attribution", text)


class ShareTest(ExportFixture):
    def setUp(self) -> None:
        super().setUp()
        self.bundle = self.build()
        self.published: list[tuple[str, str, str]] = []

    def publisher(self, bundle, destination, visibility) -> str:
        self.published.append((bundle.checksum, destination, visibility))
        return f"{destination}/{bundle.checksum[:8]}"

    def test_a_preview_performs_nothing(self) -> None:
        gate = ShareGate(publisher=self.publisher)
        preview = gate.prepare(
            self.bundle, destination="https://example.invalid/games", visibility="unlisted",
        )
        self.assertTrue(preview.allowed)
        self.assertFalse(preview.record["performed"])
        self.assertIn("a named human approver", preview.requires)
        self.assertEqual(self.published, [])

    def test_cancelling_changes_no_external_state(self) -> None:
        gate = ShareGate(publisher=self.publisher)
        preview = gate.prepare(
            self.bundle, destination="https://example.invalid/games", visibility="public",
        )
        decision = gate.decide(preview, decision="cancel", actor="miha")
        self.assertEqual(decision.outcome, "cancelled")
        self.assertFalse(decision.external_state_changed)
        self.assertIn("before any external call was made", decision.reason)
        self.assertEqual(self.published, [])

    def test_publishing_requires_a_named_approver(self) -> None:
        gate = ShareGate(publisher=self.publisher)
        preview = gate.prepare(
            self.bundle, destination="https://example.invalid/games", visibility="public",
        )
        with self.assertRaises(ValueError):
            gate.decide(preview, decision="approve", actor="   ", bundle=self.bundle)
        self.assertEqual(self.published, [])

    def test_without_a_publisher_nothing_is_published(self) -> None:
        gate = ShareGate()
        preview = gate.prepare(
            self.bundle, destination="https://example.invalid/games", visibility="public",
        )
        self.assertIn("a configured publisher; none is connected", preview.requires)
        decision = gate.decide(
            preview, decision="approve", actor="miha", bundle=self.bundle,
        )
        self.assertEqual(decision.outcome, "refused")
        self.assertFalse(decision.external_state_changed)

    def test_assets_without_rights_block_publication(self) -> None:
        gate = ShareGate(publisher=self.publisher)
        preview = gate.prepare(
            self.bundle, destination="https://example.invalid/games",
            visibility="public", rights=FakeRights(False, (("art/x.png", "unknown"),)),
        )
        self.assertFalse(preview.allowed)
        decision = gate.decide(
            preview, decision="approve", actor="miha", bundle=self.bundle,
        )
        self.assertEqual(decision.outcome, "refused")
        self.assertEqual(self.published, [])

    def test_an_approved_publication_calls_the_publisher_once(self) -> None:
        gate = ShareGate(publisher=self.publisher)
        preview = gate.prepare(
            self.bundle, destination="https://example.invalid/games", visibility="unlisted",
        )
        decision = gate.decide(
            preview, decision="approve", actor="miha", bundle=self.bundle,
        )
        self.assertEqual(decision.outcome, "published")
        self.assertTrue(decision.external_state_changed)
        self.assertEqual(len(self.published), 1)
        self.assertEqual(self.published[0][2], "unlisted")

    def test_a_different_package_cannot_ride_an_approved_preview(self) -> None:
        gate = ShareGate(publisher=self.publisher)
        preview = gate.prepare(
            self.bundle, destination="https://example.invalid/games", visibility="public",
        )
        other = ExportBundle_clone(self.bundle)
        with self.assertRaises(ExportRefused):
            gate.decide(preview, decision="approve", actor="miha", bundle=other)
        self.assertEqual(self.published, [])

    def test_visibility_and_destination_are_validated(self) -> None:
        gate = ShareGate(publisher=self.publisher)
        with self.assertRaises(ValueError):
            gate.prepare(self.bundle, destination="x", visibility="everyone")
        preview = gate.prepare(self.bundle, destination="  ", visibility="public")
        self.assertFalse(preview.allowed)
        self.assertIn("destination is required", preview.reason)

    def test_an_unknown_decision_is_refused(self) -> None:
        gate = ShareGate(publisher=self.publisher)
        preview = gate.prepare(self.bundle, destination="d", visibility="public")
        with self.assertRaises(ValueError):
            gate.decide(preview, decision="maybe", actor="miha")


def ExportBundle_clone(bundle):
    from dataclasses import replace

    return replace(bundle, checksum="f" * 64)


if __name__ == "__main__":
    unittest.main()
