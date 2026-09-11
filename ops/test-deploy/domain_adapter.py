"""Validate the exact test-domain boundary before normalizing local authority."""
from starlette.responses import JSONResponse, RedirectResponse
from urllib.parse import quote


class TestDomainIngress:
    def __init__(self, app, hostname):
        if hostname not in {'test.lokvetia.com', 'test.lokiravia.com', 'id.lokvetia.com'}:
            raise ValueError('Unconfigured application hostname')
        self.app, self.host = app, hostname.encode('ascii')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.app(scope, receive, send)
        if scope['type'] != 'http':
            return await send({'type': 'websocket.close', 'code': 1008})
        headers = scope.get('headers', [])
        values = lambda name: [v for k, v in headers if k.lower() == name]
        hosts, origins = values(b'host'), values(b'origin')
        if len(hosts) == 1 and hosts[0].split(b':')[0] in {b'localhost', b'127.0.0.1'}:
            return await self.app(scope, receive, send)
        if hosts == [self.host] and values(b'x-forwarded-proto') == [b'http'] and scope['method'] in {'GET', 'HEAD'}:
            target = 'https://' + self.host.decode() + '/' + quote(scope.get('raw_path', b'/').lstrip(b'/'), safe="/%:@!$&'()*+,;=-._~")
            if scope.get('query_string'):
                target += '?' + quote(scope['query_string'], safe="/%?:@!$&'()*+,;=-._~")
            return await RedirectResponse(target, status_code=308)(scope, receive, send)
        if (hosts != [self.host] or values(b'x-forwarded-proto') != [b'https'] or len(origins) > 1
                or (origins and origins != [b'https://' + self.host]) or len(values(b'authorization')) > 1):
            return await JSONResponse({'error': 'HTTPS origin required'}, status_code=403)(scope, receive, send)
        normalized = dict(scope, scheme='https', server=('localhost', 443))
        normalized['headers'] = [(k, v) for k, v in headers if k.lower() not in {b'host', b'origin', b'forwarded'}
                                 and not k.lower().startswith(b'x-forwarded-')]
        normalized['headers'].append((b'host', b'localhost'))
        if origins:
            normalized['headers'].append((b'origin', b'https://localhost'))
        await self.app(normalized, receive, send)
