"""Bounded, non-secret configuration and namespace-local nft transaction."""
from dataclasses import dataclass
import hashlib
import ipaddress
import json


@dataclass(frozen=True)
class NetworkConfig:
    official_ipv4: tuple[str, ...]
    postgres_ipv4: str
    keycloak_ipv4: str
    web_ipv4: str
    allow_official: bool = False


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('network config invalid')
        value[key] = item
    return value


def _address(value):
    if not isinstance(value, str):
        raise ValueError('network config invalid')
    address = ipaddress.IPv4Address(value)
    if str(address) != value:
        raise ValueError('network config invalid')
    return address


def parse_config(data: bytes) -> NetworkConfig:
    try:
        if not isinstance(data, bytes) or len(data) > 4096:
            raise ValueError()
        value = json.loads(data.decode('utf-8'), object_pairs_hook=_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        required = {'schemaVersion', 'officialIpv4', 'postgresIpv4', 'keycloakIpv4', 'webIpv4'}
        if not isinstance(value, dict) or not required <= value.keys() or value.keys() - required - {'allowOfficial'}:
            raise ValueError()
        if value['schemaVersion'] != '0.1.0' or type(value.get('allowOfficial', False)) is not bool:
            raise ValueError()
        official = value['officialIpv4']
        if not isinstance(official, list) or not 1 <= len(official) <= 16:
            raise ValueError()
        addresses = [_address(item) for item in official]
        # Also exclude Platform PublicDeepSeekExchange's conservative exceptions,
        # including globally classified protocol anycast / transition space.
        excluded = (ipaddress.IPv4Network('192.0.0.0/24'), ipaddress.IPv4Network('192.88.99.0/24'))
        if len(set(addresses)) != len(addresses) or any(not a.is_global or a.is_multicast or
                a.is_reserved or any(a in block for block in excluded) for a in addresses):
            raise ValueError()
        peers = [_address(value[key]) for key in ('postgresIpv4', 'keycloakIpv4', 'webIpv4')]
        private = tuple(ipaddress.IPv4Network(block) for block in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        if len(set(peers)) != 3 or any(not any(a in block for block in private) for a in peers):
            raise ValueError()
        return NetworkConfig(tuple(official), *(str(a) for a in peers), value.get('allowOfficial', False))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('network config invalid') from None


def config_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hosts_text(config: NetworkConfig) -> str:
    return ('127.0.0.1 localhost\n' + config.postgres_ipv4 + ' postgres\n' +
            config.keycloak_ipv4 + ' keycloak\n' +
            ''.join(ip + ' api.deepseek.com\n' for ip in config.official_ipv4))


def render_rules(config: NetworkConfig) -> str:
    """JSON nft input is also the semantic representation used for readback."""
    family, table = 'inet', 'archguard_agent'
    commands = [{'create': {'table': {'family': family, 'name': table}}}]

    def add(kind, **value):
        commands.append({'add': {kind: dict(family=family, table=table, **value)}})

    add('set', name='official_v4', type='ipv4_addr',
        **({'elem': list(config.official_ipv4)} if config.allow_official else {}))
    for chain, priority, policy in (('early_output', -310, 'accept'), ('input', 0, 'drop'),
                                     ('output', 0, 'drop'), ('forward', 0, 'drop')):
        add('chain', name=chain, type='filter', hook='output' if chain == 'early_output' else chain,
            prio=priority, policy=policy)

    def match(left, right):
        return {'match': {'op': '==', 'left': left, 'right': right}}

    def meta(key, value):
        return match({'meta': {'key': key}}, value)

    def payload(protocol, field, value):
        return match({'payload': {'protocol': protocol, 'field': field}}, value)

    def rule(chain, expressions, action='accept'):
        add('rule', chain=chain, expr=expressions + [{action: None}])

    rule('early_output', [meta('nfproto', 'ipv6')], 'drop')
    rule('early_output', [meta('l4proto', 'udp')], 'drop')
    rule('early_output', [payload('ip', 'daddr', '127.0.0.11')], 'drop')
    for port in (53, 853):
        rule('early_output', [payload('tcp', 'dport', port)], 'drop')
    # Typed ip/tcp payloads imply their protocol dependencies; nft removes
    # redundant explicit meta tests during listing. Emit that same exact form.
    established = match({'ct': {'key': 'state'}}, 'established')
    initiating = match({'ct': {'key': 'state'}}, {'set': ['new', 'established']})
    for port in (8080, 18081):
        addresses = [payload('ip', 'saddr', '127.0.0.1'), payload('ip', 'daddr', '127.0.0.1')]
        for chain in ('input', 'output'):
            rule(chain, addresses + [payload('tcp', 'dport', port), initiating])
            rule(chain, addresses + [payload('tcp', 'sport', port), established])
    for peer, port in ((config.postgres_ipv4, 5432), (config.keycloak_ipv4, 8080)):
        rule('output', [payload('ip', 'daddr', peer), payload('tcp', 'dport', port), initiating])
        rule('input', [payload('ip', 'saddr', peer), payload('tcp', 'sport', port), established])
    rule('input', [payload('ip', 'saddr', config.web_ipv4), payload('tcp', 'dport', 8080), initiating])
    rule('output', [payload('ip', 'daddr', config.web_ipv4), payload('tcp', 'sport', 8080), established])
    rule('output', [payload('ip', 'daddr', '@official_v4'), payload('tcp', 'dport', 443), initiating])
    rule('input', [payload('ip', 'saddr', '@official_v4'), payload('tcp', 'sport', 443), established])
    return json.dumps({'nftables': commands}, separators=(',', ':'))
