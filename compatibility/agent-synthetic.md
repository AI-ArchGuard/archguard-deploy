# Agent 合成验收兼容矩阵（未发布）

状态：固定主分支代码的合成候选组合；**不是 `v0.5.0-agent` 真实模型 Release**。正式发布和唯一阶段报告受 [ADR-0011](https://github.com/AI-ArchGuard/archguard-docs/blob/main/adr/0011-deepseek-official-api-egress.md)及 [Platform #43](https://github.com/AI-ArchGuard/archguard-platform/issues/43)阻塞。

| 组件 | 固定代码 | 契约 / 迁移 |
|---|---|---|
| Docs | `b16386475dfde90bc33aeb0355ed2248e653febb` 的已接受语义 | ADR-0010/0011；真实外发默认关闭 |
| Scanner | `d4b8e98bfdabbc78f65910ed37e3062167d04b07`；已发布 `v0.2.1` 兼容线 | Result/Rules Schema `0.1.0`；CLI `0/2/64/70` 不变 |
| Samples | `a53a5bbea2630aac2135aa217d961cdbb77851a3` | 固定合成治理源码、Agent 契约/安全案例；无客户源码 |
| Platform | `b7cfa56fa513d1671840160603781c2b6de440d3`（#47） | Agent API/输出 `0.1.0`；文档 API `0.1.0`；主 Flyway V1–V8、独立 Agent V9/V10 |
| Web | `cdd41cf3ecbb0779364c0b3c88140390c5328deb`（#13） | 固定 Platform 契约快照；建议/引用消费；默认关闭构建时入口开关 |
| Deploy | 本矩阵所在提交；合并/CI 证据见 #10 | 基础 Compose + 显式合成 override；仅回环 Web 端口 |
| PostgreSQL / Keycloak | 沿用 `compose.yaml` 中的固定 digest | `17.7-alpine` / `26.5.3`；只做本地演示，不声明生产身份部署 |

本地构建的 Platform Maven 版本仍是 `0.4.0`、Web package 版本仍为 `0.2.0`，不能仅凭同名版本复用阶段 3 制品；必须固定上述 SHA。未发布新 JAR、Web Release 资产或 Registry 镜像，不把本地镜像 ID 当成远程供应链 digest。Platform 首次构建基于 #47 head `132d613`，与合并后 `b7cfa56` 的树完全一致；后者 `main` CI 成功（[run 36817081806](https://github.com/AI-ArchGuard/archguard-platform/actions/runs/36817081806)）。Web [run 36815083314](https://github.com/AI-ArchGuard/archguard-web/actions/runs/36815083314)、Samples [run 36814805126](https://github.com/AI-ArchGuard/archguard-samples/actions/runs/36814805126)均成功。

## 兼容与启用顺序

Docs 语义 → Samples 固定输入 → Platform 合成适配器及引用/审计 → Web 消费 → Deploy 合成验收。所有新增 PR 及合并后的 `main` CI 成功后，才视为已合入的候选组合。Scanner 不需要修改，Gateway/Evals 不启用。

Platform 先运行主迁移至 V8，Agent 独立迁移至 V10；Agent 迁移不可用不得影响扫描和治理。先检查实际运行 JAR、迁移历史、构建上下文和只读 Scanner 制品挂载，再打开合成本地 profile。没有真实适配器、Secret 或允许的外联配置。新版本文档与解释保留旧绑定。

## 回滚

正式环境先关闭 Web Agent 入口及 Project/模型出口，再关闭部署 Agent 开关，最后回退 Web/Platform 应用。保留 V8、V9、V10 与文档、解释、预算、审计；不改写旧迁移、不做 down migration、不清空卷。

2026-10-02 的[独立合成回滚演练](../docs/agent-rollback-rehearsal.md)已验证：先关闭当前 Web 入口及 Agent API 转发、关闭 Platform 调用，再回退旧 `v0.4.0` 发布 JAR / `v0.2.0` 代码重建 Web；旧应用健康并执行新治理/Runner 工作。九组迁移/文档/解释/预算/Agent 审计记录摘要不变，恢复当前应用后旧引用可读。Web #13 [main CI](https://github.com/AI-ArchGuard/archguard-web/actions/runs/36983615611) 成功；本 Deploy 变更合并后的 CI 证据见 #10。

Web 开关为构建时展示控制，需重建，不替代后台控制；回滚代理额外对 Agent/文档路径返回明确 503。旧 Web 为适配 8081 重建，不冒充发布 tar.gz。真实 Project/Deployment 启用及适配器未交付；数据库备份恢复和生产负载未演练。真实外发仍阻止正式发布。停止合成环境用 `down` 不带 `--volumes`。
