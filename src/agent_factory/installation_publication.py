"""Windows publication primitive for an authorized, journalled host executor.

This module does not supply that executor or its policy/admission authority.
An expected receipt must be persisted outside the target before publication.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from .installation_archive import ArchiveRejected, _regular_source
from .installation_manifest import InstallationManifest, manifest_for_stage, observe_manifest
from .installation_plan import _path


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _directory(path):
    path = Path(os.path.abspath(path))
    for part in reversed((path, *path.parents)):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ArchiveRejected('Publication requires real private directories')
    return path


@dataclass(frozen=True)
class PublicationReceipt:
    snapshot: str

    def __post_init__(self):
        try:
            if not isinstance(self.snapshot, str) or len(self.snapshot) > 4*1024**2+4096:
                raise ValueError()
            doc = json.loads(self.snapshot)
            if (set(doc) != {'schema_version', 'operation_identity', 'request_digest', 'target_name', 'manifest'}
                    or type(doc['schema_version']) is not int or doc['schema_version'] != 1
                    or _json(doc) != self.snapshot
                    or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', doc['operation_identity'])
                    or not re.fullmatch(r'[a-f0-9]{64}', doc['request_digest'])
                    or '/' in doc['target_name'] or len(doc['target_name']) > 80):
                raise ValueError()
            _path(doc['target_name'])
            InstallationManifest(_json(doc['manifest']))
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ValueError('Invalid publication receipt') from None

    @property
    def digest(self):
        return hashlib.sha256(self.snapshot.encode()).hexdigest()

    def document(self):
        return json.loads(self.snapshot)


def prepare_publication(staged, *, operation_identity, request_digest, target_name):
    """Prepare expected evidence; the trusted caller must durably retain it."""
    manifest = manifest_for_stage(staged)
    return PublicationReceipt(_json({'schema_version': 1, 'operation_identity': operation_identity,
        'request_digest': request_digest, 'target_name': target_name, 'manifest': manifest.document()}))


def observe_publication(parent, expected):
    """Read actual receipt AND payload against external trusted expected evidence."""
    if type(expected) is not PublicationReceipt:
        raise ValueError('Expected trusted publication receipt')
    doc = expected.document()
    try:
        parent = _directory(parent)
        target = parent/doc['target_name']
        if not os.path.lexists(target):
            return {'state': 'absent', 'execution_eligible': False}
        _directory(target)
        with os.scandir(target) as entries:
            names = []
            for entry in entries:
                names.append(entry.name)
                if len(names) > 2:
                    break
        if sorted(names) != ['payload', 'receipt.json']:
            return {'state': 'conflict', 'execution_eligible': False}
        expected_bytes = expected.snapshot.encode()
        with _regular_source(target/'receipt.json') as handle:
            if handle.read(len(expected_bytes)+1) != expected_bytes:
                return {'state': 'conflict', 'execution_eligible': False}
        result = observe_manifest(target/'payload', InstallationManifest(_json(doc['manifest'])))
        # A present envelope with a missing payload is never an absent publication.
        if result['state'] == 'absent':
            result['state'] = 'conflict'
        return {**result, 'receipt_digest': expected.digest}
    except (OSError, ArchiveRejected):
        return {'state': 'indeterminate', 'execution_eligible': False}


def _rename_new_directory(source, target):
    # Windows os.rename fails for any existing target, including an empty
    # directory. POSIX rename can replace one, so this profile denies POSIX.
    if os.name != 'nt':
        raise NotImplementedError('Publication is supported only on Windows')
    os.rename(source, target)


def publish_staged(staged, *, parent, expected, authorize):
    """Copy verified content, then publish a complete envelope without overwrite.

    Trusted host callback must check fresh intent, mission fence, real runtime
    admission and exact one-use policy, and durably start the operation. Only
    literal True permits publication. This is not a browser or provider hook.
    No default app route calls this primitive. Target layout is an internal
    envelope; later installer composition must explicitly adopt its payload path.
    """
    if os.name != 'nt':
        raise NotImplementedError('Publication is supported only on Windows')
    if type(expected) is not PublicationReceipt or not callable(authorize):
        raise ValueError('Expected trusted receipt and host authorization boundary')
    doc = expected.document()
    parent = Path(os.path.abspath(parent))
    if str(parent).startswith('\\\\'):
        raise ValueError('Network and device publication paths are unsupported')
    parent = _directory(parent)
    target = parent/doc['target_name']
    if os.path.lexists(target):
        raise FileExistsError('Publication target already exists; observe before recovery')
    manifest = manifest_for_stage(staged)
    if manifest.document() != doc['manifest']:
        raise ArchiveRejected('Stage differs from the frozen publication receipt')
    data = expected.snapshot.encode()
    if shutil.disk_usage(parent).free < doc['manifest']['total_bytes']+len(data)+4096:
        raise ArchiveRejected('Insufficient additional publication staging space')
    # Keep the archive context's root in place. Its cleanup cannot touch the
    # published envelope. Only the random temporary directory is cleaned here.
    with tempfile.TemporaryDirectory(prefix='af-publish-', dir=parent) as temporary:
        prepared = Path(temporary)/'prepared'
        payload = prepared/'payload'
        payload.mkdir(parents=True)
        file_names = {item['path'].casefold() for item in doc['manifest']['files']}
        for item in doc['manifest']['files']:
            destination = payload/item['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(); remaining = item['bytes']
            with _regular_source(staged.directory/item['path']) as source, destination.open('xb') as output:
                while chunk := source.read(min(1024*1024, remaining+1)):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise ArchiveRejected('Publication source grew')
                    digest.update(chunk); output.write(chunk)
                if remaining or digest.hexdigest() != item['sha256']:
                    raise ArchiveRejected('Publication source changed')
                output.flush(); os.fsync(output.fileno())
        # File paths retain source spelling; create their parents first. The
        # folded directory inventory also includes otherwise empty directories.
        for path in doc['manifest']['paths']:
            if path not in file_names:
                (payload/path).mkdir(parents=True, exist_ok=True)
        with (prepared/'receipt.json').open('xb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())
        if observe_manifest(payload, manifest)['state'] != 'matched':
            raise ArchiveRejected('Prepared payload failed verification')
        _directory(parent)
        if authorize(expected) is not True:
            raise PermissionError('Current installation authorization required')
        _directory(parent)
        _rename_new_directory(prepared, target)
    result = observe_publication(parent, expected)
    if result['state'] != 'matched':
        raise OSError('Publication result is uncertain; inspect without deleting or retrying')
    return result
