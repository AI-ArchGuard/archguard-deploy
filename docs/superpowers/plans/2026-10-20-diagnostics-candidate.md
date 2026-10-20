# Diagnostics candidate synchronization implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for this one coupled task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing exact candidate and rollback binding recognize the tested Platform diagnostics increment, without granting model-call authority.

**Architecture:** Preserve the single-tuple verifier and all 21-table/history checks. Replace only its Platform source pin from `903ddc5987e0f6e63091ee4897d4311b9c41cbe9` to merged main `af821fc99553d462a2176cba5af70be7cc960c75` (main CI `39413909045`); keep all other source pins and public contracts unchanged.

**Tech Stack:** Existing Python stdlib/unittest, Markdown and current CI; no dependency changes.

**Spec:** Existing [candidate procedure](../../agent-personal-live-candidate.md), [compatibility matrix](../../../compatibility/agent-personal-live.md), and the standing stage-4 requirement to bind the actual tested current applications before final rollback evidence. This is a version synchronization of the existing design, not new architecture or model-risk acceptance.

## Global constraints

- No deployment, model/Key/account request, new expense, enablement, inventory reinitialization, release, acceptance report or Issue closure.
- Preserve the already-closed runtime, private manifests, original data/credentials/history and dirty primary checkouts.
- Protocol/model mapping, quotas, trusted accounting, public APIs and V1–V16 migrations remain unchanged.
- The first real batch stopped after failure; candidate metadata does not revive unused summary permission or approve another batch. Historical UNKNOWN charges/reservations remain untouched.

## Review focus

- A current candidate with the exact new Platform pin must pass manifest and snapshot binding.
- The former 1017 Platform pin must fail even when its snapshot agrees with it; no multi-candidate fallback.
- The older 10-15 tuple and altered source/deploy/proof/history values must continue to fail.
- Documentation must not confuse source readiness, closed restoration or a diagnostic comparison with successful real acceptance/final rollback.
- No runtime bootstrap, private data or additional model-call permission may enter this source-only change.

### Task 1: Synchronize the exact diagnostics tuple

**Files:** `scripts/test_agent_live_rollback.py`, `scripts/verify-agent-live-rollback.py`, `README.md`, `CHANGELOG.md`, `docs/agent-personal-live-candidate.md`, `compatibility/agent-personal-live.md`, this plan.

**Interface:** Existing `validate_manifest(value)` / `validate_snapshot(snapshot, candidate)` signatures and schema `0.1.0`; only the exact accepted Platform SHA changes.

- [x] Add independent literal behavioral tests accepting `af821fc99553d462a2176cba5af70be7cc960c75` and rejecting former `903ddc5987e0f6e63091ee4897d4311b9c41cbe9` in otherwise valid manifests/snapshots. Run both before changing the verifier; expect two assertion failures, not import/runtime errors.
- [x] Update only the verifier Platform pin and the independent positive fixture. Synchronize the matrix/readme/procedure with Platform PR #65/main CI, unchanged semantics and the need for fresh real-call authority after the failed batch.
- [x] Run the targeted rollback suite, full `scripts/test_*.py`, CI adapter tests, syntax/whitespace/license/secret checks and isolated Linux equivalents. Expected: no failures; disclose OS-specific skips. Do not use active runtime mounts or Secret/config files.
- [ ] Obtain an independent whole-change review; commit exact tested sources, create/attach a small PR and verify PR/main CI under the standing integration workflow. Keep all phase Issues open and runtime closed; no new operation is authorized by a green check.
