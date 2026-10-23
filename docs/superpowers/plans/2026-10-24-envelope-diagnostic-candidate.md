# Envelope diagnostic candidate synchronization and closed deployment

> **For agentic workers:** Use superpowers:executing-plans inline, test-driven-development for the source change, and verification-before-completion. Preserve local evidence; do not delete old worktrees or runtime data.

**Goal:** Promote only the reviewed Platform diagnostics merge, then deploy that exact version with all Agent entry/egress controls closed.

**Architecture:** Replace the single Platform candidate `8b547faacd7a7b09992006f677467fffc7b08919` with actual main merge `35e721bb5e612e505ae7a9a3e4b391ea64f1352e`, tree `2da62c06202e18b9dd97f320a7a83c021a6060bd`, successful main CI `39981988430`. Keep all other source identities, validators, public contracts and history semantics. No new dependency.

**Spec:** Owner-approved minimal synchronization and closed-deployment chat scope; [candidate procedure](../../agent-personal-live-candidate.md), [compatibility matrix](../../../compatibility/agent-personal-live.md), [explicit-generation boundaries](../../agent-inventory-generation-design.md), and Platform PR #68's safe-response-diagnostics design. This plan records that approved small change, not new architecture or a model-call permit.

## Global constraints

- Only the exact merged Platform identity is accepted, never PR head `2ed51225de6c6ac02d217fc73982214cbaff34f5`, local `1ba4e4479481b4b2011ab9faed9f3a82ae190d7c`, a moving ref or multiple candidates.
- Keep Docs/Web/Scanner/Samples pins, 21-table schema, audit/ACL checks, V1–V16 migrations, protocol/model/price/quotas, Compose, guard and inventory initializer unchanged.
- Failed batches, UNKNOWN costs/reservations, all old proofs and historical records remain intact. No new proof UUID/volume, enablement, batch, model/Key/account probe, retry or model expense.
- Normal PR/CI/merge only; no protection changes or review bypass. GitHub App repository access requires the owner's explicit action.
- Closed deployment only on existing archguard-agent-4h/8081: update Platform alone, keep five backend switches and three Web build switches false, model kernel egress empty. Preserve guard/Web/DB/OIDC/Runner, namespace, addresses, 12 volumes and 21-table/audit history. 8080 untouched.
- Do not expose Secret/config bodies or private digests. Do not create a release, final acceptance report, rollback capture or stage closure. A closed deployment is not actual live/final-rollback acceptance.

## Review focus

- Both real manifest/snapshot validators accept the exact new merge, with independent literal expectations.
- Former `8b547f`, prior rejected candidates, PR head and equal-tree local identities remain rejected even when snapshot and manifest agree.
- Other candidate fields, source identities, database/audit/ACL checks and historical documentation remain unchanged.
- Fixed diagnostic enums/counts do not widen unknown-field acceptance or establish the discarded real response's cause.
- Source CI, built bytes and observed closed runtime are separate evidence; no fabricated Deploy self-pin or reuse of expired/failed runtime permits.

## Task 1: exact source binding

**Files:** Modify `scripts/test_agent_live_rollback.py`, `scripts/verify-agent-live-rollback.py`, `README.md`, `CHANGELOG.md`, `docs/agent-personal-live-candidate.md`, `compatibility/agent-personal-live.md`; add this plan.

**Interfaces:** Keep `validate_manifest(value)` and `validate_snapshot(snapshot, candidate)`, schema `0.1.0`, kind `PERSONAL_LIVE_FINAL_ROLLBACK`. Produce one new exact Platform pin and the eventual actual Deploy merge/CI evidence consumed by Task 2.

- [x] Run unchanged focused rollback tests; expected clean baseline.
- [x] First update the explicit new-merge positive regression and extend existing negative cases with `8b547f`, `2ed5122` and `1ba4e44`; run both actual validators before changing production or shared fixture. Expected ordinary assertion failures, not import/environment errors.
- [x] Replace only production Platform literal and independent shared positive fixture. Synchronize current matrix/procedure/README and prepend changelog; preserve historical sections. Describe PR #68, 942 Linux tests without skips and successful image build, not actual provider success or runtime proof.
- [ ] Run focused and full scripts/CI-adapter suites, native Windows startup/owner checks, syntax and whitespace; disclose OS skips. Run full native POSIX/Compose/network checks in the unchanged PR/main workflow. Use only temporary synthetic fixtures, no activity on runtime data.
- [ ] Obtain one independent whole-branch review, commit and publish exact tested source, normal SHA-guarded merge, then verify PR/main CI. Stop on missing permission or extra approval requirement; preserve work.

## Task 2: authorized closed-state deployment

**Files:** Only separately protected local operator evidence/config and a clean source build context; no additional tracked implementation.

**Interfaces:** Consume Task 1's actual merged Deploy identity/green CI and exact Platform merge/tree. Never use the old tuple with new application bytes.

- [ ] Recheck source/CI, current complete closed kernel, switches, actual images/namespaces/mounts, private credential integrity and native volume identities. Establish pending=0 and exact 21-table/audit/migration baseline. Refuse changed prerequisites.
- [ ] Build from the actual Platform merge in a clean isolated context, record immutable image and JAR/resource hashes; retain the previous image. No deploy-root/.local/Secret enters any build context.
- [ ] Render and strictly validate all-closed Compose with existing exact mounts/namespace/network config and no source/proof/credential changes. Stop before mutation if Web/guard, addresses, data or other services would need change.
- [ ] Stop only Platform, recheck pending=0, then update only Platform with no dependencies, no build/pull, all switches false and the existing healthy closed guard. No full-stack up, bootstrap, prune, deletion or migration repair.
- [ ] Verify healthy core, actual new image/JAR, unchanged migration resources, full closed kernel/namespace and disabled proxy/entry paths. Compare all 12 volumes, protected integrity and exact 21-table/audit baseline; no new attempts or requests. Preserve private evidence and report limitations honestly.

Compatibility order: existing Docs and Platform PR #68/main CI → unchanged Web consumer → this Deploy PR/main CI → already approved closed Platform deployment. Rollback closes/keeps entry and egress closed, then restores the retained prior application image with the same data/identity/mounts; migrations and history are never reversed.
