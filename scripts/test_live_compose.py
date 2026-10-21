"""Rendered-model contract; fixtures contain synthetic values only.

Root owns execution. The separate live-compose-fixtures HTTP driver exercises
the actual nginx artifact, without reading an active Compose env file.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
VERIFIER = ROOT / 'scripts/verify-agent-live-compose-config.py'
SCRIPT = str(ROOT / 'netguard/platform-start.sh')
NETWORK = '/run/archguard-network/network.json'
INVENTORY = '/run/archguard-inventory/inventory.json'
WRAPPER = '/opt/archguard/platform-start.sh'
BINDINGS = ('PROJECT_ID', 'BATCH_ID', 'NETWORK_CHECK_REF', 'SECRET_CHECK_REF')
GENERATION = 'abcdef12-2222-4222-8222-222222222222'
PROJECT = 'archguard-generation-test'
FLAGS = ('ARCHGUARD_AGENT_ENABLED', 'ARCHGUARD_AGENT_LIVE_ENABLED',
         'ARCHGUARD_AGENT_SYNTHETIC_INVENTORY_ENABLED', 'ARCHGUARD_CREDENTIAL_MANAGEMENT_ENABLED')
WEB_FLAGS = ('VITE_AGENT_UI_ENABLED', 'VITE_AGENT_LIVE_UI_ENABLED', 'VITE_CREDENTIAL_UI_ENABLED')


def model(*, enabled=False, closed=False):
    env = {
        'SPRING_PROFILES_ACTIVE': 'oidc,local-compose,agent-live',
        'JAVA_TOOL_OPTIONS': '-Djdk.httpclient.disableRetryConnect=true',
        'ARCHGUARD_AGENT_SYNTHETIC_ENABLED': 'false',
        'ARCHGUARD_AGENT_NETWORK_SHA256': 'a' * 64,
        'ARCHGUARD_AGENT_SYNTHETIC_INVENTORY_FILE': INVENTORY,
        'ARCHGUARD_CREDENTIAL_OWNER_ID': '22222222-2222-4222-8222-222222222222',
        'ARCHGUARD_CREDENTIAL_DEPLOYMENT_ID': '33333333-3333-4333-8333-333333333333',
        'ARCHGUARD_CREDENTIAL_UI_ORIGIN': 'http://localhost:8081',
        'ARCHGUARD_CREDENTIAL_ALLOW_LOOPBACK_HTTP': 'true',
        'ARCHGUARD_CREDENTIAL_DIRECTORY': '/var/lib/archguard/credentials',
        'ARCHGUARD_CREDENTIAL_MASTER_FILE': '/run/archguard-master/master.key',
    }
    env.update({flag: 'true' if enabled else 'false' for flag in FLAGS})
    env.update({'ARCHGUARD_AGENT_LIVE_' + key: '' for key in BINDINGS})
    if enabled:
        env.update(ARCHGUARD_AGENT_LIVE_PROJECT_ID='44444444-4444-4444-8444-444444444444',
                   ARCHGUARD_AGENT_LIVE_BATCH_ID='55555555-5555-4555-8555-555555555555',
                   ARCHGUARD_AGENT_LIVE_NETWORK_CHECK_REF='network-check-20261018',
                   ARCHGUARD_AGENT_LIVE_SECRET_CHECK_REF='secret-check-20261018')
    def bind(source, target):
        return dict(type='bind', source=source, target=target, read_only=True,
                    bind={'create_host_path': False})
    services = {
        'archguard-platform': {
            'image': 'archguard/platform:personal-credentials-local',
            'build': {'context': '/controlled/platform'},
            'environment': env, 'user': '10001:10001',
            'network_mode': 'service:agent-netguard', 'restart': 'no',
            'entrypoint': ['/bin/sh', WRAPPER], 'command': [],
            'read_only': True, 'cap_drop': ['ALL'],
            'security_opt': ['no-new-privileges:true'],
            'depends_on': {'agent-netguard': {'condition': 'service_healthy'},
                           'postgres': {'condition': 'service_healthy'},
                           'keycloak': {'condition': 'service_started'},
                           'runtime-init': {'condition': 'service_completed_successfully'}},
            'volumes': [dict(type='volume', source='scanner-artifacts', target='/opt/archguard/scanner-artifacts', read_only=True),
                        dict(type='volume', source='runner-mailbox', target='/mailbox'),
                        bind('/controlled/synthetic-samples', '/sources'),
                        dict(type='volume', source='credential-ciphertext', target='/var/lib/archguard/credentials'),
                        dict(type='volume', source='credential-master', target='/run/archguard-master', read_only=True),
                        bind('/controlled/hosts', '/etc/hosts'),
                        dict(type='volume', source='agent-live-inventory', target='/run/archguard-inventory', read_only=True),
                        bind(SCRIPT, WRAPPER)],
        },
        'agent-netguard': {
            'image': 'archguard/agent-netguard:personal-live-local',
            'build': {'context': str(ROOT / 'netguard')}, 'user': '0:0',
            'entrypoint': ['python3', '/opt/archguard/netguard/guard.py'], 'command': ['serve'],
            'networks': {'backend': {'aliases': ['archguard-platform']}, 'agent-egress': None},
            'restart': 'no', 'read_only': True, 'cap_drop': ['ALL'], 'cap_add': ['NET_ADMIN'],
            'security_opt': ['no-new-privileges:true'], 'pids_limit': 32, 'mem_limit': '67108864',
            'tmpfs': ['/tmp:rw,noexec,nosuid,size=16m'],
            'healthcheck': {'test': ['CMD', 'python3', '/opt/archguard/netguard/guard.py', 'health'],
                            'interval': '5s', 'timeout': '2s', 'retries': 1},
            'volumes': [bind('/controlled/network.json', NETWORK)],
        },
        'archguard-web': {
            'ports': [{'host_ip': '127.0.0.1', 'target': 8080, 'published': '8081', 'protocol': 'tcp'}],
            'build': {'args': {flag: 'true' if enabled else 'false' for flag in WEB_FLAGS}},
            'networks': {'frontend': None, 'backend': None},
        },
        'postgres': {'networks': {'backend': None}},
        'keycloak': {'networks': {'frontend': None, 'backend': None}},
        'scanner-runner': {'network_mode': 'none'},
        'runtime-init': {'network_mode': 'none', 'cap_add': ['CHOWN']},
        'credential-init': {'network_mode': 'none', 'read_only': True, 'cap_drop': ['ALL'],
                            'cap_add': ['CHOWN'], 'profiles': ['credential-bootstrap']},
        'credential-check': {'network_mode': 'none', 'read_only': True, 'cap_drop': ['ALL'],
                             'profiles': ['credential-bootstrap'], 'user': '10001:10001',
                             'volumes': [{'read_only': True}]},
    }
    if closed:
        services['archguard-web']['volumes'] = [bind(str(ROOT / 'rollback/web.nginx.conf'), '/etc/nginx/conf.d/default.conf')]
    return {'services': services, 'networks': {'backend': {'internal': True},
            'frontend': {'internal': False}, 'agent-egress': {'internal': False}},
            'volumes': {'credential-master': {}, 'credential-ciphertext': {},
                        'scanner-artifacts': {}, 'runner-mailbox': {}, 'agent-live-inventory': {}}}


class LiveComposeTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(VERIFIER.is_file(), 'live Compose verifier is not implemented')
        spec = importlib.util.spec_from_file_location('live_config_under_test', VERIFIER)
        self.verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.verifier)

    def reject(self, changed, *, closed=False):
        with self.assertRaises(AssertionError) as rejected:
            self.verifier.verify(changed, closed=closed)
        message = str(rejected.exception)
        self.assertTrue(message, 'rejection must name a category')
        self.assertNotIn('synthetic-sensitive-sentinel', message)
        self.assertNotIn('/controlled/', message)

    def mutations(self, changes, *, enabled=False, closed=False):
        for name, mutate in changes:
            changed = model(enabled=enabled, closed=closed)
            mutate(changed)
            with self.subTest(boundary=name):
                self.reject(changed, closed=closed)

    def test_default_closed_and_explicit_concrete_live_binding(self):
        self.verifier.verify(model())
        self.verifier.verify(model(enabled=True))
        self.verifier.verify(model(closed=True), closed=True)

    def generation_model(self, **kwargs):
        value = model(**kwargs)
        value['name'] = PROJECT
        value['volumes']['agent-live-inventory']['name'] = PROJECT + '_agent-live-inventory-' + GENERATION
        return value

    def test_generation_requires_explicit_opt_in_and_accepts_closed_or_bound_models(self):
        for kwargs in ({}, {'closed': True}, {'enabled': True}):
            with self.subTest(**kwargs):
                changed = self.generation_model(**kwargs)
                self.verifier.verify(changed, closed=kwargs.get('closed', False), inventory_generation=GENERATION)
                self.reject(changed, closed=kwargs.get('closed', False))
        with self.assertRaises(AssertionError):
            self.verifier.verify(model(), inventory_generation=GENERATION)

    def test_all_services_reject_inherited_mounts_in_legacy_generation_and_closed_models(self):
        # Inheritance can expose inventory and credentials without adding any
        # explicit volumes, including through an external container reference.
        for generation in (None, GENERATION):
            for closed in (False, True):
                original = self.generation_model(closed=closed) if generation else model(closed=closed)
                self.verifier.verify(original, closed=closed, inventory_generation=generation)
                for service in original['services']:
                    for inherited in ('archguard-platform:ro', 'archguard-platform:rw',
                                      'container:synthetic-sensitive-sentinel:ro'):
                        changed = copy.deepcopy(original)
                        changed['services'][service]['volumes_from'] = [inherited]
                        with self.subTest(generation=generation, closed=closed, service=service,
                                          inherited=inherited):
                            with self.assertRaises(AssertionError) as rejected:
                                self.verifier.verify(changed, closed=closed, inventory_generation=generation)
                            self.assertEqual(str(rejected.exception), 'mount boundary')

    def test_generation_rejects_invalid_identity_physical_alias_and_mount_escapes(self):
        for generation in ('', 'bad', GENERATION.upper(), GENERATION.replace('-', ''),
                           '{' + GENERATION + '}', '00000000-0000-0000-0000-000000000000', 1, True):
            with self.subTest(invalid=generation), self.assertRaises(AssertionError):
                self.verifier.verify(self.generation_model(), inventory_generation=generation)
        changes = [
            ('missing project', lambda m: m.pop('name')),
            ('wrong project', lambda m: m.update(name='other-project')),
            ('wrong UUID', lambda m: m['volumes']['agent-live-inventory'].update(name=PROJECT + '_agent-live-inventory-11111111-1111-4111-8111-111111111111')),
            ('old name', lambda m: m['volumes']['agent-live-inventory'].update(name=PROJECT + '_agent-live-inventory')),
            ('arbitrary alias', lambda m: m['volumes']['agent-live-inventory'].update(name='synthetic-sensitive-sentinel')),
            ('implicit name', lambda m: m['volumes']['agent-live-inventory'].pop('name')),
            ('external', lambda m: m['volumes']['agent-live-inventory'].update(external=True)),
            ('driver opts', lambda m: m['volumes']['agent-live-inventory'].update(driver_opts={'device': 'synthetic-sensitive-sentinel'})),
            ('remote driver', lambda m: m['volumes']['agent-live-inventory'].update(driver='synthetic-remote-driver')),
            ('subpath', lambda m: m['services']['archguard-platform']['volumes'][6].update(volume={'subpath': 'entry'})),
            ('writable', lambda m: m['services']['archguard-platform']['volumes'][6].update(read_only=False)),
            ('wrong path', lambda m: m['services']['archguard-platform']['volumes'][6].update(target='/other')),
            ('master hijack', lambda m: m['volumes']['credential-master'].update(name=PROJECT + '_agent-live-inventory-' + GENERATION)),
            ('cipher hijack', lambda m: m['volumes']['credential-ciphertext'].update(name=PROJECT + '_agent-live-inventory-' + GENERATION)),
            ('UUID env', lambda m: m['services']['archguard-platform']['environment'].update(ARCHGUARD_AGENT_INVENTORY_GENERATION=GENERATION)),
        ]
        for name, mutate in changes:
            changed = self.generation_model()
            mutate(changed)
            with self.subTest(boundary=name), self.assertRaises(AssertionError):
                self.verifier.verify(changed, inventory_generation=GENERATION)
        for service in model()['services']:
            if service == 'archguard-platform':
                continue
            for alias in ('inventory-alias', 'postgres-data', 'credential-master'):
                changed = self.generation_model()
                changed['volumes'][alias] = {'name': PROJECT + '_agent-live-inventory-' + GENERATION}
                changed['services'][service].setdefault('volumes', []).append(
                    {'type': 'volume', 'source': alias, 'target': '/alias', 'read_only': True})
                with self.subTest(service=service, alias=alias), self.assertRaises(AssertionError):
                    self.verifier.verify(changed, inventory_generation=GENERATION)

    def test_cli_generation_stdin_file_closed_and_sanitized_argument_failures(self):
        def run(args, value=None):
            return subprocess.run([sys.executable, str(VERIFIER), *args],
                                  input=json.dumps(value) if value is not None else '',
                                  capture_output=True, text=True, timeout=10)
        for args, value in ((['-'], model()), (['-', '--closed'], model(closed=True)),
                            (['-', '--inventory-generation', GENERATION], self.generation_model()),
                            (['--closed', '--inventory-generation', GENERATION, '-'], self.generation_model(closed=True))):
            result = run(args, value)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'Live Compose configuration boundaries: PASS')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'synthetic-sensitive-sentinel.json'
            path.write_text(json.dumps(self.generation_model(closed=True)), encoding='utf-8')
            result = run([str(path), '--inventory-generation', GENERATION, '--closed'])
            self.assertEqual(result.returncode, 0, result.stderr)
        for args in ([], ['-', '--unknown', 'synthetic-sensitive-sentinel'],
                     ['-', '--closed', '--closed'], ['-', '--inventory-generation'],
                     ['-', '--inventory-generation', GENERATION, '--inventory-generation', GENERATION],
                     ['-', '--inventory-generation', '--closed'], ['-', 'synthetic-sensitive-sentinel'],
                     ['synthetic-sensitive-sentinel', '--closed', 'extra']):
            result = run(args, self.generation_model())
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr.strip(), 'arguments boundary')
            self.assertEqual(result.stdout, '')
        for args, raw in ((['-', '--inventory-generation', 'synthetic-sensitive-sentinel'], self.generation_model()),
                          (['synthetic-sensitive-sentinel'], None), (['-'], None)):
            result = run(args, raw)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('synthetic-sensitive-sentinel', result.stdout + result.stderr)
            self.assertIn(result.stderr.strip(), ('identity boundary', 'input boundary', 'model boundary'))
        for body in ('synthetic-sensitive-sentinel', '[' * 5000 + 'synthetic-sensitive-sentinel'):
            result = subprocess.run([sys.executable, str(VERIFIER), '-'], input=body,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr.strip(), 'input boundary')
            self.assertEqual(result.stdout, '')

    def test_rejects_namespace_network_and_port_escape(self):
        self.mutations([
            ('platform network', lambda m: m['services']['archguard-platform'].update(networks={'backend': None})),
            ('platform host', lambda m: m['services']['archguard-platform'].update(network_mode='host')),
            ('platform other namespace', lambda m: m['services']['archguard-platform'].update(network_mode='service:postgres')),
            ('platform port', lambda m: m['services']['archguard-platform'].update(ports=[{'target': 8080}])),
            ('guard port', lambda m: m['services']['agent-netguard'].update(ports=[{'target': 18081}])),
            ('db port', lambda m: m['services']['postgres'].update(ports=[{'target': 5432}])),
            ('guard host', lambda m: m['services']['agent-netguard'].update(network_mode='host')),
            ('guard frontend', lambda m: m['services']['agent-netguard']['networks'].update(frontend=None)),
            ('guard missing backend', lambda m: m['services']['agent-netguard']['networks'].pop('backend')),
            ('guard missing alias', lambda m: m['services']['agent-netguard']['networks']['backend'].update(aliases=[])),
            ('extra egress peer', lambda m: m['services']['archguard-web']['networks'].update({'agent-egress': None})),
            ('backend public', lambda m: m['networks']['backend'].update(internal=False)),
            ('egress internal', lambda m: m['networks']['agent-egress'].update(internal=True)),
            ('web wildcard', lambda m: m['services']['archguard-web']['ports'][0].update(host_ip='0.0.0.0')),
            ('extra web port', lambda m: m['services']['archguard-web']['ports'].append({'target': 8081, 'host_ip': '127.0.0.1'})),
            ('runner network', lambda m: m['services']['scanner-runner'].update(network_mode='bridge')),
        ])

    def test_rejects_privilege_restart_entrypoint_or_readiness_bypass(self):
        changes = []
        for service in ('archguard-platform', 'agent-netguard'):
            for key, value in (('privileged', True), ('read_only', False), ('cap_drop', []),
                               ('restart', 'unless-stopped'), ('security_opt', []),
                               ('pid', 'host'), ('ipc', 'host'), ('devices', ['/dev/net/tun'])):
                changes.append((service + ':' + key, lambda m, s=service, k=key, v=value: m['services'][s].update({k: v})))
        changes.extend([
            ('platform root', lambda m: m['services']['archguard-platform'].update(user='0:0')),
            ('platform capability', lambda m: m['services']['archguard-platform'].update(cap_add=['NET_ADMIN'])),
            ('guard excess capability', lambda m: m['services']['agent-netguard'].update(cap_add=['NET_ADMIN', 'SYS_ADMIN'])),
            ('guard missing capability', lambda m: m['services']['agent-netguard'].update(cap_add=[])),
            ('other NET_ADMIN', lambda m: m['services']['postgres'].update(cap_add=['NET_ADMIN'])),
            ('skip wrapper', lambda m: m['services']['archguard-platform'].update(entrypoint=['java', '-jar', '/opt/archguard/platform.jar'])),
            ('shell injection', lambda m: m['services']['archguard-platform'].update(command=['java'])),
            ('guard different entry', lambda m: m['services']['agent-netguard'].update(entrypoint=['/bin/sh'])),
            ('guard close at startup', lambda m: m['services']['agent-netguard'].update(command=['close'])),
            ('guard readiness disabled', lambda m: m['services']['agent-netguard']['healthcheck'].update(disable=True)),
            ('guard readiness changed', lambda m: m['services']['agent-netguard']['healthcheck'].update(test=['CMD', 'true'])),
            ('readiness dependency absent', lambda m: m['services']['archguard-platform']['depends_on'].pop('agent-netguard')),
            ('readiness started only', lambda m: m['services']['archguard-platform']['depends_on']['agent-netguard'].update(condition='service_started')),
            ('guard arbitrary context', lambda m: m['services']['agent-netguard']['build'].update(context='/controlled/unreviewed')),
            ('guard arbitrary image', lambda m: m['services']['agent-netguard'].update(image='unreviewed:latest')),
            ('guard unbounded pid', lambda m: m['services']['agent-netguard'].update(pids_limit=0)),
            ('guard unbounded memory', lambda m: m['services']['agent-netguard'].pop('mem_limit')),
        ])
        self.mutations(changes)

    def test_rejects_mount_and_secret_injection_preserves_credential_volumes(self):
        changes = []
        for service in ('archguard-platform', 'agent-netguard'):
            changes.append((service + ' secret', lambda m, s=service: m['services'][s].update(secrets=['synthetic-sensitive-sentinel'])))
            changes.append((service + ' socket', lambda m, s=service: m['services'][s]['volumes'].append(
                {'type': 'bind', 'source': '/var/run/docker.sock', 'target': '/var/run/docker.sock'})))
        changes.extend([
            ('guard source', lambda m: m['services']['agent-netguard']['volumes'].append({'type': 'bind', 'source': '/controlled/source', 'target': '/sources', 'read_only': True})),
            ('guard credential', lambda m: m['services']['agent-netguard']['volumes'].append({'type': 'volume', 'source': 'credential-master', 'target': '/master', 'read_only': True})),
            ('guard writable config', lambda m: m['services']['agent-netguard']['volumes'][0].update(read_only=False)),
            ('guard config wrong target', lambda m: m['services']['agent-netguard']['volumes'][0].update(target='/network.json')),
            ('guard missing config', lambda m: m['services']['agent-netguard'].update(volumes=[])),
            ('master writable', lambda m: m['services']['archguard-platform']['volumes'][4].update(read_only=False)),
            ('master renamed', lambda m: m['services']['archguard-platform']['volumes'][4].update(source='other-master')),
            ('cipher renamed', lambda m: m['services']['archguard-platform']['volumes'][3].update(source='other-cipher')),
            ('master replaced by bind', lambda m: m['services']['archguard-platform']['volumes'][4].update(type='bind')),
            ('cipher readonly', lambda m: m['services']['archguard-platform']['volumes'][3].update(read_only=True)),
            ('hosts writable', lambda m: m['services']['archguard-platform']['volumes'][5].update(read_only=False)),
            ('inventory writable', lambda m: m['services']['archguard-platform']['volumes'][6].update(read_only=False)),
            ('inventory wrong type', lambda m: m['services']['archguard-platform']['volumes'][6].update(type='bind')),
            ('inventory renamed', lambda m: m['services']['archguard-platform']['volumes'][6].update(source='credential-master')),
            ('inventory wrong path', lambda m: m['services']['archguard-platform']['volumes'][6].update(target='/run/other')),
            ('inventory missing', lambda m: m['services']['archguard-platform']['volumes'].pop(6)),
            ('inventory shared with guard', lambda m: m['services']['agent-netguard']['volumes'].append({'type': 'volume', 'source': 'agent-live-inventory', 'target': '/inventory', 'read_only': True})),
            ('inventory shared with web', lambda m: m['services']['archguard-web'].update(volumes=[{'type': 'volume', 'source': 'agent-live-inventory', 'target': '/inventory', 'read_only': True}])),
            ('inventory shared with helper', lambda m: m['services']['credential-check']['volumes'].append({'type': 'volume', 'source': 'agent-live-inventory', 'target': '/inventory', 'read_only': True})),
            ('inventory alias hijacked', lambda m: m['volumes']['agent-live-inventory'].update(name='credential-master')),
            ('wrapper substituted', lambda m: m['services']['archguard-platform']['volumes'][7].update(source='/controlled/unreviewed.sh')),
            ('wrapper writable', lambda m: m['services']['archguard-platform']['volumes'][7].update(read_only=False)),
            ('credential alias hijacked', lambda m: m['volumes']['credential-master'].update(name='other-master')),
        ])
        self.mutations(changes)

    def test_only_guard_can_acquire_capabilities_through_all(self):
        for service in ('credential-init', 'credential-check', 'runtime-init',
                        'scanner-runner', 'postgres', 'keycloak',
                        'archguard-web', 'archguard-platform'):
            for capability in ('ALL', 'CAP_ALL'):
                changed = model()
                changed['services'][service]['cap_add'] = [capability]
                with self.subTest(service=service, capability=capability):
                    self.reject(changed)

    def test_every_controlled_bind_requires_explicit_refusal_to_create_host_path(self):
        for service, target, closed in (
                ('agent-netguard', NETWORK, False),
                ('archguard-platform', '/etc/hosts', False),
                ('archguard-platform', WRAPPER, False),
                ('archguard-web', '/etc/nginx/conf.d/default.conf', True)):
            for mutation in ('create-enabled', 'flag-missing', 'bind-missing'):
                changed = model(closed=closed)
                mount = next(item for item in changed['services'][service]['volumes']
                             if item['target'] == target)
                if mutation == 'create-enabled':
                    mount['bind']['create_host_path'] = True
                elif mutation == 'flag-missing':
                    mount['bind'].pop('create_host_path')
                else:
                    mount.pop('bind')
                with self.subTest(service=service, target=target, mutation=mutation):
                    self.reject(changed, closed=closed)

    def test_rejects_deploy_restart_policy_even_with_service_restart_no(self):
        # The namespace lifecycle has a single fixed restart binding. Reject
        # any deploy restart-policy representation, including explicit none.
        for service in ('archguard-platform', 'agent-netguard'):
            for policy in ({'condition': 'any'}, {'condition': 'on-failure'},
                           {}, {'condition': 'none'}):
                changed = model()
                self.assertEqual(changed['services'][service]['restart'], 'no')
                changed['services'][service]['deploy'] = {'restart_policy': policy}
                with self.subTest(service=service, policy=policy):
                    self.reject(changed)

    def test_inventory_isolation_resolves_physical_volume_aliases(self):
        canonical = model()
        canonical['name'] = 'archguard-task2-synthetic'
        canonical['volumes']['agent-live-inventory']['name'] = 'archguard-task2-synthetic_agent-live-inventory'
        # Explicit rendered physical naming is valid before a second logical
        # source points at the same native volume.
        self.verifier.verify(canonical)
        for service in ('credential-check', 'runtime-init'):
            for external in (False, True):
                changed = copy.deepcopy(canonical)
                changed['volumes']['inventory-alias'] = {
                    'name': 'archguard-task2-synthetic_agent-live-inventory',
                    'external': external}
                changed['services'][service].setdefault('volumes', []).append({
                    'type': 'volume', 'source': 'inventory-alias',
                    'target': '/writable-inventory', 'read_only': False})
                with self.subTest(service=service, external=external):
                    self.reject(changed)

    def test_rejects_proxy_dns_jvm_and_secret_overrides_without_value_echo(self):
        changes = []
        for service in ('archguard-platform', 'agent-netguard'):
            for key, value in (('extra_hosts', ['api.deepseek.com:1.1.1.1']), ('dns', ['1.1.1.1']),
                               ('dns_search', ['example.invalid']), ('dns_opt', ['rotate'])):
                changes.append((service + ':' + key, lambda m, s=service, k=key, v=value: m['services'][s].update({k: v})))
            for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy',
                        'all_proxy', 'NO_PROXY', 'DEEPSEEK_API_KEY', 'OTHER_API_KEY'):
                changes.append((service + ':' + key, lambda m, s=service, k=key: m['services'][s].setdefault('environment', {}).update({k: 'synthetic-sensitive-sentinel'})))
        for key, value in (('JAVA_TOOL_OPTIONS', ''), ('JAVA_TOOL_OPTIONS', '-Djdk.httpclient.disableRetryConnect=false'),
                           ('JAVA_TOOL_OPTIONS', '-Djdk.httpclient.disableRetryConnect=true -Dhttps.proxyHost=synthetic-sensitive-sentinel'),
                           ('JDK_JAVA_OPTIONS', '-Djavax.net.debug=all'), ('_JAVA_OPTIONS', '-Djavax.net.ssl.trustStore=/controlled/other'),
                           ('ARCHGUARD_AGENT_NETWORK_SHA256', ''), ('ARCHGUARD_AGENT_NETWORK_SHA256', 'A' * 64),
                           ('SPRING_PROFILES_ACTIVE', 'oidc,local-compose,agent-synthetic'),
                           ('ARCHGUARD_AGENT_SYNTHETIC_ENABLED', 'true'),
                           ('ARCHGUARD_AGENT_SYNTHETIC_INVENTORY_FILE', '/controlled/unmounted.json')):
            changes.append((key + ':' + value, lambda m, k=key, v=value: m['services']['archguard-platform']['environment'].update({k: v})))
        self.mutations(changes)

    def test_flags_and_enabled_binding_fail_closed(self):
        for flag in FLAGS:
            for bad in ('TRUE', '1', '', True):
                changed = model()
                changed['services']['archguard-platform']['environment'][flag] = bad
                with self.subTest(flag=flag, value=bad):
                    self.reject(changed)
        for flag in WEB_FLAGS:
            changed = model()
            changed['services']['archguard-web']['build']['args'][flag] = '1'
            self.reject(changed)
        for key in BINDINGS:
            for bad in ('', '*', 'latest', 'synthetic-sensitive-sentinel/invalid'):
                changed = model(enabled=True)
                changed['services']['archguard-platform']['environment']['ARCHGUARD_AGENT_LIVE_' + key] = bad
                with self.subTest(binding=key, invalid=bad):
                    self.reject(changed)
        for flag in ('ARCHGUARD_AGENT_ENABLED', 'ARCHGUARD_AGENT_SYNTHETIC_INVENTORY_ENABLED',
                     'ARCHGUARD_CREDENTIAL_MANAGEMENT_ENABLED'):
            changed = model(enabled=True)
            changed['services']['archguard-platform']['environment'][flag] = 'false'
            self.reject(changed)

    def test_closed_model_overrides_every_flag_and_requires_exact_readonly_proxy(self):
        for flag in FLAGS:
            changed = model(closed=True)
            changed['services']['archguard-platform']['environment'][flag] = 'true'
            self.reject(changed, closed=True)
        for flag in WEB_FLAGS:
            changed = model(closed=True)
            changed['services']['archguard-web']['build']['args'][flag] = 'true'
            self.reject(changed, closed=True)
        self.mutations([
            ('closed proxy missing', lambda m: m['services']['archguard-web'].pop('volumes')),
            ('closed proxy writable', lambda m: m['services']['archguard-web']['volumes'][0].update(read_only=False)),
            ('closed proxy substituted', lambda m: m['services']['archguard-web']['volumes'][0].update(source='/controlled/other.conf')),
        ], closed=True)


if __name__ == '__main__':
    unittest.main()
