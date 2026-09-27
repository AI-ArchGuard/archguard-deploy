# Changelog

所有重要变更记录在此文件。版本遵循语义化版本；项目开发期从 `0.x.y` 开始。

## [Unreleased]

## [0.4.0] - 2026-09-27

### Added

- 阶段 3 GitHub CI 与 Webhook 模板、固定 Samples 的 Compose 治理验收。
- 重复启动复用本地凭据，Windows Runner 脚本保持 LF，新增本地启动回归测试。
- Scanner 制品卷改为专用子目录，避免遮蔽 Platform 应用 JAR；Compose 使用 Platform `0.4.0` 和 Web `0.2.0` 本地镜像标签。

## [0.3.0] - 2026-09-22

### Added

- 初始化仓库治理、协作和质量基线。
- 采用 Apache License 2.0，并在 CI 中固定标准许可证校验和。
- 增加 Platform MVP Compose：Web、Platform、PostgreSQL、本地 Keycloak 和无网络 Scanner Runner。
- 增加随机本地凭据引导、Keycloak realm 模板、Runner 文件邮箱协议和兼容矩阵。
