#!/usr/bin/env python3
"""One host-side controller for the test apps. Rollback changes routing, not data."""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid

class DeployError(RuntimeError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def read_json(path, default=None):
    if not path.exists() and default is not None:
        return default
    return json.loads(path.read_text(encoding='utf-8-sig'))

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

@contextmanager
def exclusive(path):
    with path.open('a+b') as file:
        if file.tell() == 0:
            file.write(b'0'); file.flush()
        file.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            file.seek(0)
            if os.name == 'nt':
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)

def command(args, *, cwd=None, input=None, timeout=900):
    result = subprocess.run(args, cwd=cwd, input=input, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
    if result.returncode:
        detail = (result.stderr or result.stdout)[-8000:]
        detail = re.sub(r'(?i)(bearer\s+|token[=:]\s*)\S+', r'\1[redacted]', detail)
        raise DeployError(f'{Path(args[0]).name} failed ({result.returncode}): {detail}')
    return result.stdout.strip()

def compatible(before, after):
    return all(after.get(path) == signature for path, signature in before.items())

def release_image(p, attempt):
    repository = 'lokiravia' if p['service'] == 'lokiravia' else 'lokvetia-core'
    return repository + ':release-' + p['id'] + '-' + attempt

def archive_image(container, inspected, archive):
    if archive.exists():
        return
    partial = archive.with_suffix('.partial')
    metadata = dict(source_container=container, source_image=inspected['Image'], method='image-save')
    try:
        command(['docker', 'image', 'save', '--output', str(partial), inspected['Image']])
    except DeployError as error:
        if 'no such image' not in str(error).lower() or not inspected.get('HostConfig', {}).get('ReadonlyRootfs'):
            raise
        # Docker Desktop may lose an untagged manifest while its container still runs.
        # The root filesystem is immutable; mounts are excluded, and the process is not paused.
        recovery = 'lokvetia-recovery:' + uuid.uuid4().hex
        metadata.update(method='read-only-container-snapshot', recovery_tag=recovery,
                        recovery_image=command(['docker', 'commit', '--pause=false', container, recovery]))
        command(['docker', 'image', 'save', '--output', str(partial), recovery])
    atomic_json(archive.with_suffix('.json'), metadata)
    os.replace(partial, archive)

# Bounded so a long-running controller cannot grow its published state forever.
HISTORY_PER_PROJECT = 20
HISTORY_ERROR_LIMIT = 2000


class Controller:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['state_root']).resolve()
        self.bundle = Path(config['runtime_bundle']).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.public = self.root / 'public'
        self.public.mkdir(exist_ok=True)
        self.routes_path = self.public / 'routes.json'
        self.status_path = self.public / 'status.json'
        self.status = read_json(self.status_path, {'projects': {}, 'updated_at': now()})
        # Older published state predates the release history.
        self.status.setdefault('history', {})
        for p in config['projects']:
            if p['repository'] not in {'HappyMiha/Lokvetia-Core', 'HappyMiha/Lokiravia'}:
                raise DeployError('Unapproved repository')
            if p['service'] not in {'identity', 'lokvetia', 'lokiravia'} or not re.fullmatch(r'[a-z0-9-]+', p['id']):
                raise DeployError('Invalid project configuration')
        if not self.routes_path.exists():
            atomic_json(self.routes_path, config.get('initial_routes', {}))

    def report(self, p, phase, state='in_progress', **extra):
        record = self.status['projects'].setdefault(p['id'], {})
        record.update(project=p['name'], repository=p['repository'], host=p['host'],
                      phase=phase, state=state, updated_at=now(), **extra)
        self.status['updated_at'] = now()
        if state in {'success', 'failure'}:
            self.remember(p, record)
        atomic_json(self.status_path, self.status)
        print(json.dumps({'project': p['id'], 'phase': phase, 'state': state}), flush=True)
        if record.get('deployment_id') and phase in {'backup', 'activate', 'rollback', 'success', 'failure'}:
            try:
                payload = dict(state=state if state in {'success', 'failure'} else 'in_progress',
                    environment_url='https://' + p['host'] + '/deployments',
                    description=(extra.get('error') or phase)[:140], auto_inactive=False)
                command(['gh', 'api', '--method', 'POST',
                    f"repos/{p['repository']}/deployments/{record['deployment_id']}/statuses", '--input', '-'],
                    input=json.dumps(payload), timeout=30)
            except (DeployError, subprocess.TimeoutExpired):
                record['reporting_error'] = 'GitHub status unavailable; local record is authoritative'
                atomic_json(self.status_path, self.status)

    def remember(self, p, record):
        """Keep a bounded record of finished attempts so the page shows a trail.

        Only an attempt that ended is remembered, and only the fields the page
        reads. A repeated report for the same attempt replaces its entry rather
        than adding another, so a retry of the same revision cannot inflate the
        list.
        """
        entries = self.status.setdefault('history', {}).setdefault(p['id'], [])
        entry = {
            'commit': record.get('commit', ''),
            'state': record.get('state', ''),
            'phase': record.get('phase', ''),
            'rollback': record.get('rollback', ''),
            'error': str(record.get('error') or '')[:HISTORY_ERROR_LIMIT],
            'finished_at': record.get('finished_at') or now(),
        }
        same = [
            index for index, previous in enumerate(entries)
            if previous.get('commit') == entry['commit']
            and previous.get('finished_at') == entry['finished_at']
        ]
        for index in reversed(same):
            entries.pop(index)
        entries.insert(0, entry)
        del entries[HISTORY_PER_PROJECT:]

    def checkout(self, p):
        repo = self.root / 'repositories' / p['repository'].split('/')[1]
        repo.parent.mkdir(exist_ok=True)
        if not repo.exists():
            command(['git', 'clone', '--bare', 'https://github.com/' + p['repository'] + '.git', str(repo)])
        command(['git', '-C', str(repo), 'fetch', '--no-tags', 'origin', 'refs/heads/main:refs/heads/main'])
        sha = command(['git', '-C', str(repo), 'rev-parse', 'refs/heads/main'])
        if not re.fullmatch('[0-9a-f]{40}', sha):
            raise DeployError('Invalid main revision')
        checkout = self.root / 'releases' / p['repository'].split('/')[1] / sha
        if not checkout.exists():
            checkout.parent.mkdir(parents=True, exist_ok=True)
            command(['git', '-C', str(repo), 'worktree', 'add', '--detach', str(checkout), sha])
        if command(['git', '-C', str(checkout), 'rev-parse', 'HEAD']) != sha:
            raise DeployError('Immutable checkout mismatch')
        return sha, checkout

    def checks_passed(self, p, sha):
        runs = json.loads(command(['gh', 'run', 'list', '--repo', p['repository'], '--workflow', 'autodeploy.yml',
            '--commit', sha, '--limit', '5', '--json', 'status,conclusion'], timeout=45))
        return bool(runs and runs[0]['status'] == 'completed' and runs[0]['conclusion'] == 'success')

    def health(self, container, p):
        path = '/auth/account/config' if p['service'] == 'identity' else ('/api/projects?limit=1' if p['service'] == 'lokvetia' else '/api/briefs')
        source = "from pathlib import Path;import urllib.request;token=Path('/run/secrets/access_token').read_text().strip();r=urllib.request.urlopen(urllib.request.Request('http://localhost:8080" + path + "',headers={'Authorization':'Bearer '+token}),timeout=10);assert r.status==200"
        for attempt in range(12):
            try:
                command(['docker', 'exec', container, 'python', '-c', source], timeout=20)
                return
            except (DeployError, subprocess.TimeoutExpired) as error:
                if attempt == 11:
                    raise DeployError('Readiness failed: ' + str(error))
                time.sleep(2)

    def launch(self, p, image, name, volume, shadow=False):
        args = ['docker', 'run', '-d', '--name', name, '--label', 'lokvetia.deploy.managed=true',
            '--label', 'lokvetia.deploy.project=' + p['id'], '--read-only', '--init', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges:true', '--memory', p.get('memory', '1g'), '--cpus', '2',
            '--tmpfs', '/tmp:size=128m,mode=1777', '--network', 'none' if shadow else self.config['network'],
            '--mount', 'type=volume,source=' + volume + ',target=/data,volume-nocopy',
            '--mount', 'type=bind,source=' + str(Path(p['access_token_file']).resolve()) + ',target=/run/secrets/access_token,readonly',
            '--env', 'TEST_PUBLIC_HOST=' + p['host'], '--env', 'TEMPORAL_ENABLED=false']
        if not shadow:
            args += ['--restart', 'unless-stopped']
        for key, value in p.get('environment', {}).items():
            if not key.startswith(('LOKVETIA_', 'AGENT_FACTORY_')):
                raise DeployError('Unsupported environment key')
            args += ['--env', key + '=' + value]
        for mount in p.get('secret_mounts', []):
            args += ['--mount', 'type=bind,source=' + str(Path(mount['source']).resolve()) + ',target=' + mount['target'] + ',readonly']
        command(args + [image, p['service']], timeout=60)

    def rollback_route(self, p, previous):
        routes = read_json(self.routes_path)
        if previous is None:
            routes.pop(p['host'], None)
        else:
            routes[p['host']] = previous
        atomic_json(self.routes_path, routes)

    def deploy(self, p):
        record = self.status['projects'].get(p['id'], {})
        if record.get('state') == 'in_progress':
            if 'previous_route' in record:
                self.rollback_route(p, record['previous_route'])
            self.report(p, 'failure', 'failure', error='Interrupted rollout recovered; previous routing and live data retained')
        sha, checkout = self.checkout(p)
        previous = read_json(self.routes_path).get(p['host'])
        if previous and previous.get('sha') == sha:
            return
        if record.get('commit') == sha and record.get('retry_after', 0) > time.time():
            return
        if not self.checks_passed(p, sha):
            self.report(p, 'waiting_for_ci', 'queued', commit=sha, error='Waiting for successful Auto Deploy checks on this exact main revision')
            return
        managed = command(['docker', 'ps', '-a', '--filter', 'label=lokvetia.deploy.project=' + p['id'], '--format', '{{.Names}}']).splitlines()
        if len(managed) >= self.config.get('max_retained_containers_per_project', 8):
            self.report(p, 'capacity', 'failure', commit=sha, error='Retained-release limit reached; confirm old jobs finished before retiring containers')
            return
        if shutil.disk_usage(self.root).free < 2 * 1024**3:
            raise DeployError('Insufficient backup/build disk space')
        attempt = sha[:12] + '-' + uuid.uuid4().hex[:8]
        backup = self.root / 'backups' / p['id'] / attempt
        backup.mkdir(parents=True)
        previous_sha = previous.get('sha', '') if previous else ''
        release_range = previous_sha + '..' + sha if re.fullmatch('[0-9a-f]{7,40}', previous_sha) else sha
        notes = command(['git', '-C', str(checkout), 'log', '-100', '--format=%h %s', release_range])
        self.status['projects'][p['id']] = dict(previous_route=previous, started_at=now(), backup=str(backup),
            commit=sha, release_notes=notes, error='', rollback='not_needed')
        self.report(p, 'backup')
        activated = False
        shadow = None
        try:
            result = command(['gh', 'api', '--method', 'POST', f"repos/{p['repository']}/deployments", '--input', '-'],
                input=json.dumps(dict(ref=sha, environment='test-happyducky02-' + p['id'], auto_merge=False,
                    required_contexts=[], description='HappyDucky02 ' + p['name'], payload={'release_notes': notes})), timeout=45)
            self.status['projects'][p['id']]['deployment_id'] = json.loads(result)['id']
            if previous:
                inspected = json.loads(command(['docker', 'inspect', previous['container']]))[0]
                archive = self.root / 'image-backups' / (inspected['Image'].split(':')[-1] + '.tar')
                archive.parent.mkdir(exist_ok=True)
                archive_image(previous['container'], inspected, archive)
                self.status['projects'][p['id']]['image_backup'] = str(archive)
            self.report(p, 'build')
            image = release_image(p, attempt)
            dockerfile = self.bundle / ('Dockerfile.cloud' if p['service'] == 'lokiravia' else 'Dockerfile.core')
            command(['docker', 'build', '--label', 'org.opencontainers.image.revision=' + sha, '--build-context', 'runtime=' + str(self.bundle),
                     '--file', str(dockerfile), '--tag', image, str(checkout)], timeout=1800)
            self.report(p, 'backup')
            command(['docker', 'volume', 'inspect', p['volume']], timeout=30)
            result = command(['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                # SQLite opens databases mode=ro; WAL readers still need shared-memory sidecars.
                # Never let Docker seed an empty data volume from the image's /source tree.
                '--security-opt', 'no-new-privileges:true', '--mount', 'type=volume,source=' + p['volume'] + ',target=/source,volume-nocopy',
                '--mount', 'type=bind,source=' + str(backup) + ',target=/backup', '--entrypoint', 'python', image,
                '/app/snapshot.py', '/source', '/backup/data'])
            manifest = json.loads(result)
            atomic_json(backup / 'manifest.json', dict(manifest, commit=sha, previous_route=previous))
            self.report(p, 'validate')
            volume = 'lokvetia-deploy-shadow-' + p['id'] + '-' + attempt
            command(['docker', 'volume', 'create', volume])
            command(['docker', 'run', '--rm', '--network', 'none', '--user', '0', '--mount', 'type=volume,source=' + volume + ',target=/shadow',
                '--mount', 'type=bind,source=' + str(backup / 'data') + ',target=/snapshot,readonly', '--entrypoint', 'python', image, '-c',
                "import shutil,os;shutil.copytree('/snapshot','/shadow',dirs_exist_ok=True);[(os.chown(os.path.join(r,n),10001,10001)) for r,ds,fs in os.walk('/shadow') for n in ds+fs];os.chown('/shadow',10001,10001)"])
            shadow = 'lokvetia-shadow-' + p['id'] + '-' + attempt
            self.launch(p, image, shadow, volume, True)
            self.health(shadow, p)
            schema = json.loads(command(['docker', 'exec', shadow, 'python', '/app/snapshot.py', '--schemas', '/data']))
            if not compatible(manifest['schemas'], schema):
                raise DeployError('Existing database schema would change; plan a compatible migration before rollout')
            # This isolated shadow has never handled live requests or live data.
            command(['docker', 'rm', '-f', shadow]); shadow = None
            command(['docker', 'volume', 'rm', volume])
            candidate = 'lokvetia-release-' + p['id'] + '-' + attempt
            self.launch(p, image, candidate, p['volume'])
            self.health(candidate, p)
            self.report(p, 'activate', candidate=candidate)
            routes = read_json(self.routes_path)
            routes[p['host']] = dict(container=candidate, sha=sha, image=image, project=p['id'])
            atomic_json(self.routes_path, routes)
            activated = True
            self.report(p, 'health')
            self.health(candidate, p)
            self.report(p, 'success', 'success', finished_at=now(), error='', retry_after=0)
        except Exception as error:
            rollback = 'not_needed'
            if activated:
                self.report(p, 'rollback', error=str(error))
                try:
                    self.rollback_route(p, previous)
                    if previous:
                        self.health(previous['container'], p)
                    rollback = 'success'
                except Exception as rollback_error:
                    rollback = 'failure'
                    error = DeployError(str(error) + ' | rollback: ' + str(rollback_error))
            self.report(p, 'failure', 'failure', error=str(error), rollback=rollback, finished_at=now(), retry_after=time.time() + 900)
        finally:
            if shadow:
                try:
                    command(['docker', 'rm', '-f', shadow], timeout=30)
                except Exception:
                    pass

    def cycle(self):
        with exclusive(self.root / 'controller.lock'):
            for p in self.config['projects']:
                if p.get('enabled', True):
                    try:
                        self.deploy(p)
                    except Exception as error:
                        self.report(p, 'failure', 'failure', error=str(error))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    controller = Controller(read_json(args.config))
    while True:
        controller.cycle()
        if not args.watch:
            break
        time.sleep(max(30, int(controller.config.get('poll_seconds', 60))))

if __name__ == '__main__':
    main()
