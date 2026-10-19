"""Namespace owner: install once, attest, then expose a fixed local readiness."""
import http.server
import json
from pathlib import Path
import subprocess
import socket
import sys
import time

from config import config_digest, parse_config, render_rules

CONFIG = Path('/run/archguard-network/network.json')


def _config_bytes():
    # read(max+1) bounds allocation as well as validation for the mounted file.
    with CONFIG.open('rb') as source:
        data = source.read(4097)
    parse_config(data)
    return data


def _nft(args, data=None):
    result = subprocess.run(['nft', *args], input=data, capture_output=True, text=True,
                            check=True, timeout=5)
    if len(result.stdout) > 65536:
        raise ValueError('network attestation invalid')
    return result.stdout


def _attest(transaction, readback):
    expected = [next(iter(item.values())) for item in json.loads(transaction)['nftables']]
    actual = json.loads(readback)['nftables']
    actual = [item for item in actual if 'metainfo' not in item]
    # nft adds handles and empty-set fields when listing. Retain all semantics,
    # reject extra chains/rules/sets and compare ordered rules within each chain.
    def normalized(items):
        def canonical(value):
            if isinstance(value, dict):
                return {key: sorted(canonical(item) for item in child) if key in ('set', 'elem') and isinstance(child, list)
                        else canonical(child) for key, child in value.items()}
            if isinstance(value, list):
                return [canonical(child) for child in value]
            return value
        entities = []
        for item in items:
            if len(item) != 1:
                raise ValueError('network attestation invalid')
            kind, value = next(iter(item.items()))
            value = dict(value)
            value.pop('handle', None)
            if kind == 'set' and not value.get('elem'):
                value.pop('elem', None)
            entities.append((kind, canonical(value)))
        # Readback groups rules after their owning chain; preserve rule order.
        return sorted(entities, key=lambda e: (e[0], e[1].get('name', ''), e[1].get('chain', '')))
    if normalized(expected) != normalized(actual):
        raise ValueError('network attestation invalid')


def _serve():
    data = _config_bytes()
    transaction = render_rules(parse_config(data))
    _nft(['-j', '-f', '-'], transaction)
    _attest(transaction, _nft(['-j', 'list', 'table', 'inet', 'archguard_agent']))
    digest = config_digest(data).encode('ascii')

    class Ready(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def do_GET(self):
            self.connection.settimeout(1)
            if self.path != '/ready':
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Length', '64')
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(digest)

        def setup(self):
            super().setup()
            self.connection.settimeout(1)

        def log_message(self, *_):
            pass

    class ReadyServer(http.server.HTTPServer):
        def handle_error(self, request, client_address):
            print('network guard request failed', file=sys.stderr)

    with ReadyServer(('127.0.0.1', 18081), Ready) as server:
        server.serve_forever(poll_interval=0.25)


def _health():
    deadline = time.monotonic() + 1
    digest = config_digest(_config_bytes()).encode('ascii')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        def bounded():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('network readiness deadline')
            connection.settimeout(remaining)

        bounded()
        connection.connect(('127.0.0.1', 18081))
        bounded()
        connection.sendall(b'GET /ready HTTP/1.0\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n')
        received = b''
        header_length = None
        while True:
            bounded()
            chunk = connection.recv(min(1024, 2117 - len(received) + 1))
            if not chunk:
                break
            received += chunk
            if header_length is None:
                header, separator, _ = received.partition(b'\r\n\r\n')
                if len(header) > 2048:
                    raise ValueError('network readiness invalid')
                if not separator:
                    continue
                lines = header.split(b'\r\n')
                status = lines[0].split(b' ', 2)
                if (len(status) < 2 or status[0] not in (b'HTTP/1.0', b'HTTP/1.1') or
                        status[1] != b'200' or any(byte < 32 or byte > 126 for byte in lines[0])):
                    raise ValueError('network readiness invalid')
                headers = {}
                for line in lines[1:]:
                    name, colon, value = line.partition(b':')
                    name = name.lower()
                    if (not colon or not name.replace(b'-', b'').isalnum() or name in headers or
                            any(byte != 9 and not 32 <= byte <= 126 for byte in value)):
                        raise ValueError('network readiness invalid')
                    headers[name] = value.strip(b' \t')
                if headers.get(b'content-length') != b'64' or b'transfer-encoding' in headers:
                    raise ValueError('network readiness invalid')
                header_length = len(header) + 4
            if len(received) - header_length > 64:
                raise ValueError('network readiness invalid')
        if header_length is None or received[header_length:] != digest:
            raise ValueError('network readiness invalid')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv == ['serve']:
            _serve()
        elif argv == ['close']:
            _nft(['-j', '-f', '-'], json.dumps({'nftables': [{'flush': {'set': {
                'family': 'inet', 'table': 'archguard_agent', 'name': 'official_v4'}}}]}))
        elif argv == ['health']:
            _health()
        else:
            raise ValueError('network command invalid')
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        print('network guard operation failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
