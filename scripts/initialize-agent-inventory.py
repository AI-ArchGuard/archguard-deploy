#!/usr/bin/env python3
"""Validate reviewed bytes and initialize one explicitly new, empty inventory volume.

Run manually with network none and cap_drop ALL. This is not a runtime service,
an approval issuer, a credential tool, a repair command or a rotation mechanism.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import stat
import uuid

REVIEW_FILE = Path("/reviewed/inventory.json")
VOLUME_DIR = Path("/inventory")
DESTINATION = Path("/inventory/inventory.json")
MAX_BYTES = 32768
ROOT_FIELDS = {"schemaVersion", "deploymentId", "entries"}
ENTRY_FIELDS = {"inventoryId", "projectId", "manifestSha256", "sourceKind", "fixtureSetVersion",
                "fixtureArtifactSha256", "reviewRef", "reviewedAt", "expiresAt"}


def require(condition):
    if not condition:
        raise AssertionError("INVENTORY_UNAVAILABLE")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def canonical_uuid(value):
    require(isinstance(value, str) and len(value) == 36)
    require(str(uuid.UUID(value)) == value)


def reference(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is not None)
    require(not value.lower().startswith(("sk-", "ghp_", "github_pat_")))


def instant(value):
    require(isinstance(value, str) and len(value) <= 64)
    require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value) is not None)
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None)
    return result


def validate_inventory(raw, now):
    """Pure strict validation; return content, never create or extend its proof."""
    try:
        require(isinstance(raw, bytes) and 1 <= len(raw) <= MAX_BYTES)
        require(isinstance(now, datetime) and now.utcoffset() == timedelta(0))
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique_object,
                           parse_constant=lambda _: require(False))
        require(isinstance(value, dict) and set(value) == ROOT_FIELDS)
        require(value["schemaVersion"] == "0.1.0")
        canonical_uuid(value["deploymentId"])
        entries = value["entries"]
        require(isinstance(entries, list) and 1 <= len(entries) <= 20)
        seen = set()
        for entry in entries:
            require(isinstance(entry, dict) and set(entry) == ENTRY_FIELDS)
            for key in ("inventoryId", "projectId"):
                canonical_uuid(entry[key])
            require(entry["inventoryId"] not in seen)
            seen.add(entry["inventoryId"])
            for key in ("manifestSha256", "fixtureArtifactSha256"):
                require(isinstance(entry[key], str) and re.fullmatch(r"[a-f0-9]{64}", entry[key]) is not None)
            require(entry["sourceKind"] == "CONTROLLED_SYNTHETIC_FIXTURES")
            reference(entry["fixtureSetVersion"])
            reference(entry["reviewRef"])
            reviewed, expires = instant(entry["reviewedAt"]), instant(entry["expiresAt"])
            require(reviewed <= now < expires and reviewed < expires <= reviewed + timedelta(hours=24))
        return value
    except (AssertionError, ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise AssertionError("INVENTORY_UNAVAILABLE") from None


def no_links(path):
    require(path.is_absolute() and path == path.resolve(strict=True))
    for part in (path, *path.parents):
        require(not stat.S_ISLNK(part.lstat().st_mode))


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_file(path, *, directory_fd=None, expected_mode=None):
    """Read at most MAX_BYTES+1 through a nofollow descriptor and detect changes."""
    no_links(path)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(path.name if directory_fd is not None else path, flags, dir_fd=directory_fd)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 1 <= before.st_size <= MAX_BYTES)
        if expected_mode is not None:
            require(before.st_uid == 0 and stat.S_IMODE(before.st_mode) == expected_mode)
        chunks, length = [], 0
        while length <= MAX_BYTES:
            block = os.read(fd, MAX_BYTES + 1 - length)
            if not block:
                break
            chunks.append(block)
            length += len(block)
        raw = b"".join(chunks)
        require(1 <= len(raw) <= MAX_BYTES)
        require(identity(before) == identity(os.fstat(fd)) == identity(path.lstat()))
        no_links(path)
        return raw
    finally:
        os.close(fd)


def volume_directory(final=False):
    require(os.name == "posix" and hasattr(os, "O_NOFOLLOW"))
    no_links(VOLUME_DIR)
    require(DESTINATION.parent == VOLUME_DIR and DESTINATION.name == "inventory.json")
    fd = os.open(VOLUME_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0)
        mode = stat.S_IMODE(info.st_mode)
        require(mode == 0o555 if final else mode in (0o700, 0o755))
        require((info.st_dev, info.st_ino) == (VOLUME_DIR.lstat().st_dev, VOLUME_DIR.lstat().st_ino))
        return fd
    except BaseException:
        os.close(fd)
        raise


def initialize(*, now=None):
    directory_fd = file_fd = None
    try:
        require(os.name == "posix" and os.geteuid() == 0)
        now = datetime.now(timezone.utc) if now is None else now
        directory_fd = volume_directory()
        require(os.listdir(directory_fd) == [])
        raw = read_file(REVIEW_FILE)
        validate_inventory(raw, now)
        # Recheck emptiness immediately before exclusive creation; never modify
        # an existing entry, even when it belongs to an earlier failed attempt.
        require(os.listdir(directory_fd) == [])
        file_fd = os.open("inventory.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=directory_fd)
        offset = 0
        while offset < len(raw):
            written = os.write(file_fd, raw[offset:])
            require(type(written) is int and 0 < written <= len(raw) - offset)
            offset += written
        os.fsync(file_fd)
        os.fchmod(file_fd, 0o444)
        os.fsync(file_fd)
        require(os.listdir(directory_fd) == ["inventory.json"])
        os.fchmod(directory_fd, 0o555)
        os.fsync(directory_fd)
        os.close(file_fd)
        file_fd = None
        require(read_file(DESTINATION, directory_fd=directory_fd, expected_mode=0o444) == raw)
        require(stat.S_IMODE(os.fstat(directory_fd).st_mode) == 0o555)
        no_links(VOLUME_DIR)
    except (AssertionError, OSError, ValueError, TypeError):
        # A failed exclusive write remains visible. No repair, cleanup or retry.
        raise AssertionError("INVENTORY_INITIALIZE_FAILED") from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def verify(*, now=None):
    directory_fd = None
    try:
        now = datetime.now(timezone.utc) if now is None else now
        directory_fd = volume_directory(final=True)
        require(os.listdir(directory_fd) == ["inventory.json"])
        first = read_file(DESTINATION, directory_fd=directory_fd, expected_mode=0o444)
        validate_inventory(first, now)
        require(read_file(DESTINATION, directory_fd=directory_fd, expected_mode=0o444) == first)
        require(os.listdir(directory_fd) == ["inventory.json"])
        no_links(VOLUME_DIR)
    except (AssertionError, OSError, ValueError, TypeError):
        raise AssertionError("INVENTORY_VERIFY_FAILED") from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("initialize", "verify"))
    args = parser.parse_args(argv)
    try:
        (initialize if args.action == "initialize" else verify)()
        print("PASS")
        return 0
    except AssertionError:
        print("INVENTORY_UNAVAILABLE")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
