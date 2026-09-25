# ArchGuard Deploy

ArchGuard 的本地、测试和生产部署、兼容矩阵及可观测配置仓库。

## 当前状态

阶段 2 Platform MVP 已提供本地 Docker Compose。Web 是唯一公开入口；Platform、PostgreSQL、Keycloak 内部端口与 Scanner Runner 均不暴露到主机。兼容版本见 [兼容矩阵](compatibility/platform-mvp.md)。

阶段 3E 增加 [GitHub CI 与 Webhook 接入模板](docs/governance-3e-ci.md)。模板不会自动启用；需先部署 Platform 3E 并配置 HTTPS 入口和有权限的 CI 身份。Scanner 与 Result Schema 不变。

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

在八仓库同级检出后，Windows 使用一条命令生成本地短期凭据并启动：

```powershell
.\scripts\local-up.ps1
```

脚本只把随机凭据写入被忽略的 `.local/`，并在本次终端显示演示用户 `maintainer` 的随机密码。打开 `http://localhost:8080` 完成 OIDC 登录。源码输入固定只读挂载自 `../archguard-samples`，Repository API 只接受其下相对路径。

配置验证：

```bash
docker compose --env-file .local/runtime.env config
git diff --check
git status --short
```

Runner 使用版本化文件邮箱，不接收数据库/OIDC 凭据，运行时无网络、非 root、只读根文件系统、删除全部 capabilities，并设置内存、PID、超时和进程树终止边界。任务工作目录在完成、失败或取消后立即删除；无法删除的目录留在临时文件系统，容器重启时清除。

停止环境：

```powershell
docker compose --env-file .local/runtime.env down
```

需要清空本地 PostgreSQL、邮箱和制品卷时，显式追加 `--volumes`；该操作会删除本地数据，不属于普通停止流程。

## 许可证

本仓库采用 [Apache License 2.0](LICENSE)。
