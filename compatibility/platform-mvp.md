# Platform MVP Compatibility Matrix

本矩阵是阶段 2 的可复现组合。应用仓库必须检出下列 tag；外部基础镜像同时固定 tag 与 OCI digest。

| 制品 | 版本 / 提交 | 制品摘要 | 契约 |
|---|---|---|---|
| `archguard-web` | [`v0.1.0`](https://github.com/AI-ArchGuard/archguard-web/releases/tag/v0.1.0) / `b746f4d10114d745518038123e2512cc0379dd6c` | `archguard-web-dist.tar.gz`: `sha256:43fb882a07bf42d06c5f9e82204418799951805650bc8764720514b120317892` | Platform OpenAPI v1 |
| `archguard-platform` | [`v0.3.0`](https://github.com/AI-ArchGuard/archguard-platform/releases/tag/v0.3.0) / `1e5278653c0a1b22a4332c3d6b6524eccd6c2d70` | JAR: `sha256:e3c71d084e9c3951eeb538461752178423dce39c30f21cf4b3e10122a9241f96`; OpenAPI: `sha256:962f47f037a4c23f3c0a01f3645ac79d21be2252a107527b31f4cf778d82b1f7` | Result Schema `0.1.0`、Rules Schema `0.1.0`、Runner mailbox `0.1.0` |
| `archguard-scanner` | [`v0.2.1`](https://github.com/AI-ArchGuard/archguard-scanner/releases/tag/v0.2.1) / `aad5ad6e135aa5ae86f3732f21552f9d2108e383` | JAR: `sha256:c2119c2e5ded8d5f1de18f64e0f3959864033b44af22e0ca6611c9761db1ed1f` | CLI exit `0/2/64/70`、Result/Rules Schema `0.1.0` |
| `archguard-samples` | `7b93248bf67619a6b26c1d428bcf92d1fe3a781b` | Git commit | clean / violation Compose 验收输入 |
| PostgreSQL | `17.7-alpine` | `sha256:bb377b7239d2774ac8cc76f481596ce96c5a6b5e9d141f6d0a0ee371a6e7c0f2` | Flyway V1–V2 |
| Keycloak | `26.5.3` | `sha256:5a236ae4dd8ece77490115bace15a11a4d15e9cbcf58a490b95a7da2cd71d32a` | OIDC Authorization Code + PKCE |

## 发布顺序

1. 合并 Docs Feature Spec 与独立 Web ADR。
2. 发布 Web 治理基线。
3. 发布 Scanner `v0.2.1` 并记录 JAR SHA-256。
4. 发布 Platform `v0.3.0`；按本矩阵从固定 Scanner 源码与 JAR 构建本地 Runner 镜像。
5. 发布 Web `v0.1.0`。
6. 固定外部镜像 digest、Scanner JAR SHA-256 和 Samples 提交后发布 Deploy `v0.3.0`。

## 回滚

先撤销 Web/Compose 入口，再回退 Platform 应用。Flyway V2 保留且不执行 down migration；旧应用不得访问 V2 新表。Scanner `v0.2.1` 向后兼容并保留。最后才回退 Docs 状态。

阶段 2 不发布 ArchGuard 容器到远程 Registry；Compose 中 `archguard/scanner`、`archguard/platform` 和 `archguard/web` 是从上述不可变源码版本构建的本地镜像标签。不得把本地 image ID 当作可跨主机验证的 Registry digest。远程镜像发布与供应链签名留到后续发布阶段。
