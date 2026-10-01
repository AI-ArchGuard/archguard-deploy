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
    for name, service in services.items():
        if name != "archguard-web":
            assert not service.get("ports"), f"Internal service exposed: {name}"
    ports = services["archguard-web"]["ports"]
    assert len(ports) == 1 and ports[0]["host_ip"] == "127.0.0.1" and ports[0]["target"] == 8080
    assert services["scanner-runner"]["network_mode"] == "none"
    assert model["networks"]["backend"]["internal"] is True

if __name__ == "__main__":
    source = sys.stdin.read() if sys.argv[1] == "-" else Path(sys.argv[1]).read_text(encoding="utf-8-sig")
    verify(json.loads(source))
    print("Synthetic Compose profile/network boundaries: PASS")
