"""What was downloaded, and whether it is what was published."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from agent_factory.distribution import (
    Artifact,
    DistributionRefused,
    Release,
    build_release,
    describe,
    load_release,
    verify,
    tried_platforms,
    verify_all,
    write_manifest,
)
from agent_factory.localisation import LANGUAGES, Message


class ArtifactTests(unittest.TestCase):
    def test_a_checksum_that_is_not_a_checksum_is_refused(self):
        with self.assertRaises(DistributionRefused) as caught:
            Artifact("core.whl", 10, "probably-fine")
        self.assertIn("64 hexadecimal", caught.exception.text("en"))

    def test_a_published_file_has_a_size(self):
        with self.assertRaises(ValueError):
            Artifact("core.whl", 0, "a" * 64)


class ReleaseTests(unittest.TestCase):
    def release(self, **rest):
        options = {
            "version": "0.2.0",
            "artifacts": (Artifact("core.whl", 10, "a" * 64),),
            "tried_on": ("linux",),
        }
        options.update(rest)
        return Release(**options)

    def test_a_version_that_is_not_a_version_is_refused(self):
        with self.assertRaises(DistributionRefused) as caught:
            self.release(version="latest")
        self.assertIn("latest", caught.exception.text("en"))

    def test_a_release_with_no_file_has_nothing_to_install(self):
        with self.assertRaises(DistributionRefused):
            self.release(artifacts=())

    def test_an_unknown_operating_system_is_refused(self):
        with self.assertRaises(DistributionRefused):
            self.release(tried_on=("plan9",))

    def test_a_system_it_was_tried_on_says_so(self):
        self.assertIn("tried on linux", self.release().platform_note("linux").text("en"))

    def test_a_system_it_was_not_tried_on_does_not_pretend(self):
        note = self.release().platform_note("windows").text("en")
        self.assertIn("not been tried", note)
        self.assertIn("we have not checked", note)

    def test_every_supported_system_is_described_either_way(self):
        record = self.release().record("en")
        self.assertEqual(set(record["platforms"]), {"windows", "macos", "linux"})

    def test_a_checksum_is_never_presented_as_a_signature(self):
        record = self.release().record("en")
        self.assertIn("does not prove who published", record["checksums_are_not_a_signature"])

    def test_the_release_reads_in_both_languages(self):
        for language in LANGUAGES:
            self.assertTrue(self.release().record(language)["python"])
        self.assertNotEqual(
            self.release().record("uk")["python"],
            self.release().record("en")["python"])

    def test_a_manifest_round_trips(self):
        original = self.release(notes=Message("Перший реліз.", "First release."))
        restored = load_release(original.manifest())
        self.assertEqual(restored.version, original.version)
        self.assertEqual(restored.artifacts, original.artifacts)
        self.assertEqual(restored.notes.text("en"), "First release.")

    def test_an_unsupported_manifest_schema_is_refused(self):
        with self.assertRaises(ValueError):
            load_release({"schema_version": 99, "version": "0.2.0", "artifacts": []})

    def test_describe_says_whether_this_very_system_was_tried(self):
        described = describe(self.release(), platform="windows", language="en")
        self.assertFalse(described["tried_here"])
        self.assertIn("not been tried", described["platform_note"])


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name)

    def publish(self, content=b"a wheel, more or less", name="core.whl", **rest):
        path = self.directory / name
        path.write_bytes(content)
        return build_release("0.2.0", [path], **rest), path

    def test_a_release_is_described_by_reading_the_files_not_by_being_told(self):
        release, path = self.publish()
        artifact = release.artifacts[0]
        self.assertEqual(artifact.size_bytes, path.stat().st_size)
        self.assertEqual(
            artifact.sha256, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_an_untouched_download_verifies(self):
        release, _ = self.publish()
        result = verify(release, self.directory, "core.whl")
        self.assertTrue(result.matches)
        self.assertIn("matches what was published", result.summary.text("en"))

    def test_a_missing_file_is_refused(self):
        release, path = self.publish()
        path.unlink()
        with self.assertRaises(DistributionRefused) as caught:
            verify(release, self.directory, "core.whl")
        self.assertIn("missing", caught.exception.text("en"))

    def test_a_file_of_the_wrong_size_is_refused_before_it_is_hashed(self):
        release, path = self.publish()
        path.write_bytes(b"something else entirely, and longer")
        with self.assertRaises(DistributionRefused) as caught:
            verify(release, self.directory, "core.whl")
        self.assertIn("is not that file", caught.exception.text("en"))

    def test_a_file_of_the_right_size_but_wrong_content_is_refused(self):
        release, path = self.publish()
        same_length = b"X" * path.stat().st_size
        path.write_bytes(same_length)
        with self.assertRaises(DistributionRefused) as caught:
            verify(release, self.directory, "core.whl")
        self.assertIn("Do not install it", caught.exception.text("en"))

    def test_the_refusal_names_both_checksums(self):
        release, path = self.publish()
        path.write_bytes(b"Y" * path.stat().st_size)
        message = None
        try:
            verify(release, self.directory, "core.whl")
        except DistributionRefused as refused:
            message = refused.text("en")
        self.assertIsNotNone(message)
        self.assertIn(release.artifacts[0].sha256[:12], message)

    def test_every_published_file_is_checked(self):
        first = self.directory / "core.whl"
        first.write_bytes(b"one")
        second = self.directory / "core.tar.gz"
        second.write_bytes(b"two")
        release = build_release("0.2.0", [first, second])
        self.assertEqual(len(verify_all(release, self.directory)), 2)

    def test_a_manifest_written_next_to_the_files_can_verify_them(self):
        release, _ = self.publish(tried_on=("linux",))
        path = write_manifest(release, self.directory / "distribution.json")
        restored = load_release(json.loads(path.read_text(encoding="utf-8")))
        self.assertTrue(verify(restored, self.directory, "core.whl").matches)

    def test_describing_a_file_that_does_not_exist_is_refused(self):
        with self.assertRaises(DistributionRefused):
            build_release("0.2.0", [self.directory / "nothing.whl"])

    def test_an_unknown_file_name_is_refused_rather_than_invented(self):
        release, _ = self.publish()
        with self.assertRaises(KeyError):
            verify(release, self.directory, "somebody-elses.whl")



class TriedPlatformTests(unittest.TestCase):
    """A release claims a system only when something was actually done there."""

    def test_building_without_installing_claims_nothing(self):
        self.assertEqual(
            tried_platforms((), install_checked=False, here="linux"), ())

    def test_installing_the_wheel_here_claims_this_system(self):
        self.assertEqual(
            tried_platforms((), install_checked=True, here="linux"), ("linux",))

    def test_a_system_someone_tested_by_hand_is_kept(self):
        self.assertEqual(
            tried_platforms(("windows",), install_checked=True, here="linux"),
            ("windows", "linux"))

    def test_the_same_system_is_not_listed_twice(self):
        self.assertEqual(
            tried_platforms(("linux", "linux"), install_checked=True, here="linux"),
            ("linux",))

    def test_a_system_that_does_not_exist_is_refused(self):
        with self.assertRaises(DistributionRefused):
            tried_platforms(("plan9",), install_checked=True, here="linux")

    def test_an_unknown_build_machine_claims_nothing_for_itself(self):
        self.assertEqual(
            tried_platforms(("linux",), install_checked=True, here="haiku"),
            ("linux",))


if __name__ == "__main__":
    unittest.main()
