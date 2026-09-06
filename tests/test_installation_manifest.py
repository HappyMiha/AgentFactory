from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_factory.installation_manifest import manifest_for_stage, observe_manifest, InstallationManifest
from agent_factory.installation_archive import ArchiveRejected
import test_installation_archive as fixture


class InstallationManifestTests(unittest.TestCase):
    setUp = fixture.InstallationArchiveTests.setUp
    archive = fixture.InstallationArchiveTests.archive
    catalog = fixture.InstallationArchiveTests.catalog
    stage = fixture.InstallationArchiveTests.stage
    assert_clean = fixture.InstallationArchiveTests.assert_clean

    def test_verified_stage_hashes_and_reopened_manifest_match_without_authority(self):
        catalog=self.archive()
        with self.stage(catalog) as staged:
            manifest=manifest_for_stage(staged)
            document=manifest.document()
            self.assertEqual(document['total_bytes'],10)
            self.assertEqual(len(document['files']),2)
            self.assertEqual(document['archive_sha256'],staged.sha256)
            self.assertEqual(observe_manifest(staged.directory,manifest)['state'],'matched')
            self.assertFalse(observe_manifest(staged.directory,manifest)['execution_eligible'])
            reopened=InstallationManifest(manifest.snapshot)
            self.assertEqual(reopened.digest,manifest.digest)
            self.assertEqual(observe_manifest(staged.directory,reopened)['state'],'matched')
            document['files'].clear(); self.assertEqual(len(manifest.document()['files']),2)
            with self.assertRaises(FrozenInstanceError): manifest.snapshot='{}'
        self.assert_clean()

    def test_same_size_content_change_missing_and_additional_files_do_not_match(self):
        for change in ('bytes','missing','extra','empty-directory'):
            with self.subTest(change=change), self.stage(self.archive()) as staged:
                manifest=manifest_for_stage(staged)
                target=staged.directory/'folder/game.txt'
                if change=='bytes': target.write_bytes(b'evil')
                if change=='missing': target.unlink()
                if change=='extra': (staged.directory/'extra').write_bytes(b'')
                if change=='empty-directory': (staged.directory/'extra').mkdir()
                self.assertEqual(observe_manifest(staged.directory,manifest)['state'],'conflict')
        self.assert_clean()

    def test_absent_and_oversized_content_never_match(self):
        with self.stage(self.archive()) as staged:
            manifest=manifest_for_stage(staged)
            self.assertEqual(observe_manifest(self.root/'not-created'/'target',manifest)['state'],'absent')
            (staged.directory/'folder/game.txt').write_bytes(b'x'*100)
            self.assertEqual(observe_manifest(staged.directory,manifest)['state'],'indeterminate')
        self.assert_clean()

    def test_stage_inventory_substitution_cannot_create_manifest(self):
        with self.stage(self.archive()) as staged:
            (staged.directory/'extra').write_bytes(b'')
            with self.assertRaises(ArchiveRejected): manifest_for_stage(staged)
        self.assert_clean()

    def test_same_size_stage_tamper_cannot_borrow_verified_archive_identity(self):
        with self.stage(self.archive()) as staged:
            (staged.directory/'folder/game.txt').write_bytes(b'evil')
            with self.assertRaises(ArchiveRejected): manifest_for_stage(staged)
        self.assert_clean()

    def test_empty_directory_stage_tamper_cannot_borrow_archive_identity(self):
        with self.stage(self.archive()) as staged:
            (staged.directory/'extra').mkdir()
            with self.assertRaises(ArchiveRejected): manifest_for_stage(staged)
        self.assert_clean()

    def test_read_failure_and_mid_read_mutation_are_indeterminate(self):
        with self.stage(self.archive()) as staged:
            manifest=manifest_for_stage(staged)
            with patch('agent_factory.installation_manifest._regular_source',side_effect=PermissionError('private path')):
                self.assertEqual(observe_manifest(staged.directory,manifest),{'state':'indeterminate','execution_eligible':False})
            actual_fstat=os.fstat; calls={}
            def changing(fd):
                info=actual_fstat(fd); calls[fd]=calls.get(fd,0)+1
                if calls[fd]==3:
                    class Changed:
                        st_size=info.st_size
                        st_mtime_ns=info.st_mtime_ns+1
                        st_ctime_ns=info.st_ctime_ns
                    return Changed()
                return info
            with patch('agent_factory.installation_manifest.os.fstat',changing):
                self.assertEqual(observe_manifest(staged.directory,manifest)['state'],'indeterminate')
        self.assert_clean()

    def test_malformed_or_noncanonical_saved_manifest_is_rejected(self):
        with self.stage(self.archive()) as staged:
            manifest=manifest_for_stage(staged)
        with self.assertRaises(ValueError): InstallationManifest('{}')
        with self.assertRaises(ValueError): InstallationManifest(manifest.snapshot+' ')
        for field,value in (('schema_version',True),('total_bytes',-1),('total_bytes',True),('paths',['../outside']),('archive_sha256','bad')):
            document=manifest.document(); document[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                InstallationManifest(json.dumps(document,sort_keys=True,separators=(',',':')))

    @unittest.skipUnless(hasattr(os,'mkfifo'),'POSIX FIFO is unavailable on this platform')
    def test_actual_fifo_and_symlink_are_not_followed(self):
        with self.stage(self.archive()) as staged:
            manifest=manifest_for_stage(staged)
            fifo=staged.directory/'pipe'; os.mkfifo(fifo)
            self.assertEqual(observe_manifest(staged.directory,manifest)['state'],'indeterminate')
            fifo.unlink()
            link=staged.directory/'linked'; link.symlink_to(self.neighbour)
            self.assertEqual(observe_manifest(staged.directory,manifest)['state'],'indeterminate')
            link.unlink()
            outside=self.root/'outside-link'; outside.symlink_to(self.parent,target_is_directory=True)
            self.assertEqual(observe_manifest(outside/'missing',manifest)['state'],'indeterminate')
            outside.unlink()
        self.assert_clean()


if __name__=='__main__': unittest.main()
