"""Real disposable archives, filesystem failures and untouched-neighbour checks."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from agent_factory.installation_archive import ArchiveRejected, stage_verified_zip
from agent_factory.installation_plan import load_catalog


class InstallationArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / 'staging'; self.parent.mkdir()
        self.neighbour = self.parent / 'existing.txt'; self.neighbour.write_bytes(b'keep')
        self.source = self.root / 'source.zip'

    def archive(self, entries=(('folder/game.txt', b'game'), ('LICENSE.txt', b'notice')),
                compression=zipfile.ZIP_DEFLATED):
        with zipfile.ZipFile(self.source, 'w', compression=compression) as archive:
            for name, content in entries:
                archive.writestr(name, content)
        return self.catalog()

    def catalog(self):
        catalog = load_catalog()
        package = catalog['packages']['godot-editor']
        data = self.source.read_bytes()
        package.update(download_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                       extraction_budget_bytes=1024 * 1024)
        return catalog

    def stage(self, catalog):
        return stage_verified_zip(self.source, catalog=catalog, package_id='godot-editor',
                                  staging_parent=self.parent)

    def assert_clean(self):
        self.assertEqual(self.neighbour.read_bytes(), b'keep')
        self.assertEqual(list(self.parent.iterdir()), [self.neighbour])

    def test_verified_content_is_temporary_and_source_and_neighbours_unchanged(self):
        catalog = self.archive(); original = self.source.read_bytes()
        with self.stage(catalog) as result:
            self.assertEqual(result.extracted_bytes, 10)
            self.assertEqual(result.files, ('folder/game.txt', 'LICENSE.txt'))
            self.assertEqual((result.directory/'folder/game.txt').read_bytes(), b'game')
            self.assertEqual(result.sha256, catalog['packages']['godot-editor']['sha256'])
            directory = result.directory
        self.assertFalse(directory.exists())
        self.assertEqual(self.source.read_bytes(), original)
        self.assert_clean()

    def test_repeated_staging_is_isolated_and_does_not_publish(self):
        catalog = self.archive()
        with self.stage(catalog) as first, self.stage(catalog) as second:
            self.assertNotEqual(first.directory, second.directory)
            self.assertEqual(first.files, second.files)
        self.assert_clean()

    def test_size_and_hash_mismatch_fail_before_zip_parsing(self):
        for change in ('larger', 'shorter', 'hash'):
            with self.subTest(change=change):
                catalog = self.archive(); package = catalog['packages']['godot-editor']
                if change == 'hash': package['sha256'] = '0'*64
                else: package['download_bytes'] += 1 if change == 'larger' else -1
                with patch('agent_factory.installation_archive.zipfile.ZipFile', side_effect=AssertionError('parsed')):
                    with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
                self.assert_clean()

    def test_unsafe_windows_names_never_escape_staging(self):
        for name in ('../escape', '/escape', 'C:/escape', 'a\\escape', 'a//b', 'a/./b',
                     'file:stream', 'CON.txt', 'aux/x', 'COM1', 'folder./a', 'folder /a',
                     ' space', 'x~1', 'a\tname', 'unicode-é'):
            with self.subTest(name=name):
                # ZipInfo normalizes Windows backslashes at creation. Replace the
                # bytes afterwards so the fixture actually contains that path.
                catalog = self.archive(((name.replace('\\', '/'), b'x'),))
                if '\\' in name:
                    data = self.source.read_bytes().replace(name.replace('\\', '/').encode(), name.encode())
                    self.source.write_bytes(data); catalog = self.catalog()
                with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
                self.assertFalse((self.root/'escape').exists())
                self.assert_clean()

    def test_duplicates_case_aliases_and_file_directory_conflicts(self):
        for names in (('File', 'file'), ('same', 'same'), ('a', 'a/child'), ('A/b', 'a'), ('A/b', 'a/c')):
            with self.subTest(names=names):
                with patch('warnings.warn'):
                    catalog = self.archive(tuple((name, b'x') for name in names))
                with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
                self.assert_clean()

    def test_links_devices_and_directory_data_are_rejected(self):
        for mode, name, content in ((stat.S_IFLNK, 'link', b'../../other'),
                                    (stat.S_IFCHR, 'device', b''),
                                    (stat.S_IFDIR, 'dir/', b'data')):
            with self.subTest(mode=mode):
                info = zipfile.ZipInfo(name); info.create_system = 3
                info.external_attr = (mode | 0o755) << 16
                catalog = self.archive(((info, content),))
                with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
                self.assert_clean()

    def test_extraction_budget_rejected_before_content_writes(self):
        catalog = self.archive((('large', b'A' * 8192),))
        catalog['packages']['godot-editor']['extraction_budget_bytes'] = 8191
        with patch('zipfile.ZipFile.open', side_effect=AssertionError('entry opened')):
            with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
        self.assert_clean()

    def test_crc_failure_cleans_partially_written_content(self):
        self.archive((('first', b'good'), ('second', b'bad-payload')), compression=zipfile.ZIP_STORED)
        data = self.source.read_bytes().replace(b'bad-payload', b'bad-payloae')
        self.source.write_bytes(data); catalog = self.catalog()
        with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
        self.assert_clean()

    def test_disk_capacity_and_write_failure_preserve_neighbours(self):
        catalog = self.archive()
        with patch('agent_factory.installation_archive.shutil.disk_usage') as usage:
            usage.return_value.free = 0
            with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
        real_open = Path.open
        @contextmanager
        def failing_open(path, *args, **kwargs):
            if path.name == 'game.txt': raise OSError('injected disk full')
            with real_open(path, *args, **kwargs) as handle: yield handle
        with patch.object(Path, 'open', failing_open):
            with self.assertRaises(OSError), self.stage(catalog): pass
        self.assert_clean()

    def test_caller_failure_removes_only_own_temporary_content(self):
        catalog = self.archive()
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            with self.stage(catalog): raise RuntimeError('interrupted')
        self.assert_clean()

    def test_bounds_are_checked_before_central_directory_allocation(self):
        for field, value in ((3, 8193), (4, 8193), (5, 5*1024*1024), (1, 1), (6, 0xffffffff)):
            with self.subTest(field=field):
                self.archive(); data = self.source.read_bytes()
                values = list(struct.unpack('<4s4H2LH', data[-22:])); values[field] = value
                self.source.write_bytes(data[:-22] + struct.pack('<4s4H2LH', *values))
                with patch('agent_factory.installation_archive.zipfile.ZipFile', side_effect=AssertionError('parsed')):
                    with self.assertRaises(ArchiveRejected), self.stage(self.catalog()): pass
                self.assert_clean()

    def test_empty_prefixed_trailing_and_truncated_archives_are_rejected(self):
        for kind in ('empty', 'prefix', 'trailing', 'truncated'):
            with self.subTest(kind=kind):
                self.archive(() if kind == 'empty' else (('game', b'x'),))
                data = self.source.read_bytes()
                if kind == 'prefix': data = b'prefix' + data
                if kind == 'trailing': data += b'trailer'
                if kind == 'truncated': data = data[:-10]
                self.source.write_bytes(data)
                with self.assertRaises(ArchiveRejected), self.stage(self.catalog()): pass
                self.assert_clean()

    def test_unreviewed_package_cannot_stage(self):
        catalog = self.archive()
        with self.assertRaises(ArchiveRejected):
            with stage_verified_zip(self.source, catalog=catalog, package_id='missing', staging_parent=self.parent): pass
        self.assert_clean()

    def test_nul_names_and_encrypted_entries_are_rejected(self):
        for kind in ('nul', 'encrypted'):
            with self.subTest(kind=kind):
                self.archive((('bad-name', b'x'),))
                data = bytearray(self.source.read_bytes())
                if kind == 'nul': data = data.replace(b'bad-name', b'bad\0name')
                else:
                    central = data.index(b'PK\x01\x02')
                    data[central + 8] |= 1
                    data[6] |= 1
                self.source.write_bytes(data)
                with self.assertRaises(ArchiveRejected), self.stage(self.catalog()): pass
                self.assert_clean()

    def test_source_replacement_after_copy_cannot_change_staged_content(self):
        from agent_factory.installation_archive import _check_directory_bound
        catalog = self.archive()
        def replace_original(copy):
            self.source.write_bytes(b'changed original')
            return _check_directory_bound(copy)
        with patch('agent_factory.installation_archive._check_directory_bound', replace_original):
            with self.stage(catalog) as result:
                self.assertEqual((result.directory/'folder/game.txt').read_bytes(), b'game')
        self.assert_clean()

    def test_explicit_directory_entries_and_stored_files_work(self):
        catalog = self.archive((('folder/', b''), ('folder/game', b'contents')), compression=zipfile.ZIP_STORED)
        with self.stage(catalog) as result:
            self.assertEqual(result.files, ('folder/game',))
            self.assertEqual(result.extracted_bytes, 8)
        self.assert_clean()

    def test_zip64_extra_and_unreviewed_compression_are_rejected(self):
        for kind in ('zip64', 'compression'):
            with self.subTest(kind=kind):
                info = zipfile.ZipInfo('game')
                if kind == 'zip64': info.extra = struct.pack('<HHQQ', 1, 16, 1, 1)
                else: info.compress_type = zipfile.ZIP_BZIP2
                catalog = self.archive(((info, b'x'),))
                with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
                self.assert_clean()

    def test_nonregular_source_is_rejected_before_opening(self):
        catalog = self.archive()
        self.source.unlink(); self.source.mkdir()
        actual_open = os.open
        def reject_source(path, *args, **kwargs):
            if Path(path) == self.source: raise AssertionError('opened special source')
            return actual_open(path, *args, **kwargs)
        with patch('agent_factory.installation_archive.os.open', reject_source):
            with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
        self.assert_clean()

    def test_changed_descriptor_is_rejected_and_closed(self):
        catalog = self.archive()
        other = self.root/'other.zip'; other.write_bytes(self.source.read_bytes())
        actual_open = os.open
        descriptors = []
        def switched_open(source, flags, *args, **kwargs):
            if Path(source) != self.source:
                return actual_open(source, flags, *args, **kwargs)
            descriptor = actual_open(other, flags, *args, **kwargs)
            descriptors.append(descriptor)
            return descriptor
        with patch('agent_factory.installation_archive.os.open', switched_open):
            with self.assertRaises(ArchiveRejected), self.stage(catalog): pass
        for descriptor in descriptors:
            with self.assertRaises(OSError): os.fstat(descriptor)
        self.assert_clean()

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO is unavailable on this platform')
    def test_actual_fifo_and_check_open_swap_reject_without_waiting(self):
        catalog = self.archive()
        fifo = self.root/'pipe'; os.mkfifo(fifo)
        # Run in a separate process so a regression has a bounded timeout and
        # cannot hang the suite. Also substitute a FIFO after a regular lstat.
        program = '''
import json, os, sys
from pathlib import Path
from unittest.mock import patch
from agent_factory.installation_archive import ArchiveRejected, stage_verified_zip
source, fifo, parent, catalog = sys.argv[1:]
catalog = json.loads(catalog)
def check(path):
    try:
        with stage_verified_zip(path, catalog=catalog, package_id='godot-editor', staging_parent=parent):
            raise AssertionError('Special source accepted')
    except ArchiveRejected:
        pass
check(fifo)
actual_open = os.open
def swap(path, flags, *args, **kwargs):
    if Path(path) != Path(source):
        return actual_open(path, flags, *args, **kwargs)
    return actual_open(fifo, flags, *args, **kwargs)
with patch('agent_factory.installation_archive.os.open', swap):
    check(source)
assert sorted(p.name for p in Path(parent).iterdir()) == ['existing.txt']
'''
        result = subprocess.run([sys.executable, '-c', program, str(self.source), str(fifo),
                                 str(self.parent), json.dumps(catalog)], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_clean()


if __name__ == '__main__': unittest.main()
