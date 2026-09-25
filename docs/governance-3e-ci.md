# 3E：GitHub CI 与 Webhook 接入

这是部署模板，不自动启用任何仓库的门禁。先部署含 Flyway V5 的 Platform 3E，待 `main` CI 通过后，再配置本模板。Scanner 保持 `v0.2.1`，Result Schema 保持 `0.1.0`。

1. 以 Project Maintainer 身份调用 Platform `PUT /api/v1/projects/{projectId}/repositories/{repositoryId}/github/link`，请求 `providerRepositoryId` 为 GitHub 数字 Repository ID。绑定不可改；填错时需显式数据修复流程，不能覆盖旧值。
2. 给 Platform 注入独立随机 `ARCHGUARD_GITHUB_WEBHOOK_SECRET`。GitHub Repository Webhook 的 Payload URL 指向已配置的 HTTPS 入口 `/api/v1/github/webhooks`，Content type 为 `application/json`，Secret 为相同值，事件只选 Pull requests。不要把 Platform、数据库或 Keycloak 内部端口直接暴露公网。本地 Compose 只绑定 `127.0.0.1:8080`，不能直接接收 GitHub 云端投递。
3. 在受信任仓库复制 [`examples/github-actions/governance.yml`](../examples/github-actions/governance.yml)，替换 `REPLACE_WITH_REVIEWED_DEPLOY_COMMIT` 为本 Deploy PR 合并后经审核的完整 commit SHA。目标仓库放置版本化 `.archguard/rules.yaml`。配置非敏感 repository variables `ARCHGUARD_PLATFORM_URL`（HTTPS）、`ARCHGUARD_PROJECT_ID`、`ARCHGUARD_REPOSITORY_ID`、`ARCHGUARD_RULESET_VERSION_ID`；仅把具有对应 Project Maintainer 权限、短期有效的 Platform OIDC Bearer Token 放入 `ARCHGUARD_CI_TOKEN` secret。不得使用 GitHub PAT 代替 Platform 身份，亦不得把 token 写入日志。生产建议由受信任的身份代理按作业签发短期 token；本阶段模板不承担签发职责。
4. 首次启用前在 Platform 为默认分支提升成功扫描为不可变基线，并确认 RuleSetVersion 一致。GitHub Actions 需 `contents: read`、`statuses: write`；分支保护可要求 `archguard/governance` 状态。来自 fork 的 PR 默认拿不到 secret，因此失败关闭，不应改用 `pull_request_target` 执行不受信任源码。

CI 固定 Scanner JAR SHA-256，在自己的 checkout 执行扫描。Scanner `2` 仍提交报告，Platform 的最终门禁才决定退出 `0/2/64/70`。PR 使用真实 head SHA 而非 GitHub 合成 merge SHA；签名 Webhook 必须先到达并指向该 head，CI 才发布状态。迟到扫描不覆盖新 head；事件缺失或服务不可达时退出 `70`，不会伪报通过。Webhook 重放、乱序和签名错误由 Platform 安全处理。

回滚：先禁用目标仓库工作流和 Webhook，再回退 Platform 应用；Flyway V5 与审计事实保留，不执行 down migration。只有受信任的 HTTPS 入口、可用 OIDC token、GitHub Webhook 和基线全部就绪，模板才是可运行的门禁；本地 Compose 模拟不等于公网投递验收。
