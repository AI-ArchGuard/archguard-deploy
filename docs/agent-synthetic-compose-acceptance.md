# Agent 合成 Compose 验收

状态：合成 API 与真实 Web 操作通过；真实模型发布、旧应用完整回退和阶段退出仍未验收。唯一阶段报告只在退出关卡满足时创建，当前执行证据保留在 [4H Issue](https://github.com/AI-ArchGuard/archguard-deploy/issues/10)。

本组合只有无网络的确定性适配器，**不会调用 DeepSeek**。固定文本、100/80 Token 与 260 µUSD 都是合成测试值，不能代表真实模型质量、Token 估算、供应商延迟或账单。ADR-0011/#43 的账户级审批仍缺失。

## 固定输入与启动

先核对[兼容矩阵](../compatibility/agent-synthetic.md)的提交和 CI。在独立、干净的工作树中设置四个固定输入目录，不使用含用户修改的根检出。合成 override 必须提供这些目录；缺失时配置失败，不回退到旧默认路径。

```powershell
$env:COMPOSE_PROJECT_NAME = 'archguard-agent-4h'
$env:COMPOSE_FILE = 'compose.yaml;compose.agent-synthetic.yaml'
$env:ARCHGUARD_SCANNER_CONTEXT = '<pinned-scanner-checkout>'
$env:ARCHGUARD_PLATFORM_CONTEXT = '<pinned-platform-checkout>'
$env:ARCHGUARD_WEB_CONTEXT = '<pinned-web-checkout>'
$env:ARCHGUARD_SOURCES_CONTEXT = '<pinned-synthetic-samples-checkout>'
.\scripts\local-up.ps1 -Port 8081 6>$null
docker compose --env-file .local/runtime.env config --quiet
docker compose --env-file .local/runtime.env config --format json | py scripts/verify-agent-compose-config.py -
docker compose --env-file .local/runtime.env up -d --no-build --wait
docker compose --env-file .local/runtime.env cp runtime-init:/opt/archguard/scanner.jar .local/scanner.jar
```

只暴露 Web `127.0.0.1:8081`；数据库、Platform、Keycloak 与 Runner 不暴露主机端口。此项目与已有 8080 演示并存，不停止或清空旧数据。OIDC issuer、回调、realm 与 Web 构建参数必须统一使用 8081。重复启动复用 `.local/` 凭据；已有端口不匹配则拒绝启动，不轮换已有卷密码。所有后续命令须在同一终端保留四个固定上下文。

## API 和故障验证

```powershell
py scripts/verify-agent-compose.py --samples-root $env:ARCHGUARD_SOURCES_CONTEXT
```

脚本复用阶段 3 的真实 Scanner 合成旅程，经实际 Web 反向代理访问 Platform/PostgreSQL。先复验缺基线 `ERROR/64`、违规 `FAIL/2`、有效例外 `PASS/0`、到期 `FAIL/2`、修复 `PASS/0`，然后验证解释、摘要、Evidence/文档真实引用、旧文档版本、幂等冲突及跨 Project 资源隐藏。Agent 前后比较整个 ScanJob/Finding 响应及历史门禁结果。

成功后另建合成 PR head `dddd…` 和违规报告，供独立 Web 操作使用；这属于明确的测试准备，不是模型写入。输出 `.local/agent-acceptance-SUCCEEDED.json` 与便利入口 `.local/agent-acceptance-result.json` 不含 Token。脚本始终写 `browserVerified=false`，不会把 API 调用冒充浏览器验收。管理 Token 可能在长旅程中过期，清理临时客户端时重新取得短期 Token；失败必须显式报告。

逐个切换部署人员控制的场景，等待健康后再运行（不允许 API 用户选择场景）：

```powershell
$env:ARCHGUARD_AGENT_SYNTHETIC_SCENARIO = 'TIMEOUT'
docker compose --env-file .local/runtime.env up -d --no-build --wait archguard-platform
py scripts/verify-agent-compose.py --samples-root $env:ARCHGUARD_SOURCES_CONTEXT --expected MODEL_TIMEOUT
```

相同方法对应 `OUTPUT_INVALID`、`CITATION_INVALID`、`UNAVAILABLE`（预期 `MODEL_UNAVAILABLE`）。关闭调用使用 `ARCHGUARD_AGENT_ENABLED=false`、场景 `SUPPORTED`，预期 `MODEL_DISABLED`。失败时结果为空，历史 `PASS/FAIL` 不变；超时不重试、未知费用保持预留。

## 真实 Web 操作

在 `http://localhost:8081` 使用本地 realm 的随机演示账户登录，密码从被忽略的 `.local/` 获取，不贴到 Git、Issue、日志或截图。

1. 打开输出的 Project，显式上传 [合成文档](../fixtures/agent-architecture.md)，确认创建新不可变版本。
2. 从扫描历史打开 `browserScanJobId`，选择文档的旧版本 1，显式点击解释。核对固定合成说明、Evidence 覆盖与 traceId。
3. 点击 Evidence 和文档引用，确认解析到同 Project/扫描与旧版本全文；最新版本变化不改写旧引用。
4. 打开持续治理的当前 PR #7，选择 Finding，显式生成摘要。页面仍显示 `FAIL / CI 2`，解释与摘要都只是建议。
5. 关闭 Agent 后再次显式请求，确认显示“模型调用已关闭”，仍保留 `FAIL / CI 2`。

2026-10-01 的独立环境实际完成步骤 1–5：Project `dd295849-7151-4212-a763-5dc8ed0a10b7`；Web 上传得到版本 3，解释引用版本 1 `1974538b-e821-43e5-90fd-958fd85b7aa7`；实际解析 Evidence 路径与旧正文。上传/加载后请求数仍为 2，显式解释和摘要后为 4。解释 traceId `dd21011b221a2ac303e187059119d356`，摘要 `54369aae7ca5de662bedc1dd896c0395`。关闭后再请求显示“模型调用已关闭”，`FAIL / CI 2` 保持不变。截图留在本地和 Issue，未提交认证会话或运行数据。

## 边界与后续关卡

本轮实际执行成功、超时、无效输出、伪造引用、不可用和关闭场景；每次治理复验的 `0/2/64` 与原结果保持不变。`70` 的 Runner 错误映射、并发费用、额度耗尽、授权撤销和遗留请求恢复使用 4G/现有自动化证据，不能冒充本轮 Compose 覆盖。没有真实模型、账户审批、供应商用量/账单或生产负载验收。

回滚顺序及未验证项见矩阵。停环境只用 `docker compose --env-file .local/runtime.env down`，不加 `--volumes`；文档、解释、额度、审计和已发布迁移均保留。阶段 5 Gateway、阶段 6 正式 Evals 未启用。
