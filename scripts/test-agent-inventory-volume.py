#!/usr/bin/env python3
"""Root-run native inventory proof on one newly created disposable Docker volume.

Requires an already-built immutable local guard image ID. Never builds/pulls,
uses an existing volume, loads runtime.env, activates Compose or calls a model.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import tempfile
import uuid

INITIALIZER = Path(__file__).with_name("initialize-agent-inventory.py").resolve()
LABEL = "io.archguard.inventory-fixture"


def require(condition, category):
    if not condition:
        raise AssertionError("INVENTORY_FIXTURE_" + category)


def docker(*args, timeout=20, check=True):
    try:
        result = subprocess.run(["docker", *map(str, args)], capture_output=True, text=True, timeout=timeout)
        if check:
            require(result.returncode == 0, "DOCKER_FAILED")
        return result
    except (OSError, subprocess.SubprocessError):
        raise AssertionError("INVENTORY_FIXTURE_DOCKER_FAILED") from None


def synthetic_review():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {"schemaVersion": "0.1.0", "deploymentId": "11111111-1111-4111-8111-111111111111",
            "entries": [{"inventoryId": "22222222-2222-4222-8222-222222222222",
                         "projectId": "33333333-3333-4333-8333-333333333333",
                         "manifestSha256": "a" * 64, "sourceKind": "CONTROLLED_SYNTHETIC_FIXTURES",
                         "fixtureSetVersion": "docker-fixture-only", "fixtureArtifactSha256": "b" * 64,
                         "reviewRef": "synthetic-offline-test-only",
                         "reviewedAt": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                         "expiresAt": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")}]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="already-built local guard sha256 image ID")
    args = parser.parse_args(argv)
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", args.image) is not None, "IMMUTABLE_IMAGE_REQUIRED")
    image = json.loads(docker("image", "inspect", args.image).stdout)
    require(len(image) == 1 and image[0]["Id"] == args.image, "IMAGE_ID_MISMATCH")
    prefix = "archguard-inventory-test-" + uuid.uuid4().hex
    volume_name = prefix + "-volume"
    volume = None
    containers = []
    try:
        with tempfile.TemporaryDirectory(prefix="archguard-inventory-test-") as temporary:
            source = Path(temporary) / "inventory.json"
            original = json.dumps(synthetic_review(), separators=(",", ":")).encode("utf-8")
            source.write_bytes(original)
            # A named volume has no separate numeric ID: its exact returned name
            # plus the unique owner label is its deletion identity.
            volume = docker("volume", "create", "--name", volume_name, "--label", LABEL + "=" + prefix).stdout.strip()
            require(volume == volume_name, "VOLUME_ID_MISMATCH")
            owned = json.loads(docker("volume", "inspect", volume).stdout)
            require(len(owned) == 1 and owned[0]["Name"] == volume_name and
                    owned[0].get("Labels", {}).get(LABEL) == prefix, "VOLUME_OWNERSHIP")

            def execute(suffix, action, *, readonly, user, expected):
                name = prefix + "-" + suffix
                create = ["create", "--pull=never", "--name", name, "--label", LABEL + "=" + prefix,
                          "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
                          "--user", user, "--no-healthcheck", "--pids-limit=32", "--memory=64m",
                          "--env", "PYTHONDONTWRITEBYTECODE=1", "--entrypoint", "python3",
                          "--mount", "type=bind,source=" + str(INITIALIZER) + ",target=/fixture/initializer.py,readonly",
                          "--mount", "type=volume,source=" + volume + ",target=/inventory" + (",readonly" if readonly else "")]
                if action == "initialize":
                    create += ["--mount", "type=bind,source=" + str(source) + ",target=/reviewed/inventory.json,readonly"]
                create += [args.image, "/fixture/initializer.py", action]
                identity = docker(*create).stdout.strip()
                require(re.fullmatch(r"[a-f0-9]{64}", identity) is not None, "CONTAINER_ID")
                containers.append((identity, name))
                model = json.loads(docker("container", "inspect", identity).stdout)[0]
                require(model["Name"] == "/" + name and model["Config"]["Labels"].get(LABEL) == prefix,
                        "CONTAINER_OWNERSHIP")
                host = model["HostConfig"]
                require(host["NetworkMode"] == "none" and host["ReadonlyRootfs"] and
                        host["CapDrop"] == ["ALL"] and not host.get("CapAdd") and not host["Privileged"], "CONTAINER_PRIVILEGES")
                require(model["Config"]["User"] == user, "CONTAINER_USER")
                mounted = [item for item in model["Mounts"] if item["Destination"] == "/inventory"]
                require(len(mounted) == 1 and mounted[0]["Name"] == volume and mounted[0]["RW"] is (not readonly), "VOLUME_MOUNT")
                result = docker("start", "-a", identity, check=False)
                ended = json.loads(docker("container", "inspect", identity).stdout)[0]
                require(ended["State"]["Status"] == "exited" and ended["State"]["ExitCode"] == expected,
                        "CONTAINER_EXIT")
                require(result.returncode in (0, expected) and not result.stderr, "PROCESS_RESULT")
                require(result.stdout.strip() == ("PASS" if expected == 0 else "INVENTORY_UNAVAILABLE"), "SAFE_RESULT")

            execute("initialize", "initialize", readonly=False, user="0:0", expected=0)
            execute("verify", "verify", readonly=True, user="10001:10001", expected=0)
            # New valid reviewed bytes must not overwrite, chmod or repair the
            # already initialized volume; verify its preserved original bytes.
            replacement = synthetic_review()
            replacement["entries"][0]["reviewRef"] = "different-synthetic-test-review"
            source.write_bytes(json.dumps(replacement, separators=(",", ":")).encode("utf-8"))
            execute("overwrite-refused", "initialize", readonly=False, user="0:0", expected=1)
            source.write_bytes(original)
            execute("verify-after-refusal", "verify", readonly=True, user="10001:10001", expected=0)
            # Internal byte comparison only: the host receives no inventory body,
            # IDs or SHA values. The check runs nonroot with both mounts readonly.
            name = prefix + "-unchanged"
            comparison = ("from pathlib import Path; import sys; "
                          "sys.exit(0 if Path('/inventory/inventory.json').read_bytes()=="
                          "Path('/reviewed/inventory.json').read_bytes() else 1)")
            identity = docker("create", "--pull=never", "--name", name, "--label", LABEL + "=" + prefix,
                              "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
                              "--user=10001:10001", "--no-healthcheck", "--pids-limit=32", "--memory=64m",
                              "--mount", "type=volume,source=" + volume + ",target=/inventory,readonly",
                              "--mount", "type=bind,source=" + str(source) + ",target=/reviewed/inventory.json,readonly",
                              "--entrypoint", "python3", args.image, "-c", comparison).stdout.strip()
            require(re.fullmatch(r"[a-f0-9]{64}", identity) is not None, "CONTAINER_ID")
            containers.append((identity, name))
            result = docker("start", "-a", identity, check=False)
            state = json.loads(docker("container", "inspect", identity).stdout)[0]
            require(result.returncode == 0 and state["State"]["Status"] == "exited" and
                    state["State"]["ExitCode"] == 0 and not result.stdout and not result.stderr, "BYTES_CHANGED")
    finally:
        cleanup_failed = False
        for identity, name in reversed(containers):
            inspected = docker("container", "inspect", identity, check=False)
            if inspected.returncode:
                cleanup_failed = True
                continue
            model = json.loads(inspected.stdout)[0]
            if model["Id"] != identity or model["Name"] != "/" + name or not name.startswith(prefix + "-") or \
                    model["Config"].get("Labels", {}).get(LABEL) != prefix:
                cleanup_failed = True
                continue
            cleanup_failed |= docker("rm", "-f", identity, check=False).returncode != 0
        if volume:
            inspected = docker("volume", "inspect", volume, check=False)
            if inspected.returncode:
                cleanup_failed = True
            else:
                model = json.loads(inspected.stdout)[0]
                if model["Name"] != volume_name or volume != volume_name or not volume.startswith(prefix + "-") or \
                        model.get("Labels", {}).get(LABEL) != prefix:
                    cleanup_failed = True
                else:
                    cleanup_failed |= docker("volume", "rm", volume, check=False).returncode != 0
        require(not cleanup_failed, "CLEANUP_FAILED")
    print("PASS: inventory initialized; nonrootReadonly=true; overwriteRefused=true; bytesUnchanged=true; modelCalls=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, ValueError, KeyError, TypeError):
        print("INVENTORY_FIXTURE_FAILED")
        raise SystemExit(1) from None
