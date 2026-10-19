"""Root-run actual nginx HTTP regression on a new internal Docker network.

Requires an already-local Web image ID via --image; never builds/pulls, starts an
application, mounts runtime config, or connects to an existing network/volume.
Only test-owned uniquely named containers/network are removed in finally.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[2]
PROXY = ROOT / 'rollback/web.nginx.conf'


def docker(*args, check=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=30)
    if check and result.returncode:
        raise AssertionError('temporary nginx fixture Docker operation failed')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='already-local Web sha256 image ID')
    parser.add_argument('--client-image', required=True, help='already-local guard Python sha256 image ID')
    args = parser.parse_args()
    assert re.fullmatch(r'sha256:[a-f0-9]{64}', args.image), 'fixture requires an immutable local image ID'
    assert re.fullmatch(r'sha256:[a-f0-9]{64}', args.client_image), 'fixture requires an immutable local client image ID'
    prefix = 'archguard-task2-http-' + uuid.uuid4().hex[:12]
    upstream, proxy, network = prefix + '-upstream', prefix + '-proxy', prefix + '-net'
    created_containers = []
    network_id = None
    try:
        with tempfile.TemporaryDirectory(prefix='archguard-task2-http-') as temporary:
            temporary = Path(temporary)
            upstream_conf = temporary / 'upstream.conf'
            proxy_conf = temporary / 'proxy.conf'
            # Synthetic configuration only. The route artifact itself is mounted
            # byte-for-byte from rollback/web.nginx.conf, never rewritten.
            upstream_conf.write_text('pid /tmp/nginx.pid;\nevents {}\nhttp {\naccess_log off;\n'
                'server { listen 8080; location / { default_type application/json; '
                'return 200 \'{"fixture":"deterministic-upstream"}\'; } }\n}\n', encoding='utf-8')
            proxy_conf.write_text('pid /tmp/nginx.pid;\nevents {}\nhttp {\naccess_log off;\n'
                'include /etc/nginx/mime.types;\ninclude /etc/nginx/conf.d/default.conf;\n}\n', encoding='utf-8')
            network_id = docker('network', 'create', '--internal', network).stdout.strip()
            assert re.fullmatch('[a-f0-9]{64}', network_id), 'fixture network identity boundary'
            common = ['create', '--pull', 'never', '--read-only', '--cap-drop', 'ALL',
                      '--security-opt', 'no-new-privileges:true', '--user', '10001:10001',
                      '--pids-limit', '32', '--memory', '64m', '--network', network,
                      '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m,mode=1777',
                      '--tmpfs', '/var/cache/nginx:rw,noexec,nosuid,size=16m,mode=1777',
                      '--tmpfs', '/var/run:rw,noexec,nosuid,size=4m,mode=1777', '--entrypoint', 'nginx']
            upstream_id = docker(*common, '--name', upstream, '--network-alias', 'archguard-platform',
                   '--network-alias', 'keycloak', '--mount',
                   f'type=bind,src={upstream_conf},dst=/etc/nginx/nginx.conf,readonly',
                   args.image, '-g', 'daemon off;').stdout.strip()
            created_containers.append((upstream_id, upstream))
            assert re.fullmatch('[a-f0-9]{64}', upstream_id), 'fixture container identity boundary'
            docker('start', upstream_id)
            proxy_id = docker(*common, '--name', proxy, '--mount',
                   f'type=bind,src={proxy_conf},dst=/etc/nginx/nginx.conf,readonly', '--mount',
                   f'type=bind,src={PROXY},dst=/etc/nginx/conf.d/default.conf,readonly',
                   args.image, '-g', 'daemon off;').stdout.strip()
            created_containers.append((proxy_id, proxy))
            assert re.fullmatch('[a-f0-9]{64}', proxy_id), 'fixture container identity boundary'
            docker('start', proxy_id)
            client_name = prefix + '-client'
            client_script = Path(__file__).with_name('test_client.py').resolve()
            client_id = docker('create', '--pull', 'never', '--name', client_name,
                   '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                   '--user', '10001:10001', '--pids-limit', '32', '--memory', '64m',
                   '--network', 'container:' + proxy_id, '--entrypoint', 'python3', '--mount',
                   f'type=bind,src={client_script},dst=/fixture/test_client.py,readonly',
                   args.client_image, '/fixture/test_client.py').stdout.strip()
            created_containers.append((client_id, client_name))
            assert re.fullmatch('[a-f0-9]{64}', client_id), 'fixture client identity boundary'
            result = docker('start', '-a', client_id, check=False)
            terminal = docker('wait', client_id, check=False)
            state = docker('container', 'inspect', '--format', '{{.State.Status}} {{.State.ExitCode}}', client_id)
            if result.returncode or terminal.returncode or terminal.stdout.strip() != '0' or state.stdout.strip() != 'exited 0':
                # Only fixed client assertion categories are exposed. Never echo
                # full container config/environment or arbitrary Docker stderr.
                category = next((line.split('AssertionError: ', 1)[1] for line in result.stderr.splitlines()
                                 if line.startswith('AssertionError: ')), 'temporary HTTP client failed')
                assert False, category
    finally:
        cleanup_failed = False
        for container_id, expected_name in reversed(created_containers):
            if not re.fullmatch('[a-f0-9]{64}', container_id):
                cleanup_failed = True
                continue
            inspected = docker('container', 'inspect', '--format', '{{.Name}}', container_id, check=False)
            name = inspected.stdout.strip()
            if inspected.returncode or name != '/' + expected_name or not name.startswith('/' + prefix + '-'):
                cleanup_failed = True
                continue
            cleanup_failed |= docker('rm', '-f', container_id, check=False).returncode != 0
        if network_id:
            if re.fullmatch('[a-f0-9]{64}', network_id):
                inspected = docker('network', 'inspect', '--format', '{{.Name}}', network_id, check=False)
                name = inspected.stdout.strip()
                if inspected.returncode or name != network or not name.startswith(prefix + '-'):
                    cleanup_failed = True
                else:
                    cleanup_failed |= docker('network', 'rm', network_id, check=False).returncode != 0
            else:
                cleanup_failed = True
        assert not cleanup_failed, 'temporary nginx fixture cleanup failed'
    print('Temporary nginx HTTP rollback boundaries: PASS')


if __name__ == '__main__':
    main()
