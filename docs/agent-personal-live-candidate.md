# 个人 Agent 受限出口候选与最终回滚手册

这是显式 1017 候选及后续操作手册，不是运行验收、Release 或唯一阶段报告。当前固定 Docs/Platform/Web SHA 已合并且 main CI 成功，提供方 Settings/ack `0.4.0` 与消费者显式确认精确配对获批 `DeepSeek-V4.1-Flash-1017`；来源和 CI 见兼容矩阵。旧 10-15 工程组合不再是当前候选，历史记录保留。当前默认关闭真实 Agent、live、inventory、凭据管理和三个 Web 构建入口，官方地址集合默认为空。实现、离线/临时容器验证不消费模型授权。实际栈启用仍须本 Deploy PR/main CI、合并后真实 Deploy SHA、固定制品和新鲜人工绑定条件通过；本实现任务不启动活动环境、不读取运行 Secret、不查询模型账户。

固定源码、制品差异和回滚顺序见[兼容矩阵](../compatibility/agent-personal-live.md)。历史[九表合成演练](agent-rollback-rehearsal.md)保持原语义；这里新增的 21 表最终校验不能用旧报告替代。Scanner Result/Rules Schema、确定性 Findings、门禁与退出码保持不变，不启用 Gateway/Evals。

## 工程验证边界

CI 保留已有治理适配器、Compose/凭据卷、Windows 启动/owner 和 LF 检查，增加默认关闭/显式绑定/关闭后的 live 渲染模型。渲染只用合成值，不启动服务或证明真实批准。

live 渲染契约核验版本为 Docker Compose `5.5.1`；不承诺所有 `>=2.24.4` 版本都保留安全字段。2026-10-19 CI 的 `2.38.2` 将三个受控 bind 的显式 `create_host_path: false` 渲染为 `bind: {}`，严格 verifier 因而拒绝，不能把缺失字段解释为 false。CI 仅在本 job 的 `RUNNER_TEMP/archguard-compose` 下载[官方 v5.5.1 Linux x86_64 二进制](https://github.com/docker/compose/releases/download/v5.5.1/docker-compose-linux-x86_64)，先验证 SHA256 `db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576`，再赋予执行权限并以绝对路径使用；不全局安装或修改 Docker 配置。来源与摘要由操作员从[官方发布](https://github.com/docker/compose/releases/tag/v5.5.1)实际核对（发布时间 2026-09-03）。这是已使用的 Apache-2.0 Compose 工具版本固定，不增加运行依赖；相较自动更新宿主插件或增加安装 Action，独立文件无需改变宿主工具和引入额外 Action 依赖。本机操作同样须核对 `5.5.1`，升级/替代版本须重跑全部模型和字段保留验证。

同一套完整 `scripts/test_*.py` 在 Windows 上覆盖原生 ACL；Linux 在已构建 guard 镜像内以 UID0、cap_drop ALL、只读仓库、network none 和临时 `/tmp` 运行，从而实际覆盖原生 POSIX 所有权/模式。容器 UID0 不要求宿主测试进程以 root 运行。真实本地 socket 是离线测试，不是官方外发。

临时 Docker 网络测试只连接自有合成 TCP peer，覆盖精确 DB/OIDC/Web、官方形状 /32、DNS/UDP/IPv6、错误端口、真实 shell/curl 的代理/curlrc/重定向拒绝、就绪失败、guard crash 与已建立连接撤销。HTTP fixture 使用真实 nginx 回滚代理。镜像先构建/拉取再取得本地不可变 ID，测试本身禁止拉取、活动卷、Secret、宿主 namespace、Docker socket 挂载和真实官方请求。

构建上下文只允许 `netguard/`、`scripts/ci-curl-fixture/` 和单独核验的 Platform/Web/Scanner 仓库。Deploy `.local` 必须位于每个实际构建/打包上下文之外；Git ignore 本身不能证明 Docker 排除。禁止改成 Deploy 根目录构建。依赖、许可证及非位级复现限制见[guard 说明](../netguard/DEPENDENCIES.md)和[测试 curl 镜像说明](../scripts/ci-curl-fixture/DEPENDENCIES.md)。CI 测试基础镜像 pin 不会自动修改业务 Dockerfile 的浮动 runtime 标签；实际候选仍须记录构建字节、包版本和镜像 ID。

操作员可在 root 审核后运行这些测试；参数必须是刚核验的本地 `sha256:...` image ID，不能用标签或把本地 ID 当作 registry digest：

```powershell
python scripts/test-agent-network.py --image $guardImage --platform-image $curlFixtureImage
python scripts/live-compose-fixtures/test_rollback_proxy_http.py --image $nginxFixtureImage --client-image $guardImage
python scripts/test-agent-inventory-volume.py --image $guardImage
```

第三条只创建唯一临时空卷：UID0/no capabilities/network none 初始化，UID10001/只读卷验证，拒绝覆盖后再次验证并内部比较字节；仅输出 PASS/布尔。按返回的精确 container ID、卷名及独有标签核验后清理，没有 prune、通配删除或活动卷名。具体执行结果以 root 的当前日志/PR CI 为准；文档不预先宣称这些新 CI 和 volume fixture 已通过。

## 实际操作前必须满足的条件

1. 核对[矩阵](../compatibility/agent-personal-live.md)全部源码 SHA、实际当前 JAR/Web 字节和构建参数；所有相关 PR/main CI 成功。Deploy SHA 只能在合并后由操作员提供真实值，不能伪造 self-pin、pending 值或用旧版本号替代。备份、回滚旧制品来源和本机私有证据位置也须事先确认。
2. 继续使用同一 `archguard-agent-4h` project、8081、原配套 runtime/credentials 配置、deployment UUID 和全部既有卷。8080 环境不动。Keycloak 当前账号/已改密码不以导入种子恢复；不删除/重建 Keycloak，不重置账号，不自动恢复旧 Key 或临时密码。
3. 只由所有者在原只写 UI 输入新 Key。不要使用聊天中暴露的 Key，不探测有效性、余额、账户或新增请求。不把 Key 放入 Compose/JSON/环境变量/脚本。此前的凭据状态读取及凭据卷保留比较须在最终 capture 前完成；状态 GET 可能访问后端密文并记审计。
4. 必须新建符合当前 cost policy 的明确 Project enablement 和批准 batch。旧 acknowledgement 缺少当前策略/绑定就拒绝，不能自动迁移、沿用批准或自动选最新 Project/batch。固定 current credentialVersion、deployment/project/batch/inventory UUID、manifest SHA、networkCheckRef、secretCheckRef 和有效期，均不能通配。
5. 官方协议、价格和模型映射必须在实际两次请求前重新核对。2026-10-18 的人工更新只涉及 `DeepSeek-V4.1-Flash-1017` 官方映射；其他条件及总计两次上限不变，不能推导更多调用。当前候选使用 Settings/ack `0.4.0` 与精确 1017 配对；Batch `0.3.0`、live API/输出和 Scanner Schema `0.1.0` 不变。旧确认可读、撤销、独立结算，但不得静默升级为当前批准或产生新真实发送。固定请求名及单元素响应白名单均仅为 `deepseek-flash`，公告快照名不能加入白名单；与获批映射不一致即停止，不擅改 endpoint/model 或价格策略。固定 `/responses`、非流式、无工具/会话/重试、`reasoning.effort=none`、`tool_choice=none`、`store=false` 及上下文价格版本 `deepseek-flash-context-peak-usd-2026-10-15` 不变。
6. 每次完整请求至多 6000 UTF-8 字节、输出至多 1500 Token；输入 8000 是调用后的观察阈值，不是增加请求大小的许可。每次预留 316373 microUSD，单次/批次上限 350000/700000，Project/部署日上限 5000000/20000000。费用、真实 usage 或引用异常立即停止，无探测、自动重试或失败替代。

## 新的受控 inventory 原生卷

inventory 是来源审查记录，不是调用许可。Platform 保持现有严格校验，缺失/失效只使 Agent 不可用；不会阻止核心启动。Windows host bind 在 Linux 显示 0777，不能冒充 Platform 所需的原生权限证明。

操作员必须先人工审查固定合成 fixture，再准备受控 UTF-8 `inventory.json`：根键严格为 `schemaVersion=0.1.0`、实际 `deploymentId`、`entries`。每项严格包含 `inventoryId/projectId/manifestSha256/sourceKind/fixtureSetVersion/fixtureArtifactSha256/reviewRef/reviewedAt/expiresAt`；sourceKind 为 `CONTROLLED_SYNTHETIC_FIXTURES`，ID/摘要/短 ref 必须规范、无 URL/路径/凭据前缀，所有条目都有效且无重复 ID，1–20 项，1–32768 字节。reviewedAt 不晚于当前 UTC，expiresAt 在当前 UTC 之后且距离 review 至多 24 小时。不得让初始化器生成 review、时间、manifest 或批准。

只针对显式新建、已确认不存在的专用 `archguard-agent-4h_agent-live-inventory` 空卷执行一次。卷若已经存在、部分初始化或包含任何条目（含 dotfile/目录/链接），立即停止人工核对；不得通过删除、chmod、repair 或换用旧卷来重跑。核对 Compose 渲染的实际卷名与该名字完全一致，不能只看逻辑 key。

初始化器命令只有 `initialize/verify`，内部输入 `/reviewed/inventory.json`、卷 `/inventory`、目标 `/inventory/inventory.json` 固定，不接受任意路径或命令参数。初始化以 UID0、cap_drop ALL、network none、只读根运行，仅该新 inventory 卷可写；只读挂载审查文件和初始化器单个脚本，禁止 credential/source/DB 卷、CHOWN/NET_ADMIN/SYS_ADMIN。先确认卷不存在，再显式 `docker volume create archguard-agent-4h_agent-live-inventory`；这不是幂等的日常启动步骤。

```powershell
$initializer = "$PWD/scripts/initialize-agent-inventory.py"
# $reviewedInventory 是本次人工审查文件的绝对路径；不打印其内容。
docker run --rm --pull=never --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges:true --user=0:0 --no-healthcheck --pids-limit=32 --memory=64m --mount "type=bind,source=$initializer,target=/fixture/initializer.py,readonly" --mount "type=bind,source=$reviewedInventory,target=/reviewed/inventory.json,readonly" --mount "type=volume,source=archguard-agent-4h_agent-live-inventory,target=/inventory" --entrypoint python3 $guardImage /fixture/initializer.py initialize
# 每一步必须检查成功；验证不需要再挂载审查源文件。
docker run --rm --pull=never --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges:true --user=10001:10001 --no-healthcheck --pids-limit=32 --memory=64m --mount "type=bind,source=$initializer,target=/fixture/initializer.py,readonly" --mount "type=volume,source=archguard-agent-4h_agent-live-inventory,target=/inventory,readonly" --entrypoint python3 $guardImage /fixture/initializer.py verify
```

目标最终 root-owned 目录 0555、文件 0444；保持原审查字节，exclusive/nofollow 创建、有界写入和 fsync，失败不清理/修复/重试。验证以 UID10001 只读检查实际 native 权限、无链接/额外条目、内容边界及内部字节稳定。Platform 仅只读挂载到 `/run/archguard-inventory`，其他服务不得挂载。后端仍权威校验具体 deployment/Project/manifest 匹配和批次有效期。

## 命名空间准备、启动和两次请求

本节是工程及 main CI 全通过后的人工运行关卡，不由本任务执行。用 base + personal-credentials + agent-live 三层，不混用 synthetic 或历史 rollback override。以同一受控配置显式提供绝对 network JSON、Platform hosts 路径和原始 JSON SHA256；默认开关仍 false。JSON 只包含版本、规范公网 IPv4 官方集合和本次实际 postgres/keycloak/web RFC1918 地址，可选 allowOfficial 默认为 false。官方地址须在本次准备中核对，仅固定 `api.deepseek.com` IPv4:443；不使用 CDN 网段、代理、DNS 自动放宽或 IPv6。

Platform 的单独只读 `/etc/hosts` 必须固定 localhost、postgres、keycloak 和相同官方地址；共享 network namespace 不共享 hosts。核对现有 DB/OIDC/Web 实际 IP；任何重建导致地址变化都失败关闭、重新审查，不为此重建 Keycloak。Web 是唯一回环入口；DB/OIDC/Platform/guard 无新增主机端口。guard 是唯一 NET_ADMIN 持有者；Platform UID10001、cap_drop ALL、只读，双方 restart=no。

```powershell
$live = @('-p','archguard-agent-4h','-f','compose.yaml','-f','compose.personal-credentials.yaml',
          '-f','compose.agent-live.yaml','--env-file','.local/runtime.env',
          '--env-file','.local/credentials.env','--env-file','.local/agent-personal-live/live.env')
docker compose @live --profile credential-bootstrap config --format json |
  python scripts/verify-agent-live-compose-config.py -
```

不要显示完整 config/inspect/env，它们可能包含 DB/OIDC 凭据。live.env 仅本机受控、非 Key 配置和具体绑定。Web UI 开关是构建时参数，需要在变更后重建并核对实际产物，不替代后端权限。

任何创建/替换 namespace 都先停止 Platform，再创建 guard、等同 namespace readiness 摘要匹配后重建/启动 Platform。不得先启动 Java、依赖自动 restart 或把存活健康检查当作自动停机。`guard.py close` 只能撤销官方集合，没有自动 reopen；需要开启官方集合时必须用新审查配置按同样顺序替换 namespace。所有服务地址变化均须重新审查。

在明确绑定新 Project/batch/inventory/current credential/refs、24 小时来源证明和原两次条件授权后，才显式打开所需开关和官方集合：串行解释一次 → 成功且结算 → 摘要一次。任何一步失败、UNKNOWN、超阈值、引用/审计异常都停止，不补次数。核对真实 usage/费用/引用、保留原 PASS/FAIL 和退出码；不通过额外模型请求“测试连接”。

## 最终关闭、私有 capture、旧应用与恢复

1. 在 capture 前完成 Project 禁用/撤销、batch stop、调用终态及 worker 清理；关闭部署 Agent/live/inventory/管理和全部 Web 入口，重建关闭入口的 Web 并启用 live-closed 回滚代理。该代理拒绝 Agent/文档路径为稳定 503/no-store/traceId，同时核心扫描/治理/OIDC仍保留。
2. 用仍运行的 guard 显式清空官方集合，检查本表 readback 及同 namespace 的受控证明；确认既有连接也被切断。仅 YAML=false 不是内核关闭证明。guard crash 仅保证过滤规则留在仍持有 namespace 的 Platform；Docker 可能移除 bridge/路由，不承诺 DB/OIDC/Web 可用，更不是即时费用/权限撤销。

```powershell
docker compose @live exec -T agent-netguard python3 /opt/archguard/netguard/guard.py close
# 后续关闭配置使用同一 project/env/卷，额外加 -f compose.agent-live-closed.yaml。
# 先停 Platform 并确认 worker 终止，再捕获；不要执行 down --volumes。
docker compose @live stop archguard-platform
```

3. 在 capture 前由受控操作员比较原 credential-master/ciphertext 卷的身份、权限、大小和本地摘要；共享证据只写 unchanged 布尔，不公开文件内容或其摘要。此工程脚本不访问凭据卷。所有凭据状态 GET 均安排在 capture 前，之后 `agent.`、`agent_document.`、`AGENT_CREDENTIAL_`（包括 null-project、失败/拒绝/STATUS）不得再追加审计。
4. 在固定 Deploy `.local/agent-personal-live/` 准备私有 `candidate.json`：schemaVersion `0.1.0`、kind `PERSONAL_LIVE_FINAL_ROLLBACK`、实际 deploymentId、矩阵中的五个 `candidates` SHA + 实际合并 `candidates.deploy` SHA、namespaceProofRef、configProofRef、仅在上述完成后置 true 的 shutdownComplete。当前 verifier 只接受矩阵中的精确 1017 新组合，拒绝旧工程组合；不接受多候选、通配或摘要绕过。Deploy SHA 仍由操作员在本 PR 合并/main CI 后填入，不能使用旧基线、PR head 或伪造 self-pin。默认省略 allowedAuditAppends；若旧应用受控确定性旅程需要追加审计，必须事先列出确切 `[action, projectUUID, traceId]` 三元组，不能用前缀/通配/事后补许可或脚本自动生成集合。该布尔和 ref 是操作员绑定，不替代运行证明。
5. Windows 目录与文件必须当前用户所有，仅 owner/SYSTEM 有 ALLOW 权限，无链接/reparse。POSIX 要求当前用户所有、目录 0700/文件 0600。操作员事先设置私有权限，校验器只读检查，不更改 ACL；它固定使用系统 PowerShell 模块、五秒超时、env-carried literal path，只接收布尔。ACL 不可用则拒绝写入。private 路径必须排除 Git、所有实际 Docker context、包、日志、浏览器附件和公开 CI artifacts。

```powershell
python scripts/verify-agent-live-rollback.py capture
# --validate-only 明确不写文件、不证明 protected runtime capture。
python scripts/verify-agent-live-rollback.py capture --validate-only
```

capture 仅在没有 QUEUED/RUNNING 时执行，固定 `archguard-agent-4h-postgres-1`/archguard 数据库。它不登录 API、不启动/停服务、不迁移/修复数据库、不执行模型请求。固定 readonly repeatable-read UTC 事务，statement/lock timeout 各 5 秒，Docker 进程至多 15 秒；服务端原生 SHA256 对每张完整行按唯一键排序，绝不返回完整行。任何缺失/额外/重复/坏摘要/异常/超时都拒绝。审计总数与完整 UUID 列表核对，最多 5000；超出时停止，不通过 LIMIT 截断冒充完整。

固定 21 表/key 如下（V13 inventory_proof 是 live_batches 列，不是第 22 表）：

- `public.flyway_schema_history(installed_rank)`、`public.flyway_agent_schema_history(installed_rank)`。
- `agent_document.upload_requests(project_id,idempotency_key)`、`documents(id)`、`document_versions(id)`、`document_fragments(version_id,fragment_index)`。
- `agent.requests(id)`、`budget_usage(scope,scope_id,utc_day)`、`personal_enablements(id)`、`enablement_revocations(enablement_id)`、`project_settings(project_id)`。
- `agent.live_batches(id)`、`live_batch_usage(batch_id)`、`live_batch_revocations(batch_id)`、`live_budget_usage(scope,scope_id,utc_day)`、`live_attempts(request_id)`、`live_outcomes(request_id)`、`live_request_links(request_id)`、`live_batch_stops(batch_id)`、`live_template_request_slots(project_id,batch_id,template_id)`。
- `audit.audit_records(id)` 的全部 baseline UUID、完整行摘要和受控 action/project/trace；不保存 metadata/body。

主 Flyway 必须精确 V1–V8 SQL；Agent 精确 baseline8（checksum NULL）+ V9–V16 SQL（checksum 非空）、成功、脚本/type 匹配，跨阶段完整行及历史 checksum 不变。来源文件 SHA256 不等于 Flyway checksum。

6. 固定旧制品实际来源及哈希后，使用旧 Web/Platform 应用运行受控确定性旅程；旧 Web 如为 8081 重建，必须记录实际构建字节/参数，不能冒充默认 Release tarball。Agent/文档/凭据仍关闭；原数据库 V1–V16、identity、卷和 deployment UUID 保留，不 down migration、不 repair、不禁用校验。完成后运行 `python scripts/verify-agent-live-rollback.py old`。
7. 恢复矩阵固定当前制品，按先停 Platform → guard readiness → 同 namespace Platform 的顺序。保持调用关闭，单独核对当前正常 Flyway validate/Agent-ready（不发请求）、实际 JAR 内迁移资源 SHA 与固定源码一致，以及旧建议/引用的受控可读性。若读取会新增禁止审计则安排在最终 capture 前或另列运行关卡，不调整允许集合掩盖它。运行 `python scripts/verify-agent-live-rollback.py restored`，严格比较所有非审计表全行、全部 baseline 审计 UUID/摘要及仅事先批准的新增三元组。

固定快照 `rollback-history.json` 使用 exclusive 创建，已有文件/链接/不安全父目录一律拒绝，不覆盖或自动删除。三阶段只输出阶段、表数、布尔和固定失败类别。私有快照包含候选/部署 ID、计数、摘要、必要审计 UUID/分类/trace 和迁移元数据；不含源码/模型/文档/审计正文或 Secret，仍不应公开。

## 仍未执行的运行与关闭关卡

本工程不证明活动栈受限接通、两次真实 usage/费用/引用、最终 21 表实际回滚恢复、凭据卷实际保留、数据库/身份灾备或正式发布。临时 ACL/SQL/网络/原生卷测试也不替代这些结果。全部工程及 main CI 后才执行原授权的运行关卡，再核对固定制品矩阵、唯一 Docs 阶段报告和所有 main CI，最后关闭 Issue。没有新 Release、唯一验收报告或提前阶段关闭。
