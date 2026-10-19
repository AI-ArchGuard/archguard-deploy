"""Required offline Linux integration; only exact owned disposable Docker IDs are removed.

Supply locally built IDs: --image <guard sha256:...> --platform-image <cached Platform sha256:...>.
No builds, pulls, ports, active volumes, credentials or provider traffic occur here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).with_name('network-fixtures').resolve()


def check(value, category):
    if not value:
        raise AssertionError('isolated network check failed: ' + category)


class Harness:
    def __init__(self, image, platform, directory):
        self.image, self.platform, self.directory = image, platform, directory
        self.prefix = 'archguard-net-test-' + uuid.uuid4().hex
        self.containers, self.networks = [], []

    def docker(self, *args, ok=True, timeout=30):
        result = subprocess.run(['docker', *map(str, args)], capture_output=True, text=True, timeout=timeout)
        check((result.returncode == 0) == ok, str(args[0]))
        return result.stdout.strip()

    def network(self):
        name = self.prefix + '-backend'
        identity = self.docker('network', 'create', '--internal', name)
        self.networks.append(identity)
        network = json.loads(self.docker('network', 'inspect', identity))[0]
        check(network['Internal'] and not network['EnableIPv6'], 'private internal bridge')
        # Docker normally allocates RFC1918. The production parser independently
        # rejects any backend that does not meet that contract.
        return identity

    def create(self, suffix, *, network='none', image=None, caps=False, user='10001:10001', mounts=(),
               env=(), entry='python3', command=(), wrapper_markers=False, pid_namespace=None):
        args = ['create', '--pull=never', '--name', self.prefix + '-' + suffix,
                '--network', network, '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                '--user', user, '--no-healthcheck', '--pids-limit', '64', '--memory', '128m',
                '--tmpfs', '/tmp:rw,' + ('exec' if wrapper_markers else 'noexec') + ',nosuid,size=16m,mode=1777']
        if caps:
            args += ['--cap-add=NET_ADMIN']
        if pid_namespace is not None:
            check(pid_namespace in self.containers, 'owned PID namespace holder')
            args += ['--pid', 'container:' + pid_namespace]
        for source, target in [(FIXTURES, '/fixture'), *mounts]:
            args += ['--mount', f'type=bind,source={source},target={target},readonly']
        for value in env:
            args += ['--env', value]
        args += ['--entrypoint', entry, image or self.image, *command]
        identity = self.docker(*args)
        self.containers.append(identity)
        return identity

    def start(self, identity):
        self.docker('start', identity)

    def run(self, identity, *, ok=True):
        _, code = self.attach(identity)
        check((code == 0) == ok, 'container exit status')

    def attach(self, identity):
        result = subprocess.run(['docker', 'start', '-a', identity], capture_output=True, text=True, timeout=70)
        model = json.loads(self.docker('inspect', identity))[0]
        check(model['State']['Status'] == 'exited', 'attached container reached terminal state')
        code = model['State']['ExitCode']
        # Docker versions may report 0 or propagate the attached process status.
        # CLI failure with a created/running/missing container remains a failure.
        check(result.returncode in (0, code), 'attach CLI status agrees with container exit')
        return result.stdout.strip(), code

    def fixture(self, container, *command, ok=True):
        return self.docker('exec', container, 'python3', '/fixture/fixture.py', *command, ok=ok)

    def wait(self, predicate, label):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.15)
        raise AssertionError('isolated network readiness failed: ' + label)

    def ready(self, container, marker='fixture-ready'):
        result = subprocess.run(['docker', 'exec', container, 'python3', '/fixture/fixture.py', 'ready', marker],
                                capture_output=True, timeout=5)
        return result.returncode == 0

    def ip(self, container):
        model = json.loads(self.docker('inspect', container))[0]
        values = list(model['NetworkSettings']['Networks'].values())
        check(len(values) == 1, 'single fixture bridge')
        return values[0]['IPAddress']

    def link_public_peer(self, guard, peer, slot):
        check(slot in (0, 1), 'fixed fixture veth slot')
        for identity in (guard, peer):
            check(identity in self.containers, 'owned veth namespace')
            model = json.loads(self.docker('inspect', identity))[0]
            check(model['Name'].startswith('/' + self.prefix + '-') and model['State']['Running'],
                  'live owned veth namespace')
        expected_guard = self.docker('exec', guard, 'readlink', '/proc/self/ns/net')
        expected_peer = self.docker('exec', peer, 'readlink', '/proc/self/ns/net')
        check(all(re.fullmatch(r'net:\[\d+\]', value) for value in (expected_guard, expected_peer))
              and expected_guard != expected_peer, 'distinct owned namespace IDs')
        helper = self.create('link-helper-' + str(slot), network='container:' + peer,
                             pid_namespace=guard, caps=True, user='0:0',
                             command=['/fixture/fixture.py', 'link-peer', expected_guard, expected_peer, str(slot)])
        self.run(helper)
        guard_device = 'agg' + str(slot)
        guard_address, peer_address = ('10.254.254.1', '10.254.254.2') if slot == 0 else ('10.254.254.5', '10.254.254.6')
        self.docker('exec', guard, 'ip', 'addr', 'add', guard_address + '/30', 'dev', guard_device)
        self.docker('exec', guard, 'ip', 'link', 'set', guard_device, 'up')
        for address in ('8.8.8.8', '8.8.4.4'):
            self.docker('exec', guard, 'ip', 'route', 'add', address + '/32', 'via', peer_address, 'dev', guard_device)

    def owned_rules(self, namespace, suffix):
        check(namespace in self.containers, 'owned rule-read namespace')
        reader = self.create('rule-reader-' + suffix, network='container:' + namespace,
                             caps=True, user='0:0', entry='nft',
                             command=['-j', 'list', 'table', 'inet', 'archguard_agent'])
        output, code = self.attach(reader)
        check(code == 0, 'owned nft table readback')
        entries = json.loads(output)['nftables']
        return [entry for entry in entries if 'metainfo' not in entry]

    def cleanup(self):
        failures = []
        for identity in reversed(self.containers):
            try:
                model = json.loads(self.docker('inspect', identity))[0]
                check(model['Name'].startswith('/' + self.prefix + '-'), 'container ownership')
                self.docker('rm', '-f', identity)
            except (AssertionError, subprocess.SubprocessError):
                failures.append('container')
        for identity in reversed(self.networks):
            try:
                model = json.loads(self.docker('network', 'inspect', identity))[0]
                check(model['Name'].startswith(self.prefix + '-'), 'network ownership')
                self.docker('network', 'rm', identity)
            except (AssertionError, subprocess.SubprocessError):
                failures.append('network')
        check(not failures, 'owned fixture cleanup')

    def wrapper(self, namespace, suffix, digest, *, success, probes, hostile=True):
        setup = ('mkdir /tmp/bin; cp /fixture/java /fixture/curl /fixture/sleep /tmp/bin/; '
                 'chmod 755 /tmp/bin/java /tmp/bin/curl /tmp/bin/sleep; '
                 'cp /fixture/curlrc /tmp/.curlrc; '
                 'PATH=/tmp/bin /bin/sh /startup.sh; status=$?; '
                 'if [ -f /tmp/java-marker ]; then cat /tmp/java-marker; fi; '
                 'printf "probes="; if [ -f /tmp/curl-probes ]; then wc -l < /tmp/curl-probes; else echo 0; fi; '
                 'printf "intervals="; if [ -f /tmp/sleep-probes ]; then wc -l < /tmp/sleep-probes; else echo 0; fi; '
                 'exit "$status"')
        env = ['PATH=/tmp/bin:/usr/bin:/bin', 'HOME=/tmp', 'CURL_HOME=/tmp',
               'ARCHGUARD_AGENT_NETWORK_SHA256=' + digest]
        if hostile:
            env += ['http_proxy=http://127.0.0.1:19001', 'HTTP_PROXY=http://127.0.0.1:19001',
                    'ALL_PROXY=http://127.0.0.1:19001', 'all_proxy=http://127.0.0.1:19001', 'NO_PROXY=', 'no_proxy=']
        container = self.create('wrapper-' + suffix, network='container:' + namespace, image=self.platform,
                                mounts=[(ROOT / 'netguard/platform-start.sh', '/startup.sh')], env=env,
                                entry='/bin/sh', command=['-c', setup], wrapper_markers=True)
        output, code = self.attach(container)
        check((code == 0) == success, 'wrapper admission ' + suffix)
        check(('-jar\n/opt/archguard/platform.jar' in output) == success, 'Java marker ' + suffix)
        check([line[len('probes='):].strip() for line in output.splitlines()
               if line.startswith('probes=')] == [str(probes)], 'bounded probe count ' + suffix)
        check([line[len('intervals='):].strip() for line in output.splitlines()
               if line.startswith('intervals=')] == [str(max(0, probes - 1))], 'bounded intervals ' + suffix)


def exercise(h):
    network = h.network()
    peers = {}
    for name in ('postgres', 'keycloak', 'web', 'public'):
        container = h.create(name, network=network, user='0:0', caps=name == 'public',
                             command=['/fixture/fixture.py', 'peer', *(['public'] if name == 'public' else [])])
        h.start(container)
        h.wait(lambda: h.ready(container), name)
        peers[name] = container
    addresses = {name: h.ip(identity) for name, identity in peers.items()}
    dns_name = json.loads(h.docker('inspect', peers['postgres']))[0]['Name'].removeprefix('/')
    check(dns_name == h.prefix + '-postgres', 'exact owned local Docker DNS name')
    data = json.dumps(dict(schemaVersion='0.1.0', officialIpv4=['8.8.8.8'],
                          postgresIpv4=addresses['postgres'], keycloakIpv4=addresses['keycloak'],
                          webIpv4=addresses['web'], allowOfficial=True)).encode()
    config = h.directory / 'network.json'
    config.write_bytes(data)
    hosts = h.directory / 'hosts'
    hosts.write_text('127.0.0.1 localhost\n' + addresses['postgres'] + ' postgres\n' +
                     addresses['keycloak'] + ' keycloak\n8.8.8.8 api.deepseek.com\n', encoding='ascii')
    guard = h.create('guard', network=network, caps=True, user='0:0',
                     mounts=[(config, '/run/archguard-network/network.json')],
                     command=['/fixture/fixture.py', 'guard-with-dns-control', dns_name, addresses['postgres']])
    h.start(guard)
    def guard_ready(identity):
        result = subprocess.run(['docker', 'exec', identity, 'python3', '/opt/archguard/netguard/guard.py', 'health'],
                                capture_output=True, timeout=5)
        return result.returncode == 0
    h.wait(lambda: guard_ready(guard), 'attested guard')
    h.link_public_peer(guard, peers['public'], 0)
    platform = h.create('platform', network='container:' + guard, mounts=[(hosts, '/etc/hosts')],
                        command=['/fixture/fixture.py', 'app'])
    h.start(platform)
    h.wait(lambda: h.ready(platform), 'shared namespace Platform')
    h.fixture(platform, 'hosts', 'official')
    h.fixture(guard, 'hosts')
    h.fixture(platform, 'readiness')
    model = json.loads(h.docker('inspect', platform))[0]
    check(any(m['Destination'] == '/etc/hosts' and m['RW'] is False for m in model['Mounts']), 'Platform-only readonly hosts')
    h.wrapper(guard, 'guard-ready', hashlib.sha256(data).hexdigest(), success=True, probes=1, hostile=False)
    for peer, port in (('postgres', 5432), ('keycloak', 8080)):
        h.fixture(platform, 'connect', addresses[peer], str(port), 'allow')
    for peer, port in (('postgres', 8080), ('keycloak', 5432), ('web', 8080), ('public', 443),
                       ('postgres', 53), ('postgres', 853)):
        h.fixture(platform, 'connect', addresses[peer], str(port), 'deny')
    for host, port in (('8.8.8.8', 443), ('127.0.0.1', 8080), ('127.0.0.1', 18081)):
        if port == 18081:
            continue  # HTTP digest is verified by guard health and the actual wrapper.
        h.fixture(platform, 'connect', host, str(port), 'allow')
    for host, port in (('8.8.8.8', 4444), ('8.8.4.4', 443), ('127.0.0.1', 9090)):
        h.fixture(platform, 'connect', host, str(port), 'deny')
    h.fixture(platform, 'connect', addresses['postgres'], '4444', 'deny', 'udp')
    h.fixture(platform, 'connect', '::1', '9090', 'deny', 'ipv6')
    h.fixture(platform, 'dns', dns_name, addresses['postgres'], 'deny', 'udp')
    h.fixture(platform, 'dns', dns_name, addresses['postgres'], 'deny', 'tcp')
    guard_ip = h.ip(guard)
    h.fixture(peers['web'], 'connect', guard_ip, '8080', 'allow')
    h.fixture(peers['postgres'], 'connect', guard_ip, '8080', 'deny')
    h.fixture(peers['web'], 'connect', guard_ip, '18081', 'deny')

    closed_data = json.loads(data)
    del closed_data['allowOfficial']
    closed_config = h.directory / 'network-default-closed.json'
    closed_config.write_text(json.dumps(closed_data), encoding='ascii')
    default_closed = h.create('default-closed', network=network, caps=True, user='0:0',
                              mounts=[(closed_config, '/run/archguard-network/network.json')],
                              command=['/fixture/fixture.py', 'guard-with-dns-control', dns_name, addresses['postgres']])
    h.start(default_closed)
    h.wait(lambda: guard_ready(default_closed), 'default-closed guard')
    h.link_public_peer(default_closed, peers['public'], 1)
    h.fixture(default_closed, 'connect', '8.8.8.8', '443', 'deny')
    h.fixture(default_closed, 'connect', addresses['postgres'], '5432', 'allow')

    # Revoke the live flow while the network owner is alive; private services
    # must remain available after official membership is removed.
    h.docker('exec', '-d', platform, 'python3', '/fixture/fixture.py', 'stream')
    h.wait(lambda: h.ready(platform, 'stream-ready'), 'established official stream')
    closer = h.create('closer', network='container:' + platform, caps=True, user='0:0',
                      command=['/opt/archguard/netguard/guard.py', 'close'])
    h.run(closer)
    h.fixture(platform, 'write', 'stream-close')
    h.wait(lambda: h.ready(platform, 'stream-blocked'), 'established flow revoked')
    h.fixture(peers['public'], 'no-stream-leak')
    h.fixture(platform, 'connect', '8.8.8.8', '443', 'deny')
    h.fixture(platform, 'connect', addresses['postgres'], '5432', 'allow')
    h.fixture(platform, 'connect', addresses['keycloak'], '8080', 'allow')
    h.fixture(peers['web'], 'connect', guard_ip, '8080', 'allow')
    before_crash = h.owned_rules(platform, 'before-crash')
    h.docker('kill', guard)
    after_crash = h.owned_rules(platform, 'after-crash')
    check(before_crash == after_crash, 'complete owned rules persist after owner crash')
    # Docker may remove the owner's bridge interfaces/routes on exit. Exact
    # owned rules plus a live allowed/forbidden loopback pair attest retention
    # independently of transport disappearance; crash availability is not promised.
    h.fixture(platform, 'connect', '127.0.0.1', '8080', 'allow')
    h.fixture(platform, 'connect', '127.0.0.1', '9090', 'deny')
    h.wrapper(platform, 'crashed-no-ready', hashlib.sha256(data).hexdigest(), success=False, probes=30, hostile=False)

    # Real shell+curl characterization in a network=none namespace. Local hostile
    # proxy/curlrc/redirect recorders can observe any accidental extra request.
    http = h.create('http', command=['/fixture/fixture.py', 'http'])
    h.start(http)
    h.wait(lambda: h.ready(http), 'controlled HTTP responder')
    h.wrapper(http, 'missing-digest', '', success=False, probes=0)
    h.wrapper(http, 'bad-digest', 'A' * 64, success=False, probes=0)
    for mode in ('mismatch', 'oversize', 'redirect', 'valid'):
        h.fixture(http, 'write', 'http-mode', mode)
        h.wrapper(http, mode, 'a' * 64, success=mode == 'valid', probes=1 if mode == 'valid' else 30)
    h.fixture(http, 'no-hits')
    # Invalid input + existing table independently refuse readiness/Java.
    for case in ('invalid', 'existing'):
        badconfig = h.directory / ('network-' + case + '.json')
        badconfig.write_bytes(b'{}' if case == 'invalid' else data)
        keeper = h.create('failure-keeper-' + case, command=['-c', 'import time; time.sleep(90)'])
        h.start(keeper)
        setup = ('nft create table inet archguard_agent; ' if case == 'existing' else '')
        failed = h.create('failure-' + case, network='container:' + keeper, caps=True, user='0:0',
                          mounts=[(badconfig, '/run/archguard-network/network.json')], entry='/bin/sh',
                          command=['-c', setup + 'exec python3 /opt/archguard/netguard/guard.py serve'])
        h.run(failed, ok=False)
        h.wrapper(keeper, 'failure-' + case, hashlib.sha256(data).hexdigest(), success=False, probes=30, hostile=False)
    print('PASS: namespace tuples/DNS/UDP/IPv6/hosts/crash/close/real-sh-curl admission; modelCalls=0')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--platform-image', required=True)
    args = parser.parse_args()
    for identity in (args.image, args.platform_image):
        check(re.fullmatch(r'sha256:[0-9a-f]{64}', identity) is not None, 'locally built image ID required')
    with tempfile.TemporaryDirectory(prefix='archguard-net-fixture-') as directory:
        harness = Harness(args.image, args.platform_image, Path(directory))
        try:
            harness.docker('image', 'inspect', args.image)
            harness.docker('image', 'inspect', args.platform_image)
            exercise(harness)
        finally:
            harness.cleanup()


if __name__ == '__main__':
    main()
