"""Verified ZIP staging for a trusted installer; no download or installation.

The caller owns authorization, journaling and publication. The staging parent
must be a private host-controlled directory, inaccessible to untrusted writers.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import tempfile
import zipfile

from .installation_plan import validate_catalog


class ArchiveRejected(ValueError):
    """Archive does not match the reviewed package or supported format."""


@dataclass(frozen=True)
class StagedArchive:
    package_id: str
    sha256: str
    directory: Path
    files: tuple[str, ...]
    extracted_bytes: int
    file_digests: tuple[tuple[str, str], ...]


_CHUNK = 1024 * 1024
_MAX_ENTRIES = 8192
_MAX_CENTRAL_BYTES = 4 * 1024 * 1024
_RESERVED = {'con', 'prn', 'aux', 'nul'} | {
    f'{prefix}{n}' for prefix in ('com', 'lpt') for n in range(1, 10)
}


def _private_parent(parent):
    parent = Path(os.path.abspath(parent))
    for part in (parent, *parent.parents):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ArchiveRejected('Staging parent must contain only real directories')
    return parent


@contextmanager
def _regular_source(source):
    # Check before opening: a FIFO can otherwise wait forever for a writer.
    # O_NONBLOCK also closes the POSIX check/open race; fstat still checks the
    # opened descriptor. The caller's private-host trust boundary remains.
    expected = os.lstat(source)
    if (not stat.S_ISREG(expected.st_mode)
            or getattr(expected, 'st_file_attributes', 0) & 0x400):
        raise ArchiveRejected('Expected a regular archive file without links')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(source, flags)
    try:
        actual = os.fstat(descriptor)
        if (not stat.S_ISREG(actual.st_mode)
                or (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino)):
            raise ArchiveRejected('Archive source changed while opening')
        with os.fdopen(descriptor, 'rb', closefd=False) as handle:
            yield handle
    finally:
        os.close(descriptor)


def _copy_verified(source, destination, package):
    digest = hashlib.sha256()
    remaining = package['download_bytes']
    with _regular_source(source) as src, destination.open('xb') as dst:
        while True:
            chunk = src.read(min(_CHUNK, remaining + 1))
            if not chunk:
                break
            remaining -= len(chunk)
            if remaining < 0:
                raise ArchiveRejected('Archive exceeds reviewed download size')
            digest.update(chunk)
            dst.write(chunk)
    if remaining or digest.hexdigest() != package['sha256']:
        raise ArchiveRejected('Archive size or SHA-256 differs from reviewed package')


def _check_directory_bound(archive):
    """Bound central-directory allocation before ZipFile parses any entries.

    Initial profile accepts ordinary single-volume ZIP only. ZIP64, split and
    self-extracting archives need separate review, not a permissive fallback.
    """
    size = archive.stat().st_size
    with archive.open('rb') as handle:
        handle.seek(max(0, size - 65557))
        tail = handle.read(65557)
    at = tail.rfind(b'PK\x05\x06')
    if at < 0 or len(tail) - at < 22:
        raise ArchiveRejected('Missing ZIP end record')
    _, disk, directory_disk, disk_count, count, length, offset, comment = struct.unpack(
        '<4s4H2LH', tail[at:at + 22])
    end_at = size - len(tail) + at
    if (disk or directory_disk or disk_count != count or not 0 < count <= _MAX_ENTRIES
            or length > _MAX_CENTRAL_BYTES or offset == 0xffffffff
            or length == 0xffffffff or offset + length != end_at
            or len(tail) - at != 22 + comment):
        raise ArchiveRejected('Unsupported or unbounded ZIP directory')
    return count


def _entries(archive, expected_count, budget):
    entries = archive.infolist()
    if len(entries) != expected_count:
        raise ArchiveRejected('ZIP entry count mismatch')
    seen = {}
    spellings = {}
    total = 0
    result = []
    for entry in entries:
        # orig_filename retains embedded NUL which ZipInfo.filename truncates.
        original = entry.orig_filename
        directory = original.endswith('/')
        name = original[:-1] if directory else original
        parts = name.split('/')
        if (not name or len(name) > 240 or not original.isascii()
                or any(not re.fullmatch(r'[A-Za-z0-9_. -]+', p) or p in {'.', '..'}
                       or p != p.strip() or p.endswith('.')
                       or p.split('.')[0].casefold() in _RESERVED for p in parts)):
            raise ArchiveRejected('Unsafe or unsupported Windows archive path')
        mode = entry.external_attr >> 16
        kind = stat.S_IFMT(mode)
        extra = entry.extra
        while extra:
            if len(extra) < 4:
                raise ArchiveRejected('Malformed ZIP extra field')
            tag, size = struct.unpack('<HH', extra[:4])
            if tag == 1 or len(extra) < 4 + size:
                raise ArchiveRejected('ZIP64 or malformed extra field is unsupported')
            extra = extra[4 + size:]
        if (kind not in (0, stat.S_IFDIR if directory else stat.S_IFREG)
                or entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                or (directory and entry.file_size) or entry.file_size < 0):
            raise ArchiveRejected('Unsupported ZIP entry type or compression')
        key = name.casefold()
        for n in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:n])
            folded = prefix.casefold()
            if folded in spellings and spellings[folded] != prefix:
                raise ArchiveRejected('Case-aliased archive directory')
            spellings[folded] = prefix
        if key in seen:
            raise ArchiveRejected('Duplicate or case-aliased archive path')
        seen[key] = directory
        total += entry.file_size
        if total > budget:
            raise ArchiveRejected('Archive exceeds reviewed extraction budget')
        result.append((entry, name, directory))
    for key in seen:
        parts = key.split('/')
        if any(seen.get('/'.join(parts[:n])) is False for n in range(1, len(parts))):
            raise ArchiveRejected('File blocks an archive directory')
    if not any(not directory for _, _, directory in result):
        raise ArchiveRejected('Archive contains no files')
    return result


@contextmanager
def stage_verified_zip(source, *, catalog, package_id, staging_parent):
    """Yield temporary verified content, then remove only this private staging.

    Catalogue is trusted host input, not browser JSON or evidence of consent.
    The caller must not move/replace the staging root or permit concurrent writers.
    A hard process kill may leave the random directory for future journal repair.
    No files are published, executed, or written to a package installation target.
    """
    checked = validate_catalog(catalog)
    if package_id not in checked['packages']:
        raise ArchiveRejected('Package is absent from reviewed catalogue')
    package = checked['packages'][package_id]
    parent = _private_parent(staging_parent)
    needed = package['download_bytes'] + package['extraction_budget_bytes']
    if shutil.disk_usage(parent).free < needed:
        raise ArchiveRejected('Insufficient staging disk capacity')
    with tempfile.TemporaryDirectory(prefix='af-package-', dir=parent) as temporary:
        root = Path(temporary)
        copy = root / 'package.zip'
        _copy_verified(source, copy, package)
        expected_count = _check_directory_bound(copy)
        content = root / 'content'
        total = 0
        names = []
        digests = []
        try:
            with zipfile.ZipFile(copy) as archive:
                entries = _entries(archive, expected_count, package['extraction_budget_bytes'])
                if min(entry.header_offset for entry, _, _ in entries) != 0:
                    raise ArchiveRejected('Prefixed ZIP archives are unsupported')
                content.mkdir()
                for entry, name, directory in entries:
                    target = content.joinpath(*name.split('/'))
                    if directory:
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    count = 0
                    digest = hashlib.sha256()
                    with archive.open(entry) as src, target.open('xb') as dst:
                        while chunk := src.read(_CHUNK):
                            count += len(chunk)
                            total += len(chunk)
                            if count > entry.file_size or total > package['extraction_budget_bytes']:
                                raise ArchiveRejected('Actual extraction exceeds reviewed bounds')
                            dst.write(chunk)
                            digest.update(chunk)
                    if count != entry.file_size:
                        raise ArchiveRejected('Extracted entry size mismatch')
                    names.append(name)
                    digests.append((name, digest.hexdigest()))
        except (zipfile.BadZipFile, NotImplementedError, EOFError) as error:
            raise ArchiveRejected('Corrupt or unsupported ZIP content') from error
        yield StagedArchive(package_id, package['sha256'], content, tuple(names), total, tuple(digests))
