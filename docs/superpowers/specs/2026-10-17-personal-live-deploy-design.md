# 个人 Agent 最终候选：受限出口与回滚设计

状态：实施设计，不是部署、真实验收或阶段报告。依据所有者“仅自行输入新 Key，其余按计划完成”的持续执行要求；具体工程选择由实施者作出，未增加调用/费用授权。

## 目标和前置

仅为已批准的两次合成验收交付可验证的本地部署路径。浏览器只访问同源 Platform；不部署模型。Docs ADR-0012/0013/0014 已接受，固定协议/模型/最小投影保持不变。

候选顺序：Docs `0d0f5ede505f9afa6f369226eb7263ed123dfa3f` → Platform `9f68dea97fca7893961c8305ce84ff215be9d0df`（main CI 38876407444）→ Web `961244ef3486967186cd4a41375fb29d25786043`（PR #15 / main CI 39025229825）→ 本 Deploy PR/main CI。Scanner `d4b8e98bfdabbc78f65910ed37e3062167d04b07`、Samples `a53a5bbea2630aac2135aa217d961cdbb77851a3` 不变。代码版本仍是 Platform 0.4.0 / Web 0.2.0，不能用同名旧制品替代 SHA。

本切片只实现配置、网络守卫、离线/假 TCP 回归和只读回滚校验器。实现时不更新活动栈、不读取运行 Secret、不调用 DeepSeek/模型/账户、不创建 Release 或阶段报告。全部工程与 main CI 成功后，才另行按 ADR-0014 绑定并执行已有两次条件授权；任意失败即停止，不重批补次数。

## 不变范围

- 完整请求最多 6000 UTF-8 字节，输出最多 1500 Token；输入 8000 是调用后观察阈值。
- 固定 `https://api.deepseek.com/responses`、`deepseek-flash`、无工具/会话/流/重试，TLS/SNI 不变。
- 每请求预留 316373 microUSD，本地单次 350000、批次 700000 上限；Project/部署日限额保持 5000000/20000000。
- 双开关默认 false；具体 Project、batch、networkCheckRef、secretCheckRef 不允许通配/自动选最新。旧策略不能被升级为新批准。
- owner 凭据继续只写加密存储；新 Key 只由人通过原 UI 输入。新 Compose 不注入 Key，不探测 Key/余额。
- 保持模块化单体、Scanner Schema/门禁/退出码；不开发 Gateway/Evals，不删除旧数据或迁移。

## 网络方案（实施者选择）

比较了直接给 Platform 接外网（无法独立约束目标）、TLS 代理（增加信任和证书/代理协议变化）、容器专用 network namespace 守卫。本切片选择后者；不改变应用固定直接 HTTPS 客户端，不操作宿主机全局防火墙。

### 容器和生命周期

新增 `agent-netguard`：唯一持有 `NET_ADMIN` 的受限根进程，cap_drop ALL、只读根、有限 tmpfs/PID/内存、no-new-privileges；不挂载 Secret、Docker socket、源码、数据库/凭据卷，不 privileged/host network。只接原 internal backend 和单独非 internal `agent-egress`，后者只有守卫加入。backend 上由守卫提供 `archguard-platform` alias，供现有 Web 代理使用。

Platform 保持 UID/GID 10001、cap_drop ALL、只读根及原卷，改为 `network_mode: service:agent-netguard`，以 `!reset []` 删除继承 networks；不得同时配置 networks/extra_hosts/DNS 覆盖。DB、Keycloak、Web、Runner 网络/端口不扩张。守卫与 Platform 的 restart 均为 `no`，不依赖 Docker 自动重启顺序保证安全。

守卫先校验有界配置，再以一次 `nft -f` 事务安装默认拒绝规则，最后才启动仅 `127.0.0.1:18081` 的固定 `/ready` 服务；响应为配置原始字节 SHA-256，最大 64 字符，无控制写端点。只读健康探测使用固定 AF_INET socket 和贯穿连接/发送/每次读取的单调时钟一秒总截止时间，拒绝慢速 header/body 延长探测；最多 2048 header 字节、单一 Content-Length=64、HTTP200、精确摘要及无额外 body，不接受 Transfer-Encoding。Platform 每次启动 Java 前运行有界 wrapper（最多 30 次、每次 curl 总时限 1 秒、间隔 1 秒），只在 HTTP200 且就绪摘要与明确配置摘要完全相等时 exec 原 Java。curl 第一参数 `--disable`，显式 `--noproxy '*' --proto '=http'`、字面量 IPv4、无重定向/重试，禁止 curlrc/代理在规则尚未安装时外发。等待失败不启动 Java。

守卫退出不得删除/flush 防火墙表，内核规则在仍持有 namespace 的 Platform 中保留。当前 Docker Engine 在网络所有者容器停止时会移除其 bridge 接口和路由，因此崩溃不保证 DB/OIDC/Web 可用性；该断链行为也不能代替显式出口关闭证明。测试先在守卫存活时证明 close 切断既有官方连接且内部业务仍可用，再比较崩溃前后完整自有规则、验证仍存活的本机允许/拒绝端口和 Java 就绪拒绝。没有自动重启；替换/重建 namespace 必须先停 Platform，再建守卫并等待就绪，再启动 Platform。只读健康检查不能承诺自动停止现有应用。威胁边界不防御拥有 Docker 管理权限的人主动改网络/启动命令。

### 配置、规则与关闭

守卫只接受最大 4096 字节、重复/未知字段拒绝的 UTF-8 JSON，严格六个键：必需 `schemaVersion=0.1.0`、`officialIpv4`（1–16 个不同规范公网 IPv4）、`postgresIpv4`、`keycloakIpv4`、`webIpv4`（不同的规范 RFC1918 backend IPv4），以及可省略的 `allowOfficial`（省略即 false，提供时必须是 boolean）。不接受主机名、CIDR、端口、命令、任意文件路径或 IPv6；地址不能重叠。官方 IPv4 为操作员在本次准备中核对的固定地址，变化时关闭并重新验证，不能动态放宽到整个 CDN。

新独立 JSON 文件仅包含上述非敏感网络信息，可信操作员控制、只读挂载；Platform 专用只读 `/etc/hosts` 文件固定 localhost、postgres、keycloak 及完全相同的官方地址集合。共享 namespace 不共享 `/etc/hosts`；禁止用 `extra_hosts` 代替。本机当前 DB/OIDC/Web IP 在实际准备时记录，任何容器重建导致地址变化须失败关闭；不为此重建 Keycloak。

规则限于单独 `inet archguard_agent` 表；单次事务第一条使用独占 `create table`（不是可接受既有表的 `add table`），其余添加链/集合/规则，首次安装不得 flush ruleset/其他表。既有同名表不静默替换（需要明确关闭、停止 app、重建 namespace）；错误配置或 nft 错误不启动就绪服务。主要规则：

- output 早于 DNAT 的链拒绝全部 UDP、TCP 53/853、IPv6，防止 Docker 127.0.0.11 DNS 在普通 output 链前被改写/转发。
- input/output/forward 默认 drop；forward 不放行任何流量。
- 只允许 IPv4 localhost 8080/18081 及其精确回复；不 blanket 放行 loopback。
- 只允许向确切 postgres:5432、keycloak:8080 发起 TCP，及确切地址/源端口的 established 回复。
- 只允许确切 Web IPv4 访问 app:8080，以及 app:8080 的 established 回复。
- 仅当 `allowOfficial=true` 时把冻结的官方地址加入集合；input/output 每个官方报文（包括 established）都要求当前集合成员与 TCP 443 匹配。不得有通用 established/related accept 绕过撤销。

`guard.py close` 仅清空本表官方集合，保留 DB/OIDC/Web 和全部 drop。操作失败必须显式失败；无自动重新添加。它不是费用授权或 Project 关闭的替代品。最终关闭先禁 Project/部署/前端/凭据管理，清空集合，再回退应用。测试须证明已建立的 keepalive 在清空后也不能继续传输。

### 运行依赖及许可证

新增 nftables，仅此网络基础设施需要 Linux namespace 内核过滤，许可证 GPL-2.0-or-later；Python stdlib 用于严格 JSON/IP 校验、有界子进程和本机就绪服务，PSF-2.0，无 pip/第三方 Python 包。拟复用仓库已经固定并可本机构建的 `postgres:17.7-alpine@sha256:bb377b7239d2774ac8cc76f481596ce96c5a6b5e9d141f6d0a0ee371a6e7c0f2`（实际 Alpine 3.23.3）作为守卫基础镜像，不运行 postgres/其原 entrypoint；明确保留镜像内额外二进制的攻击面限制。nftables 固定 1.1.5-r2；Python 选择构建时同分支已签名的受支持 3.12 包，并记录实际版本/image ID，不把未锁定传递包声称为位级可复现。分发守卫镜像时须随资产提供对应许可证和可获取源码/包版本说明；本切片不发布镜像。

不选宿主机防火墙（影响其他栈）、代理（扩展既有客户端协议）、未核验第三方守卫镜像。Python 官方新基础镜像的 registry 查询本机超时，未伪造 digest，也不把它作为成功构建证据；若固定基础镜像不能实际构建/内核不支持所需规则，停止此工程关卡，不允许取消规则换通用外网。

依据：[Docker network_mode](https://docs.docker.com/reference/compose-file/services/#network_mode)、[合并与 reset](https://docs.docker.com/reference/compose-file/merge/)、[启动依赖边界](https://docs.docker.com/compose/how-tos/startup-order/)、[nftables 包和许可](https://pkgs.alpinelinux.org/package/v3.23/main/x86_64/nftables)。2026-10-17 核对。

## Compose、启动前检查及默认关闭

新增 `compose.agent-live.yaml`，只与 base + personal-credentials 组合，不与 synthetic/历史 rollback 组合。默认 Agent=false、live=false、inventory=false、官方集合关闭、Web Agent/live/credential=false、凭据管理=false。显式设置所有开关也不会跳过实际授权、绑定、当前凭据和来源核验。

使用 `oidc,local-compose,agent-live` profile，以及 `JAVA_TOOL_OPTIONS=-Djdk.httpclient.disableRetryConnect=true`；不接受代理/DNS/HTTP 调试/不安全 TLS 参数。只读 inventory、网络配置、hosts、启动 wrapper 挂载路径必须显式，不能指向含用户修改的根源码。inventory 使用独立非敏感命名卷 `agent-live-inventory`，仅 Platform 只读挂载到 `/run/archguard-inventory`，固定 `ARCHGUARD_AGENT_SYNTHETIC_INVENTORY_FILE=/run/archguard-inventory/inventory.json`。实际 Windows 只读 bind 的父目录和文件呈现 0777，不能通过现有来源校验；不得削弱 Platform 权限检查。后续独立受控初始化须使用原生 POSIX 目录 0555/文件 0444，拒绝覆盖和符号链接；本 Compose 不自动初始化或写入。真实绑定 ID/ref 默认空，live 关闭时可启动；live 开启时 verifier 要求有效且具体。管理 owner/deployment 仍来自专用个人配置，两个密钥卷名称/挂载和稳定 deployment UUID 不变。

新增独立 verifier：严格断言最终渲染模型中的守卫权限、namespace、restart、入口 wrapper、网络、无端口/Secret、readonly 路径、固定上下文/镜像、六类默认关闭与 live 开启的具体绑定。保留旧 credential/synthetic verifiers 的历史语义；为它们补充原 Platform backend-only 断言，不能让 base 被静默接外网而旧检查仍过。

live 渲染器契约固定已核验的 Docker Compose `5.5.1`，不以 `>=2.24.4` 推断安全字段保留。2026-10-19 CI 确认 `2.38.2` 输出省略 bind 的显式 `create_host_path: false`；verifier 继续拒绝缺失字段。CI 在专用临时目录使用官方独立 `5.5.1`，核对固定 SHA256 后才 chmod/执行，不全局安装或改变 Docker 配置；来源、Apache-2.0 许可和替代方案见[候选手册](../../agent-personal-live-candidate.md)。后续版本须重新验证渲染契约。

Task3 的来源卷补充采用独立 stdlib 操作员 helper，而非 Compose 自动初始化服务：固定 `/reviewed/inventory.json` → 新空原生卷 `/inventory/inventory.json`，严格复用既有 schema/20条/32768字节/24小时约束，保留人工审查原始字节。UID0、cap_drop ALL、network none，exclusive/nofollow/有界写入/fsync，目录0555/文件0444；已有任何条目（含隐藏文件、目录、链接）一律拒绝，不覆盖、不chmod既有条目、不cleanup/repair/retry。UID10001 只读验证实际 native 权限、无额外条目及字节稳定。仅 Platform 只读挂载该独立非Secret卷，不访问凭据/源码/DB卷；backend 的 deployment/Project/manifest 权威校验不变。root 专属临时卷 fixture 只用已构建 immutable guard ID，按精确返回 ID/卷名和自有标签清理，不操作活动卷。完整原有 Python suite 在 guard 容器UID0/只读源码/networknone/tmpfs运行以实际覆盖POSIX所有权，不用跳过或放松断言绕过；Windows仍运行同一完整suite与原生ACL回归。

新 `compose.agent-live-closed.yaml` 明确覆盖所有调用/来源/管理/UI 开关为 false，使用拒绝全部 `/api/v1/agent/` 及项目 agent/documents 的回滚代理。guard close 为独立必做步骤，不能仅凭 YAML 值声称内核出口已关闭。代理返回稳定 503/no-store/traceId，扫描/门禁/OIDC 继续工作。

## 最终只读历史校验器

新增单独 `verify-agent-live-rollback.py`，不重解释历史九表的 synthetic 脚本/报告。capture/old/restored 三阶段不部署、修改数据库、发起模型或读取明文凭据。私有快照只含候选/部署标识、稳定排序摘要、必要的审计 UUID/行摘要和迁移元数据；不保存源码/模型/文档/审计正文。路径仅本机受保护且排除 Git/构建上下文。

独立冻结 21 表/key：两张 Flyway history（installed_rank）；四张 agent_document 表（upload_requests: project_id,idempotency_key；documents/document_versions: id；document_fragments: version_id,fragment_index）；agent.requests(id)、budget_usage(scope,scope_id,utc_day)、personal_enablements(id)、enablement_revocations(enablement_id)、project_settings(project_id)、live_batches(id)、live_batch_usage(batch_id)、live_batch_revocations(batch_id)、live_budget_usage(scope,scope_id,utc_day)、live_attempts/live_outcomes/live_request_links(request_id)、live_batch_stops(batch_id)、live_template_request_slots(project_id,batch_id,template_id)；audit.audit_records(id)。V13 inventory_proof 是 live_batches 列而非另一张表。

先完成显式关闭/撤销和 worker 清理，确认无 QUEUED/RUNNING，再 capture。所有非审计表全行按唯一键排序，以 PostgreSQL 原生 sha256 计算摘要，跨三个阶段完全相同。全程一个有界 READ ONLY REPEATABLE READ 事务、UTC、固定排序；失败、缺表/重复/坏摘要/未知条目均拒绝，不能把空表当遗漏。

Flyway 单独验证主 SQL V1–8、Agent baseline8 + SQL V9–16 精确脚本/type/success 和 SQL checksum 非空；快照之间完整行/历史 checksum 不变。来源文件另用 SHA-256 绑定固定当前制品，不能把 SHA 当 Flyway checksum；实际当前应用恢复时另核对其正常 Flyway validate/Agent-ready，禁止 repair/关闭校验/down migration。

审计保存完整 baseline UUID→完整行 SHA-256，后续不能删除/改写。新增审计仅允许受控确定性旅程中显式列出的实际 Project、traceId、action 三元组；不得用宽泛前缀或时间/UUID 最大值代替。默认不允许任何新增。Agent/document/credential 三类（agent.、agent_document.、AGENT_CREDENTIAL_）均不允许在 capture 后新增，包含 null-project 失败/拒绝/STATUS；必要凭据状态读取安排在 capture 前，不能声称状态 GET 不消费后端密文或不记审计。运行脚本不自行创造允许集合。

凭据保留证明在实际演练另由受控操作员比较两个既有卷及文件权限/大小/本地摘要，只输出 unchanged booleans；不把主密钥/密文/摘要输出到共享证据。此工程脚本不读取这些文件。旧 Key/临时密码不自动恢复，不重建 Keycloak，不声称身份或数据库灾备已验收。

## 验证与实际验收后续

离线先 RED/GREEN：配置注入/重复字段/IP边界，规则不存在/安装失败零就绪，DNS/IPv6/代理绕过，reset/network/Secret/权限突变，精确默认关闭，21 表独立清单/全部缺失和改动、V16/checksum/审计追加边界。实际 Docker 临时隔离网络只使用合成本地 TCP 服务、无外部网络、无活动卷；覆盖允许 DB/OIDC/Web/合成官方目标、错误 IP/端口/DNS/IPv6 拒绝、guard crash 后仍限制、规则失败不就绪、清空集合切断既有连接。测试 fake official 的公网形状 /32 仅配置在临时服务容器 loopback；它与守卫之间使用仅存在于两个自有 namespace 的直接 veth/私有 /30 链路，避免 Docker internal bridge 拦截非 IPAM 目标。主守卫与默认关闭守卫使用不同 veth 名称和 /30，帮助容器仅持 NET_ADMIN、共享指定自有 PID/network namespace，并在移动配对接口前校验 namespace 标识和真实 peer index。不得使用 host namespace、SYS_ADMIN、NAT、公共子网 Docker bridge 或宿主机公共路由；生产解析器和规则不变，仍拒绝私有官方地址。

临时 Docker DNS 回归只查询已核验存在的自有 peer 容器名称；在同一守卫 namespace 安装规则前先验证 UDP/TCP 本地 Docker DNS 正常返回该 peer 地址，再安装后对完全相同查询断言拒绝，不查询外部或不存在域名。此前置 helper 仅属于离线测试，随后 exec 固定生产 guard；不加入生产镜像入口。持久连接测试按精确四字节 tick 读取，覆盖 TCP 分段/合并；shell 测试只给启动脚本提供 marker 专用 PATH，curl helper 显式执行既有真实 curl，防止 marker 失败时退回真实 Java。

本地最小检查 → 全部 Python/CI/Windows 检查 → Compose 全部组合 → 临时 Docker 网络回归 → 独立审查 → PR CI → 合并后 main CI。真实官方文档/模型映射/价格须在两次运行前重核，不用账户查询替代文档。

上述全部通过后，才准备同一 8081 栈、具体新策略 Project（legacy current acknowledgement 拒绝，不静默迁移）、合成模板/manifest/24小时来源证明、当前 credentialVersion、network/secret 检查 refs、明确批准批次，按已有授权串行解释一次→成功并结算→摘要一次。仅两次，无额外探测/失败替代。核对真实 usage/费用/引用/审计与原 PASS/FAIL，再关闭、最终回滚恢复、制品矩阵、唯一 Docs 报告和 main CI，最后关 Issue。当前文档不宣称任何这些运行关卡已通过。
