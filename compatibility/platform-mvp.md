# Platform MVP Compatibility Matrix

| 制品 | 版本 | 契约 |
|---|---|---|
| `archguard-web` | `v0.1.0` | Platform OpenAPI v1 |
| `archguard-platform` | `v0.3.0` | Result Schema `0.1.0`、Rules Schema `0.1.0`、Runner mailbox `0.1.0` |
| `archguard-scanner` | `v0.2.1` | CLI exit `0/2/64/70`、Result/Rules Schema `0.1.0` |
| PostgreSQL | `17.7` | Flyway V1–V2 |
| Keycloak | `26.5.3` | OIDC Authorization Code + PKCE |

## 发布顺序

1. 合并 Docs Feature Spec 与独立 Web ADR。
2. 发布 Web 治理基线。
3. 发布 Scanner `v0.2.1` 并记录 JAR SHA-256。
4. 发布 Platform `v0.3.0` 和 Runner 镜像。
5. 发布 Web `v0.1.0`。
6. 更新这里的镜像 digest、Scanner JAR SHA-256 和 Samples 摘要后发布 Deploy。

## 回滚

先撤销 Web/Compose 入口，再回退 Platform 应用。Flyway V2 保留且不执行 down migration；旧应用不得访问 V2 新表。Scanner `v0.2.1` 向后兼容并保留。最后才回退 Docs 状态。

正式发布前必须把本地构建标签替换为不可变镜像 digest；当前未发布分支不能伪造 digest 或 JAR SHA-256。
