# 持续治理 `v0.4.0-governance` 兼容矩阵

状态：版本制品已发布且最终 Compose 复验通过；Deploy 主分支检查完成后作为阶段 3 的可复现组合。各仓库独立版本，不把阶段名当作统一制品版本。

| 组件 | 固定版本 / 提交 | 已发布制品或固定输入 | 契约 |
|---|---|---|---|
| Platform | [`v0.4.0`](https://github.com/AI-ArchGuard/archguard-platform/releases/tag/v0.4.0) / `354392e58e2fac7dc79de3619e39aebb1e03bee7` | `archguard-platform-0.4.0.jar` SHA-256 `1ab6f01551c1aa79edb42c5365d041f621e9ea3a690f727c1ad4efb7f67c26ba`；`platform-v1.yaml` SHA-256 `962f47f037a4c23f3c0a01f3645ac79d21be2252a107527b31f4cf778d82b1f7` | Flyway V1–V7；治理只读 API `0.2.0`；Scanner Result/Rules Schema `0.1.0` |
| Web | [`v0.2.0`](https://github.com/AI-ArchGuard/archguard-web/releases/tag/v0.2.0) / `a05cffb665d2ddc1d185991890c0183357572f8a` | `archguard-web-dist.tar.gz` SHA-256 `e5e73509c003f1722912db6a105b9c2810b359bdc6be42c7304a48a8c5638773` | 使用固定的 Platform 治理只读 API `0.2.0` 快照；PR 差异仅只读 |
| Scanner | [`v0.2.1`](https://github.com/AI-ArchGuard/archguard-scanner/releases/tag/v0.2.1) / `aad5ad6e135aa5ae86f3732f21552f9d2108e383` | 发布 JAR SHA-256 `c2119c2e5ded8d5f1de18f64e0f3959864033b44af22e0ca6611c9761db1ed1f`；本地容器从 Docker 构建修复提交 `d4b8e98bfdabbc78f65910ed37e3062167d04b07` 构建 | CLI `0/2/64/70`；Result/Rules Schema 仍为 `0.1.0`，无阶段 3 Scanner 代码或 Schema 修改 |
| Samples | `4b63edb8909d9c12b93c2dc9ad07707cb009781a` | `governance/java-ci-journey` 合成 clean / violation 输入 | 仅固定测试输入；不含客户源码 |
| PostgreSQL | `17.7-alpine` | OCI digest `sha256:bb377b7239d2774ac8cc76f481596ce96c5a6b5e9d141f6d0a0ee371a6e7c0f2` | 保存不可变基线、PR head 历史和治理审计 |
| Keycloak | `26.5.3` | OCI digest `sha256:5a236ae4dd8ece77490115bace15a11a4d15e9cbcf58a490b95a7da2cd71d32a` | 本地 OIDC PKCE 演示身份；不作为生产身份部署 |

Scanner 的 `d4b8e98` 只修改 Dockerfile 与容器 CI，没有改动 Java 源码或契约；本地从源码重新打包的 JAR 不能冒充 `v0.2.1` 发布资产的字节摘要。阶段 3 Compose 验收记录构建提交，正式下载发布 JAR 时必须验证上表摘要。ArchGuard 容器只在本地从固定源码构建，未推送远程 Registry，不声明跨主机镜像 digest 或供应链签名。

## 发布和启用顺序

1. Docs 冻结 Feature Spec、ADR-0008/0009；Samples 固定合成输入。Scanner 继续使用 `v0.2.1` 契约。
2. 备份 PostgreSQL；部署 Platform `v0.4.0`，运行 Flyway V7，并核对容器内应用 JAR 未被 Scanner 制品卷遮蔽、迁移版本为 V7。Platform 不保存 Git 凭据，也不克隆源码。
3. 部署 Web `v0.2.0`。配置 CI 在自己的工作区运行 Scanner，提交报告与 Git 元数据；Webhook 配置 HMAC Secret、时间窗口和重放防护。
4. 使用此矩阵固定的 Samples 和 Deploy Compose，复验新增违规 `FAIL/2`、例外有效/到期、修复 `PASS/0`、独立 PR 差异 `RESOLVED=1`、基线差异 `RESOLVED=0`，再发布 Deploy `v0.4.0`。

## 回滚边界

先撤销 Web 的 PR 修订差异入口，再停止 CI 报告提交和 Webhook，再回退 Platform 应用。V7 是追加迁移，**不执行 down migration、不删除 head 历史或审计**；部署旧 Platform 版本前必须先验证其对 V7 数据库的兼容性，不能把未演练的 `v0.3.0` 回滚宣称为已验证。Scanner `v0.2.1` 与 Result/Rules Schema `0.1.0` 保留。恢复服务后重放幂等报告，核对当前 PR head 和门禁指针，不以迟到结果覆盖当前状态。
