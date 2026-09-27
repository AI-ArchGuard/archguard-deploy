# 3H 本地 Compose 治理验收

状态：正式版本组合的合成 Compose 闭环已通过；Deploy PR/`main` CI 和阶段报告仍待核对。本步骤只使用合成 Samples 和本地临时凭据；不能代表公网上的 GitHub Webhook 投递或实际 GitHub Status 发布。固定制品见[持续治理兼容矩阵](../compatibility/governance-v0.4.md)。

## 固定输入与启动

将 Deploy、Platform、Web、Samples 分别检出到已合并 `main` 的固定提交，将 Scanner 检出到已核对的固定提交。记录各 SHA 后，把四个构建/源码上下文指向这些目录。使用专用 Compose 项目名，避免复用其他实验留下的数据卷：

```powershell
$env:COMPOSE_PROJECT_NAME = 'archguard-governance-3h'
$env:ARCHGUARD_SCANNER_CONTEXT = '<fixed-scanner-checkout>'
$env:ARCHGUARD_PLATFORM_CONTEXT = '<fixed-platform-checkout>'
$env:ARCHGUARD_WEB_CONTEXT = '<fixed-web-checkout>'
$env:ARCHGUARD_SOURCES_CONTEXT = '<fixed-samples-checkout>'
.\scripts\local-up.ps1
docker compose --env-file .local/runtime.env config --quiet
docker compose --env-file .local/runtime.env ps --all
docker compose --env-file .local/runtime.env cp runtime-init:/opt/archguard/scanner.jar .local/scanner.jar
```

`local-up.ps1` 首次生成随机凭据，重复启动必须复用它们；不要在有数据卷时删除或改写 `.local/`。只有 Web 绑定主机回环 `127.0.0.1:8080`，Platform、PostgreSQL、Keycloak 和 Runner 不应暴露主机端口。Runner 应持续运行，不应循环重启。

## 合成闭环

使用固定的 `governance/java-ci-journey` 合成源码。脚本在本地 Keycloak realm 临时创建仅用于验收的直授客户端，取得 Maintainer Token，并在成功或失败时删除客户端。它用实际 Scanner JAR 分别扫描干净与违规源码，向运行中的 Platform 提交原始报告，验证：

- 无基线时明确 `ERROR/64`，提升成功扫描后基线版本为 1；
- 签名 PR Webhook 生效，错误签名拒绝；
- 新增 high Finding 得到 `NEW=1`、`FAIL/2`，相同报告重放返回同一提交；
- 有效例外得到 `PASS/0`，到期后重新得到 `FAIL/2`；
- 修复后当前 PR head 更新且门禁 `PASS/0`；
- 修复后基线比较仍为 `RESOLVED=0`，独立 PR 修订差异返回 `RESOLVED=1`；两种参考点不得混用。

```powershell
$python = '<Python 3 executable>'
& $python scripts/verify-governance-compose.py --samples-root $env:ARCHGUARD_SOURCES_CONTEXT
```

2026-09-27 使用 Platform `16dd5e5`、Web `437eb6b`、Samples `4b63edb` 和 Scanner `d4b8e98` 完成一次真实 Compose 重跑，脚本输出 `newCount=1`、`introducedExit=2`、`exceptionExit=0`、`expiredExit=2`、`repairExit=0`、`baselineResolvedCount=0`、`prRevisionResolvedCount=1`。PostgreSQL 审计查询确认该合成 Project 的基线提升 1 次、比较 2 次、门禁 5 次、Webhook 2 次、例外创建 1 次、报告接收/完成各 3 次。Platform 从现存 Flyway V6 数据卷正常升级到 V7，未清空卷。

同日再次从 Platform [`v0.4.0`](https://github.com/AI-ArchGuard/archguard-platform/releases/tag/v0.4.0) 对应提交 `354392e5`、Web [`v0.2.0`](https://github.com/AI-ArchGuard/archguard-web/releases/tag/v0.2.0) 对应提交 `a05cffb6`、上述固定 Scanner/Samples 构建 Compose：Platform/Web/PostgreSQL 健康，Runner 持续运行，只有 Web 暴露 `127.0.0.1:8080`。Flyway 校验 7 个迁移、当前为 V7。完整脚本再次得到 `NEW=1`、`FAIL/2`、有效例外 `PASS/0`、到期后 `FAIL/2`、修复 `PASS/0`、基线 `RESOLVED=0` 与 PR 修订差异 `RESOLVED=1`。最终 Project `10a862b9-1efe-4475-a8a8-ac796e2756eb` 的审计计数：基线 1、比较 2、门禁 5、Webhook 2、例外 1、报告接收/完成各 3；测试用 Keycloak 客户端在脚本结束时已删除。

首次重跑发现 Scanner 制品卷遮蔽了 Platform 镜像自带的应用 JAR，导致容器仍运行 V6 代码并返回 500。现已把卷移至 `/opt/archguard/scanner-artifacts` 并加入 Compose 布局断言；修复后迁移到 V7、闭环通过。此复现说明升级检查必须核对运行容器内的实际应用和迁移版本，不能仅凭镜像构建成功。

本地环境停止使用 `docker compose --env-file .local/runtime.env down`；不加 `--volumes`，保留验收数据以便复核。不要把本地 `.local/`、Token、密码或扫描报告提交到仓库。
