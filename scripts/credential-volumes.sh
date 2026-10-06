#!/bin/sh
# Only bootstrap fresh, empty Docker volumes. Never rotate or repair existing secrets.
set -eu
umask 077
fail() { echo 'Credential volume setup refused; restore operator-managed state.' >&2; exit 1; }
directory() {
  test -d "$1" && test ! -L "$1" || fail
  test "$(stat -c '%u:%g:%a' "$1")" = '10001:10001:700' || fail
}
case "${1:-}" in
  initialize)
    test "$(id -u)" = 0 || fail
    # Stat mount roots without entering private directories. Validation runs as app UID.
    if test "$(stat -c '%u' /master)" = 10001 && test "$(stat -c '%u' /ciphertext)" = 10001; then
      directory /master
      directory /ciphertext
      echo 'Existing private volumes retained; run the unprivileged verifier.'
      exit 0
    fi
    for path in /master /ciphertext; do
      test -d "$path" && test ! -L "$path" || fail
      test "$(stat -c '%u:%g' "$path")" = '0:0' || fail
      test -z "$(find "$path" -mindepth 1 -maxdepth 1 -print -quit)" || fail
    done
    # A partial/crashed bootstrap is refused on the next attempt, never silently reset.
    # Exclusive shell creation also refuses a concurrent bootstrap's newly created file.
    (set -C; dd if=/dev/urandom bs=32 count=1 2>/dev/null > /master/master.key) || fail
    test "$(stat -c '%s' /master/master.key)" = 32 || fail
    chmod 0400 /master/master.key
    chown 10001:10001 /master/master.key
    chmod 0700 /master /ciphertext
    chown 10001:10001 /master /ciphertext
    echo 'Independent master and ciphertext volumes initialized.'
    ;;
  verify)
    test "$(id -u)" = 10001 || fail
    directory /master
    directory /ciphertext
    test -f /master/master.key && test ! -L /master/master.key || fail
    test "$(stat -c '%u:%g:%a:%s' /master/master.key)" = '10001:10001:400:32' || fail
    test -r /master/master.key || fail
    test "$(find /master -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ')" = 1 || fail
    for path in /ciphertext/* /ciphertext/.[!.]* /ciphertext/..?*; do
      test -e "$path" || { test ! -L "$path" || fail; continue; }
      test "$path" = /ciphertext/deepseek.credential || fail
      test -f "$path" && test ! -L "$path" || fail
      test "$(stat -c '%u:%g:%a' "$path")" = '10001:10001:600' || fail
      test "$(stat -c '%s' "$path")" -le 512 || fail
    done
    echo 'Private volume ownership, modes and master size: PASS (no secret readback).'
    ;;
  *) fail ;;
esac
