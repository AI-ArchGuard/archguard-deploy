# 个人凭据入口与本地托管

依据 Docs [ADR-0013](https://github.com/AI-ArchGuard/archguard-docs/blob/main/adr/0013-personal-write-only-credential-management.md)。这是管理入口部署，不是 DeepSeek 真实接通、费用批准或阶段退出报告。不要使用聊天中已暴露的 Key；撤销后仅在 Web 输入新 Key。

## 固定候选与兼容顺序

Docs `fce238beeb2f3c611fb40e98ce45c849425c221c` → Platform `710025dc82b406bec2765dffe2c2749315c199ed`（API 0.1.0，应用仍 0.4.0）→ Web `888885ad0db012491ca3075bf03452056ec2ac40`（仍 0.2.0）→ 本 Deploy 配置。三个提供方/消费者的 PR 与 main CI 均成功后才配置。源码必须是这些提交或相同完整 Git tree 的已测试独立工作树；不覆盖根检出的用户修改。Scanner 0.2.1、Schema、数据库迁移及历史结果不变。

仅个人 `localhost`，沿用独立 `archguard-agent-4h` / 8081；8080 旧环境不动。不要叠加 synthetic/rollback override；本配置显式关闭 Agent 与假模型。Web 构建参数和后端管理开关默认都 false，下面的已确认个人配置才显式打开。Web 仅绑定 127.0.0.1，其他服务无主机端口，Platform 后端网络 internal。没有远程/公网 HTTPS 部署能力承诺。

## 确认专用 OIDC 身份

不复用 `admin` 或共享 `maintainer`。在拥有现有 Keycloak 配置的本机 Windows 用户下执行：

```powershell
./scripts/configure-personal-owner.ps1 `
  -RuntimeDirectory 'C:/absolute/existing-deploy/.local' `
  -PlatformContext 'C:/absolute/verified-platform' `
  -WebContext 'C:/absolute/verified-web' `
  -SourcesContext 'C:/absolute/verified-synthetic-samples' `
  -Port 8081
```

脚本从配套 runtime.env 在内存中取得现有本地管理员凭据，创建 `agent-owner`，使用服务实际分配的 UUID，不默认授予项目/管理员权限。初始随机密码仅写入 `.local/private/agent-owner.json`，文件/目录 ACL 仅当前 Windows 用户和 SYSTEM；首次登录要求 UPDATE_PASSWORD。不要把该文件内容贴入聊天、截图、Issue 或日志。脚本不打印密码/Token，不测试模型。账户/配置不一致则拒绝，不自动接管、删除或重置账号。部分失败须私下核对账号与恢复记录后人工恢复，不盲目重跑/删文件。

`.local/credentials.env` 只有非敏感 owner UUID、稳定 deployment UUID、显式开关及固定上下文路径；复用现有 DB/OIDC/Webhook runtime.env，不轮换现有凭据。脚本保留 realm 中其他账号，并为新账号保留相同 UUID 的导入种子。保管 deployment UUID，它绑定密文 AAD，改动后旧密文不可解密。

现有 Keycloak 是开发模式，数据库在容器可写层，并非生产身份托管。普通容器 restart 保留账号；**删除/重建 Keycloak 可能重新导入初始临时密码**，导入种子不是已改密码/会话的备份。完成首次改密后私下更新/清理初始恢复材料；不要据此声称 OIDC 备份恢复已通过。Keycloak 持久化/备份升级另列切片，不能删旧容器/卷来“修复登录”。

## 独立主密钥与密文卷

两个专用命名卷：`credential-master` 和 `credential-ciphertext`，保留相同 Compose project 名。master.key 是 32 个**原始随机字节**，不是十六进制文本；仅首次空卷初始化生成。UID/GID 10001，目录 0700、master 0400。Platform master 挂载只读 `/run/archguard-master`，密文目录可写 `/var/lib/archguard/credentials`；不进入业务数据库/镜像/Git。两个卷仍属于同一受控 Docker 主机，不能防御被攻陷的 Docker 管理员。不要共同导出/公开备份。

```powershell
$args = @('-p', 'archguard-agent-4h', '-f', 'compose.yaml', '-f', 'compose.personal-credentials.yaml',
          '--env-file', '.local/runtime.env', '--env-file', '.local/credentials.env')
docker compose @args run --rm --no-deps credential-init
docker compose @args run --rm --no-deps credential-check
docker compose @args build archguard-platform archguard-web
docker compose @args up -d --no-deps archguard-platform archguard-web
```

每一步须检查成功再执行下一步。init 无网络、只读根目录、仅 CHOWN capability；仅初始化两个 root-owned **空卷**，重复执行不轮换。已有私有卷由 UID 10001 的无 capability verifier 检查；master 缺失/长度错、权限异常、符号链接、额外文件均拒绝，无 ACL 修复/明文回退/自动重新生成。错误 master/认证失败由 Platform 校验，保留原文件。单进程部署，不允许多个实例共享卷。

不要直接显示 `docker compose config` 或 `docker inspect` 全量输出，它们可能含现有 DB/OIDC 密码。配置校验应通过不打印值的 verifier：

```powershell
docker compose @args --profile credential-bootstrap config --format json |
  py -3.14 scripts/verify-credential-compose-config.py -
```

打开 `http://localhost:8081/settings/model-credentials`，用专用账号登录并完成首次改密。输入框只写不读；保存/替换/删除均不验证余额/有效性、不发起模型请求。删除本地 Key 不等于提供方撤销。专用账号是部署凭据 owner，不自动获得现有项目访问权限。

## 验证与回滚

本地/CI：配置默认关闭与网络/挂载边界断言，真实 Docker 临时合成卷首次/重复初始化、权限/符号链接/缺失 master 拒绝；Windows 离线账号测试覆盖私有 ACL、服务分配 UUID、首登改密、重复配置和身份不匹配拒绝。只删除测试自己创建的唯一临时卷/目录，不删除活动卷。

实际部署须核对 Web/Platform 健康、匿名 401 / 非 owner 403、owner 状态无 Key、no-store、密文及 master 在容器 restart 后保留。owner 完成首次登录前不能声称已通过该账号的实际写删验收。真实 Key 只由用户输入；不要自动用合成测试覆盖已有活动 Key。所有凭据操作都不启用真实出口，阶段 Issue 继续打开。

`scripts/verify-personal-login.mjs` 可复用已安装的 Web Playwright 开发依赖（无新增依赖）进行实际环回登录 smoke；参数依次是 Web 上下文、原配套 runtime 目录、受保护 owner JSON 绝对路径、环回 Origin。只在内存读取登录密码，无截图/trace/录像/原始错误输出，拒绝浏览器外部请求，不提交任何 Key；验证 401、maintainer 403、专用账号初始密码可登录且必须改密，并把首次改密留给所有者。owner 改密后不要再用该初始密码 smoke。重启测试仅重启两个应用，不删除/重建 Keycloak 或 DB。

回滚先将 credentials.env 中两个管理开关改为 false（Web 需重新构建），确认接口拒绝/入口关闭，Agent/模型仍 false，再回退应用。保留两个专用卷、稳定 deployment UUID、数据库和审计；不执行 `down --volumes`，不改写迁移，不回退到环境变量 Key。主密钥丢失/篡改须人工恢复，不自动销毁密文；删除本地槽位也不承诺物理/快照擦除。
