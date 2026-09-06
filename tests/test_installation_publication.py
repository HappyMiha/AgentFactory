from dataclasses import FrozenInstanceError
import multiprocessing
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_factory.installation_archive import ArchiveRejected
from agent_factory.installation_manifest import manifest_for_stage
from agent_factory.installation_publication import (
    PublicationReceipt, prepare_publication, publish_staged, observe_publication,
)
import test_installation_archive as fixture


def _publish_child(staged, parent, snapshot, queue, proceed, mode):
    from agent_factory import installation_publication as module
    receipt = PublicationReceipt(snapshot)
    def authorize(expected):
        queue.put('prepared')
        if not proceed.wait(20):
            raise TimeoutError()
        return True
    original = module._rename_new_directory
    def renamed(source, target):
        original(source, target)
        queue.put('renamed')
        # The parent terminates this real process to simulate lost completion.
        proceed.clear()
        proceed.wait(20)
    try:
        with patch.object(module, '_rename_new_directory', renamed if mode == 'after' else original):
            publish_staged(staged, parent=parent, expected=receipt, authorize=authorize)
        queue.put('published')
    except FileExistsError:
        queue.put('conflict')
    except Exception as error:
        queue.put(type(error).__name__)


class InstallationPublicationTests(unittest.TestCase):
    setUp = fixture.InstallationArchiveTests.setUp
    archive = fixture.InstallationArchiveTests.archive
    catalog = fixture.InstallationArchiveTests.catalog
    stage = fixture.InstallationArchiveTests.stage
    assert_clean = fixture.InstallationArchiveTests.assert_clean

    def receipt(self, staged, **changes):
        return prepare_publication(staged, **({'operation_identity': 'fixture-operation',
            'request_digest': 'a'*64, 'target_name': 'installed'} | changes))

    def publish(self, staged, receipt, **changes):
        return publish_staged(staged, **({'parent': self.root, 'expected': receipt,
            'authorize': lambda expected: True} | changes))

    def test_receipt_is_bounded_immutable_and_bound_to_original_stage(self):
        with self.stage(self.archive()) as staged:
            receipt = self.receipt(staged)
            self.assertEqual(PublicationReceipt(receipt.snapshot).digest, receipt.digest)
            with self.assertRaises(FrozenInstanceError): receipt.snapshot = '{}'
            for changes in ({'target_name': '../outside'}, {'target_name': 'con'},
                            {'request_digest': 'bad'}, {'operation_identity': 'bad\nvalue'}):
                with self.assertRaises(ValueError): self.receipt(staged, **changes)
            self.assertNotEqual(self.receipt(staged, operation_identity='another').digest, receipt.digest)
            (staged.directory/'folder/game.txt').write_bytes(b'evil')
            with self.assertRaises(ArchiveRejected): self.receipt(staged)
        self.assert_clean()

    def test_observer_requires_external_receipt_and_complete_exact_envelope(self):
        # Portable observation fixture, not a Windows publication claim.
        import shutil
        with self.stage(self.archive()) as staged:
            receipt = self.receipt(staged)
            self.assertEqual(observe_publication(self.root, receipt)['state'], 'absent')
            target = self.root/'installed'; target.mkdir()
            shutil.copytree(staged.directory, target/'payload')
            (target/'receipt.json').write_text(receipt.snapshot, encoding='utf-8')
            self.assertEqual(observe_publication(self.root, receipt)['state'], 'matched')
            other = self.receipt(staged, operation_identity='another')
            self.assertEqual(observe_publication(self.root, other)['state'], 'conflict')
            (target/'extra').mkdir()
            self.assertEqual(observe_publication(self.root, receipt)['state'], 'conflict')
            (target/'extra').rmdir()
            (target/'payload/folder/game.txt').write_bytes(b'evil')
            self.assertEqual(observe_publication(self.root, receipt)['state'], 'conflict')
        self.assert_clean()

    @unittest.skipIf(os.name == 'nt', 'Actual unsupported-platform test')
    def test_posix_publication_denies_before_authorization_or_writes(self):
        with self.stage(self.archive()) as staged:
            receipt = self.receipt(staged)
            with self.assertRaises(NotImplementedError):
                self.publish(staged, receipt, authorize=lambda _: self.fail('Must not authorize'))
            self.assertFalse((self.root/'installed').exists())
        self.assert_clean()

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows no-overwrite publication')
    def test_publication_survives_stage_cleanup_and_never_overwrites(self):
        with self.stage(self.archive(entries=(('Folder/game.txt', b'game'), ('empty/', b'')))) as staged:
            receipt = self.receipt(staged)
            result = self.publish(staged, receipt)
            self.assertEqual(result['state'], 'matched')
            self.assertFalse(result['execution_eligible'])
            self.assertEqual(manifest_for_stage(staged).document(), receipt.document()['manifest'])
            with self.assertRaises(FileExistsError):
                self.publish(staged, receipt, authorize=lambda _: self.fail('Must not consume again'))
        self.assert_clean()
        self.assertEqual(observe_publication(self.root, receipt)['state'], 'matched')
        self.assertEqual((self.root/'installed/payload/Folder/game.txt').read_bytes(), b'game')

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows publication failures')
    def test_denied_authority_capacity_and_existing_empty_target_preserve_data(self):
        import shutil
        with self.stage(self.archive()) as staged:
            receipt = self.receipt(staged)
            for answer in (False, None, 1):
                with self.assertRaises(PermissionError): self.publish(staged, receipt, authorize=lambda _: answer)
            self.assertFalse((self.root/'installed').exists())
            actual = shutil.disk_usage(self.root)
            with patch('agent_factory.installation_publication.shutil.disk_usage', return_value=actual._replace(free=0)):
                with self.assertRaises(ArchiveRejected): self.publish(staged, receipt)
            (self.root/'installed').mkdir()
            with self.assertRaises(FileExistsError): self.publish(staged, receipt)
            self.assertEqual(list((self.root/'installed').iterdir()), [])
        self.assert_clean()
        self.assertFalse(list(self.root.glob('af-publish-*')))

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows no-replace race')
    def test_late_competing_target_is_not_replaced_even_when_empty(self):
        with self.stage(self.archive()) as staged:
            receipt = self.receipt(staged)
            def competing(_):
                (self.root/'installed').mkdir()
                return True
            with self.assertRaises(FileExistsError): self.publish(staged, receipt, authorize=competing)
            self.assertEqual(list((self.root/'installed').iterdir()), [])
        self.assert_clean()

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows filesystem failure')
    def test_write_failure_cleans_only_private_staging(self):
        with self.stage(self.archive()) as staged:
            receipt = self.receipt(staged)
            with patch('agent_factory.installation_publication.os.fsync', side_effect=OSError('disk full')):
                with self.assertRaises(OSError): self.publish(staged, receipt)
            self.assertFalse((self.root/'installed').exists())
        self.assert_clean()
        self.assertFalse(list(self.root.glob('af-publish-*')))

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows changed-source rejection')
    def test_changed_stage_cannot_publish_with_old_receipt(self):
        with self.stage(self.archive()) as staged:
            receipt = self.receipt(staged)
            (staged.directory/'folder/game.txt').write_bytes(b'evil')
            with self.assertRaises(ArchiveRejected):
                self.publish(staged, receipt, authorize=lambda _: self.fail('Must not authorize'))
            self.assertFalse((self.root/'installed').exists())
        self.assert_clean()

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows junction path rejection')
    def test_linked_parent_does_not_touch_neighbour(self):
        import subprocess
        neighbour = self.root/'neighbour'; neighbour.mkdir()
        sentinel = neighbour/'keep.txt'; sentinel.write_bytes(b'keep')
        link = self.root/'linked'
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(neighbour)],
            check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with self.stage(self.archive()) as staged:
                receipt = self.receipt(staged)
                with self.assertRaises(ArchiveRejected): self.publish(staged, receipt, parent=link)
                self.assertEqual(observe_publication(link, receipt)['state'], 'indeterminate')
                self.assertFalse((neighbour/'installed').exists())
                self.assertEqual(sentinel.read_bytes(), b'keep')
        finally:
            link.rmdir()  # Remove the junction itself, never its target tree.
        self.assert_clean()

    @unittest.skipUnless(os.name == 'nt', 'Actual spawned Windows publishers')
    def test_two_processes_publish_at_most_one_complete_envelope(self):
        context = multiprocessing.get_context('spawn')
        queue = context.Queue(); proceed = context.Event()
        with self.stage(self.archive()) as staged:
            receipt = self.receipt(staged)
            processes = [context.Process(target=_publish_child,
                args=(staged, self.root, receipt.snapshot, queue, proceed, 'race')) for _ in range(2)]
            try:
                for process in processes: process.start()
                self.assertEqual([queue.get(timeout=20), queue.get(timeout=20)], ['prepared', 'prepared'])
                proceed.set()
                self.assertEqual(sorted([queue.get(timeout=20), queue.get(timeout=20)]), ['conflict', 'published'])
                for process in processes:
                    process.join(10); self.assertEqual(process.exitcode, 0)
            finally:
                for process in processes:
                    if process.is_alive(): process.terminate(); process.join(10)
                queue.close(); queue.join_thread()
            self.assertEqual(observe_publication(self.root, receipt)['state'], 'matched')
        self.assert_clean()

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows process interruption')
    def test_process_kill_before_and_after_rename_is_observable_without_retry(self):
        context = multiprocessing.get_context('spawn')
        for mode in ('before', 'after'):
            with self.subTest(mode=mode), self.stage(self.archive()) as staged:
                receipt = self.receipt(staged, target_name=mode)
                queue = context.Queue(); proceed = context.Event()
                process = context.Process(target=_publish_child,
                    args=(staged, self.root, receipt.snapshot, queue, proceed, mode))
                try:
                    process.start(); self.assertEqual(queue.get(timeout=20), 'prepared')
                    if mode == 'after':
                        proceed.set(); self.assertEqual(queue.get(timeout=20), 'renamed')
                    process.terminate(); process.join(10)
                    self.assertFalse(process.is_alive())
                finally:
                    if process.is_alive(): process.terminate(); process.join(10)
                    queue.close(); queue.join_thread()
                self.assertEqual(observe_publication(self.root, receipt)['state'],
                    'absent' if mode == 'before' else 'matched')
                self.assertTrue(list(self.root.glob('af-publish-*')))  # No ownership-based cleanup yet.
        self.assert_clean()


if __name__ == '__main__': unittest.main()
