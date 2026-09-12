"""Read-only online backups: each SQLite backup is transaction-consistent.

No restore operation exists here. Cross-database disaster recovery requires
separate application reconciliation; automatic code rollback retains live data.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys


def databases(root):
    result = set()
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('Symlink in data volume; configure an explicit backup adapter')
        if path.is_file():
            with path.open('rb') as stream:
                if stream.read(16) == b'SQLite format 3\0':
                    result.add(path)
    return result


def schemas(root):
    """Signature every stored object separately, so additions stay visible as additions.

    One hash for a whole database cannot tell a new table apart from a changed
    one. Per-object signatures let the controller allow a release that only adds
    tables while still refusing one that rewrites or drops what already holds
    client data.
    """
    result = {}
    for path in databases(root):
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)) as db:
            rows = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
            result[str(path.relative_to(root))] = {
                row[1]: hashlib.sha256(json.dumps(row).encode()).hexdigest() for row in rows}
    return result


def backup(source, destination):
    destination.mkdir(parents=True, exist_ok=False)
    sql = databases(source)
    sidecars = {Path(str(path) + suffix) for path in sql for suffix in ('-wal', '-shm', '-journal')}
    for path in sorted(source.rglob('*')):
        if not path.is_file() or path in sidecars:
            continue
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path in sql:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)) as src:
                with closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
                    dst.execute('PRAGMA journal_mode=DELETE')
                    if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                        raise RuntimeError('SQLite snapshot failed integrity check')
        else:
            before = path.stat()
            shutil.copy2(path, target)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError('Data file changed during backup; retry after its write completes')
    manifest = {}
    for path in destination.rglob('*'):
        if path.is_file():
            with path.open('rb') as stream:
                manifest[str(path.relative_to(destination))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(files=manifest, schemas=schemas(destination))


if __name__ == '__main__':
    if sys.argv[1] == '--schemas':
        print(json.dumps(schemas(Path(sys.argv[2]))))
    else:
        print(json.dumps(backup(Path(sys.argv[1]), Path(sys.argv[2]))))
