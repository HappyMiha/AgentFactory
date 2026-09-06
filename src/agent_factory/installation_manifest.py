"""Read-only content evidence for future installation reconciliation.

An expected manifest must come from trusted verified staging/journal evidence,
never from a manifest found inside the directory being inspected.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .installation_archive import ArchiveRejected, StagedArchive, _regular_source


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


@dataclass(frozen=True)
class InstallationManifest:
    snapshot: str

    def __post_init__(self):
        try:
            if not isinstance(self.snapshot,str) or len(self.snapshot)>4*1024**2:
                raise ValueError()
            document=json.loads(self.snapshot)
            if (set(document)!={'schema_version','package_id','archive_sha256','files','paths','total_bytes'}
                    or type(document['schema_version']) is not int or document['schema_version']!=1 or _json(document)!=self.snapshot
                    or not re.fullmatch('[a-z0-9][a-z0-9._-]{0,79}',document['package_id'])
                    or not re.fullmatch('[a-f0-9]{64}',document['archive_sha256'])):
                raise ValueError()
            files,paths,total=document['files'],document['paths'],document['total_bytes']
            if (type(total) is not int or not 0<=total<=4*1024**3 or not 1<=len(files)<=8192
                    or not 1<=len(paths)<=8192 or paths!=sorted(set(paths))):
                raise ValueError()
            for path in paths:
                if (not isinstance(path,str) or not 0<len(path)<=240 or path!=path.casefold()
                        or any(not re.fullmatch(r'[a-z0-9_. -]+',part) or part in {'.','..'}
                               or part!=part.strip() or part.endswith('.') for part in path.split('/'))):
                    raise ValueError()
            names=[]
            for item in files:
                if (set(item)!={'path','bytes','sha256'} or not isinstance(item['path'],str)
                        or item['path'].casefold() not in paths or type(item['bytes']) is not int
                        or not 0<=item['bytes']<=total or not re.fullmatch('[a-f0-9]{64}',item['sha256'])):
                    raise ValueError()
                names.append(item['path'])
            if (names!=sorted(names) or len(set(name.casefold() for name in names))!=len(names)
                    or sum(item['bytes'] for item in files)!=total):
                raise ValueError()
        except (ValueError,TypeError,KeyError,AttributeError):
            raise ValueError('Invalid installation content manifest') from None

    @property
    def digest(self):
        return hashlib.sha256(self.snapshot.encode()).hexdigest()

    def document(self):
        return json.loads(self.snapshot)


def _scan(root, budget):
    root = Path(os.path.abspath(root))
    # Check ancestors before following any path through them, including when a
    # link points at a missing child. No recursive traversal follows links.
    for path in reversed((root, *root.parents)):
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ArchiveRejected('Directory or ancestor is not a real directory')
    pending = [root]; files = []; total = 0; entries = 0; folded = set()
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as children:
            for child in children:
                entries += 1
                if entries > 8192:
                    raise ArchiveRejected('Content entry limit exceeded')
                path = Path(child.path)
                relative = path.relative_to(root).as_posix()
                if len(relative) > 240 or not relative.isascii() or relative.casefold() in folded:
                    raise ArchiveRejected('Unsupported or aliased content path')
                folded.add(relative.casefold())
                info = child.stat(follow_symlinks=False)
                if getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ArchiveRejected('Reparse content is unsupported')
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    digest = hashlib.sha256(); size = 0
                    with _regular_source(path) as handle:
                        before = os.fstat(handle.fileno())
                        while chunk := handle.read(min(1024 * 1024, budget - total + 1)):
                            total += len(chunk); size += len(chunk)
                            if total > budget:
                                raise ArchiveRejected('Content exceeds expected byte budget')
                            digest.update(chunk)
                        after = os.fstat(handle.fileno())
                        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                                after.st_size, after.st_mtime_ns, after.st_ctime_ns) or size != after.st_size:
                            raise ArchiveRejected('Content changed during observation')
                    files.append({'path':relative,'bytes':size,'sha256':digest.hexdigest()})
                else:
                    raise ArchiveRejected('Links and special content are unsupported')
    return sorted(files, key=lambda item:item['path']), sorted(folded), total


def manifest_for_stage(staged):
    """Hash a verified private staging tree; does not prove install authority."""
    if (type(staged) is not StagedArchive or type(staged.extracted_bytes) is not int
            or not 0 <= staged.extracted_bytes <= 4 * 1024**3
            or not re.fullmatch('[a-f0-9]{64}', staged.sha256)):
        raise ValueError('Expected a supported verified stage')
    files, paths, total = _scan(staged.directory, staged.extracted_bytes)
    if (total != staged.extracted_bytes or [item['path'] for item in files] != sorted(staged.files)
            or [(item['path'],item['sha256']) for item in files] != sorted(staged.file_digests)):
        raise ArchiveRejected('Staged inventory changed')
    return InstallationManifest(_json({'schema_version':1,'package_id':staged.package_id,
        'archive_sha256':staged.sha256,'files':files,'paths':paths,'total_bytes':total}))


def observe_manifest(root, expected):
    """Return content state only; never delete, repair, execute or mark Ready.

    Root and expected evidence are trusted host inputs in a private workspace.
    No hostile same-user concurrent writer isolation is claimed. Even a matched
    tree needs a separate owned publication receipt and executable postcondition.
    """
    if type(expected) is not InstallationManifest:
        raise ValueError('Expected trusted staging manifest')
    document = expected.document()
    budget = document['total_bytes']
    if type(budget) is not int or not 0 <= budget <= 4 * 1024**3:
        raise ValueError('Invalid manifest byte budget')
    try:
        files, paths, total = _scan(root, budget)
    except FileNotFoundError:
        # A disappearing child is not proof the entire installation is absent.
        if os.path.lexists(root):
            state = 'indeterminate'
        else:
            state = 'absent'
        return {'state':state,'execution_eligible':False}
    except (ArchiveRejected, OSError):
        return {'state':'indeterminate','execution_eligible':False}
    matched = (files == document['files'] and paths == document['paths'] and total == budget)
    return {'state':'matched' if matched else 'conflict', 'manifest_digest':expected.digest,
            'execution_eligible':False}
