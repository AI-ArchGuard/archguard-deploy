#!/bin/sh
set -eu

mkdir -p /mailbox/requests /mailbox/responses /mailbox/cancellations
while true; do
  found=false
  for request in /mailbox/requests/*.request.json; do
    [ -f "$request" ] || continue
    found=true
    base=$(basename "$request" .request.json)
    task="/work/$base"
    cancel="/mailbox/cancellations/$base.cancel"
    status="/mailbox/responses/$base.status.json"
    report="/mailbox/responses/$base.report.json"
    mkdir -p "$task"

    repository=$(jq -er '.repositoryPath' "$request") || repository=''
    rules=$(jq -er '.rulesYamlBase64' "$request") || rules=''
    case "$repository" in ''|/*|*'..'*) exit_code=64 ;; *) exit_code='' ;; esac
    if [ -z "$exit_code" ]; then
      printf '%s' "$rules" | base64 -d > "$task/rules.yaml" || exit_code=64
    fi
    if [ -z "$exit_code" ] && [ ! -d "/sources/$repository" ]; then exit_code=64; fi

    if [ -z "$exit_code" ]; then
      java -jar /opt/archguard/scanner.jar scan "/sources/$repository" --rules "$task/rules.yaml" --output "$task/report.json" >"$task/stdout" 2>"$task/stderr" &
      pid=$!
      deadline=$(( $(date +%s) + 330 ))
      cancelled=false
      while kill -0 "$pid" 2>/dev/null; do
        if [ -f "$cancel" ]; then
          cancelled=true; kill -TERM "$pid" 2>/dev/null || true; sleep 2; kill -KILL "$pid" 2>/dev/null || true; break
        fi
        if [ "$(date +%s)" -ge "$deadline" ]; then
          kill -TERM "$pid" 2>/dev/null || true; sleep 2; kill -KILL "$pid" 2>/dev/null || true; break
        fi
        sleep 1
      done
      if wait "$pid"; then exit_code=0; else exit_code=$?; fi
      if [ "$cancelled" = true ]; then exit_code=130; fi
    fi

    if [ -f "$task/report.json" ]; then mv "$task/report.json" "$report.tmp"; mv "$report.tmp" "$report"; fi
    jq -n --argjson exitCode "$exit_code" '{protocolVersion:"0.1.0",exitCode:$exitCode}' > "$status.tmp"
    mv "$status.tmp" "$status"
    rm -f "$request" "$cancel" "$task/rules.yaml" "$task/stdout" "$task/stderr"
    rmdir "$task" 2>/dev/null || true
  done
  [ "$found" = true ] || sleep 1
done
