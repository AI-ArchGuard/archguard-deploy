# 4H 合成环境应用回滚演练

状态：2026-10-02 独立 `archguard-agent-4h` / 回环 8081 环境通过关闭入口、旧应用回退及当前应用恢复。真实 DeepSeek 仍关闭；不是生产容量、数据库灾备或阶段退出报告。已有 8080 环境未改动。

## 固定输入与风险

- 当前 Platform 使用矩阵的 `b7cfa56`；Web 使用 [#13](https://github.com/AI-ArchGuard/archguard-web/pull/13) 合并提交 `cdd41cf3ecbb0779364c0b3c88140390c5328deb`，[main CI](https://github.com/AI-ArchGuard/archguard-web/actions/runs/36983615611) 全部成功。
- 旧 Platform 使用已发布 `v0.4.0` JAR，SHA-256 `1ab6f01551c1aa79edb42c5365d041f621e9ea3a690f727c1ad4efb7f67c26ba`。只在包含此 JAR 的独立目录用 [Dockerfile](../rollback/platform.Dockerfile) 打包，构建中再次校验摘要；不能上传工作区、备份或凭据作为上下文。
- 旧 Web 从 `v0.2.0` 提交 `a05cffb665d2ddc1d185991890c0183357572f8a` 重建，公开 OIDC 回调设为 8081；不冒充发布 tar.gz 的相同字节制品。本轮没有 Registry 镜像发布。
- Web 展示开关 `VITE_AGENT_UI_ENABLED` 默认 `false`，只有精确 `true` 启用。它是构建参数，修改必须重建部署，不是热开关或授权，不能约束旧页面或直接 API 请求。真实 Project/Deployment 外发启用仍未交付。
- 旧版没有 Agent/文档接口，初次请求返回 `500 internal.error`（通用处理器捕获 `NoResourceFoundException`）。没有修改已发布 JAR或把此错误记为通过。回滚代理 [web.nginx.conf](../rollback/web.nginx.conf) 明确阻断这些路径，返回统一 `503 agent.unavailable`、traceId 与 `no-store`；其他扫描、门禁与身份路径继续代理。

## 顺序与可执行步骤

在独立 Deploy 检出设置合成验收所需的四个固定上下文和 `COMPOSE_PROJECT_NAME=archguard-agent-4h`。使用既有配套 `.local/runtime.env` / realm，不重新生成或轮换卷凭据。跨 Deploy 检出时，为每条 Compose 命令添加 `--project-directory <existing-runtime-root>`，使用原 runtime.env 及新 Deploy 文件的绝对路径；服务/卷名与端口不变。

先下载官方旧 JAR 至被忽略的 `<jar-only-context>/platform.jar` 并核对上述 SHA-256；构建目录不得包含备份。构建：

```powershell
docker build -f rollback/platform.Dockerfile -t archguard/platform:4h-v0.4.0-rollback-local <jar-only-context>
docker build --build-arg VITE_OIDC_AUTHORITY=http://localhost:8081/auth/realms/archguard --build-arg VITE_OIDC_REDIRECT_URI=http://localhost:8081/auth/callback --build-arg VITE_OIDC_POST_LOGOUT_REDIRECT_URI=http://localhost:8081/ --build-arg VITE_AGENT_UI_ENABLED=false -t archguard/web:4h-entry-off-local <current-pinned-web-context>
docker build --build-arg VITE_OIDC_AUTHORITY=http://localhost:8081/auth/realms/archguard --build-arg VITE_OIDC_REDIRECT_URI=http://localhost:8081/auth/callback --build-arg VITE_OIDC_POST_LOGOUT_REDIRECT_URI=http://localhost:8081/ -t archguard/web:4h-v0.2.0-rollback-local <old-pinned-web-context>
```

以下示例假定在配套运行目录执行；跨检出按上文补齐路径。先要有成功合成验收输出 `.local/agent-acceptance-result.json`；没有历史数据不能演练。

```powershell
$env:ARCHGUARD_AGENT_ENABLED = 'false'
$env:ARCHGUARD_AGENT_UI_ENABLED = 'false'
$env:ARCHGUARD_AGENT_WEB_IMAGE = 'archguard/web:4h-entry-off-local'
$env:ARCHGUARD_ROLLBACK_NGINX_CONFIG = '<absolute-pinned-rollback/web.nginx.conf>'

# 1. 捕获历史并备份；备份只保存在受控且被忽略的本地目录。
py scripts/verify-agent-rollback.py capture --runtime-root <existing-runtime-root>
docker exec archguard-agent-4h-postgres-1 pg_dump -U archguard -d archguard -Fc -f /tmp/archguard-4h-before-rollback.dump
docker cp archguard-agent-4h-postgres-1:/tmp/archguard-4h-before-rollback.dump <ignored-backup-directory>/database-before-rollback.dump
docker exec archguard-agent-4h-postgres-1 pg_restore -l /tmp/archguard-4h-before-rollback.dump

# 2. 先关闭当前 Web 入口及 Agent API 转发，同时关闭 Platform 调用。
docker compose -f compose.yaml -f compose.agent-synthetic.yaml -f compose.agent-entry-closed.yaml --env-file .local/runtime.env up -d --no-build --no-deps --wait --wait-timeout 60 archguard-web archguard-platform
# 刷新浏览器：文档深链接“Agent 入口已关闭”，解释/摘要消失，FAIL / CI 2 不变。

# 3. 再回退旧应用，保留数据库、迁移与所有卷；禁止 --build 重建旧标签。
docker compose -f compose.yaml -f compose.agent-synthetic.yaml -f compose.agent-entry-closed.yaml -f compose.agent-rollback.yaml --env-file .local/runtime.env up -d --no-build --no-deps --wait --wait-timeout 60 archguard-web archguard-platform
docker compose -f compose.yaml -f compose.agent-synthetic.yaml -f compose.agent-rollback.yaml --env-file .local/runtime.env config --format json | py scripts/verify-agent-compose-config.py - --rollback
py scripts/verify-agent-rollback.py old --runtime-root <existing-runtime-root> --samples-root <pinned-synthetic-samples-context>

# 4. 恢复当前应用，移除旧应用/代理覆盖，仍关闭展示与模型。
docker compose -f compose.yaml -f compose.agent-synthetic.yaml --env-file .local/runtime.env up -d --no-build --no-deps --wait --wait-timeout 60 archguard-web archguard-platform
py scripts/verify-agent-rollback.py restored --runtime-root <existing-runtime-root>
```

任一步非零退出必须停止诊断。旧版健康失败时用步骤 4 的当前镜像恢复；保留备份/数据库，不禁用 Flyway 校验，不 `repair` 历史，不清空卷。恢复后 Platform 授权的 API 可读旧解释；重新打开展示需另建 `true` 的 Web 包。实际交接保持 UI/模型 `false`。

## 实际证据与限制

- 容器内旧 JAR 摘要与发布资产一致，旧应用健康。Flyway 对未来主迁移 V8 有版本警告但验证成功；未禁用校验。主 V1–V8 与独立 Agent 基线 V8/V9/V10 保留。
- 回退前、回退中及恢复后，九组历史记录行数/全文排序摘要一致：主迁移 8，Agent 迁移 3，上传幂等记录 11，文档 8，文档版本 11，片段 11，Agent 请求 13，预算 8，Agent 审计 35。只读比较不打印正文/凭据；额外合成扫描/治理审计允许正常追加，不声称整库未发生新工作。
- 原 Finding/ScanJob/门禁响应及 PR 确定性字段相同，历史 `FAIL/2` 不变。恢复当前应用后原成功解释、摘要与旧文档内容摘要引用再次可读。
- 旧应用中的新合成旅程：缺基线 `ERROR/64`、违规 `FAIL/2`、有效例外 `PASS/0`、到期 `FAIL/2`、修复 `PASS/0`；PR 修订 `RESOLVED=1`、相对基线 `RESOLVED=0`。真实 Runner 扫描 `403ac1c4-b821-4829-82a9-f091a4ca37da` 为 `SUCCEEDED/PASS` 且无 Finding，幂等重放任务不变。
- 浏览器实际验证默认关闭深链接和旧版门禁。脚本保持 `browserVerified=false`，不冒充 UI 测试。custom-format 数据库备份成功创建并列出 230 行目录；没有数据库备份恢复测试，不声称灾备通过。
- 首轮治理脚本误假定旧 PR DTO 有 4F 新字段，旅程结束后报错。新增回归后允许阶段 3 回调缺字段；Agent 专项仍强制要求可信修订，不降级摘要绑定。

此演练只证明本地合成组合的应用回滚，不覆盖生产负载、真实提供方/账单和真实 Project 外发。真实发布仍由 [Platform #43](https://github.com/AI-ArchGuard/archguard-platform/issues/43) 阻塞；唯一阶段退出报告不创建。PR 和合并后 CI 证据见 [4H Issue](https://github.com/AI-ArchGuard/archguard-deploy/issues/10)。
