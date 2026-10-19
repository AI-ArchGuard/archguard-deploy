"""Pure guard contracts. Linux sh/kernel enforcement is mandatory in test-agent-network.py."""
import dataclasses
import copy
import hashlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import mock_open, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'netguard'))


def production(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        raise AssertionError('Missing namespace guard implementation: ' + name) from None


def raw(**changes):
    value = dict(schemaVersion='0.1.0', officialIpv4=['8.8.8.8', '1.1.1.1'],
                 postgresIpv4='172.28.0.2', keycloakIpv4='172.28.0.3', webIpv4='172.28.0.4')
    value.update(changes)
    return json.dumps(value).encode()


class ConfigTests(unittest.TestCase):
    def test_missing_allow_official_is_closed_and_config_immutable(self):
        config = production('config').parse_config(raw())
        self.assertIs(config.allow_official, False)
        self.assertEqual(config.official_ipv4, ('8.8.8.8', '1.1.1.1'))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            config.allow_official = True

    def test_digest_is_raw_bytes_and_hosts_are_fixed(self):
        module = production('config')
        data = raw()
        self.assertEqual(module.config_digest(data), hashlib.sha256(data).hexdigest())
        self.assertNotEqual(module.config_digest(data), module.config_digest(data + b' '))
        self.assertEqual(module.hosts_text(module.parse_config(data)),
                         '127.0.0.1 localhost\n172.28.0.2 postgres\n172.28.0.3 keycloak\n'
                         '8.8.8.8 api.deepseek.com\n1.1.1.1 api.deepseek.com\n')

    def test_rejects_malformed_schema_and_nonboolean_switch(self):
        module = production('config')
        cases = [b'\xff', b'[]', b'null', b'{}', raw(extra='x'), raw(schemaVersion='0.2.0'),
                 raw(allowOfficial='true'), raw(allowOfficial=1), raw(allowOfficial=None),
                 raw()[:-1] + b',"schemaVersion":"0.1.0"}', b' ' * 4097,
                 raw()[:-1] + b',"allowOfficial":NaN}', raw(officialIpv4='8.8.8.8')]
        for data in cases:
            with self.subTest(data=data[:30]), self.assertRaises(ValueError):
                module.parse_config(data)
        for key in ('schemaVersion', 'officialIpv4', 'postgresIpv4', 'keycloakIpv4', 'webIpv4'):
            value = json.loads(raw())
            del value[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                module.parse_config(json.dumps(value).encode())

    def test_public_address_boundary_has_no_private_test_exception(self):
        module = production('config')
        bad = ['0.0.0.0', '10.1.1.1', '127.0.0.1', '169.254.1.2', '172.16.0.1',
               '192.168.0.1', '100.64.1.1', '192.0.0.9', '192.0.2.1', '192.88.99.1',
               '198.18.0.1', '198.51.100.1', '203.0.113.1', '224.0.0.1', '240.0.0.1',
               '255.255.255.255', '::1', '::ffff:8.8.8.8', '8.8.8.8/32', '008.8.8.8',
               'api.deepseek.com', '8.8.8.8:443', '8.8.8.8\nflush ruleset', 42, None]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.parse_config(raw(officialIpv4=[value]))
        for values in ([], ['8.8.8.8'] * 2, ['8.8.4.' + str(i) for i in range(1, 18)]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                module.parse_config(raw(officialIpv4=values))

    def test_internal_peers_are_distinct_canonical_rfc1918_only(self):
        module = production('config')
        for key in ('postgresIpv4', 'keycloakIpv4', 'webIpv4'):
            for value in ('8.8.8.8', '127.0.0.1', '100.64.0.1', '172.28.0.02', '::1', '10.0.0.1/24'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    module.parse_config(raw(**{key: value}))
        with self.assertRaises(ValueError):
            module.parse_config(raw(webIpv4='172.28.0.2'))


class RuleTests(unittest.TestCase):
    def commands(self, enabled=False):
        module = production('config')
        return json.loads(module.render_rules(module.parse_config(raw(allowOfficial=enabled))))['nftables']

    def test_transaction_only_adds_owned_table_and_default_drop_chains(self):
        commands = self.commands()
        self.assertTrue(all(set(command) == {'add'} for command in commands[1:]))
        self.assertEqual(commands[0], {'create': {'table': {'family': 'inet', 'name': 'archguard_agent'}}})
        chains = [c['add']['chain'] for c in commands[1:] if 'chain' in c['add']]
        self.assertEqual({c['hook']: c['policy'] for c in chains if c['name'] != 'early_output'},
                         {'input': 'drop', 'output': 'drop', 'forward': 'drop'})
        early = next(c for c in chains if c['name'] == 'early_output')
        self.assertLess(early['prio'], -100)
        self.assertFalse(any(c['add'].get('rule', {}).get('chain') == 'forward' for c in commands[1:]))

    def test_official_set_defaults_empty_and_every_official_packet_checks_set(self):
        for enabled in (False, True):
            commands = self.commands(enabled)
            sets = [c['add']['set'] for c in commands[1:] if 'set' in c['add']]
            self.assertEqual(len(sets), 1)
            self.assertEqual(sets[0]['name'], 'official_v4')
            self.assertEqual(sets[0].get('elem', []), ['8.8.8.8', '1.1.1.1'] if enabled else [])
            rules = [c['add']['rule'] for c in commands[1:] if 'rule' in c['add']]
            provider = [r for r in rules if '@official_v4' in json.dumps(r)]
            self.assertEqual({r['chain'] for r in provider}, {'input', 'output'})
            self.assertEqual(len(provider), 2)
            for rule in provider:
                self.assertIn(443, [e.get('match', {}).get('right') for e in rule['expr']])
            for rule in rules:
                if {'accept': None} in rule['expr']:
                    matches = [e['match'] for e in rule['expr'] if 'match' in e]
                    self.assertTrue(any('payload' in m['left'] for m in matches), 'blanket accept')
                    self.assertFalse(any(m['left'] == {'ct': {'key': 'state'}} and
                                         m['right'] == {'set': ['established', 'related']} for m in matches))

    def test_default_closed_set_omits_nft_invalid_empty_element_array(self):
        # Real nft 1.1.5 rejected elem:[]; an empty set is declared without elem.
        closed = next(command['add']['set'] for command in self.commands()[1:] if 'set' in command['add'])
        self.assertNotIn('elem', closed)
        enabled = next(command['add']['set'] for command in self.commands(True)[1:] if 'set' in command['add'])
        self.assertEqual(enabled['elem'], ['8.8.8.8', '1.1.1.1'])

    def test_early_dns_udp_ipv6_denials_and_exact_internal_ports(self):
        rules = [c['add']['rule'] for c in self.commands()[1:] if 'rule' in c['add']]
        early = [r['expr'] for r in rules if r['chain'] == 'early_output']
        for value in ('ipv6', 'udp', '127.0.0.11', 53, 853):
            self.assertTrue(any(value in [e.get('match', {}).get('right') for e in expr] and
                                {'drop': None} in expr for expr in early), value)
        accepted = [r for r in rules if {'accept': None} in r['expr']]
        for peer, port in (('172.28.0.2', 5432), ('172.28.0.3', 8080), ('172.28.0.4', 8080)):
            exact = [r for r in accepted if peer in [e.get('match', {}).get('right') for e in r['expr']]]
            self.assertEqual(len(exact), 2)
            self.assertTrue(all(port in [e.get('match', {}).get('right') for e in r['expr']] for r in exact))


class GuardTests(unittest.TestCase):
    def test_real_nft_115_readback_attests_without_redundant_protocol_guards(self):
        module = production('guard')
        transaction = production('config').render_rules(production('config').parse_config(
            raw(officialIpv4=['8.8.8.8'], allowOfficial=True)))
        # Frozen independently from root's actual nft 1.1.5 Linux kernel output,
        # not generated by render_rules. nft elides implied protocol dependencies.
        readback = (ROOT / 'scripts/network-fixtures/nft-readback-1.1.5.json').read_text()
        try:
            result = module._attest(transaction, readback)
        except ValueError:
            self.fail('legitimate nft readback rejected')
        self.assertIsNone(result)

    def test_readback_rejects_policy_port_set_omission_and_rule_order_mutations(self):
        module = production('guard')
        transaction = production('config').render_rules(production('config').parse_config(
            raw(officialIpv4=['8.8.8.8'], allowOfficial=True)))
        frozen = json.loads((ROOT / 'scripts/network-fixtures/nft-readback-1.1.5.json').read_text())
        cases = []
        changed = copy.deepcopy(frozen)
        next(item['chain'] for item in changed['nftables'] if item.get('chain', {}).get('name') == 'input')['policy'] = 'accept'
        cases.append(changed)
        changed = copy.deepcopy(frozen)
        next(item['set'] for item in changed['nftables'] if 'set' in item)['elem'] = ['8.8.4.4']
        cases.append(changed)
        changed = copy.deepcopy(frozen)
        rule = next(item['rule'] for item in changed['nftables'] if item.get('rule', {}).get('chain') == 'output')
        next(expr['match'] for expr in rule['expr'] if expr.get('match', {}).get('right') == 8080)['right'] = 9090
        cases.append(changed)
        changed = copy.deepcopy(frozen)
        changed['nftables'].pop()
        cases.append(changed)
        changed = copy.deepcopy(frozen)
        rules = [index for index, item in enumerate(changed['nftables']) if item.get('rule', {}).get('chain') == 'early_output']
        changed['nftables'][rules[0]], changed['nftables'][rules[1]] = changed['nftables'][rules[1]], changed['nftables'][rules[0]]
        cases.append(changed)
        for index, changed in enumerate(cases):
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                module._attest(transaction, json.dumps(changed))

    def test_install_error_or_bad_readback_never_opens_readiness(self):
        module = production('guard')
        cases = [subprocess.CalledProcessError(1, ['nft']), subprocess.TimeoutExpired(['nft'], 5),
                 subprocess.CompletedProcess(['nft'], 0, '{"nftables":[]}', '')]
        for result in cases:
            with self.subTest(result=type(result).__name__):
                def nft(*args, **kwargs):
                    if isinstance(result, Exception):
                        raise result
                    return result
                with patch.object(Path, 'open', mock_open(read_data=raw())), \
                     patch.object(module.subprocess, 'run', side_effect=nft) as external, \
                     patch.object(module.http.server, 'HTTPServer') as server, \
                     patch.object(sys, 'stderr', new_callable=io.StringIO) as error:
                    self.assertNotEqual(module.main(['serve']), 0)
                    self.assertEqual(error.getvalue(), 'network guard operation failed\n')
                    server.assert_not_called()
                    self.assertEqual(external.call_count, 1 if isinstance(result, Exception) else 2)
                    if not isinstance(result, Exception):
                        self.assertEqual(external.call_args.args[0], ['nft', '-j', 'list', 'table', 'inet', 'archguard_agent'])

    def test_close_only_flushes_current_official_set_atomically(self):
        module = production('guard')
        with patch.object(module.subprocess, 'run', return_value=subprocess.CompletedProcess(['nft'], 0, '', '')) as nft:
            self.assertEqual(module.main(['close']), 0)
        args, kwargs = nft.call_args
        self.assertEqual(args[0], ['nft', '-j', '-f', '-'])
        self.assertLessEqual(kwargs['timeout'], 5)
        self.assertEqual(json.loads(kwargs['input']), {'nftables': [{'flush': {'set': {
            'family': 'inet', 'table': 'archguard_agent', 'name': 'official_v4'}}}]})
        with patch.object(module.subprocess, 'run', side_effect=OSError('sensitive detail')), \
             patch.object(sys, 'stderr', new_callable=io.StringIO) as error:
            self.assertNotEqual(module.main(['close']), 0)
            self.assertEqual(error.getvalue(), 'network guard operation failed\n')


if __name__ == '__main__':
    unittest.main()
