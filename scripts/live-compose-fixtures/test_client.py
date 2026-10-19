"""Synthetic actual HTTP assertions, executed only in the owned proxy namespace."""
import http.client
import json
import re
import time


def request(port, method, path):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        connection.request(method, path, body=b'{}' if method in ('POST', 'PUT', 'PATCH') else None,
                           headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read(4097)
    finally:
        connection.close()


def verify_http(port):
    denied = ('/api/v1/agent/model-credentials', '/api/v1/agent/requests',
              '/api/v1/agent/', '/api/v1/agent',
              '/api/v1/projects/synthetic/agent', '/api/v1/projects/synthetic/agent/requests',
              '/api/v1/projects/synthetic/documents', '/api/v1/projects/synthetic/documents/versions')
    for path in denied:
        for method in ('GET', 'POST', 'PUT', 'DELETE'):
            status, headers, body = request(port, method, path)
            assert status == 503, 'rollback Agent route must return 503'
            assert headers.get('Cache-Control') == 'no-store', 'rollback response cache boundary'
            assert headers.get('Content-Type', '').startswith('application/json'), 'rollback response media boundary'
            parsed = json.loads(body)
            assert parsed['code'] == 'agent.unavailable', 'rollback response category'
            assert re.fullmatch('[a-f0-9]{32}', parsed['traceId']), 'rollback response trace boundary'
            assert parsed['details'] == {}, 'rollback response detail boundary'
    for path in ('/api/v1/projects/synthetic/scans', '/api/v1/projects/synthetic/gates',
                 '/auth/realms/archguard/.well-known/openid-configuration'):
        status, _, body = request(port, 'GET', path)
        assert status == 200 and json.loads(body) == {'fixture': 'deterministic-upstream'}, 'deterministic/OIDC forwarding boundary'


def main():
    ready = False
    for _ in range(30):
        try:
            status, _, _ = request(8080, 'GET', '/api/v1/projects/synthetic/scans')
            if status == 200:
                ready = True
                break
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.2)
    assert ready, 'temporary nginx fixture readiness failed'
    verify_http(8080)
    print('Temporary nginx HTTP client assertions: PASS')


if __name__ == '__main__':
    main()
