"""Stable test-runtime entry point. No background game or AI workers are restarted."""
import json
import os
from pathlib import Path
import sys
import uvicorn

from domain_adapter import TestDomainIngress

token = Path('/run/secrets/access_token').read_text().strip()
if len(token) < 32:
    raise RuntimeError('Missing application credential')
os.environ['AGENT_FACTORY_API_TOKEN'] = token
os.environ['AGENT_FACTORY_API_ACTOR'] = 'HappyDucky02-test'
folder = Path('/data')
service = sys.argv[1]
if service == 'lokvetia':
    from agent_factory.web import create_app
    app = create_app(folder, folder / 'state.db')
elif service == 'lokiravia':
    from agentfactory_cloud.brief_web import create_app
    app = create_app(folder)
elif service == 'identity':
    from agent_factory.identity_service import create_identity_app
    clients = json.loads(Path('/run/secrets/identity_clients').read_text())
    app = create_identity_app(folder, clients)
else:
    raise RuntimeError('Unknown application')
app = TestDomainIngress(app, os.environ['TEST_PUBLIC_HOST'])
uvicorn.run(app, host='0.0.0.0', port=8080, workers=1, proxy_headers=False,
            timeout_keep_alive=10, limit_concurrency=128, access_log=False)
