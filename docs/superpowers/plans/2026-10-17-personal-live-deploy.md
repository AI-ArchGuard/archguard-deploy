# Personal Live Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a default-closed local candidate with enforced provider destination isolation and complete read-only rollback-history verification, without deploying or making a model request.

**Architecture:** A namespace-local nftables guard owns networking; nonroot Platform admits Java only after loopback configuration readiness. Separate rendered-model and historical-snapshot verifiers retain existing synthetic/credential semantics.

**Tech Stack:** Docker Compose 5.5.1 for the verified live render contract (not a blanket >=2.24.4 guarantee), existing pinned Alpine-based image, nftables 1.1.5-r2, Python 3.12+ stdlib, POSIX sh, existing PowerShell checks; no SDK/pip/npm dependency.

**Spec:** `docs/superpowers/specs/2026-10-17-personal-live-deploy-design.md`

## Global Constraints

- No active runtime/Keycloak/DB/volume changes, runtime Secret access, official model/account requests, release, or stage closure in implementation.
- All new live/Agent/inventory/credential/UI switches default false; official destination set is empty by default.
- Only guard NET_ADMIN, no privileged/host/Docker socket/Secret/source mounts; Platform UID10001, cap_drop ALL, readonly, restart no, namespace only.
- Exact api.deepseek.com IPv4:443, exact DB/OIDC/Web peers; early DNS/UDP/IPv6 denial; no blanket loopback/established or automatic retries/proxy/redirects.
- Guard crash retains filtering, not instantaneous revocation; coordinated namespace replacement stops Platform first. Java never starts before same-namespace readiness.
- Preserve migrated V1–V16, credential volumes/stable deployment UUID, deterministic findings/gates/exit codes; no Gateway/Evals/Scanner Schema change.
- Keep historical synthetic verifier/report unchanged; final new snapshot contains no raw model/source/document/audit/Secret content.
- Root owns all test/build/Docker/commit commands. Workers edit only assigned files, pause tests-first for root RED, then root GREEN. No concurrent source writes during verification. No nested subagents.

## Review Focus

- Embedded Docker DNS translated before normal OUTPUT must never relay a request; early-hook kernel test owns this in Task1.
- Hostile curlrc/proxy env cannot emit a pre-firewall startup request; execute actual wrapper against controlled local responders in Task1.
- Existing keepalive must cease after official set closure, even with conntrack state; isolated fake-TCP test in Task1.
- Compose merge must remove Platform's inherited networks, not append a public interface; actual render and mutation tests in Task2.
- Same audit row count can hide deletion/mutation plus append; UUID-bound historical digests and exact allowed append triples in Task3.

## Task 1: Namespace guard and bounded Java startup

**Files:** Create `netguard/config.py`, `netguard/guard.py`, `netguard/platform-start.sh`, `netguard/Dockerfile`, `netguard/DEPENDENCIES.md`, `scripts/test_network_guard.py`, `scripts/test-agent-network.py` and test-only fixture helper(s) under `scripts/network-fixtures/` if needed. Modify `.gitattributes` only to force netguard shell LF.

**Interfaces:**
- Consumes the spec's exact six-key network JSON, max4096 UTF-8 bytes; fixed CLI input `/run/archguard-network/network.json`.
- Produces `parse_config(data: bytes) -> NetworkConfig`, `render_rules(config: NetworkConfig) -> str`, `hosts_text(config: NetworkConfig) -> str`, `config_digest(data: bytes) -> str` in config.py. NetworkConfig is immutable. No partial/default coercion except documented allowOfficial defaultfalse; reject duplicate/unknown fields.
- guard.py CLI `serve` installs owned table atomically, refuses existing same table, readback-verifies, then serves exact digest on IPv4 GET `/ready`; `close` atomically flushes only official set; `health` checks bounded local response/config digest. Subprocess timeout<=5s, readiness request<=1s, no raw errors/values. Read only fixed config, no network resolution. No readiness on any setup error; signal/close never flush entire ruleset.
- platform-start.sh consumes `ARCHGUARD_AGENT_NETWORK_SHA256` (exact lowercase64hex) and fixed localhost18081; produces `exec java -jar /opt/archguard/platform.jar` only after exact digest, bounded30x1s probe/1s interval. No unsafe option/URL/command injection; no args supplied by request.
- Docker image uses spec's pinned cached base, apk nftables=1.1.5-r2 + supported Python3.12, no runtime installation; no default Postgres entrypoint. Record licenses/actual-version limitations, no model SDK.

- [ ] Step1: Add tests with independent valid JSON/expected addresses. Assert defaultfalse leaves official set empty; all malformed/duplicate/mapped/private official/IPv6/too many/oversize/injection/nonboolean cases reject. Assert emitted real nft boundary has only exact tuples/early drops and close keeps base restrictions. Execute guard against fake nft subprocess to prove setup failure/no ready, not only grep source. Add actual fixed-loopback health slow-header/body total-deadline regressions and fast strict-framing controls; actual socketpair TCP segmented/coalesced/short-frame controls. Execute actual shell wrapper using controlled marker-only PATH and real curl for missing/mismatch/redirect/proxy/curlrc/valid readiness; no external target. Docker DNS tests query only the verified existing owned peer name, prove UDP/TCP resolution in the same namespace before installing guard, then require denial of the same queries afterward.
- [ ] Step2: Root runs `py -3.14 -m unittest discover -s scripts -p 'test_network_guard.py'`, records expected assertion RED before implementation. Stubs are permitted to expose missing behavior, not to fake passing actions.
- [ ] Step3: Implement only above interfaces, fixed controls, strict public-address conservative subset consistent with provider. Keep test-only networking injection out of production parser/CLI.
- [ ] Step4: Root runs focused + all Python script suite; implementer pauses source edits. Root builds guarded image, records actual package/image IDs.
- [ ] Step5: Add/execute `py -3.14 scripts/test-agent-network.py --image <built-id> --platform-image <cached-shell-test-image-id>`. Unique temporary containers/networks only, all Docker bridges private/internal, no host ports/volumes/internet. Fake listeners use known local peer tuples; official public-shaped /32 lives only on the owned fakepeer loopback, reached over namespace-only veth/private /30 links (different names/subnets for main/default-closed guards). NET_ADMIN-only helper joins owned fakepeer network + owned guard PID namespace, verifies namespace IDs and discovered peer index before moving interface; no host namespace/SYS_ADMIN/NAT/public bridge route. Production parser/filter remain unchanged. Test correct/wrongIP/port, all DNS forms/IPv6/UDP, readonly Platform-only hosts isolation, guardfailure/no ready and sharednamespace startup. While owner guard is alive, official close must stop already-established traffic and preserve DB/OIDC/Web continuity. Capture complete owned nft readback after close, kill owner, compare unchanged owned semantics excluding metainfo via owned NET_ADMIN helper, verify live allowed/forbidden loopback ports and failed Java admission. Docker owner exit may remove bridge interfaces/routes; do not assert post-crash business availability or infer security from that disappearance. Cleanup only exact test IDs it created, never prune or active names. Report modelCalls=0; network failure stops gate, no relaxation.
- [ ] Step6: Root records tested tree/diff/report and dispatches independent task spec+quality review. Fix/retest/scoped review before Task2.

## Task 2: Default-closed Compose contract and entry closure

**Files:** Create `compose.agent-live.yaml`, `compose.agent-live-closed.yaml`, `scripts/verify-agent-live-compose-config.py`, `scripts/test_live_compose.py`; modify `scripts/verify-agent-compose-config.py`, `scripts/verify-credential-compose-config.py`, their existing test models, `rollback/web.nginx.conf`. Task3 owns CI/docs integration.

**Interfaces:**
- Consumes Task1 image/build context, fixed config/hosts/start-wrapper paths and readiness digest; no guard paths or secrets exposed via API.
- Produces live model base+personal+live with Platform network_mode service:agent-netguard, networks reset, alias on guardbackend, dedicatedegress onlyguard, exact pre-Java wrapper, profile oidc,local-compose,agent-live, safeJAVA_TOOL_OPTIONS, noautomaticrestart, no extra_hosts/DNS/proxy overrides. Only127.0.0.1Webport. Existing DB/OIDC definitions unchanged.
- New env names exactly `ARCHGUARD_AGENT_ENABLED`, `ARCHGUARD_AGENT_LIVE_ENABLED`, `ARCHGUARD_AGENT_SYNTHETIC_INVENTORY_ENABLED`, `ARCHGUARD_CREDENTIAL_MANAGEMENT_ENABLED`, `ARCHGUARD_AGENT_UI_ENABLED`, `ARCHGUARD_AGENT_LIVE_UI_ENABLED`, `ARCHGUARD_CREDENTIAL_UI_ENABLED` defaultfalse; synthetic false. Runtime binding `ARCHGUARD_AGENT_LIVE_PROJECT_ID`, `...BATCH_ID`, `...NETWORK_CHECK_REF`, `...SECRET_CHECK_REF` empty defaultallowed onlylivefalse. Inventory uses dedicated nonSecret named volume `agent-live-inventory`, Platform-only readonly `/run/archguard-inventory`, exact existing env `ARCHGUARD_AGENT_SYNTHETIC_INVENTORY_FILE=/run/archguard-inventory/inventory.json`. Actual Windows readonlybind mode0777 is incompatible with unchanged Platform provenance checks; later bounded once-only nativePOSIX bootstrap directory0555/file0444, no overwrite/symlink and no auto-init/live service; root/Task3 owns that follow-up.
- New `verify(model: dict, *, closed: bool=False) -> None` validates complete renderedmodel; errors contain categories only. Existing two verifiers retain originalmode and now assert Platform backend-only. closedoverridereturns allflagsfalse and fixedreadonly rollbackproxy; firewall close explicitlyseparateoperatoraction.

- [ ] Step1: New model fixtures validate proper falsedefaults plus explicitlyenabledconcretebinding. Mutation tests reject each network/capability/mount/Secret/entrypoint/restart/flag/proxy/JVM/credentialvolume/port violation; verifybodyroute `/api/v1/agent/` closure through actual temporarynginx HTTP test or existing executableartifacttest, notsourcegrep.
- [ ] Step2: Root runs `py -3.14 -m unittest discover -s scripts -p 'test_live_compose.py'` plus existingboundarytests, captures actualRED beforeproductionchanges.
- [ ] Step3: Implement Compose/verifiers/proxy and no unrelatedservice/releasechanges.
- [ ] Step4: Root renders base,synthetic,credentials,livefalse,livesynthetic-enabled-binds,closed using disposable nonSecret envfixtures; pipesJSON intoverifiers withoutdumpingfullmodel. Assert reset supportactualinstalledCompose and originalDB/OIDCserviceequivalence. Run focused+fullPython checks.
- [ ] Step5: Independenttaskreview with testedtree/diff; coverfixes andscopedrereview.

## Task 3: Final history verifier, CI and candidate handoff

**Files:** Create `scripts/verify-agent-live-rollback.py`, `scripts/test_agent_live_rollback.py`, `scripts/initialize-agent-inventory.py`, `scripts/test_agent_inventory.py`, `scripts/test-agent-inventory-volume.py`, test-only scoped `scripts/ci-curl-fixture/Dockerfile` and dependency notes, `docs/agent-personal-live-candidate.md`, `compatibility/agent-personal-live.md`; modify `.github/workflows/baseline.yml`, README.md, CHANGELOG.md. Only scoped inventory-bootstrap clarification in this plan/design; no Task1/2 source changes, existingacceptancereport rewrites or newstagereport.

**Interfaces:**
- CLI capture/old/restored with fixed local Composeproject/db identity and explicitlyboundcandidate manifest; no model/APIwrites. Snapshot schemaversion0.1.0, kindPERSONAL_LIVE_FINAL_ROLLBACK, pinnedPlatform/Web/Docs/Samples/Scanner +actualDeploySHA supplied byoperator, namespace/configproofrefs, full21table inventory.
- Freeze `TABLES: dict[str,str]` exactlyfromspec. Pure `parse_database_snapshot(records)`, `validate_migrations(main, agent)`, `assert_unchanged(before, after, allowed_audit_appends=())`; outputs no rawrows.
- One readonly repeatable-read UTC SQL transaction,5sstatement/locktimeout, exactfixedtables with server-side nativeSHA256 and count; audit UUID/action/project/trace/digest bounded5000rows and no metadata/body. Query count bound checked evenif outputlimited; docker subprocess timeout<=15s. No arbitrarycommand/container/SQL/pathinput, fixed project container postgres, read-onlypsqlON_ERROR_STOP.
- Capture after noqueued/runningrequests and explicitlycompletedshutdown; phases exactstablefullrowdigests. AuditbaselineeveryUUIDpreserved; newrows accepted only if exact approved action/project/trace triple, defaultnone. Agent/document/credentialactions neverappendaftercapture. Filecannotoverwriteexistingcapture; requireprivatesnapshotparent/file permissions withtestedWindows/POSIXvalidation or explicit no-write validate-only fallback (must notclaimruntimecapturepassed).
- Migrationexactversions main1–8 SQL, Agent8BASELINEchecksumNULL +9–16SQLnonnullchecksum/success/scripts; comparefullmigrationrowdigests acrossphases, don'tcomputeFlywaychecksumasSHA. RuntimehandbookrequirescurrentFlywayvalidate+JARresourceSHAverification separately.
- Inventorybootstrap: boundedstdlibonlyoperatorhelper, exactreviewfile `/reviewed/inventory.json`, newEMPTYnativevolume `/inventory`, exactdestination `inventory.json`; content1..32768bytes/1..20uniqueIDs/strictUTF8JSON/24hclockbound/originalbytes. UID0/capdropALL/networknone, exclusivelycreate/nofollow/fsync, finalrootowned0555/0444; existingentry/symlink/unsafemode/partialfailure denies withoutoverwrite/chmodexisting/repair/retry/cleanup. NonrootUID10001readonlyverify plus root-rununiquetemporaryDockerproof; noactualvolumeprovisioning inimplementation.

- [ ] Step1: Independentlyspellall21table/keypairsandmigrationexpectedfilenamesintests, noexpectedsetderivedfromTABLES. Missing/extra/duplicate/badcount/digest/table, per-tablemissing/deleted/changed/append, policy/proof/slot/day/revision-only mutations fail. Auditdeleted+replacedrowssamecountfails; exactapproveddeterministicappendpasses, wrongproject/trace/action/agentdocumentcredentialSTATUSfails. Parser/failure/timeout/privacy cases. Snapshotkind/candidates/unsafeACL reject.
- [ ] Step2: Root capturesfocusedRED, implementminimalpurehelpers/CLI, focusedGREEN; unchangedlegacy9tabletests stillpass.
- [ ] Step3: Add CI live renderedmodels and temporaryisolatednetworktest alongsideoldchecks; imagebuildbeforefixturetest, no liveSecrets/officialAPI. Keep SAMEcompletePythonSuite inbuiltguardUID0/capdropALL/readonlysource/networknone/tmpfs foractualPOSIXownership and WindowscompleteSuite/nativeACL; nohostroot/skipsorassertionweakening. Addnativeinventoryinit/nonrootROverify/overwrite-refusalproof with exactownedIDcleanup. Existingguardcontextunchanged; test-onlyscopedrealcurlruntimebase andHTTPnginxbase useofficialverifiedindexdigest, actualIDsresolvedafterbuild/pull, nofake/cachepins. Keep Windowschecks and LF guardwrapperassertion. Add truthfulcandidateinstructions,pins,dependencylicense/rebuildlimits,exactliveandclosuresteps, legacyackblock, noKeycloakrecreate, all21histories, rollbackrecordprivacy and knownnotyetexecutedgates.
- [ ] Step4: Root all Python/CI/Windowschecks,Composemodels,localguardDockerfixture,whitespace/Secrets/license; reviewtaskthenwholebranch once. Fixwave +scopedreview, preserveactualfailures.
- [ ] Step5: Commit once finaltreeisreviewed/tested; publishSHA/treeguardedPR, attachPR, allrequiredCI thennormalSHAguardedmerge andmainCI. Recordproof, noactualruntimeactivation inthisimplementationtask.

## Beyond this implementation plan (still part of stage goal)

- [ ] After all engineering/mainCI: actualrestrictedruntimecandidate, exactnonlegacyProject/batch/24hsyntheticinventory/keyversion/refs +officialprotocol/pricedocumentrecheck.
- [ ] Onlythen2authorizedserialWebcalls, explanationthen(success+settled)summary, USD.35each/.70total, failurestop/noextraquery/replacement.
- [ ] Explicitentry/outletclosure, finalcandidateapplicationrollback/restore with21table/migration/credentialproof, deterministicgatesunchanged.
- [ ] Versionedreleaseassets+matrix, uniqueDocsreportPR/mainCI, onlythen#43/#10/#34/Project2Doneandgoalcomplete.
