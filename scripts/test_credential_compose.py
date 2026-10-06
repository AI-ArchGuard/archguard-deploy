import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('credential_config', Path(__file__).with_name('verify-credential-compose-config.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CredentialComposeTest(unittest.TestCase):
    def setUp(self):
        env = dict(SPRING_PROFILES_ACTIVE='oidc,local-compose', ARCHGUARD_AGENT_ENABLED='false',
                   ARCHGUARD_AGENT_SYNTHETIC_ENABLED='false', ARCHGUARD_CREDENTIAL_OWNER_ID='22222222-2222-4222-8222-222222222222',
                   ARCHGUARD_CREDENTIAL_DEPLOYMENT_ID='33333333-3333-4333-8333-333333333333',
                   ARCHGUARD_CREDENTIAL_UI_ORIGIN='http://localhost:8081', ARCHGUARD_CREDENTIAL_ALLOW_LOOPBACK_HTTP='true',
                   ARCHGUARD_CREDENTIAL_MANAGEMENT_ENABLED='false', ARCHGUARD_CREDENTIAL_DIRECTORY='/var/lib/archguard/credentials',
                   ARCHGUARD_CREDENTIAL_MASTER_FILE='/run/archguard-master/master.key')
        self.model = {'services': {
            'archguard-platform': {'environment': env, 'read_only': True, 'cap_drop': ['ALL'], 'volumes': [
                {'target': '/var/lib/archguard/credentials', 'source': 'cipher', 'type': 'volume'},
                {'target': '/run/archguard-master', 'source': 'master', 'type': 'volume', 'read_only': True}]},
            'archguard-web': {'ports': [{'host_ip': '127.0.0.1', 'target': 8080, 'published': '8081'}],
                              'build': {'args': {'VITE_AGENT_UI_ENABLED': 'false', 'VITE_CREDENTIAL_UI_ENABLED': 'false'}}},
            'scanner-runner': {'network_mode': 'none'},
            'credential-init': {'network_mode': 'none', 'read_only': True, 'cap_drop': ['ALL'], 'cap_add': ['CHOWN'], 'profiles': ['credential-bootstrap']},
            'credential-check': {'network_mode': 'none', 'read_only': True, 'cap_drop': ['ALL'], 'profiles': ['credential-bootstrap'],
                                 'user': '10001:10001', 'volumes': [{'read_only': True}]}},
            'networks': {'backend': {'internal': True}}}

    def test_safe_defaults_and_explicit_enable(self):
        module.verify(self.model)
        self.model['services']['archguard-platform']['environment']['ARCHGUARD_CREDENTIAL_MANAGEMENT_ENABLED'] = 'true'
        self.model['services']['archguard-web']['build']['args']['VITE_CREDENTIAL_UI_ENABLED'] = 'true'
        module.verify(self.model)

    def test_fail_closed_boundaries(self):
        mutations = [
            lambda m: m['services']['archguard-web']['ports'][0].update(host_ip='0.0.0.0'),
            lambda m: m['services']['archguard-platform']['volumes'][1].update(read_only=False),
            lambda m: m['services']['archguard-platform']['volumes'][1].update(source='cipher'),
            lambda m: m['services']['archguard-platform']['environment'].update(ARCHGUARD_AGENT_ENABLED='true'),
            lambda m: m['services']['archguard-platform']['environment'].update(DEEPSEEK_API_KEY='synthetic-forbidden'),
            lambda m: m['services']['credential-init'].update(network_mode='bridge'),
            lambda m: m['services']['credential-check'].update(cap_add=['CHOWN']),
            lambda m: m['services']['scanner-runner'].update(ports=[{'target': 8080}]),
            lambda m: m['services']['archguard-platform']['environment'].update(ARCHGUARD_CREDENTIAL_UI_ORIGIN='http://localhost:8080'),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                model = copy.deepcopy(self.model)
                mutate(model)
                with self.assertRaises(AssertionError):
                    module.verify(model)


if __name__ == '__main__':
    unittest.main()
