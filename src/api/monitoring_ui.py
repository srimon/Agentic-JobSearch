"""Authenticated, fixed-upstream access to the real monitoring interfaces."""
from pathlib import Path
from urllib.parse import unquote, urlsplit
import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from graphql import parse, OperationType
from graphql.language.ast import OperationDefinitionNode

BASES = {'prometheus': 'http://prometheus:9090', 'grafana': 'http://grafana:3000', 'phoenix': 'http://phoenix:6006'}
PREFIX = '/api/monitoring/'
MAX_RESPONSE = 32 * 1024 * 1024

def validate(tool, path, method, body):
    if tool not in BASES:
        raise HTTPException(404, 'Unknown monitoring tool')
    decoded = unquote(path)
    if any(c in decoded for c in ('\\', '%', '?', '#', '\x00')) or any(s in ('.', '..') for s in decoded.split('/')) or decoded.startswith('/'):
        raise HTTPException(400, 'Invalid monitoring path')
    if method in ('GET', 'HEAD'):
        return
    if method == 'POST' and tool == 'grafana' and path in ('api/ds/query', 'apis/features.grafana.app/v0alpha1/namespaces/default/ofrep/v1/evaluate/flags'):
        return  # Grafana also enforces the server-side Viewer role.
    if method == 'POST' and tool == 'phoenix' and path.rstrip('/') == 'graphql':
        import json
        try:
            payload = json.loads(body)
            document = parse(payload['query'])
            operations = [n for n in document.definitions if isinstance(n, OperationDefinitionNode)]
            if operations and all(n.operation == OperationType.QUERY for n in operations):
                return
        except Exception:
            pass
    raise HTTPException(403, 'Monitoring is read-only')

def fetch(tool, path, query, method, body):
    headers = {'Accept-Encoding': 'identity'}
    if tool == 'phoenix' and path.rstrip('/') == 'graphql' and method == 'GET':
        headers['Accept'] = 'text/html'
    if body:
        headers['Content-Type'] = 'application/json'
    if tool == 'grafana':
        headers['Authorization'] = 'Bearer ' + Path('/run/secrets/grafana_viewer_token').read_text().strip()
    url = BASES[tool] + '/' + path + ('?' + query if query else '')
    try:
        with requests.Session() as client:
            client.trust_env = False
            with client.request(method, url, data=body or None, headers=headers, timeout=(3, 25), allow_redirects=False, stream=True) as upstream:
                content = bytearray()
                for chunk in upstream.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > MAX_RESPONSE:
                        raise HTTPException(502, 'Monitoring response too large')
                response_headers = {'Content-Type': upstream.headers.get('Content-Type', 'application/octet-stream'),
                                    'Content-Security-Policy': "frame-ancestors 'self'", 'X-Frame-Options': 'SAMEORIGIN'}
                location = upstream.headers.get('Location')
                if location:
                    target = urlsplit(location)
                    if target.netloc and target.netloc != urlsplit(BASES[tool]).netloc:
                        raise HTTPException(502, 'External monitoring redirect rejected')
                    prefix = PREFIX + tool + '/'
                    dest = target.path
                    if not dest.startswith(prefix):
                        dest = prefix + dest.lstrip('/')
                    response_headers['Location'] = dest + ('?' + target.query if target.query else '')
                return Response(bytes(content), status_code=upstream.status_code, headers=response_headers)
    except requests.RequestException:
        raise HTTPException(503, 'Monitoring service is unavailable') from None

def create_router(operator):
    router = APIRouter()
    @router.get('/api/monitoring-status/{tool}', dependencies=[Depends(operator)])
    async def readiness(tool: str):
        validate(tool, '', 'GET', b'')
        path = {'grafana':'api/health', 'prometheus':'-/ready', 'phoenix':'healthz'}[tool]
        try:
            result = await run_in_threadpool(fetch, tool, path, '', 'GET', b'')
            return {'available': result.status_code == 200}
        except HTTPException:
            return {'available': False}
    @router.api_route(PREFIX + '{tool}/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'], dependencies=[Depends(operator)])
    async def display(tool: str, path: str, request: Request):
        body = await request.body()
        validate(tool, path, request.method, body)
        if tool == 'phoenix' and path.rstrip('/') == 'graphql' and request.method == 'GET' and request.query_params.get('query'):
            import json
            validate(tool, path, 'POST', json.dumps({'query':request.query_params['query']}).encode())
        return await run_in_threadpool(fetch, tool, path, request.url.query, request.method, body)
    return router
