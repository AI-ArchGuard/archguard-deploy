"""Verify a rendered personal credential model; never print environment values."""
import json
from pathlib import Path
import sys
import uuid


def verify(model):
    services = model['services']
    platform = services['archguard-platform']
    env = platform['environment']
    assert env['SPRING_PROFILES_ACTIVE'] == 'oidc,local-compose'
    assert env['ARCHGUARD_AGENT_ENABLED'] == env['ARCHGUARD_AGENT_SYNTHETIC_ENABLED'] == 'false'
    assert not any('API_KEY' in key or 'DEEPSEEK' in key for key in env)
    uuid.UUID(env['ARCHGUARD_CREDENTIAL_OWNER_ID'])
    uuid.UUID(env['ARCHGUARD_CREDENTIAL_DEPLOYMENT_ID'])
    port = services['archguard-web']['ports'][0]
    assert port['host_ip'] == '127.0.0.1' and port['target'] == 8080
    assert env['ARCHGUARD_CREDENTIAL_UI_ORIGIN'] == f"http://localhost:{port['published']}"
    assert env['ARCHGUARD_CREDENTIAL_ALLOW_LOOPBACK_HTTP'] == 'true'
    assert env['ARCHGUARD_CREDENTIAL_MANAGEMENT_ENABLED'] in ('true', 'false')
    assert services['archguard-web']['build']['args']['VITE_AGENT_UI_ENABLED'] == 'false'
    assert services['archguard-web']['build']['args']['VITE_CREDENTIAL_UI_ENABLED'] in ('true', 'false')
    mounts = {v['target']: v for v in platform['volumes']}
    cipher = mounts['/var/lib/archguard/credentials']
    master = mounts['/run/archguard-master']
    assert cipher['type'] == master['type'] == 'volume'
    assert cipher['source'] != master['source']
    assert not cipher.get('read_only', False) and master['read_only'] is True
    assert env['ARCHGUARD_CREDENTIAL_DIRECTORY'] == cipher['target']
    assert env['ARCHGUARD_CREDENTIAL_MASTER_FILE'] == master['target'] + '/master.key'
    assert platform['read_only'] and platform['cap_drop'] == ['ALL']
    for name, service in services.items():
        if name != 'archguard-web':
            assert not service.get('ports'), 'Internal port exposed'
    for name in ('credential-init', 'credential-check'):
        service = services[name]
        assert service['network_mode'] == 'none' and service['read_only']
        assert service['cap_drop'] == ['ALL']
        assert 'credential-bootstrap' in service['profiles']
    assert services['credential-init']['cap_add'] == ['CHOWN']
    assert not services['credential-check'].get('cap_add')
    assert services['credential-check']['user'] == '10001:10001'
    assert all(v.get('read_only') for v in services['credential-check']['volumes'])
    assert model['networks']['backend']['internal'] is True
    assert services['scanner-runner']['network_mode'] == 'none'


if __name__ == '__main__':
    value = sys.stdin.read() if sys.argv[1] == '-' else Path(sys.argv[1]).read_text(encoding='utf-8-sig')
    verify(json.loads(value))
    print('Credential Compose isolation/defaults: PASS')
