"""Synthetic namespace services only. Never contacts a provider or reads credentials."""
import http.server
import http.client
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
import time


def require(value):
    if not value:
        raise AssertionError('isolated namespace fixture assertion failed')


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(60)
        try:
            while data := self.request.recv(4096):
                if data == b'stream':
                    self.request.settimeout(0.1)
                    deadline = time.monotonic() + 60
                    while time.monotonic() < deadline:
                        self.request.sendall(b'tick')
                        try:
                            incoming = self.request.recv(4096)
                            if b'after-close' in incoming:
                                Path('/tmp/stream-leaked').touch()
                            if not incoming:
                                return
                        except socket.timeout:
                            pass
                    return
                self.request.sendall(data)
        except (OSError, TimeoutError):
            pass


class Udp(socketserver.BaseRequestHandler):
    def handle(self):
        data, connection = self.request
        connection.sendto(data, self.client_address)


class Tcp(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def background(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()


def peers(public=False):
    if public:
        for address in ('8.8.8.8', '8.8.4.4'):
            subprocess.run(['ip', 'addr', 'add', address + '/32', 'dev', 'lo'], check=True, timeout=5)
    for port in (53, 443, 5432, 8080, 4444, 853):
        background(Tcp(('0.0.0.0', port), Echo))
    background(socketserver.ThreadingUDPServer(('0.0.0.0', 4444), Udp))
    Path('/tmp/fixture-ready').touch()
    while True:
        time.sleep(1)


def link_peer(expected_guard, expected_peer, slot):
    """Move one verified veth peer between two disposable namespaces only."""
    require(slot in ('0', '1'))
    require(os.readlink('/proc/1/ns/net') == expected_guard)
    require(os.readlink('/proc/self/ns/net') == expected_peer)
    require(expected_guard != expected_peer)
    peer_device, guard_device = 'agp' + slot, 'agg' + slot

    def ip(*args):
        subprocess.run(['ip', *args], check=True, timeout=5)

    # BusyBox ignores `peer name`; discover the actual paired index instead.
    ip('link', 'add', peer_device, 'type', 'veth')
    peer_index = int(Path('/sys/class/net/' + peer_device + '/iflink').read_text())
    generated_peer = dict(socket.if_nameindex())[peer_index]
    require(generated_peer not in ('lo', peer_device))
    require(socket.if_nametoindex(generated_peer) == peer_index)
    ip('link', 'set', generated_peer, 'name', guard_device)
    require(os.readlink('/proc/1/ns/net') == expected_guard)
    ip('link', 'set', guard_device, 'netns', '1')
    peer_address = '10.254.254.' + ('2' if slot == '0' else '6') + '/30'
    ip('addr', 'add', peer_address, 'dev', peer_device)
    ip('link', 'set', peer_device, 'up')


def app():
    for port in (8080, 9090):
        background(Tcp(('0.0.0.0', port), Echo))
    class Tcp6(Tcp):
        address_family = socket.AF_INET6
    # Explicit listener prevents an IPv6 refusal from masquerading as filtering.
    background(Tcp6(('::1', 9090), Echo))
    Path('/tmp/fixture-ready').touch()
    while True:
        time.sleep(1)


def connect(host, port, allowed, udp=False, ipv6=False):
    connection = socket.socket(socket.AF_INET6 if ipv6 else socket.AF_INET,
                               socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
    connection.settimeout(0.6)
    succeeded = False
    try:
        connection.connect((host, port))
        connection.send(b'isolated-fixture')
        succeeded = connection.recv(64) == b'isolated-fixture'
    except OSError:
        pass
    finally:
        connection.close()
    require(succeeded == allowed)


def read_exact(connection, length):
    data = b''
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise ValueError('short synthetic TCP frame')
        data += chunk
    return data


def dns(name, address, allowed, transport):
    # Only the exact existing owned peer name is queried, never an outside name.
    require(name.startswith('archguard-net-test-') and len(name) <= 63)
    require(all(character.isascii() and (character.isalnum() or character == '-') for character in name))
    require(transport in ('udp', 'tcp'))
    encoded = name.encode('ascii')
    query = (b'\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00' +
             bytes([len(encoded)]) + encoded + b'\x00\x00\x01\x00\x01')
    udp = transport == 'udp'
    answer = b''
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM) as connection:
        connection.settimeout(0.6)
        try:
            connection.connect(('127.0.0.11', 53))
            require(udp or allowed)  # A forbidden TCP DNS handshake must fail.
            connection.send(query if udp else len(query).to_bytes(2, 'big') + query)
            if udp:
                answer = connection.recv(512)
            else:
                length = int.from_bytes(read_exact(connection, 2), 'big')
                require(12 <= length <= 512)
                answer = read_exact(connection, length)
        except OSError:
            pass
    if allowed:
        require(len(answer) >= 12 and answer[:2] == b'\x12\x34' and answer[2] & 0x80 and
                answer[3] & 0x0f == 0 and int.from_bytes(answer[6:8], 'big') >= 1 and
                socket.inet_aton(address) in answer[12:])
    else:
        require(not answer)


def hosts(official):
    text = Path('/etc/hosts').read_text()
    require(('api.deepseek.com' in text) == official)
    if official:
        require(socket.gethostbyname('api.deepseek.com') == '8.8.8.8')
        try:
            with Path('/etc/hosts').open('a') as target:
                target.write('unexpected-write')
        except OSError:
            return
        require(False)


def readiness():
    for method, path, status in (('GET', '/ready', 200), ('GET', '/other', 404), ('POST', '/ready', 501)):
        connection = http.client.HTTPConnection('127.0.0.1', 18081, timeout=1)
        try:
            connection.request(method, path)
            response = connection.getresponse()
            require(response.status == status)
            if status == 200:
                body = response.read(65)
                require(len(body) == 64 and all(byte in b'0123456789abcdef' for byte in body))
        finally:
            connection.close()


def stream():
    with socket.create_connection(('8.8.8.8', 443), timeout=1) as connection:
        connection.settimeout(0.5)
        connection.sendall(b'stream')
        require(read_exact(connection, 4) == b'tick')
        Path('/tmp/stream-ready').touch()
        deadline = time.monotonic() + 45
        while not Path('/tmp/stream-close').exists():
            require(time.monotonic() < deadline)
            time.sleep(0.05)
        connection.sendall(b'after-close')
        # Drain bytes already queued before close; later ticks must be filtered.
        connection.setblocking(False)
        try:
            while connection.recv(4096):
                pass
        except BlockingIOError:
            pass
        connection.settimeout(0.6)
        try:
            require(not connection.recv(64))
        except socket.timeout:
            pass
    Path('/tmp/stream-blocked').touch()


def http_fixture():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.server.server_port in (19001, 19002):
                with Path('/tmp/forbidden-hits').open('a') as target:
                    target.write('hit\n')
            mode = Path('/tmp/http-mode').read_text()
            digest = 'a' * 64
            body = digest if mode not in ('mismatch', 'oversize') else ('b' * 64 if mode == 'mismatch' else digest + 'suffix')
            self.send_response(301 if mode == 'redirect' else 200)
            if mode == 'redirect':
                self.send_header('Location', 'http://127.0.0.1:19002/forbidden')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body.encode())
        def log_message(self, *_):
            pass
    Path('/tmp/http-mode').write_text('valid')
    for port in (18081, 19001, 19002):
        background(http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler))
    Path('/tmp/fixture-ready').touch()
    while True:
        time.sleep(1)


if __name__ == '__main__':
    mode, *args = sys.argv[1:]
    if mode == 'peer':
        peers(bool(args))
    elif mode == 'app':
        app()
    elif mode == 'connect':
        connect(args[0], int(args[1]), args[2] == 'allow', 'udp' in args, 'ipv6' in args)
    elif mode == 'dns':
        dns(args[0], args[1], args[2] == 'allow', args[3])
    elif mode == 'guard-with-dns-control':
        dns(args[0], args[1], True, 'udp')
        dns(args[0], args[1], True, 'tcp')
        os.execv(sys.executable, [sys.executable, '/opt/archguard/netguard/guard.py', 'serve'])
    elif mode == 'hosts':
        hosts(args == ['official'])
    elif mode == 'readiness':
        readiness()
    elif mode == 'stream':
        stream()
    elif mode == 'http':
        http_fixture()
    elif mode == 'ready':
        require(Path('/tmp/' + (args[0] if args else 'fixture-ready')).exists())
    elif mode == 'write':
        # Test-only fixed /tmp marker names; not an exposed production control.
        require(args[0] in ('stream-close', 'http-mode'))
        Path('/tmp/' + args[0]).write_text(args[1] if len(args) > 1 else '')
    elif mode == 'no-hits':
        require(not Path('/tmp/forbidden-hits').exists())
    elif mode == 'no-stream-leak':
        require(not Path('/tmp/stream-leaked').exists())
    elif mode == 'link-peer':
        link_peer(*args)
    else:
        raise SystemExit(1)
