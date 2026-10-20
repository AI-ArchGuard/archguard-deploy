# 个人 Agent 最终候选兼容矩阵（未发布）

状态：获批 `DeepSeek-V4.1-Flash-1017` 的显式提供方/消费者候选组合，替代旧 10-15 工程组合。Docs、Platform、Web 已合并且 main CI 成功；本 Deploy 变更仍须完成自身审查、PR/main CI 及合并后私有 manifest 绑定。不是正式 `v0.5.0-agent`，不表示活动环境或两次真实模型验收已通过。操作步骤、费用/授权、21 表历史及隐私要求见[候选手册](../docs/agent-personal-live-candidate.md)。历史 synthetic 矩阵与报告不重写。

## 固定来源与实际制品

- Docs：`077a7c5afa12557543ee04e14321701c3537931a`；main CI `39144567175` 成功。ADR-0015 仅更新获批 `DeepSeek-V4.1-Flash-1017` 映射，保留 ADR-0012/0013/0014 原协议、费用和调用次数；实际前仍重核官方协议/映射/价格。
- Platform：`af821fc99553d462a2176cba5af70be7cc960c75`；诊断增量 PR #65 已合并，main CI `39413909045` 成功。替代原 `903ddc5987e0f6e63091ee4897d4311b9c41cbe9`，只新增固定脱敏拒绝分类，不放宽输出、引用或用量校验。Maven 仍 `0.4.0`；Settings/ack 契约 `0.4.0` 明确配对 1017，Batch `0.3.0`、live API/输出 `0.1.0`。主 Flyway V1–V8、Agent baseline8 + V9–V16 不变。当前 JAR 来源 SHA、构建字节及正常 Flyway validate/迁移资源 SHA 必须另外核对。
- Web：`5c5a7a021210876cda55850d7898e11aa52781aa`；PR #16 已合并，main CI `39220944637` 成功。package 仍 `0.2.0`；消费 Platform 生成契约，仅提交当前 `0.4.0` 显式确认。默认 Release tarball 三类 Agent/live/credential UI 关闭；显式 8081 Docker 构建与默认 tarball 字节/参数不同。只有实际核验的构建参数与产物才能证明入口状态，tag 或 package 版本不够。
- Scanner：`d4b8e98bfdabbc78f65910ed37e3062167d04b07`，既有 `0.2.1` 兼容线；Result/Rules Schema `0.1.0`、CLI `0/2/64/70` 不变。
- Samples：`a53a5bbea2630aac2135aa217d961cdbb77851a3`；受控合成 fixture，无客户源码。
- Deploy：最终合并 SHA 由操作员在合并/main CI 成功后填入私有 candidate manifest；当前文档不伪造 self-pin/pending SHA。PR/head tree 及本地 image ID 不能冒充合并 SHA 或 registry digest。
- PostgreSQL：`postgres:17.7-alpine@sha256:bb377b7239d2774ac8cc76f481596ce96c5a6b5e9d141f6d0a0ee371a6e7c0f2`；Keycloak：`quay.io/keycloak/keycloak:26.5.3@sha256:5a236ae4dd8ece77490115bace15a11a4d15e9cbcf58a490b95a7da2cd71d32a`，沿用现有 project/身份/卷，不重建 Keycloak。

Platform 原业务 Dockerfile runtime `eclipse-temurin:21-jre-jammy` + apt curl、Web 业务 runtime `nginxinc/nginx-unprivileged:1.29.5-alpine` 不是本变更新增的完整业务供应链锁。保留这项限制，记录实际业务 image/JAR/Web 字节；本任务不修改它们或宣称发布。

该组合仅更新映射确认与候选绑定：请求别名和单元素响应白名单仍为 `deepseek-flash`，固定 `/responses`、非流式、无工具/会话/重试，原 `reasoning.effort=none`、`tool_choice=none`、`store=false` 不变。上下文价格版本仍为 `deepseek-flash-context-peak-usd-2026-10-15`，每请求预留 `316373` microUSD，单次/两次 USD `0.35/0.70`，完整请求 6000 UTF-8 字节、输出 1500 Token、输入 8000 调用后观察阈值及日限额均不变。旧确认可读、撤销和按自身绑定结算，但不得静默升级或用于新真实发送。

首次真实批次已在解释 `OUTPUT_INVALID` 后停止并撤销；实际费用仍为 `UNKNOWN`，原预留和历史保留，未发送摘要。原始响应已丢弃，不能用新增诊断追认根因，也不能把关闭状态恢复当作真实验收或最终回滚通过。新批次须重新取得具体调用与费用批准，未使用的旧摘要许可不得复用；本候选同步不授予这些权限。

## 测试镜像与依赖证明

guard 使用上述固定 PostgreSQL base，仅 `netguard/` 上下文，nftables `1.1.5-r2`，Python3.12 stdlib。GPL/PSF 及传递包、来源/分发责任和未完全锁定包版本见[依赖说明](../netguard/DEPENDENCIES.md)。guard image 不运行数据库；保留额外 PostgreSQL 二进制的攻击面限制。

CI 测试 shell/curl 使用 `eclipse-temurin:21-jre-jammy@sha256:affcab5356e1270ac35d2361ee83135af2f03e8d580eca78a6d5d6fdbf048db0`；HTTP fixture 使用 `nginxinc/nginx-unprivileged:1.29.5-alpine@sha256:42a7d7f2ee23e9f5a1dcdf3647ba5c585bbd18f79e79cd817e70e8cd61c55779`。两者为 2026-10-18 root 实际查验的官方公开 Docker Hub index digest，分别来自 [Temurin 元数据](https://hub.docker.com/v2/repositories/library/eclipse-temurin/tags/21-jre-jammy)及 [nginx 元数据](https://hub.docker.com/v2/repositories/nginxinc/nginx-unprivileged/tags/1.29.5-alpine)。这不是构建/拉取成功证明；registry 请求/包失败必须使 CI 失败，不换镜像或放松检查。

CI 先构建/拉取再取得本地不可变 ID，才运行 fake TCP/HTTP fixture 和 native inventory 证明；不硬编码 root 缓存 ID。apt curl/传递包未完全锁定，见[测试镜像依赖说明](../scripts/ci-curl-fixture/DEPENDENCIES.md)。nginx 保留 BSD-2-Clause 及原镜像内依赖许可证；测试不分发镜像。任何今后分发须附相关许可证、版本及所需可获取源码。没有新增 pip/npm/model SDK 依赖。

## 兼容顺序和回滚边界

已完成来源顺序：Docs ADR-0015/main CI → 固定 Samples/Scanner → Platform 生产者 `0.4.0` 合入/main CI → Web 当前显式确认消费契约合入/main CI。后续顺序：Deploy 审查、全部 CI、正常 SHA-guarded 合并/main CI → 操作员填入真实 Deploy 合并 SHA、核对实际制品并重新绑定 owner/deployment/Project/manifest/来源/batch/templates/current credentialVersion/检查 refs/`0.4.0`/1017/价格与预留策略/有效期及原两次限额 → 本机运行。原始代码版本仍 `0.4.0/0.2.0`；顺序和版本号不能替代实际 SHA/字节。当前 verifier 只接受本矩阵精确新组合并拒绝旧工程组合；不得通过放松校验或多候选接受跳过契约变更。所有新 live/UI/管理/来源开关默认 false，官方集合默认空，独立 inventory 原生卷不自动初始化。旧成本 acknowledgement 不升级为新批准。

实际回滚先完成 Project/batch/worker 关闭、所有入口关闭、guard 清空官方集合，再停 Platform 并 capture。保持同一 `archguard-agent-4h`/8081、原 DB/OIDC/凭据卷与 deployment UUID；不轮换密码、不清空卷、不重建 Keycloak、不改 V1–V16、不 repair/down migration。固定旧应用制品的实际哈希后运行旧治理/Runner 旅程，比较全部 21 表；恢复当前应用时另核对 Flyway validate、JAR资源SHA和引用可读性，调用仍关闭。替换 namespace 必须先停 Platform、等 guard readiness 后启动 Java。

快照固定 schema `0.1.0`、kind `PERSONAL_LIVE_FINAL_ROLLBACK`，不使用历史九表报告冒充最终结果。非审计表全行不变；每条 baseline 审计 UUID/完整行摘要必须保留，新增仅事先明确 action/Project/trace 三元组；Agent/document/credential（含 STATUS/null-project）绝不追加。当前实现验证不包含实际两次调用/费用结算、运行回滚、凭据卷保留或身份/DB灾备；唯一 Docs 报告、Release 和 Issue 关闭仍是后续条件关卡。
