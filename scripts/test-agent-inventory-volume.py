#!/usr/bin/env python3
"""Prove independent generations on two newly owned disposable native volumes.

Requires an immutable prebuilt local image ID. No pull/build, existing volumes,
runtime.env, Compose activation, Secret, model calls or host clock changes.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

INITIALIZER = Path(__file__).with_name('initialize-agent-inventory.py').resolve()
LABEL = 'io.archguard.inventory-fixture'
FIRST = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
CURRENT = FIRST + timedelta(days=1)
# Test-only optional clock seam; production initializer and CLI are unchanged.
HARNESS = '''import importlib.util
from datetime import datetime
from pathlib import Path
import stat
import sys
spec = importlib.util.spec_from_file_location('initializer', '/fixture/initializer.py')
initializer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(initializer)
action, clock = sys.argv[1:]
try:
    if action == 'archive':
        assert Path('/inventory/inventory.json').read_bytes() == Path('/reviewed/inventory.json').read_bytes()
        assert stat.S_IMODE(Path('/inventory').stat().st_mode) == 0o555
        assert stat.S_IMODE(Path('/inventory/inventory.json').stat().st_mode) == 0o444
        assert Path('/inventory').stat().st_uid == Path('/inventory/inventory.json').stat().st_uid == 0
        assert list(Path('/inventory').iterdir()) == [Path('/inventory/inventory.json')]
    else:
        getattr(initializer, action)(now=datetime.fromisoformat(clock))
except (AssertionError, OSError, ValueError, TypeError):
    print('INVENTORY_UNAVAILABLE')
    sys.exit(1)
print('PASS')
'''


def require(condition, category):
    if not condition:
        raise AssertionError('INVENTORY_FIXTURE_' + category)


def docker(*args, timeout=20, check=True):
    try:
        result = subprocess.run(['docker', *map(str, args)], capture_output=True, text=True, timeout=timeout)
        if check:
            require(result.returncode == 0, 'DOCKER_FAILED')
        return result
    except (OSError, subprocess.SubprocessError):
        raise AssertionError('INVENTORY_FIXTURE_DOCKER_FAILED') from None


def synthetic_review(*, current=False):
    now = CURRENT if current else FIRST
    return {'schemaVersion': '0.1.0', 'deploymentId': '11111111-1111-4111-8111-111111111111',
            'entries': [{'inventoryId': ('44444444-4444-4444-8444-444444444444' if current else
                                         '22222222-2222-4222-8222-222222222222'),
                         'projectId': '33333333-3333-4333-8333-333333333333',
                         'manifestSha256': 'a' * 64, 'sourceKind': 'CONTROLLED_SYNTHETIC_FIXTURES',
                         'fixtureSetVersion': 'docker-fixture-only', 'fixtureArtifactSha256': 'b' * 64,
                         'reviewRef': 'synthetic-new-review' if current else 'synthetic-old-review',
                         'reviewedAt': (now - timedelta(minutes=1)).isoformat().replace('+00:00', 'Z'),
                         'expiresAt': (now + timedelta(hours=1)).isoformat().replace('+00:00', 'Z')}]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='already-built local guard sha256 image ID')
    args = parser.parse_args(argv)
    require(re.fullmatch(r'sha256:[a-f0-9]{64}', args.image) is not None, 'IMMUTABLE_IMAGE_REQUIRED')
    image = json.loads(docker('image', 'inspect', args.image).stdout)
    require(len(image) == 1 and image[0]['Id'] == args.image, 'IMAGE_ID_MISMATCH')
    declared_volumes = set(image[0]['Config'].get('Volumes') or {})
    require(declared_volumes <= {'/var/lib/postgresql/data'}, 'IMAGE_VOLUME_BOUNDARY')
    prefix = 'archguard-inventory-test-' + uuid.uuid4().hex
    volumes, containers = [], []

    def owned_volume(name):
        inspected = json.loads(docker('volume', 'inspect', name).stdout)
        require(len(inspected) == 1 and inspected[0]['Name'] == name and name.startswith(prefix + '-') and
                inspected[0].get('Labels', {}).get(LABEL) == prefix and
                inspected[0].get('Driver') == 'local' and not inspected[0].get('Options'), 'VOLUME_OWNERSHIP')

    try:
        with tempfile.TemporaryDirectory(prefix='archguard-inventory-test-') as temporary:
            temporary = Path(temporary)
            harness = temporary / 'harness.py'
            harness.write_text(HARNESS, encoding='utf-8')
            sources = {}
            for generation in ('old', 'new'):
                source = temporary / (generation + '.json')
                source.write_bytes(json.dumps(synthetic_review(current=generation == 'new'), separators=(',', ':')).encode('utf-8'))
                sources[generation] = source
                name = prefix + '-' + generation
                # Even an existing empty volume cannot count as first creation.
                require(docker('volume', 'inspect', name, check=False).returncode != 0, 'VOLUME_ALREADY_EXISTS')
                returned = docker('volume', 'create', '--driver=local', '--name', name,
                                  '--label', LABEL + '=' + prefix).stdout.strip()
                require(returned == name, 'VOLUME_ID_MISMATCH')
                volumes.append(name)
                owned_volume(name)

            def execute(suffix, generation, action, *, readonly, user, clock, expected, review=None):
                volume = prefix + '-' + generation
                require(volume in volumes, 'VOLUME_ID_MISMATCH')
                owned_volume(volume)
                name = prefix + '-' + suffix
                mounts = [('/fixture/initializer.py', 'bind', str(INITIALIZER), False),
                          ('/fixture/harness.py', 'bind', str(harness), False),
                          ('/inventory', 'volume', volume, not readonly)]
                if review:
                    mounts.append(('/reviewed/inventory.json', 'bind', str(sources[review]), False))
                create = ['create', '--pull=never', '--name', name, '--label', LABEL + '=' + prefix,
                          '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                          '--user', user, '--no-healthcheck', '--pids-limit=32', '--memory=64m',
                          '--env', 'PYTHONDONTWRITEBYTECODE=1', '--entrypoint', 'python3']
                # The guard's PostgreSQL base declares an unused data VOLUME.
                # Mask it with bounded tmpfs so Docker creates no anonymous volume.
                for target in sorted(declared_volumes):
                    create += ['--tmpfs', target + ':rw,noexec,nosuid,size=1m']
                for target, kind, source, writable in mounts:
                    create += ['--mount', 'type=' + kind + ',source=' + source + ',target=' + target +
                               ('' if writable else ',readonly')]
                create += [args.image, '/fixture/harness.py', action, clock.isoformat()]
                identity = docker(*create).stdout.strip()
                require(re.fullmatch(r'[a-f0-9]{64}', identity) is not None, 'CONTAINER_ID')
                containers.append((identity, name))
                model = json.loads(docker('container', 'inspect', identity).stdout)[0]
                require(model['Id'] == identity and model['Name'] == '/' + name and
                        model['Config']['Labels'].get(LABEL) == prefix and model['Image'] == args.image,
                        'CONTAINER_OWNERSHIP')
                host = model['HostConfig']
                require(host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] and
                        host['CapDrop'] == ['ALL'] and not host.get('CapAdd') and not host['Privileged'] and
                        host['SecurityOpt'] == ['no-new-privileges:true'] and not host.get('Devices') and
                        host['PidsLimit'] == 32 and host['Memory'] == 67108864, 'CONTAINER_PRIVILEGES')
                require(model['Config']['User'] == user, 'CONTAINER_USER')
                require(host.get('Tmpfs', {}) == {target: 'rw,noexec,nosuid,size=1m' for target in declared_volumes},
                        'TMPFS_BOUNDARY')
                actual_mounts = [item for item in model['Mounts'] if item['Type'] != 'tmpfs']
                require(len(actual_mounts) == len(mounts) and all(
                    item['Type'] != 'tmpfs' or item['Destination'] in declared_volumes for item in model['Mounts']),
                    'MOUNT_BOUNDARY')
                for target, kind, source, writable in mounts:
                    actual = [item for item in model['Mounts'] if item['Destination'] == target]
                    require(len(actual) == 1 and actual[0]['Type'] == kind and actual[0]['RW'] is writable,
                            'MOUNT_BOUNDARY')
                    if kind == 'volume':
                        require(actual[0]['Name'] == source and actual[0]['Driver'] == 'local', 'VOLUME_MOUNT')
                    # Desktop translates host paths, so also check requested
                    # bind identity in HostConfig.Mounts before execution.
                    requested = [item for item in host['Mounts'] if item['Target'] == target]
                    source_names = {source}
                    if kind == 'bind' and re.match(r'^[A-Za-z]:\\', source):
                        desktop_path = source[0].lower() + source[2:].replace('\\', '/')
                        source_names |= {'/run/desktop/mnt/host/' + desktop_path,
                                         '/host_mnt/' + desktop_path}
                    require(len(requested) == 1 and requested[0]['Source'] in source_names and
                            requested[0].get('ReadOnly', False) is (not writable), 'MOUNT_SOURCE')
                result = docker('start', '-a', identity, check=False)
                ended = json.loads(docker('container', 'inspect', identity).stdout)[0]
                require(ended['State']['Status'] == 'exited' and ended['State']['ExitCode'] == expected,
                        'CONTAINER_EXIT')
                require(result.returncode in (0, expected) and not result.stderr, 'PROCESS_RESULT')
                require(result.stdout.strip() == ('PASS' if expected == 0 else 'INVENTORY_UNAVAILABLE'), 'SAFE_RESULT')

            execute('old-initialize', 'old', 'initialize', readonly=False, user='0:0', clock=FIRST, expected=0, review='old')
            execute('old-initial-verify', 'old', 'verify', readonly=True, user='10001:10001', clock=FIRST, expected=0)
            execute('new-initialize', 'new', 'initialize', readonly=False, user='0:0', clock=CURRENT, expected=0, review='new')
            execute('old-expired', 'old', 'verify', readonly=True, user='10001:10001', clock=CURRENT, expected=1)
            execute('new-current', 'new', 'verify', readonly=True, user='10001:10001', clock=CURRENT, expected=0)
            execute('old-overwrite-refused', 'old', 'initialize', readonly=False, user='0:0', clock=CURRENT, expected=1, review='new')
            execute('old-still-expired', 'old', 'verify', readonly=True, user='10001:10001', clock=CURRENT, expected=1)
            for generation in ('old', 'new'):
                execute(generation + '-unchanged', generation, 'archive', readonly=True, user='10001:10001',
                        clock=CURRENT, expected=0, review=generation)
    finally:
        cleanup_failed = False
        for identity, name in reversed(containers):
            try:
                inspected = json.loads(docker('container', 'inspect', identity).stdout)
                require(len(inspected) == 1, 'CONTAINER_OWNERSHIP')
                model = inspected[0]
                require(model['Id'] == identity and model['Name'] == '/' + name and name.startswith(prefix + '-') and
                        model['Config'].get('Labels', {}).get(LABEL) == prefix, 'CONTAINER_OWNERSHIP')
                require(docker('rm', '-f', identity, check=False).returncode == 0, 'CLEANUP_FAILED')
            except (AssertionError, ValueError, KeyError, TypeError):
                cleanup_failed = True
        for name in reversed(volumes):
            try:
                owned_volume(name)
                require(docker('volume', 'rm', name, check=False).returncode == 0, 'CLEANUP_FAILED')
            except (AssertionError, ValueError, KeyError, TypeError):
                cleanup_failed = True
        require(not cleanup_failed, 'CLEANUP_FAILED')
    print('PASS: independentGenerations=true; oldExpired=true; newCurrent=true; nonrootReadonly=true; overwriteRefused=true; bytesAndModesUnchanged=true; modelCalls=0')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, ValueError, KeyError, TypeError):
        print('INVENTORY_FIXTURE_FAILED')
        raise SystemExit(1) from None
