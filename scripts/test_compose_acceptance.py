import importlib.util
from pathlib import Path
import unittest
import copy
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("governance", Path(__file__).with_name("verify-governance-compose.py"))
governance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(governance)
config_spec = importlib.util.spec_from_file_location("config", Path(__file__).with_name("verify-agent-compose-config.py"))
config = importlib.util.module_from_spec(config_spec)
config_spec.loader.exec_module(config)


class CredentialCleanupTest(unittest.TestCase):
    def test_cleanup_obtains_fresh_admin_token_instead_of_expired_start_token(self):
        calls = []
        def fake_request(url, method="GET", **kwargs):
            calls.append((url, method, kwargs))
            if url.endswith("/token"):
                return 200, {"access_token": "fresh"}, {}
            self.assertEqual(kwargs["token"], "fresh")
            return 204, {}, {}
        with patch.object(governance, "request", fake_request):
            governance.cleanup_client("http://127.0.0.1:8081", {"ARCHGUARD_LOCAL_KEYCLOAK_ADMIN_PASSWORD": "test-only"}, "id")
        self.assertEqual([c[1] for c in calls], ["POST", "DELETE"])


class ComposeBoundaryTest(unittest.TestCase):
    def model(self):
        return {"services": {"archguard-platform": {"environment": {
            "SPRING_PROFILES_ACTIVE": "oidc,local-compose,agent-synthetic",
            "ARCHGUARD_AGENT_SYNTHETIC_ENABLED": "true",
            "ARCHGUARD_AGENT_SYNTHETIC_SCENARIO": "SUPPORTED",
            "ARCHGUARD_AGENT_PROVIDER_TIMEOUT": "2s"}},
            "archguard-web": {"ports": [{"host_ip": "127.0.0.1", "target": 8080}]},
            "scanner-runner": {"network_mode": "none"}}, "networks": {"backend": {"internal": True}}}

    def test_accepts_local_synthetic_only(self):
        config.verify(self.model())

    def test_rejects_exposure_external_credentials_and_changed_model_boundary(self):
        base = self.model()
        mutations = [
            lambda m: m["services"]["archguard-web"]["ports"][0].update(host_ip="0.0.0.0"),
            lambda m: m["services"]["archguard-platform"].update(ports=[{"target": 8080}]),
            lambda m: m["services"]["archguard-platform"]["environment"].update(DEEPSEEK_API_KEY="test-only"),
            lambda m: m["services"]["archguard-platform"]["environment"].update(ARCHGUARD_AGENT_SYNTHETIC_SCENARIO="real"),
            lambda m: m["networks"]["backend"].update(internal=False),
        ]
        for mutation in mutations:
            model = copy.deepcopy(base)
            mutation(model)
            with self.assertRaises(AssertionError):
                config.verify(model)

    def test_rollback_requires_old_images_closed_model_and_readonly_proxy_guard(self):
        model = self.model()
        platform = model["services"]["archguard-platform"]
        platform["image"] = "archguard/platform:4h-v0.4.0-rollback-local"
        platform["environment"].update(SPRING_PROFILES_ACTIVE="oidc,local-compose", ARCHGUARD_AGENT_ENABLED="false", ARCHGUARD_AGENT_SYNTHETIC_ENABLED="false")
        web = model["services"]["archguard-web"]
        web.update(image="archguard/web:4h-v0.2.0-rollback-local", build={"args": {"VITE_AGENT_UI_ENABLED": "false"}},
                   volumes=[{"type": "bind", "target": "/etc/nginx/conf.d/default.conf", "read_only": True}])
        config.verify_rollback(model)
        mutations = [
            lambda m: m["services"]["archguard-platform"]["environment"].update(ARCHGUARD_AGENT_ENABLED="true"),
            lambda m: m["services"]["archguard-web"]["build"]["args"].update(VITE_AGENT_UI_ENABLED="true"),
            lambda m: m["services"]["archguard-web"]["volumes"][0].update(read_only=False),
            lambda m: m["services"]["archguard-web"].update(image="unpinned:latest"),
        ]
        for mutation in mutations:
            changed = copy.deepcopy(model)
            mutation(changed)
            with self.assertRaises(AssertionError):
                config.verify_rollback(changed)


if __name__ == "__main__":
    unittest.main()
