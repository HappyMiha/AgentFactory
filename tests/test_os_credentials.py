"""Synthetic native Windows entries only; every allocated reference is cleaned."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid
from agent_factory.os_credentials import WindowsCredentialStore, CredentialStoreUnavailable

@unittest.skipUnless(os.name == 'nt', 'Native Windows Credential Manager qualification')
class NativeCredentialTests(unittest.TestCase):
    def setUp(self):
        self.namespace = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        self.store = WindowsCredentialStore(self.namespace)
        self.reference = uuid.uuid4().hex
        self.addCleanup(self.store.delete, self.reference)
        self.secret = 'synthetic-native-' + uuid.uuid4().hex

    def test_fresh_process_reads_persistent_value_and_revocation_survives_restart(self):
        self.store.put(self.reference, self.secret)
        env = os.environ.copy(); env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        code = """import json,sys
from agent_factory.os_credentials import WindowsCredentialStore,CredentialStoreUnavailable
d=json.load(sys.stdin);s=WindowsCredentialStore(d['namespace'])
if d['action']=='read':
 assert s.get(d['reference'])==d['secret']
else:
 try:s.get(d['reference'])
 except CredentialStoreUnavailable:pass
 else:raise AssertionError('Revoked credential remains readable')
print('PASS')
"""
        for action in ['read','missing']:
            if action == 'missing': self.store.delete(self.reference)
            p = subprocess.run([sys.executable,'-c',code], input=json.dumps({'namespace':self.namespace,'reference':self.reference,'secret':self.secret,'action':action}),env=env,text=True,capture_output=True,timeout=15)
            self.assertEqual(p.returncode,0,'Child credential assertion failed')
            self.assertEqual(p.stdout.strip(),'PASS')
            self.assertNotIn(self.secret,p.stdout+p.stderr)

    def test_utf8_and_reference_isolation(self):
        value = self.secret + '☃'
        self.store.put(self.reference,value)
        self.assertEqual(self.store.get(self.reference),value)
        other = WindowsCredentialStore(hashlib.sha256(uuid.uuid4().bytes).hexdigest())
        with self.assertRaises(CredentialStoreUnavailable): other.get(self.reference)
        with self.assertRaises(ValueError): self.store.get('../foreign')
        with self.assertRaises(ValueError): self.store.put(self.reference,'x'*2049)
        self.assertEqual(self.store.get(self.reference),value)

    def test_native_connection_admission_and_disconnect_across_fresh_processes(self):
        import tempfile
        from agent_factory.credential_connections import CredentialConnections
        with tempfile.TemporaryDirectory() as root:
            database=Path(root)/'connections.db'
            service=CredentialConnections(database)
            env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1]/'src')
            code="""import sys,json
from pathlib import Path
from agent_factory.credential_connections import CredentialConnections
from agent_factory.credentials import CredentialBroker
from agent_factory.storage import SQLiteStorage
d=json.load(sys.stdin);s=CredentialConnections(Path(d['database']))
if d['action']=='connect':
 print(json.dumps(s.connect(actor='Owner',tenant='local',provider='openai',secret=d['secret'])))
else:
 storage=SQLiteStorage(Path(d['database']).with_name('core.db'))
 try:
  def execute(env,args):
   assert env['OPENAI_API_KEY']==d['secret']
   return {'echo':env['OPENAI_API_KEY']}
  try:
   result=s.execute(d['reference'],actor='Owner',tenant='local',broker=CredentialBroker(storage),mission_id='m',tool_key='p',operation='read',preapproved_operations={'read'},prompt='safe',arguments={},executor=execute)
  except PermissionError:
   assert d['action']=='revoked'
  else:
   assert d['action']=='use' and d['secret'] not in str(result)
  print('PASS')
 finally:storage.close()
"""
            data={'database':str(database),'secret':self.secret,'action':'connect'}
            ref=None
            try:
                for action in ('connect','use','revoked'):
                    data['action']=action
                    if action=='revoked':service.disconnect(ref,actor='Owner',tenant='local')
                    child=subprocess.run([sys.executable,'-c',code],input=json.dumps(data),env=env,text=True,capture_output=True,timeout=20)
                    self.assertEqual(child.returncode,0,'Native connection child failed')
                    self.assertNotIn(self.secret,child.stdout+child.stderr)
                    if action=='connect':ref=json.loads(child.stdout)['id'];data['reference']=ref
                    else:self.assertEqual(child.stdout.strip(),'PASS')
                for path in Path(root).rglob('*'):
                    if path.is_file():self.assertNotIn(self.secret.encode(),path.read_bytes())
            finally:
                for row in service.list(actor='Owner',tenant='local'):
                    service.disconnect(row['id'],actor='Owner',tenant='local')
