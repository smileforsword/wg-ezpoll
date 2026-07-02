# 内部 WireGuard VPN 控制系统 PRD 与技术方案

版本：v0.1  
日期：2026-06-26  
状态：方案草案  
项目代号：WirePortal，可后续替换

## 1. 概述

本项目要建设一个面向中小型团队的内部 VPN 申请、审批、账号和 WireGuard peer 生命周期管理系统。

系统不做复杂 SD-WAN 或完整零信任平台，核心定位是：

- WireGuard 负责 VPN 数据面。
- 自研 Web 控制台负责申请、审批、用户、设备、安装包、访问组、审计和状态展示。
- Windows 用户通过一次性专属安装包完成安装和配置导入。
- 每台设备独立 WireGuard peer、独立密钥、独立 VPN IP。
- 默认单机部署，WireGuard 跑宿主机，Web 控制台使用 Vue + FastAPI + Nginx。

## 2. 背景与问题

团队需要一个轻量、可控、易安装的内部 VPN 系统。原生 WireGuard 性能好、配置简单，但不提供用户申请、审批、账号生命周期、设备管理、安装包分发、访问组、防火墙规则、审计和运维状态页。

现有重型方案如 NetBird 更偏完整 overlay 网络和控制面，本项目希望只在一台机器上部署 WireGuard 和一个中小型控制系统，降低复杂度。

## 3. 目标

1. 支持公网提交 VPN 申请。
2. 支持管理员/审批员审批申请，授予设备额度、访问组和有效期。
3. 支持审批通过后用户设置密码并登录。
4. 支持用户按需创建 Windows 设备安装包。
5. 支持安装包内置 WireGuard 官方安装器和专属 WireGuard 配置。
6. 支持安装包下载窗口、重试次数、SHA256 校验信息、确认下载完成后销毁产物。
7. 支持确认下载完成后才启用 WireGuard peer。
8. 支持基于访问组的客户端 AllowedIPs 和服务端 nftables 防火墙规则。
9. 支持默认 SNAT/MASQUERADE，降低部署者对内网回程路由的要求。
10. 支持设备状态、last handshake、流量统计、系统健康页和审计日志。
11. 支持 SQLite/MySQL 在部署时二选一。
12. 支持 Ubuntu/Debian 单机一键安装。

## 4. 非目标

V1 不做：

- NetBird/Tailscale 类完整 overlay 网络。
- 多机高可用控制面。
- OIDC/LDAP/SSO 正式集成，仅预留模型。
- macOS/Linux 完整安装器。
- 移动端深度安装体验，V1 可先用二维码或配置文件过渡。
- 全流量代理 `0.0.0.0/0`。
- 复杂限速、流量配额和计费。
- 多级审批流。
- 强制 MFA。
- Redis/Celery 任务队列。
- 自研 VPN 客户端。

## 5. 用户角色

### 5.1 申请人/普通用户

- 提交 VPN 申请。
- 审批通过后设置密码。
- 登录用户页面。
- 按额度创建设备。
- 下载 Windows 安装包。
- 确认下载完成。
- 查看自己设备状态。
- 提交设备丢失/停用申请。

### 5.2 审批员

- 查看待审批申请。
- 批准或拒绝申请。
- 授予设备数量、访问组、有效期。
- 审批普通访问组。
- 查看审批记录。

### 5.3 管理员

- 拥有审批员能力。
- 创建和管理访问组。
- 修改系统配置。
- 重置设备安装包。
- 吊销用户或设备。
- 配置网络、防火墙、NAT、SMTP、签名等。
- 管理高权限访问组审批。
- 查看系统健康页和审计日志。

### 5.4 审计员

- 只读查看申请、审批、设备、审计和状态。

## 6. V1 主流程

### 6.1 首次初始化

```text
安装完成
 -> 访问 /setup
 -> 系统检测无 admin
 -> 创建第一个 admin
 -> 配置系统名称、公网域名、endpoint、VPN 地址池、默认访问组、SMTP 可选项
 -> setup_completed = true
 -> /setup 永久关闭
```

重置初始化状态只能通过服务器本地命令完成。

### 6.2 申请与审批

```text
用户访问公开申请页
 -> 填写申请信息
 -> 审批员/管理员审批
 -> 审批通过后创建用户
 -> 发送或复制设置密码链接
 -> 用户设置密码
 -> 用户登录
```

申请字段：

- 姓名
- 邮箱/手机号
- 部门/公司
- 申请原因
- 需要使用 VPN 的设备数量

设备数量规则：

- 普通申请最多填写 3 个设备。
- 审批员最多批准 10 个设备。
- 超过 10 个需要管理员调整。

审批时授予：

- 批准/拒绝
- 批准设备数量
- 一个或多个访问组
- 有效期或永久有效
- 审批备注

### 6.3 用户创建设备

```text
用户登录
 -> 点击添加设备
 -> 填设备名和平台
 -> 系统检查设备额度
 -> 创建设备记录
 -> 异步构建安装包
 -> 用户下载
 -> 用户确认下载完成
 -> 系统启用 peer
```

在用户绑定模式下，审批只审批用户和设备额度，用户按需创建设备。设备默认继承用户已批准的一个或多个访问组。

在设备绑定模式下，每台设备需要单独审批，审批通过后才能生成安装包。该模式作为系统配置项保留。

### 6.4 Windows 安装包安装

```text
用户运行安装包
 -> 检测 WireGuard 是否已安装
 -> 未安装则运行内置 WireGuard 官方安装器
 -> 导入专属 tunnel
 -> 删除临时 conf
 -> 安装结束页默认勾选“立即连接 VPN”
 -> 用户可取消立即连接
```

系统不要求安装器回传安装成功。后台通过 `last_handshake`、`rx`、`tx` 判断连接状态。

## 7. 核心产品决策

### 7.1 设备与 peer

系统不变量：

```text
每个设备 = 一个 WireGuard peer = 一个 public key = 一个 VPN IP = 一个安装包
禁止多设备共用同一个 WireGuard peer/config
```

用户可以有多台设备，但每台设备独立 peer。用户绑定模式只是表示审批一次后可在额度内自助创建设备，不表示多设备共用配置。

### 7.2 安装包分发

Windows V1 使用 Inno Setup 构建安装包。V1 默认在 Linux 主机上通过 Wine 运行 Inno Setup 命令行编译器 `ISCC.exe`，以满足 Ubuntu/Debian 单机部署目标。

构建器需要设计为可替换 Adapter：

- V1 默认实现：`WineInnoBuilder`。
- 后续可替换实现：`WindowsRemoteBuilder`，用于原生 Windows 构建、代码签名或安装冒烟测试。
- 上层设备状态机、下载窗口、审计和 peer 启用逻辑不依赖具体构建 Adapter。

安装包包含：

- 固定版本的 WireGuard 官方 Windows 安装器。
- 当前设备专属 WireGuard 客户端配置。
- 安装导入逻辑。

WireGuard 官方 Windows 安装器随包内置，不在用户安装时临时下载。系统需要在构建配置或系统设置中记录安装器版本、文件 SHA256、来源 URL 或人工上传记录。

安装包下载规则：

- 默认下载窗口 2 小时，可配置。
- 默认最多 5 次下载尝试，可配置。
- 下载确认前允许重试。
- 用户确认下载完成后删除安装包产物。
- 确认后再次下载必须由管理员重新生成。
- 过期未确认时自动删除产物。

下载页展示：

- 文件名
- 文件大小
- SHA256
- 签名状态
- 过期时间
- 已下载次数/最大次数
- 确认下载完成按钮

### 7.3 安装包签名

V1 默认不签名。

系统支持配置 Windows 代码签名：

- 签名证书可选。
- 未配置签名也可以构建安装包。
- 后台提示生产环境建议签名。
- 下载页展示“已签名/未签名”状态。

### 7.4 客户端 private key

客户端 private key 不长期保存到数据库。

流程：

```text
构建时生成 keypair
 -> public key 保存数据库
 -> private key 写入临时 client.conf
 -> 打进安装包
 -> 删除临时 conf
```

安装包丢失后不能重新下载同一配置，只能管理员重置生成新 key。

### 7.5 服务端 private key

服务端 WireGuard private key 加密保存到数据库，便于迁移。

加密策略：

- `server private key` 加密后保存数据库。
- `master key` 不保存数据库。
- 默认 `master key` 初始化生成到 `/var/lib/yourvpn/master.key`，权限 `0600`。
- 支持 `YOURVPN_MASTER_KEY` 环境变量覆盖。
- 建议使用 AES-256-GCM 或 XChaCha20-Poly1305。
- secret 表保留 `key_version`、`nonce`、`ciphertext`、`rotated_at` 等字段。

迁移恢复需要：

```text
数据库备份 + 相同 master key
```

### 7.6 访问组

访问组由审批员/管理员授予，用户创建设备时不可自选。

V1 数据模型预留多访问组：

- 审批时可授予一个或多个访问组。
- 用户持有一个或多个已批准访问组。
- 设备默认继承用户已批准访问组。
- 管理员可在设备级调整访问组，但普通用户不可自选。
- 高权限访问组仍需要 admin 授予或调整。

访问组同时控制：

1. 客户端配置里的 `AllowedIPs`。
2. 服务端 nftables 防火墙规则。

当用户或设备拥有多个访问组时：

- 客户端 `AllowedIPs` 由所有启用访问组的路由聚合生成。
- 服务端 nftables 规则由设备 VPN IP 和所有访问组目标网段聚合生成。
- 重叠 CIDR 需要在生成阶段归并或去重，避免生成重复规则。

内置建议组：

- `default`：基础办公服务。
- `dev`：开发环境。
- `ops`：运维环境，高权限。
- `vendor`：外包/临时访问。
- `full`：全量内网，仅 admin 可分配。

客户端 `AllowedIPs` 不是安全边界，真正安全限制由服务端防火墙执行。

### 7.7 网络与路由

默认：

- Split tunnel。
- 不支持全流量代理。
- 不默认下发 `0.0.0.0/0`。

VPN 默认地址池：

```text
10.77.0.0/20
服务端 wg0：10.77.0.1/20
客户端 peer：固定 /32
```

容量：

- `/20` 总地址数 4096。
- 约 4093 个 peer 可用，避开网络地址、广播地址和服务端地址。

IP 分配：

- 自动分配。
- `vpn_ip` 唯一。
- 设备禁用时保留 IP。
- 吊销后进入冷却期。
- 默认冷却期 7 天。

服务器默认开启 IPv4 转发并启用 SNAT/MASQUERADE。

```text
客户端 10.77.0.x
 -> VPN Server
 -> SNAT 为服务器内网 IP
 -> 内网目标
```

高级模式允许关闭 NAT，改为真实 VPN 客户端 IP，但部署者必须配置内网回程路由：

```text
10.77.0.0/20 via VPN 服务器内网 IP
```

### 7.8 防火墙

V1 以 nftables 为主要后端。

原则：

- `wg-agent` 独占管理 `yourvpn` 专用 table。
- 不修改宿主机其它防火墙规则。
- 启动/reconcile 时可按数据库重建 `yourvpn` table。
- NAT 和访问控制规则都由访问组、peer IP、目标网段生成。

### 7.9 状态与启用时机

peer 在用户确认下载完成后才真正启用到 WireGuard。

```text
审批通过
 -> 分配 VPN IP
 -> 生成 key/config
 -> 构建安装包
 -> ready_to_download

用户下载
 -> downloading
 -> 可在窗口内重试

用户确认下载完成
 -> 删除安装包产物
 -> wg set 添加 peer
 -> active
```

## 8. 状态机

### 8.1 申请状态

```text
submitted
 -> approved
 -> account_setup_pending
 -> active

submitted -> rejected
submitted -> cancelled
active -> disabled
active -> expired
```

### 8.2 用户状态

```text
pending_password
active
disabled
expired
```

### 8.3 设备状态

```text
draft
pending_approval        # 仅设备绑定模式
pending_build
built
ready_to_download
downloading
download_confirmed
active
disabled
revoked
expired
reset_pending
```

### 8.4 安装包状态

```text
pending_build
building
ready_to_download
downloading
download_confirmed
artifact_deleted
expired
revoked
failed
```

规则：

- `downloading` 状态允许同一用户在窗口内重试。
- `download_confirmed` 后删除产物并禁止再次下载。
- `expired` 后删除产物，需要管理员重新生成。

### 8.5 Job 状态

```text
pending
running
succeeded
failed
cancelled
```

## 9. 系统架构

```text
Browser
  -> Nginx
     -> Vue frontend
     -> FastAPI API
          -> Database SQLite/MySQL
          -> Jobs table
          -> Audit logs
          -> Unix socket call to wg-agent, where needed

Worker
  -> Database jobs
  -> Build installer
  -> Send SMTP
  -> Traffic sampling
  -> Reconcile target state
  -> Unix socket call to wg-agent

wg-agent
  -> WireGuard wg/wg-quick
  -> nftables
  -> sysctl/ip_forward
  -> host health checks
```

## 10. 技术栈

### 10.1 前端

- Vue
- TypeScript
- 管理后台和用户门户共用前端项目。

### 10.2 后端

- FastAPI
- SQLAlchemy
- Alembic
- Argon2id 密码哈希
- Cookie 会话，`HttpOnly`、`Secure`
- Cookie 鉴权时启用 CSRF 防护

### 10.3 Worker

- Python
- 数据库 jobs 表轮询
- SQLite 默认单 worker
- MySQL 可少量并发 worker

### 10.4 wg-agent

- Python
- 独立最小进程
- root 或具备必要能力运行
- 只监听 Unix socket
- 不直接读数据库
- 只作为本机系统执行器
- 接收 API/worker 传入的目标状态

### 10.5 安装包

- Inno Setup
- Linux + Wine 运行 `ISCC.exe` 作为 V1 默认构建方式
- 构建器以 Adapter 形式封装，预留原生 Windows builder
- 内置固定版本 WireGuard 官方 Windows 安装器
- 记录 WireGuard 安装器版本、SHA256 和来源
- 支持可选签名

### 10.6 数据库

部署时通过 `DATABASE_URL` 二选一：

```text
sqlite:////var/lib/yourvpn/yourvpn.db
mysql+pymysql://user:pass@127.0.0.1:3306/yourvpn
```

默认 SQLite，生产推荐 MySQL。不支持运行时热切换。

### 10.7 部署

V1 优先 Ubuntu/Debian 单机一键安装。

核心组件跑 systemd：

- `yourvpn-api.service`
- `yourvpn-worker.service`
- `yourvpn-wg-agent.service`
- `nginx.service`
- `mysql.service`，可选

不强制全 Docker。

## 11. Monorepo 结构

```text
/apps/frontend
/apps/api
/apps/worker
/apps/wg-agent
/installer/windows-inno
/deploy/systemd
/deploy/nginx
/docs
```

## 12. wg-agent 接口草案

wg-agent 只监听 Unix socket，不暴露给公网和 Nginx。

接口：

```text
POST /peers/apply
POST /peers/remove
POST /firewall/apply
POST /reconcile
GET  /wg/status
GET  /health
```

原则：

- wg-agent 不读数据库。
- API/worker 从数据库读取权威状态。
- API/worker 计算目标状态并传给 wg-agent。
- wg-agent 执行 `wg`、`nft`、`sysctl` 等系统操作。

## 13. 数据模型草案

### 13.1 users

- `id`
- `display_name`
- `email`
- `phone`
- `department_or_company`
- `status`
- `role`
- `password_hash`
- `approved_device_limit`
- `expires_at`
- `is_permanent`
- `created_at`
- `updated_at`

### 13.2 user_identities

预留 SSO/LDAP。

- `id`
- `user_id`
- `provider`
- `provider_subject`
- `username`

### 13.3 applications

- `id`
- `name`
- `email_or_phone`
- `department_or_company`
- `reason`
- `requested_device_count`
- `status`
- `submitted_ip`
- `created_at`
- `updated_at`

### 13.4 approval_records

- `id`
- `application_id`
- `approver_id`
- `decision`
- `approved_device_limit`
- `approved_access_group_ids_json`
- `expires_at`
- `is_permanent`
- `comment`
- `created_at`

### 13.5 devices

- `id`
- `user_id`
- `name`
- `platform`
- `mode`
- `status`
- `public_key`
- `vpn_ip`
- `expires_at`
- `is_permanent`
- `last_handshake_at`
- `latest_endpoint`
- `latest_rx_bytes`
- `latest_tx_bytes`
- `created_at`
- `updated_at`

约束：

- `public_key` 唯一。
- `vpn_ip` 唯一。
- 每个设备一个 peer。

### 13.6 user_access_groups

- `id`
- `user_id`
- `access_group_id`
- `granted_by`
- `created_at`

约束：

- `user_id` + `access_group_id` 唯一。

### 13.7 device_access_groups

- `id`
- `device_id`
- `access_group_id`
- `source`
- `granted_by`
- `created_at`

说明：

- `source` 表示访问组来源，如 `inherited_from_user` 或 `admin_override`。
- 默认设备访问组从用户访问组继承生成。
- `device_id` + `access_group_id` 唯一。

### 13.8 install_packages

- `id`
- `device_id`
- `platform`
- `delivery_type`
- `status`
- `artifact_path`
- `file_name`
- `file_size`
- `sha256`
- `signed_status`
- `wireguard_installer_version`
- `wireguard_installer_sha256`
- `download_attempts`
- `max_download_attempts`
- `download_window_expires_at`
- `confirmed_at`
- `artifact_deleted_at`
- `created_at`
- `updated_at`

### 13.9 access_groups

- `id`
- `name`
- `description`
- `is_high_privilege`
- `enabled`
- `created_at`
- `updated_at`

### 13.10 access_group_routes

- `id`
- `access_group_id`
- `cidr`
- `description`

### 13.11 traffic_snapshots

- `id`
- `device_id`
- `sampled_at`
- `rx_bytes`
- `tx_bytes`
- `last_handshake_at`

### 13.12 jobs

- `id`
- `type`
- `payload_json`
- `status`
- `attempts`
- `max_attempts`
- `run_after`
- `locked_at`
- `locked_by`
- `last_error`
- `created_at`
- `updated_at`

### 13.13 audit_logs

- `id`
- `actor_id`
- `action`
- `target_type`
- `target_id`
- `before_json`
- `after_json`
- `ip`
- `user_agent`
- `created_at`

### 13.14 server_secrets

- `id`
- `secret_type`
- `ciphertext`
- `nonce`
- `key_version`
- `created_at`
- `rotated_at`

### 13.15 system_settings

- `key`
- `value_json`
- `updated_by`
- `updated_at`

## 14. API 草案

公开：

- `POST /api/applications`
- `GET /api/setup/status`
- `POST /api/setup`

认证：

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `POST /api/auth/password/setup`
- `POST /api/auth/password/reset`

用户：

- `GET /api/me`
- `GET /api/me/devices`
- `POST /api/me/devices`
- `GET /api/me/packages/{id}`
- `GET /api/me/packages/{id}/download`
- `POST /api/me/packages/{id}/confirm-download`
- `POST /api/me/devices/{id}/report-lost`

审批：

- `GET /api/admin/applications`
- `POST /api/admin/applications/{id}/approve`
- `POST /api/admin/applications/{id}/reject`

管理员：

- `GET /api/admin/users`
- `POST /api/admin/users/{id}/disable`
- `POST /api/admin/devices/{id}/revoke`
- `POST /api/admin/devices/{id}/reset`
- `GET /api/admin/access-groups`
- `POST /api/admin/access-groups`
- `GET /api/admin/health`
- `GET /api/admin/audit-logs`

## 15. 安全要求

### 15.1 密码

- Argon2id 哈希。
- 最少 8 位。
- 必须包含字母和数字。
- 预留弱密码黑名单。

### 15.2 登录安全

- 登录限流，按账号和 IP。
- 多次失败临时锁定。
- 会话 Cookie 使用 `HttpOnly`、`Secure`、`SameSite`。
- Cookie 鉴权启用 CSRF 防护。

### 15.3 管理后台

- 管理后台可配置 IP 白名单，V1 在 API 层实现。
- 申请、设置密码、用户登录、用户下载可公网 HTTPS 访问。
- 管理后台需要登录权限和可选 IP 白名单。
- IP 白名单由 FastAPI middleware 对 `/api/admin/*` 等管理接口统一拦截。
- 如部署在 Nginx 之后，API 只信任受控反向代理传入的真实客户端 IP，不直接信任任意 `X-Forwarded-For`。
- IP 白名单拒绝事件需要记录安全日志或审计日志。
- 敏感操作需要二次确认或重新输入密码。

敏感操作包括：

- 批准申请
- 重新生成安装包
- 吊销设备
- 修改访问组
- 修改网段/NAT/防火墙配置
- 提升用户角色

### 15.4 审计

必须记录：

- actor
- action
- target
- before/after 摘要
- IP
- user agent
- timestamp

### 15.5 安装包安全

- 安装包产物目录权限收紧。
- 构建临时目录权限收紧。
- 临时 client.conf 构建后删除。
- 安装包确认下载后删除。
- 安装包不进入备份。

## 16. 通知

V1 使用 SMTP 邮件通知，后台可复制链接。

SMTP 不可用时，通知全部降级为后台复制链接：

- 审批、密码设置、安装包构建等主流程不因 SMTP 不可用而阻断。
- 通知模块需要记录投递结果，如 `email_sent`、`email_failed`、`manual_link_required`。
- 后台在相关详情页展示可复制链接和降级原因。
- 通知降级事件需要进入审计日志或操作记录。

通知事件：

- 用户提交申请，通知审批员。
- 审批通过，通知用户设置密码。
- 审批拒绝，通知用户。
- 安装包构建完成，通知用户可下载。
- 账号即将过期，通知用户/审批员。
- 设备重置/吊销，通知用户。

Webhook 预留但不作为 V1 首要能力。

## 17. 监控与状态

### 17.1 系统健康页

显示：

- WireGuard 接口状态。
- wg-agent 状态。
- worker 最近心跳。
- 数据库连接状态。
- nftables `yourvpn` table 状态。
- 公网 endpoint。
- VPN 地址池使用率。
- 待处理申请数。
- 构建队列长度。

### 17.2 设备状态页

显示：

- 用户
- 设备名
- 平台
- VPN IP
- 访问组
- 状态
- last handshake
- rx/tx
- endpoint
- 疑似在线状态

在线状态推断：

```text
last_handshake <= 3 分钟：在线
3 到 30 分钟：最近在线
> 30 分钟：离线/未知
从未 handshake：未连接
```

### 17.3 流量统计

V1 做 peer 级流量统计：

- 定时采样 `wg show`。
- 今日流量。
- 近 7 天流量。
- 近 30 天流量。
- 异常大流量排行。

限速和配额字段预留，功能后续。

## 18. 备份与恢复

### 18.1 常规备份

包含：

- 数据库。
- 加密后的 server private key。
- 系统设置。
- 访问组。
- 用户、设备、public key、VPN IP。
- 审计日志。

不包含：

- master key。
- 安装包产物。
- 构建临时目录。
- 客户端 private key。

### 18.2 灾备备份

包含：

- 常规备份。
- master key。

灾备备份必须再次加密或由管理员口令保护。

恢复流程：

```text
恢复数据库
 -> 放置相同 master key
 -> 解密 server private key
 -> 重建 /etc/wireguard/wg0.conf
 -> wg-agent reconcile peers
 -> 重建 nftables
```

## 19. 部署安装

V1 提供 Ubuntu/Debian 一键安装脚本。

安装脚本负责：

- 检测系统版本。
- 安装 `wireguard-tools`、`nftables`、`nginx`、Python 运行环境等。
- 创建 `yourvpn` 用户。
- 初始化配置目录。
- 生成 master key。
- 初始化数据库。
- 生成或恢复 WireGuard server key。
- 配置 wg0。
- 安装 systemd 服务。
- 配置 Nginx。
- 启动服务。
- 输出管理后台地址。

## 20. 测试策略

### 20.1 测试原则

- 优先测试外部行为，不测试实现细节。
- 状态机、权限边界、密钥处理和系统执行器是重点。
- SQLite 和 MySQL 都要有基础测试矩阵。

### 20.2 必测场景

申请流程：

- 提交申请。
- 审批通过。
- 审批拒绝。
- 设备数限制。
- 高权限访问组仅 admin 审批。

账号流程：

- 设置密码链接过期。
- 密码复杂度。
- 登录限流。
- 会话和权限。

设备流程：

- 用户按额度创建设备。
- 禁止超过批准额度。
- 每设备独立 public key 和 VPN IP。
- 重置设备生成新 key。
- 默认复用原 VPN IP。

安装包流程：

- 构建成功。
- 构建失败重试。
- 下载窗口内可重试。
- 确认下载后删除产物。
- 过期后删除产物。
- 确认后启用 peer。

WireGuard 流程：

- `wg set` 添加 peer。
- remove peer。
- reconcile 修复漂移。
- wg-agent 不读数据库。

防火墙流程：

- 访问组生成 nftables 规则。
- SNAT 默认开启。
- 不改宿主机其它防火墙规则。

安全流程：

- 客户端 private key 不入库。
- server private key 加密入库。
- master key 不入库。
- 审计日志完整。

## 21. V1 验收标准

1. 管理员可通过 `/setup` 完成首次初始化。
2. 申请人可公开提交申请。
3. 审批员可审批普通访问组申请。
4. 管理员可审批高权限访问组申请。
5. 审批通过后用户可设置密码并登录。
6. 用户可按额度创建 Windows 设备。
7. 系统可异步生成 Windows Inno 安装包。
8. 下载页展示文件名、大小、SHA256、签名状态、过期时间和下载次数。
9. 下载确认前 peer 不启用。
10. 下载确认后安装包产物删除，peer 启用。
11. Windows 安装包可安装 WireGuard 或检测已有安装，并导入 tunnel。
12. 默认勾选安装后立即连接 VPN。
13. 后台能看到 last handshake 和流量。
14. 访问组能限制服务端可访问目标网段。
15. 默认 SNAT 能让客户端访问内网，无需配置内网回程路由。
16. 管理员可重置设备，旧 peer 吊销，新 key 生成。
17. 审计日志记录关键操作。
18. SQLite 默认可运行，MySQL 可通过部署配置启用。

## 22. 后续路线

V2 候选：

- OIDC/LDAP/企业身份源。
- 飞书/钉钉/企业微信通知。
- 移动端二维码体验完善。
- macOS/Linux 安装器。
- Webhook 正式化。
- MFA。
- 用户自助吊销开关。
- 流量限速与配额。
- 更细粒度端口级 ACL。
- 备份恢复 UI。

V3 候选：

- 多机 HA。
- 多 VPN 网关。
- 多地域接入。
- 外部 Secret Manager。
- 更完整的报表和安全告警。

## 23. 已确认关键决策清单

- 使用 WireGuard 宿主机部署。
- Web 控制台使用 Vue + FastAPI + Nginx。
- 数据库 SQLite/MySQL 部署时二选一，默认 SQLite。
- wg-agent 使用 Python，独立进程，Unix socket，不读数据库。
- 数据库为权威状态，WireGuard 运行态由 reconcile 修正。
- 运行时 peer 变更使用 `wg set`。
- 防火墙/NAT 主后端使用 nftables。
- 默认 split tunnel，不做全流量代理。
- 默认 SNAT/MASQUERADE。
- 默认 VPN 地址池 `10.77.0.0/20`。
- 每台设备独立 peer/config/key/IP。
- 禁止多设备共用 peer/config。
- Windows V1 使用 Inno Setup。
- V1 默认在 Linux 主机通过 Wine 运行 `ISCC.exe` 构建 Inno 安装包。
- 安装包构建器以 Adapter 封装，预留原生 Windows builder。
- 安装包内置固定版本 WireGuard 官方 Windows 安装器。
- WireGuard 官方 Windows 安装器随包分发，不在用户安装时临时下载。
- 系统记录内置 WireGuard 安装器版本、SHA256 和来源。
- 签名可选，默认不签名。
- 安装包确认下载后删除。
- peer 在确认下载完成后才启用。
- 客户端 private key 不入库。
- 服务端 private key 加密入库。
- master key 默认本机文件，可用环境变量覆盖。
- 公开申请 `open_apply`。
- 先申请，审批通过后设置密码并创建账号。
- 审批时授予设备额度、一个或多个访问组和有效期。
- V1 数据模型预留多访问组，用户和设备通过关联表绑定访问组。
- 设备默认继承用户已批准访问组。
- 用户登录后按需创建设备安装包。
- 普通申请最多 3 个设备，审批员最多批准 10 个。
- 账号/设备支持有效期，也允许永久有效。
- 管理后台可配置 IP 白名单，V1 在 API 层实现。
- SMTP 不可用时，通知全部降级为后台复制链接，不阻断主流程。
- V1 使用数据库 jobs 表，不引入 Redis/Celery。
