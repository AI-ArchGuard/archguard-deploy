# 手动来源证明换版设计

状态：2026-10-21 项目所有者批准设计、离线实现与 CI。批准每版重新审查同一组合成数据、新 inventoryId、新原生卷、保留旧卷及最多 24 小时有效期；只有出口关闭且没有在途请求时才允许实际选择新代。本次不创建或切换实际部署卷、不部署、不调用模型、不产生费用，也不批准恢复任何旧失败批次。

## 问题与范围

来源证明不可变且会过期。过期不是卷损坏，不能 chmod、删除、修复、重新初始化、延长旧证明或在旧文件追加记录来恢复许可。本增量只提供显式选代的静态配置、严格校验、回归和操作门槛，不提供 Docker/DB 自动切换工具、自动续期、热切换、Secret 轮换或通用卷别名。

Platform 已有当前证明全文件校验、批次 proof 快照和发送前精确比较；V16 槽位按 project/batch/template 隔离。因此 Platform 只增加测试，不改生产代码/API/Schema/迁移。应用层历史测试使用既有 fake，不能替代真实 reader 对 ID/有效期的测试。

## 最小接口

- 原 `compose.agent-live.yaml` 和默认旧卷行为不变。新增可选 `compose.agent-inventory-generation.yaml`，只能改逻辑卷 `agent-live-inventory` 的物理 `name`；无 services/networks/ports/images 或凭据/DB 改动。
- 必填 `ARCHGUARD_AGENT_INVENTORY_GENERATION` 是规范非零 UUID，等于新证明唯一条目的 inventoryId。物理名固定为 `<actual Compose project>_agent-live-inventory-<UUID>`，不允许任意名称、external 或 driver_opts；缺参不能随机生成。插值必须由固定 Compose5.5.1 的实际离线渲染证明。
- 静态 verifier 新增 `--inventory-generation UUID` 和 Python 同名关键字参数。无参数只接受原名；有参数只接受实际 project 与规范 UUID 对应的新名。拒绝错代、跨 project、旧名冒充、新名未显式 opt-in、非规范/零/大小写 UUID、缺 project。
- 固定 logical key、Platform 只读挂载和 `/run/archguard-inventory/inventory.json`；任何其他服务不得挂入同一物理卷或别名。保留既有 mount/capability/network/Secret/DB 原生身份检查。UUID 不进入 Platform env/API 或提供方请求。
- 初始化器不改：固定路径、空目录、O_EXCL/O_NOFOLLOW、文件0444/目录0555，失败残留不修复/重试；不制造 UUID、reviewRef、时间、manifest 或批准。新文件只含重新审查的当前 active entry，旧过期 entry 留在旧卷，不追加进新 active 文件。

## 实际运行顺序（设计，不在本次执行）

1. 另获实际卷操作及关闭部署批准，重新核对候选和 PR/main CI。候选 pin 提升须普通评审，不因本设计默许部署最新 Platform。失败批次保持停止/撤销，UNKNOWN 不退款。
2. 关闭 Web、Project、部署/live 入口并复核完整内核出口关闭；停止 Platform、确认没有 Java/在途发送，另用既有只读 DB 检查证明 pending=0。仅进程停止不等于 pending=0；有 pending 必须停，不自动取消、释放费用或重试。记录21表/audit及原 DB、master、ciphertext、旧 inventory 物理身份基线。
3. 人工重新审查同一 deployment/Project/模板/manifest/fixture artifact，确定新 inventoryId/reviewRef/reviewedAt/expiresAt（最多24小时），不含客户数据。新来源审查不批准模型调用。确认精确新物理卷不存在；即便已存在空卷也停止，不把 create 的幂等返回当首次创建证据。
4. 单独获批后只创建全新 native volume，受限初始化器只执行一次，不挂旧卷，不访问/迁移/重置 Key/master/ciphertext。失败保留新卷原样，不修复、不自动换 UUID 重试。
5. Platform 停止且出口关闭期间显式选代；复核渲染配置、实际 mount 的精确物理身份/只读目标、新文件元数据/UUID/SHA、旧卷字节和权限未变、DB/master/ciphertext未换、21表/audit完全不变。只用 no-deps/pull-never 启动所有开关关闭的 Platform；保留 DB/OIDC/Runner/守卫和命名空间，不用全栈 up/bootstrap，不热改文件/挂载，不 down --volumes/prune/删除旧卷。若另需 Web/守卫变化，另列关闭部署计划。
6. 新证明有效不是调用许可。后续必须新 owner 确认、新 batch、单独的具体次数/费用批准和来源/价格/模型/运行绑定；旧确认/批次/请求槽位/费用不升级，不补发。应用回退先关闭入口/出口再退应用，保留迁移、证明及历史；回挂旧过期卷不能恢复许可，也不能恢复旧失败批次。

静态 verifier 不证明 kernel、实际 Docker mount、进程、pending 或21表历史。独立受保护的操作员证据记录 UUID、物理身份、文件摘要和检查索引；configProofRef 只是索引，不是动态证明。现有回滚21表捕获/manifest Schema 不变，不增加自填“许可已验证”布尔值。未来自动化 Docker/DB 切换须另行设计批准。

## 验证与兼容

先对缺失选代能力观察 RED，再 GREEN；默认/新代/关闭模型及所有错配必须离线渲染/校验。测试同时保持 alias隔离、只读路径、external/driver_opts、凭据/DB身份边界。用两个测试独占、唯一标记的临时合成 native volumes 证明新卷初始化、旧字节/权限不变、覆盖和失败残留拒绝；固定测试时钟下旧 verify 仍因过期失败，另做归档完整性检查，新代当前有效。归档 hash 相同不能称作当前有效。

CI 的临时合成卷不是活动或预定部署卷，不共享名称，不挂 Secret；精确核对所有权后只清理测试自有资源，不 prune。生产初始化器、回滚 Schema、网络守卫、真实运行环境及候选 pin 不改。完整测试、独立评审、PR/main CI 后仍不代表实际部署或真实验收。

兼容顺序：既有 Docs 边界 → Platform tests-only → Deploy 配置/校验/手册 → 另批实际关闭部署 → 另批真实验收。固定合成数据、协议、费用和默认关闭不变；4H/#43/阶段4保持未完成，不创建最终验收报告。
