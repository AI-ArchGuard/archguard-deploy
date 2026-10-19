#!/usr/bin/env python3
"""Validate a complete rendered local live model without reading mounted files.

Only fixed rejection categories leave this verifier. A valid configuration is
not runtime approval, inventory provenance, or proof that the kernel is closed.
"""
import json
from pathlib import Path
import re
import sys
import uuid


ROOT = Path(__file__).resolve().parent.parent
FLAGS = ('ARCHGUARD_AGENT_ENABLED', 'ARCHGUARD_AGENT_LIVE_ENABLED',
         'ARCHGUARD_AGENT_SYNTHETIC_INVENTORY_ENABLED', 'ARCHGUARD_CREDENTIAL_MANAGEMENT_ENABLED')
WEB_FLAGS = ('VITE_AGENT_UI_ENABLED', 'VITE_AGENT_LIVE_UI_ENABLED', 'VITE_CREDENTIAL_UI_ENABLED')
WRAPPER = '/opt/archguard/platform-start.sh'
INVENTORY = '/run/archguard-inventory'
NETWORK = '/run/archguard-network/network.json'


def require(condition, category):
    if not condition:
        raise AssertionError(category)


def path_equal(actual, expected):
    return isinstance(actual, str) and Path(actual).resolve() == expected.resolve()


def absolute_source(value):
    # Compose can emit Windows or POSIX paths. No file is opened or resolved
    # through the mount source: private configuration stays private.
    return isinstance(value, str) and bool(re.match(r'^(?:[A-Za-z]:[/\\]|/)', value))


def exact_mounts(service, targets):
    mounts = service.get('volumes', [])
    require(isinstance(mounts, list), 'mount boundary')
    require(len(mounts) == len(targets), 'mount boundary')
    require(all(isinstance(item, dict) for item in mounts), 'mount boundary')
    require({item.get('target') for item in mounts} == set(targets), 'mount boundary')
    return {item['target']: item for item in mounts}


def volume(mount, source, readonly):
    require(mount.get('type') == 'volume' and mount.get('source') == source,
            'volume identity boundary')
    require(mount.get('read_only', False) is readonly, 'mount permission boundary')
    require(not mount.get('volume', {}).get('subpath'), 'volume identity boundary')


def bind(mount):
    require(mount.get('type') == 'bind' and mount.get('read_only') is True,
            'mount permission boundary')
    require(absolute_source(mount.get('source')), 'mount source boundary')
    require(mount.get('bind', {}).get('create_host_path') is False, 'mount source boundary')
    require(not mount.get('bind', {}).get('propagation') or
            mount['bind']['propagation'] == 'rprivate', 'mount propagation boundary')


def identity(value):
    require(isinstance(value, str), 'identity boundary')
    parsed = uuid.UUID(value)
    require(str(parsed) == value and parsed.int != 0, 'identity boundary')


def safe_environment(env):
    require(isinstance(env, dict), 'environment boundary')
    for key in env:
        upper = key.upper()
        require('PROXY' not in upper and 'API_KEY' not in upper and 'DEEPSEEK' not in upper,
                'environment boundary')
        require(upper not in {'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'JAVA_OPTS',
                             'RES_OPTIONS', 'LOCALDOMAIN', 'HOSTALIASES',
                             'CURL_HOME', 'CURL_CA_BUNDLE', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
                             'LD_PRELOAD', 'LD_LIBRARY_PATH', 'PATH', 'JAVA_HOME',
                             'SPRING_APPLICATION_JSON', 'SPRING_CONFIG_IMPORT',
                             'SPRING_CONFIG_LOCATION', 'SPRING_CONFIG_ADDITIONAL_LOCATION'},
                'environment boundary')


def _verify(model, *, closed):
    services = model['services']
    require(set(services) == {'runtime-init', 'postgres', 'keycloak', 'archguard-platform',
            'scanner-runner', 'archguard-web', 'credential-init', 'credential-check',
            'agent-netguard'}, 'service boundary')
    platform = services['archguard-platform']
    guard = services['agent-netguard']
    web = services['archguard-web']
    def physical_volume_name(source):
        definition = model['volumes'][source] or {}
        if definition.get('name'):
            return definition['name']
        if definition.get('external') or not model.get('name'):
            return source
        return model['name'] + '_' + source

    inventory_identity = physical_volume_name('agent-live-inventory')
    inventory_sources = {source for source in model['volumes']
                         if physical_volume_name(source) == inventory_identity}
    require(set(model['networks']) == {'frontend', 'backend', 'agent-egress'}, 'network boundary')
    for name, internal in (('backend', True), ('frontend', False), ('agent-egress', False)):
        network = model['networks'][name]
        require(network.get('internal', False) is internal, 'network boundary')
        require(not network.get('external') and not network.get('enable_ipv6'), 'network boundary')
        require(network.get('driver', 'bridge') == 'bridge', 'network boundary')
    for name, service in services.items():
        require(not service.get('privileged'), 'privilege boundary')
        require(service.get('pid') != 'host' and service.get('ipc') != 'host' and
                service.get('cgroup') != 'host', 'namespace boundary')
        if name != 'archguard-web':
            require(not service.get('ports'), 'port boundary')
        if name != 'agent-netguard':
            require('agent-egress' not in service.get('networks', {}), 'egress isolation boundary')
            capabilities = {value.upper().removeprefix('CAP_') for value in service.get('cap_add', [])}
            require(not capabilities & {'ALL', 'NET_ADMIN', 'SYS_ADMIN'}, 'capability boundary')
        if name != 'archguard-platform':
            require(not service.get('network_mode') or service.get('network_mode') == 'none',
                    'namespace boundary')
        for mount in service.get('volumes', []):
            if name != 'archguard-platform':
                require(mount.get('source') not in inventory_sources, 'inventory isolation boundary')
    require(set(services['postgres']['networks']) == {'backend'}, 'network boundary')
    for name in ('keycloak', 'archguard-web'):
        require(set(services[name]['networks']) == {'frontend', 'backend'}, 'network boundary')
    for name in ('scanner-runner', 'runtime-init', 'credential-init', 'credential-check'):
        require(services[name].get('network_mode') == 'none', 'network boundary')
    ports = web['ports']
    require(len(ports) == 1 and ports[0].get('host_ip') == '127.0.0.1' and
            ports[0].get('target') == 8080 and ports[0].get('protocol', 'tcp') == 'tcp', 'port boundary')
    published = str(ports[0]['published'])
    require(published.isdecimal() and 1 <= int(published) <= 65535, 'port boundary')

    require(platform.get('network_mode') == 'service:agent-netguard' and
            not platform.get('networks'), 'namespace boundary')
    require(set(guard['networks']) == {'backend', 'agent-egress'}, 'network boundary')
    require(guard['networks']['backend'].get('aliases') == ['archguard-platform'], 'alias boundary')
    require(platform.get('user') == '10001:10001' and guard.get('user') == '0:0', 'user boundary')
    for service in (platform, guard):
        require(service.get('read_only') is True and service.get('cap_drop') == ['ALL'], 'privilege boundary')
        require(service.get('security_opt') == ['no-new-privileges:true'], 'privilege boundary')
        require(service.get('restart') == 'no', 'restart boundary')
        require('restart_policy' not in service.get('deploy', {}), 'restart boundary')
        require(not service.get('devices') and not service.get('device_cgroup_rules'), 'device boundary')
        require(not service.get('secrets') and not service.get('configs'), 'secret boundary')
        for key in ('extra_hosts', 'dns', 'dns_search', 'dns_opt', 'links', 'external_links'):
            require(not service.get(key), 'resolver boundary')
        require(not service.get('volumes_from'), 'mount boundary')
    require(not platform.get('cap_add') and guard.get('cap_add') == ['NET_ADMIN'], 'capability boundary')
    require(platform.get('entrypoint') == ['/bin/sh', WRAPPER] and
            platform.get('command') in (None, []), 'startup boundary')
    require(guard.get('entrypoint') == ['python3', '/opt/archguard/netguard/guard.py'] and
            guard.get('command') == ['serve'], 'startup boundary')
    dependency = platform['depends_on']['agent-netguard']
    require(dependency.get('condition') == 'service_healthy' and
            dependency.get('required', True) is True and not dependency.get('restart'), 'readiness boundary')
    health = guard['healthcheck']
    require(not health.get('disable') and health.get('test') ==
            ['CMD', 'python3', '/opt/archguard/netguard/guard.py', 'health'], 'readiness boundary')
    require(health.get('interval') == '5s' and health.get('timeout') == '2s' and
            health.get('retries') == 1, 'readiness boundary')
    require(guard.get('image') == 'archguard/agent-netguard:personal-live-local', 'image boundary')
    build = guard['build']
    require(set(build) <= {'context', 'dockerfile'} and build.get('dockerfile', 'Dockerfile') == 'Dockerfile' and
            path_equal(build.get('context'), ROOT / 'netguard'), 'build boundary')
    require(type(guard.get('pids_limit')) is int and 1 <= guard['pids_limit'] <= 32, 'resource boundary')
    require(1 <= int(guard['mem_limit']) <= 67108864, 'resource boundary')
    require(guard.get('tmpfs') == ['/tmp:rw,noexec,nosuid,size=16m'], 'resource boundary')
    require(not guard.get('environment') and not guard.get('env_file'), 'environment boundary')

    guard_mounts = exact_mounts(guard, {NETWORK})
    bind(guard_mounts[NETWORK])
    mounts = exact_mounts(platform, {'/opt/archguard/scanner-artifacts', '/mailbox', '/sources',
                                   '/var/lib/archguard/credentials', '/run/archguard-master',
                                   '/etc/hosts', INVENTORY, WRAPPER})
    for target, source, readonly in (
            ('/opt/archguard/scanner-artifacts', 'scanner-artifacts', True),
            ('/mailbox', 'runner-mailbox', False),
            ('/var/lib/archguard/credentials', 'credential-ciphertext', False),
            ('/run/archguard-master', 'credential-master', True),
            (INVENTORY, 'agent-live-inventory', True)):
        volume(mounts[target], source, readonly)
    require(mounts['/sources'].get('type') == 'bind' and mounts['/sources'].get('read_only') is True and
            absolute_source(mounts['/sources'].get('source')), 'source mount boundary')
    for target in ('/etc/hosts', WRAPPER):
        bind(mounts[target])
    require(path_equal(mounts[WRAPPER]['source'], ROOT / 'netguard/platform-start.sh'), 'wrapper boundary')
    require(mounts['/etc/hosts']['source'] != guard_mounts[NETWORK]['source'], 'mount source boundary')
    for name in ('credential-master', 'credential-ciphertext', 'agent-live-inventory'):
        definition = model['volumes'][name] or {}
        require(not definition.get('external') and not definition.get('driver_opts'), 'volume identity boundary')
        if definition.get('name'):
            require(model.get('name') and definition['name'] == model['name'] + '_' + name, 'volume identity boundary')

    env = platform['environment']
    safe_environment(env)
    require(env['SPRING_PROFILES_ACTIVE'] == 'oidc,local-compose,agent-live', 'profile boundary')
    require(env.get('JAVA_TOOL_OPTIONS') == '-Djdk.httpclient.disableRetryConnect=true', 'JVM boundary')
    require(env.get('ARCHGUARD_AGENT_SYNTHETIC_ENABLED') == 'false', 'synthetic boundary')
    require(isinstance(env.get('ARCHGUARD_AGENT_NETWORK_SHA256'), str) and
            re.fullmatch('[a-f0-9]{64}', env['ARCHGUARD_AGENT_NETWORK_SHA256']), 'readiness binding boundary')
    require(env.get('ARCHGUARD_AGENT_SYNTHETIC_INVENTORY_FILE') == INVENTORY + '/inventory.json', 'inventory path boundary')
    for key in ('ARCHGUARD_CREDENTIAL_OWNER_ID', 'ARCHGUARD_CREDENTIAL_DEPLOYMENT_ID'):
        identity(env[key])
    require(env['ARCHGUARD_CREDENTIAL_UI_ORIGIN'] == 'http://localhost:' + published and
            env['ARCHGUARD_CREDENTIAL_ALLOW_LOOPBACK_HTTP'] == 'true', 'credential origin boundary')
    require(env['ARCHGUARD_CREDENTIAL_DIRECTORY'] == '/var/lib/archguard/credentials' and
            env['ARCHGUARD_CREDENTIAL_MASTER_FILE'] == '/run/archguard-master/master.key', 'credential path boundary')
    for flag in FLAGS:
        require(env.get(flag) in ('true', 'false') and isinstance(env[flag], str), 'flag boundary')
    args = web['build']['args']
    for flag in WEB_FLAGS:
        require(args.get(flag) in ('true', 'false') and isinstance(args[flag], str), 'flag boundary')
    if env['ARCHGUARD_AGENT_LIVE_ENABLED'] == 'true':
        require(all(env[flag] == 'true' for flag in FLAGS), 'live prerequisite boundary')
        for key in ('PROJECT_ID', 'BATCH_ID'):
            identity(env['ARCHGUARD_AGENT_LIVE_' + key])
        for key in ('NETWORK_CHECK_REF', 'SECRET_CHECK_REF'):
            value = env['ARCHGUARD_AGENT_LIVE_' + key]
            require(isinstance(value, str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', value) and
                    value.lower() not in {'latest', 'all', 'any'} and
                    not value.lower().startswith(('sk-', 'ghp_', 'github_pat_')), 'live reference boundary')
    if closed:
        require(all(env[flag] == 'false' for flag in FLAGS) and
                all(args[flag] == 'false' for flag in WEB_FLAGS), 'closure flag boundary')
        proxy = exact_mounts(web, {'/etc/nginx/conf.d/default.conf'})['/etc/nginx/conf.d/default.conf']
        bind(proxy)
        require(path_equal(proxy['source'], ROOT / 'rollback/web.nginx.conf'), 'closure proxy boundary')


def verify(model: dict, *, closed: bool = False) -> None:
    try:
        require(isinstance(model, dict) and type(closed) is bool, 'model boundary')
        _verify(model, closed=closed)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise AssertionError('model boundary') from None


def main():
    try:
        require(len(sys.argv) in (2, 3) and (len(sys.argv) == 2 or sys.argv[2] == '--closed'), 'arguments boundary')
        source = sys.stdin.read() if sys.argv[1] == '-' else Path(sys.argv[1]).read_text(encoding='utf-8-sig')
        verify(json.loads(source), closed=len(sys.argv) == 3)
    except (AssertionError, OSError, ValueError) as rejected:
        # OSError/JSON errors may contain private paths or content; never echo.
        category = str(rejected) if isinstance(rejected, AssertionError) else 'input boundary'
        print(category, file=sys.stderr)
        return 1
    print('Live Compose configuration boundaries: PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
