#!/usr/bin/env python3
"""Verify a rendered synthetic-only Compose model, never print environment secrets."""
import json
from pathlib import Path
import sys

def verify(model):
    services = model["services"]
    platform = services["archguard-platform"]
    environment = platform["environment"]
    assert environment["SPRING_PROFILES_ACTIVE"] == "oidc,local-compose,agent-synthetic"
    assert environment["ARCHGUARD_AGENT_SYNTHETIC_ENABLED"] == "true"
    assert environment["ARCHGUARD_AGENT_SYNTHETIC_SCENARIO"] in {
        "SUPPORTED", "OUTPUT_INVALID", "CITATION_INVALID", "TIMEOUT", "UNAVAILABLE"}
    assert environment["ARCHGUARD_AGENT_PROVIDER_TIMEOUT"] == "2s"
    assert not any("DEEPSEEK" in key or "API_KEY" in key for key in environment)
    verify_networks(model)


def verify_networks(model):
    services = model["services"]
    for name, service in services.items():
        if name != "archguard-web":
            assert not service.get("ports"), f"Internal service exposed: {name}"
    ports = services["archguard-web"]["ports"]
    assert len(ports) == 1 and ports[0]["host_ip"] == "127.0.0.1" and ports[0]["target"] == 8080
    assert services["scanner-runner"]["network_mode"] == "none"
    assert model["networks"]["backend"]["internal"] is True


def verify_rollback(model):
    verify_networks(model)
    platform = model["services"]["archguard-platform"]
    web = model["services"]["archguard-web"]
    assert platform["image"] == "archguard/platform:4h-v0.4.0-rollback-local"
    assert web["image"] == "archguard/web:4h-v0.2.0-rollback-local"
    environment = platform["environment"]
    assert environment["SPRING_PROFILES_ACTIVE"] == "oidc,local-compose"
    assert environment["ARCHGUARD_AGENT_ENABLED"] == environment["ARCHGUARD_AGENT_SYNTHETIC_ENABLED"] == "false"
    assert not any("DEEPSEEK" in key or "API_KEY" in key for key in environment)
    assert web["build"]["args"]["VITE_AGENT_UI_ENABLED"] == "false"
    guard = [v for v in web["volumes"] if v["target"] == "/etc/nginx/conf.d/default.conf"]
    assert len(guard) == 1 and guard[0]["type"] == "bind" and guard[0]["read_only"] is True

if __name__ == "__main__":
    source = sys.stdin.read() if sys.argv[1] == "-" else Path(sys.argv[1]).read_text(encoding="utf-8-sig")
    verifier = verify_rollback if len(sys.argv) == 3 and sys.argv[2] == "--rollback" else verify
    verifier(json.loads(source))
    print("Compose profile/network boundaries: PASS")
