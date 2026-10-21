# 手动来源证明换版：离线实现计划

所有者于 2026-10-21 批准设计、离线实现与 CI；这不是来源审查、实际卷操作、部署、模型调用或费用批准。详细设计见 [设计说明](../agent-inventory-generation-design.md)。

## Global Constraints

- 仅离线实现和 CI；不得读取 Secret、活动 `.local` 或实际来源卷，不部署，不调用模型或账户，不产生模型费用。
- 保留旧卷、历史、UNKNOWN 预留、停止/撤销和密文；最多 24 小时有效期不变；新版本不能复活旧批次。
- 每代新 inventoryId 与全新 native volume；只在出口关闭、Platform 停止且无在途请求时实际选代，实际操作仍须另批。
- 不改生产 Platform、Scanner/API Schema、迁移、网络守卫、回滚 21 表 Schema 或候选 pin；不增依赖。
- Docker 证明仅允许隔离、测试独占命名和标记的临时合成卷；清理精确验证所有权，禁止 prune 或接触活动/预定部署卷。
- 兼容顺序：既有 Docs → Platform tests-only → Deploy → 另批关闭部署 → 另批真实验收；回滚先关闭入口/出口，保留迁移、证明和历史，不恢复过期许可。

## Task 1: Platform 已有换版与历史边界回归

工作树：`../archguard-platform-live-execution-core`，基线 c461f6be3cac6f226750d64cdb877f412a5b9bb4。仅修改两个既有测试文件：

- `src/test/java/io/github/aiarchguard/platform/AgentContextAccountingIntegrationTest.java`
- `src/test/java/io/github/aiarchguard/platform/agent/infrastructure/ControlledSyntheticBatchInventoryTest.java`

先阅读 README、AGENTS、相关需求/设计/ADR 和相邻测试。增加真实 reader 独立旧/新文件测试：旧文件到期拒绝；同一 deployment/Project/manifest/fixture 的新 UUID 和新文件有效，旧 ID 不匹配，新 SHA 不同；旧 bytes/权限不变；把旧过期条目追加到当前文件仍拒绝；24 小时上限不放宽。临时目录和固定时钟，不访问 Docker/模型/Secret。

应用/DB 回归复用既有 integration fixtures：旧 batch 保留 UNKNOWN、预留、停止和撤销后过期；显式新 inventory UUID、同一模板/manifest 和当前确认创建新 batch，槽位按 batch 分离；旧发送前检查仍拒绝，旧请求、link、proof、ledger、audit 和 credential/settings 元数据不变，新预留累加而非退款。使用同日 +3601 秒，避免跨日预算歧义。旧 fixture 的 inventory fake 忽略 ID/过期，只证明 DB/历史边界，真实 reader 测试才证明精确来源绑定。可依据实际接口调整测试细节，但不改生产代码或弱化现有断言。

这是已有行为的 characterization，不伪造 RED。记录基线和新增断言结果。执行最小两类测试，再完整 `mvn --batch-mode --no-transfer-progress verify`（使用 JDK21）；Windows 既有 symlink skips 如实标注。自审后一个 tests-only commit，不 push/merge。评审重点：有意义的旧快照比较、无全局时钟污染、无 fake 证明夸大。

## Task 2: Deploy 显式选代及隔离证明

基线 de0c7dce296c417d2079039f207c4887bc5fcb46。依照设计实施：

1. 新建 `compose.agent-inventory-generation.yaml`，只覆盖逻辑卷 `agent-live-inventory` 的物理 `name`。必填 `ARCHGUARD_AGENT_INVENTORY_GENERATION`，物理名 `<actual Compose project>_agent-live-inventory-<canonical nonzero UUID>`；保留默认旧文件/行为。不包含 services/networks/ports/images，不把 UUID 注入 Platform env/API。
2. 扩展 `scripts/verify-agent-live-compose-config.py`：`verify(model: dict, *, closed: bool = False, inventory_generation: str | None = None) -> None`，CLI `--inventory-generation UUID`，兼容 stdin/file 和 `--closed`。无参数只允许旧名；有参数精确绑定规范非零 UUID/实际 project/新物理名。拒绝大小写、零、不规范、缺 project、错代、错 project、旧名冒充、任意 alias、external、driver_opts；原只读路径/其他服务隔离/Secret与 DB native identity 检查保持。错误仅固定分类，不能输出输入或路径。
3. 先新增测试并实际观察缺少能力的 RED，再最小实现 GREEN。扩展 `scripts/test_live_compose.py`（函数与 CLI）、`scripts/test_agent_inventory.py`（固定时钟的旧证明失效与新代区别），保留全部既有断言。
4. 扩展 `scripts/test-agent-inventory-volume.py` 为两个独占临时合成 native volumes。只新空卷初始化；旧 bytes/modes 不变；覆盖/失败残留拒绝。固定/注入测试时钟证明旧过期 verify 失败，同时归档 byte/mode 完整性通过，新代当前 verify 通过。生产 initializer 不改，不依赖等待/宿主时钟变化，不输出内容/ID/hash。使用不可变已有测试 image ID，network none，无 Secret。安全所有权清理必须覆盖两个卷及每个容器。
5. `.github/workflows/baseline.yml` 用已固定 Compose5.5.1 离线渲染 default/new/closed 并严格 verify，缺参失败，不创建实际 Compose 栈；沿用临时原生卷 CI 测试。同步 README、`docs/agent-personal-live-candidate.md`、`compatibility/agent-personal-live.md` 和设计说明。

验收：最小 Python 模块测试 → scripts 全套/ci adapter 全套/PowerShell 启动及 owner 合成测试/语法/whitespace → CI Linux 原生卷和 Compose5.5.1 渲染。当地不具备的验证交由 CI，并明确标注。不得为本地渲染读取活动 `.local`；使用系统临时目录的合成配置。一个 implementation commit（controller 预建的本计划算入同一提交），不 push/merge。

手册必须明确：静态 verifier 不证明 kernel/actual mount/进程/pending/21表；未来操作须独立批准、关闭出口、停 Platform、pending=0、21表/audit与 native DB/master/ciphertext/旧卷基线、确认新卷不存在、仅新卷初始化一次、失败不修复、不热换、只 no-deps/pull-never 关闭启动；新审查不等于调用批准；旧 UNKNOWN/失败批次不可复活。候选 pins 不因本增量提升。

评审重点：Compose 实际 project 插值、默认兼容与显式 opt-in、不扩大 native volume 白名单、双卷测试归档完整性不冒充当前有效、CI 不接触实际部署。
