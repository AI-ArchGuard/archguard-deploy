#!/bin/sh
set -eu
digest=${ARCHGUARD_AGENT_NETWORK_SHA256-}
case "$digest" in ''|*[!0-9a-f]*) exit 1 ;; esac
[ "${#digest}" -eq 64 ] || exit 1
attempt=0
while [ "$attempt" -lt 30 ]; do
    # --disable must precede every other argument, before curl reads curlrc.
    response=$(curl --disable --noproxy '*' --proto '=http' --connect-timeout 1 --max-time 1 \
        --silent --fail --write-out '\n%{http_code}' http://127.0.0.1:18081/ready 2>/dev/null) || response=''
    expected=$(printf '%s\n200' "$digest")
    if [ "$response" = "$expected" ]; then
        exec java -jar /opt/archguard/platform.jar
    fi
    attempt=$((attempt + 1))
    [ "$attempt" -ge 30 ] || sleep 1
done
exit 1
