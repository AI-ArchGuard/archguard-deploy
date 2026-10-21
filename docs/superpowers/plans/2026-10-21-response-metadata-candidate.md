# Response metadata candidate synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for this one coupled version-synchronization task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind the existing exact rollback candidate to the owner-approved response metadata implementation and latest tested Platform merge, without granting runtime authority.

**Architecture:** Replace only the Platform source pin `af821fc99553d462a2176cba5af70be7cc960c75` with current merged main `8b547faacd7a7b09992006f677467fffc7b08919` (tree `07bf49de3552741ae9b005c458f391e25f233685`, main CI `39565721127`). Keep a single tuple, public signatures, all other source pins, 21-table snapshot and history controls. This follows the existing diagnostics-candidate synchronization workflow; no new architecture or risk decision.

**Tech Stack:** Existing Python stdlib/unittest and Markdown; no new dependency.

**Spec:** [Candidate procedure](../../agent-personal-live-candidate.md), [current compatibility matrix](../../../compatibility/agent-personal-live.md), [approved explicit-generation boundaries](../../agent-inventory-generation-design.md), and Platform's approved `docs/technical-design/v0.5-agent-response-metadata-compatibility.md`. The standing stage-4 goal requires actual current tested application bindings before any later runtime proof.

## Global Constraints

- No deployment, actual proof-volume creation/selection, private `.local`/Secret reads, model/Key/account requests or fees, source review/batch approval, release, final acceptance report or stage closure.
- Preserve old immutable volumes, stopped/revoked/UNKNOWN history, reservations, ciphertext, user modifications and the maximum24h proof lifetime. No retry or revived summary allowance.
- Protocol, endpoint, request projection, models, prices, quotas, Web/API/Scanner contracts, production guard/initializer and V1–V16 migrations remain unchanged. Only already-approved inert metadata forms are described; unknown fields remain rejected.
- Exact accepted Platform identity is the actual merge SHA, not equal-tree local HEAD `dfb1f9541323b80ee46eb527e333e5f27b279be9`, intermediate metadata merge `c461f6be3cac6f226750d64cdb877f412a5b9bb4`, moving `main`, or multi-candidate fallback. Deploy self-pin is supplied only after its own merge/main CI; do not fake it in source.
- Compatibility order: existing Docs/Platform approvals and main CI → unchanged Web consumer → Deploy source pin/tests/PR/main CI → separately approved actual closed deployment/proof generation → separately approved real acceptance. Application rollback closes entry/egress first and retains migrations/history/credentials.

## Review Focus

- New exact merge identity accepted in both manifest and snapshot, independent literal fixture; both tested below.
- Superseded diagnostics and intermediate/equal-tree local commits rejected even with self-consistent snapshots; all tested below.
- Other source pins, schema and all21 history checks unchanged; existing full contract suite retained.
- Metadata compatibility described as a bounded approved change, not arbitrary unknown-field acceptance or an explanation of historical failures.
- Source/CI readiness is not actual artifact identity, runtime closure, a model-call permit or successful live/final rollback acceptance; private runtime evidence remains untouched.

### Task 1: Synchronize the exact metadata/history candidate

**Files:** `scripts/test_agent_live_rollback.py`, `scripts/verify-agent-live-rollback.py`, `README.md`, `CHANGELOG.md`, `docs/agent-personal-live-candidate.md`, `compatibility/agent-personal-live.md`, this plan.

**Interfaces:** Consume and retain `validate_manifest(value)` / `validate_snapshot(snapshot, candidate)`, schema `0.1.0`, kind `PERSONAL_LIVE_FINAL_ROLLBACK`. Produce only the updated single exact Platform pin, no API/schema/signature change.

- [x] Rename the existing current-candidate positive test for response metadata and use literal `8b547faacd7a7b09992006f677467fffc7b08919`; exercise both actual manifest and snapshot validators independently. Add negative cases for literal `af821fc99553d462a2176cba5af70be7cc960c75`, `c461f6be3cac6f226750d64cdb877f412a5b9bb4` and `dfb1f9541323b80ee46eb527e333e5f27b279be9` in otherwise valid, self-consistent manifest/snapshot pairs. Retain old903/engineering-tuple rejection and every existing history/assertion.
- [x] Run only those two methods before changing production pin/positive fixture. Expected: ordinary assertion failures accepting the new merge/rejecting old diagnostics, no import/environment error.
- [x] Change only `CANDIDATES.platform` and the independent shared positive fixture to the exact new merge. Update current matrix/README/procedure with PR66+67, actual main CI919/0/0/0, bounded four-field rules and unchanged external/consumer/history boundaries. Prepend changelog entry; do not rewrite historical entries/plans or claim actual hosted response fixed.
- [x] Run focused rollback suite, complete scripts suite, CI adapter suite, Python syntax, whitespace/canonical license/no-sensitive-diff checks. Use bundled Python `C:/Users/Lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`; expected zero failures, disclose existing OS skips. No real runtime/config/volume operations. Mandatory Linux/native/full Compose checks run in unchanged PR/main workflow.
- [ ] Self-review and commit exact tested change; fresh whole-branch reviewer on most capable model, then normal source-tree/SHA-guarded publication/merge under standing workflow and verify PR/main CI. Preserve working trees and all stage Issues; no new operational authority follows.
