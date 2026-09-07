# ArchGuard Deploy

ArchGuard 的本地、测试和生产部署、兼容矩阵及可观测配置仓库。

## 当前状态

M0 仓库基线已建立，Docker Compose、镜像和环境配置尚未添加。

## 职责

- 提供本地 Docker Compose、CI/Staging/Production 部署方案和健康检查。
- 记录各仓库可部署版本的兼容矩阵、发布顺序和回滚步骤。
- 管理可观测配置、资源限制、备份恢复与演练脚本。
- 确保镜像非 root 运行，配置与 Secret 分离，公网只暴露必要入口。

## 非职责

- 不实现 Platform、Scanner 或 MCP Gateway 的业务代码。
- 不把 Secret、私钥、真实数据或环境凭据提交到 Git。
- 不在没有容量证据时引入 Kubernetes。
- 不把数据库、Redis、内部服务或管理端口暴露到公网。

## 依赖与契约

- 仅部署已发布并记录兼容关系的 Platform、Scanner 和 Gateway 制品。
- 应用、数据库迁移和配置变化必须声明兼容顺序及回滚边界。
- 跨仓库架构与工程规范以 [archguard-docs](https://github.com/AI-ArchGuard/archguard-docs) 为准。

## 本地验证

当前基线可执行：

```bash
git diff --check
git status --short
```

添加 Compose 配置后运行 `docker compose config`，再按 README 执行启动、健康检查、备份和恢复验证。当前尚无 Compose 文件可验证。
