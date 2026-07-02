# WirePortal V1 开发文档

版本：v0.1  
日期：2026-06-26  
来源：`wireguard-vpn-portal-prd-technical-design.md`  
状态：V1 开发计划草案

## 1. 文档目标

本文档把 PRD 与技术方案落成可执行的 V1 开发计划，用于后续创建 Issue、排迭代、验收和发布。

V1 的核心目标不是做完整零信任或 SD-WAN 平台，而是做一个单机部署、轻量可控的 WireGuard 控制系统：

- 公开申请 VPN。
- 审批员或管理员审批申请。
- 审批后用户设置密码并登录。
- 用户按额度创建 Windows 设备安装包。
- 每台设备独立 WireGuard peer、密钥、VPN IP 和安装包。
- 安装包确认下载后才启用 peer。
- 访问组同时生成客户端 `AllowedIPs` 和服务端 nftables 规则。
- 默认 SNAT/MASQUERADE。
- 提供设备状态、流量、健康页和审计日志。
- 默认 Ubuntu/Debian 单机部署。

## 2. V1 已确认决策

- Web 控制台使用 Vue + TypeScript。
- 后端使用 FastAPI + SQLAlchemy + Alembic。
- Worker 使用 Python 轮询数据库 jobs 表，不引入 Redis/Celery。
- wg-agent 使用 Python 独立进程，通过 Unix socket 暴露本地接口。
- wg-agent 不读数据库，只执行 API/Worker 传入的目标状态。
- 数据库为权威状态，WireGuard/nftables 运行态由 reconcile 修正。
- SQLite/MySQL 部署时二选一，默认 SQLite。
- Windows 安装包使用项目自带自打包程序生成。
- V1 默认在 Linux 主机直接运行自打包程序，生成 Windows 自解压安装器产物。
- 安装包构建器以 Adapter 封装，预留原生 Windows builder。
- Windows 安装包是自解压安装器，随包内置固定版本 WireGuard 官方 Windows 安装器和每设备专属 WireGuard INI 配置。
- 安装器在 Windows 上检测或安装 WireGuard 后，释放 INI 文件并将其设置为 WireGuard tunnel 配置。
- 系统记录内置 WireGuard 安装器版本、SHA256 和来源。
- 签名可选，默认不签名。
- 客户端 private key 不入库。
- 服务端 WireGuard private key 加密入库。
- master key 不入库，默认本机文件，可用环境变量覆盖。
- 审批时授予设备额度、一个或多个访问组和有效期。
- 用户和设备通过关联表绑定多个访问组。
- 设备默认继承用户已批准访问组。
- 管理后台 IP 白名单放在 API 层。
- SMTP 不可用时，通知全部降级为后台复制链接，不阻断主流程。

## 3. 范围

### 3.1 V1 必做

- 首次初始化 `/setup`。
- 账号、密码设置、登录、Cookie session、CSRF。
- 管理后台 API 层 IP 白名单。
- 公开申请。
- 审批通过/拒绝。
- 多访问组授权。
- 用户设备创建。
- Windows 安装包构建、下载、确认和删除。
- peer 确认下载后启用。
- 设备重置和吊销。
- wg-agent peer apply/remove/reconcile/status。
- nftables `yourvpn` 专用 table。
- 默认 SNAT。
- SMTP 通知和后台复制链接降级。
- 审计日志。
- 健康页。
- SQLite 默认运行，MySQL 可配置。
- Ubuntu/Debian 一键安装脚本。

### 3.2 V1 不做

- 多机 HA。
- 多 VPN 网关。
- OIDC/LDAP/SSO 正式接入。
- MFA。
- Redis/Celery。
- 自研 VPN 客户端。
- macOS/Linux 完整安装器。
- 全流量代理 `0.0.0.0/0`。
- 复杂限速、配额、计费。
- 多级审批流。
- 端口级 ACL。

## 4. 架构总览

```text
Browser
  -> Nginx
     -> Vue frontend
     -> FastAPI API
        -> yourvpn-core
        -> Database Adapter: SQLite/MySQL
        -> wg-agent Unix socket Adapter

Worker
  -> yourvpn-core
  -> Jobs table
  -> Installer Builder Adapter
  -> Notification Adapter
  -> wg-agent Unix socket Adapter

wg-agent
  -> WireGuard wg/wg-quick
  -> nftables
  -> sysctl
  -> host health checks
```

推荐 monorepo 结构：

```text
/apps/frontend
/apps/api
/apps/worker
/apps/wg-agent
/packages/python/yourvpn-core
/installer/windows-self-packager
/deploy/systemd
/deploy/nginx
/deploy/install
/docs
```

核心原则：

- `yourvpn-core` 放业务规则，API/Worker 不各自复制规则。
- API 负责同步请求、权限和事务边界。
- Worker 负责异步任务、构建、通知、采样和 reconcile。
- wg-agent 是本机系统执行器，不持有业务规则。
- 数据库是权威状态，系统运行态可以被重建。

## 5. 关键 Module 与 Interface

本节使用 Module、Interface、Seam、Adapter 的语言约束架构。目标是把复杂行为放在深 Module 里，让调用方只学习小 Interface。

### 5.1 `SetupModule`

职责：

- 判断系统是否已初始化。
- 创建第一个 admin。
- 写入系统名称、公网域名、endpoint、VPN 地址池、默认访问组、SMTP 配置。
- 初始化服务端 WireGuard key 和加密 secret。
- 初始化完成后永久关闭 `/setup`。

Interface 草案：

```python
class SetupModule:
    def get_status(self) -> SetupStatus: ...
    def complete_setup(self, command: CompleteSetupCommand, actor_context: RequestContext) -> SetupResult: ...
```

规则：

- 仅当无 admin 且 `setup_completed=false` 时允许执行。
- 重置初始化状态只能通过服务器本地命令。
- 完成后写审计日志。

### 5.2 `AuthModule`

职责：

- 登录、登出。
- 密码设置链接。
- Argon2id 哈希。
- 密码复杂度校验。
- 登录限流和临时锁定。
- Cookie session 与 CSRF。

Interface 草案：

```python
class AuthModule:
    def login(self, command: LoginCommand, context: RequestContext) -> LoginResult: ...
    def logout(self, session_id: str) -> None: ...
    def create_password_setup_token(self, user_id: UUID, expires_at: datetime) -> PasswordToken: ...
    def setup_password(self, command: SetupPasswordCommand, context: RequestContext) -> None: ...
```

规则：

- 密码最少 8 位，包含字母和数字。
- token 过期或使用后不可再用。
- 登录失败按账号和 IP 计数。
- session cookie 使用 `HttpOnly`、`Secure`、`SameSite`。

### 5.3 `AuthorizationModule`

职责：

- 角色权限判断。
- 管理后台 API 层 IP 白名单判断。
- 高权限访问组授予规则。
- 敏感操作二次确认入口。

Interface 草案：

```python
class AuthorizationModule:
    def require_role(self, actor: Actor, allowed_roles: set[Role]) -> None: ...
    def require_admin_ip_allowed(self, context: RequestContext) -> None: ...
    def can_grant_access_groups(self, actor: Actor, access_group_ids: list[UUID]) -> None: ...
```

规则：

- `/api/admin/*` 由 middleware 统一执行 IP 白名单检查。
- API 只信任受控反向代理传入的真实客户端 IP。
- 高权限访问组只允许 admin 授予。
- 拒绝事件进入安全日志或审计日志。

### 5.4 `ApplicationModule`

职责：

- 提交公开申请。
- 审批通过。
- 审批拒绝。
- 创建设备额度、访问组和有效期授权。
- 创建用户与密码设置链接。

Interface 草案：

```python
class ApplicationModule:
    def submit(self, command: SubmitApplicationCommand, context: RequestContext) -> Application: ...
    def approve(self, application_id: UUID, command: ApproveApplicationCommand, actor: Actor) -> ApprovalResult: ...
    def reject(self, application_id: UUID, command: RejectApplicationCommand, actor: Actor) -> None: ...
```

规则：

- 普通申请最多请求 3 台设备。
- 审批员最多批准 10 台设备。
- 超过 10 台需要 admin 后续调整。
- 审批可以授予多个访问组。
- 高权限访问组仅 admin 可授予。
- 审批通过后用户状态为 `pending_password`。
- 审批动作必须写审计日志。

### 5.5 `AccessGroupModule`

职责：

- 管理访问组。
- 管理访问组路由。
- 用户访问组授权。
- 设备访问组继承和管理员覆盖。
- 生成客户端 `AllowedIPs`。
- 生成服务端防火墙目标规则模型。

Interface 草案：

```python
class AccessGroupModule:
    def grant_to_user(self, user_id: UUID, group_ids: list[UUID], actor: Actor) -> None: ...
    def inherit_to_device(self, user_id: UUID, device_id: UUID) -> None: ...
    def set_device_groups(self, device_id: UUID, group_ids: list[UUID], actor: Actor) -> None: ...
    def compile_allowed_ips(self, device_id: UUID) -> list[IPv4Network]: ...
    def compile_firewall_targets(self, device_id: UUID) -> list[IPv4Network]: ...
```

规则：

- 普通用户不可自选访问组。
- 设备默认继承用户已批准访问组。
- 多访问组路由需要去重。
- 重叠 CIDR 可以先去重，V1 不强制做最优 CIDR 合并。
- `AllowedIPs` 不是安全边界，安全限制由服务端 nftables 执行。

### 5.6 `DeviceModule`

职责：

- 用户创建设备。
- 设备额度检查。
- VPN IP 分配。
- 设备状态流转。
- 设备报告丢失。
- 管理员重置、吊销、禁用设备。

Interface 草案：

```python
class DeviceModule:
    def create_device(self, user_id: UUID, command: CreateDeviceCommand) -> DeviceCreationResult: ...
    def confirm_package_download(self, package_id: UUID, actor: Actor) -> DeviceActivationPlan: ...
    def report_lost(self, device_id: UUID, actor: Actor) -> None: ...
    def revoke_device(self, device_id: UUID, actor: Actor) -> RevokePlan: ...
    def reset_device(self, device_id: UUID, actor: Actor) -> ResetDeviceResult: ...
```

规则：

- 每个设备等于一个 WireGuard peer。
- 每个设备独立 public key、private key、VPN IP、安装包。
- 禁止多设备共用 peer/config。
- 创建时检查 `approved_device_limit`。
- 设备创建后进入 `pending_build`。
- 确认下载后才允许启用 peer。
- 重置设备生成新 key，旧 peer 吊销；默认复用原 VPN IP。

### 5.7 `IpAllocatorModule`

职责：

- 从 VPN 地址池分配唯一 peer IP。
- 避开网络地址、广播地址和服务端地址。
- 设备禁用时保留 IP。
- 吊销后进入冷却期。
- 重置设备默认复用原 IP。

Interface 草案：

```python
class IpAllocatorModule:
    def allocate_for_device(self, device_id: UUID) -> IPv4Address: ...
    def reserve_existing_for_reset(self, device_id: UUID) -> IPv4Address: ...
    def mark_revoked(self, device_id: UUID, cooldown_until: datetime) -> None: ...
```

规则：

- `vpn_ip` 唯一。
- 默认地址池 `10.77.0.0/20`。
- 默认服务端 `10.77.0.1/20`。
- 默认冷却期 7 天。

### 5.8 `PackageModule`

职责：

- 创建安装包记录。
- 下载窗口和下载次数控制。
- SHA256、文件大小、签名状态记录。
- 确认下载后删除产物。
- 过期清理。

Interface 草案：

```python
class PackageModule:
    def enqueue_build(self, device_id: UUID) -> InstallPackage: ...
    def mark_building(self, package_id: UUID) -> None: ...
    def mark_ready(self, package_id: UUID, artifact: ArtifactMetadata) -> None: ...
    def record_download_attempt(self, package_id: UUID, actor: Actor) -> DownloadGrant: ...
    def confirm_download(self, package_id: UUID, actor: Actor) -> None: ...
    def expire_package(self, package_id: UUID) -> None: ...
```

规则：

- 默认下载窗口 2 小时。
- 默认最多 5 次下载尝试。
- 确认下载后禁止再次下载。
- 确认下载后删除安装包产物。
- 过期未确认时自动删除产物。
- 安装包不进入备份。

### 5.9 `InstallerBuilder` Interface

职责：

- 生成每台设备专属 Windows 安装包。
- 在构建时生成客户端 keypair。
- 将 public key 保存到数据库。
- 将 private key 只写入临时 WireGuard INI 和最终自解压安装包。
- 构建完成后删除临时 INI。
- 安装器释放 INI 后将其设置为 WireGuard tunnel 配置，并清理中间释放文件。

Interface 草案：

```python
class InstallerBuilder:
    def build(self, request: BuildInstallerRequest) -> BuildInstallerResult: ...
```

V1 Adapter：

```python
class SelfPackInstallerBuilder(InstallerBuilder):
    def build(self, request: BuildInstallerRequest) -> BuildInstallerResult: ...
```

预留 Adapter：

```python
class WindowsNativeBuilder(InstallerBuilder):
    def build(self, request: BuildInstallerRequest) -> BuildInstallerResult: ...
```

规则：

- V1 默认通过项目自带自打包程序生成安装器产物。
- 固定版本 WireGuard 官方 Windows 安装器内置。
- 每设备 WireGuard 配置以 INI 文件生成并打入自解压安装器。
- 构建前校验 WireGuard 安装器 SHA256。
- 构建产物目录权限收紧。
- 临时目录权限收紧。
- 构建失败记录错误并允许重试。
- 后续签名能力不改变上层状态机。

### 5.10 `JobModule`

职责：

- jobs 表轮询。
- 任务锁定。
- 重试和失败记录。
- Worker 心跳。
- SQLite 单 Worker，MySQL 少量并发 Worker。

Interface 草案：

```python
class JobModule:
    def enqueue(self, job_type: str, payload: dict, run_after: datetime | None = None) -> Job: ...
    def claim_next(self, worker_id: str, now: datetime) -> Job | None: ...
    def mark_succeeded(self, job_id: UUID) -> None: ...
    def mark_failed(self, job_id: UUID, error: str, retry_at: datetime | None) -> None: ...
```

任务类型：

- `build_installer`
- `send_notification`
- `expire_install_package`
- `sample_wg_status`
- `reconcile_runtime_state`
- `apply_peer`
- `remove_peer`
- `apply_firewall`
- `notify_expiring_accounts`

### 5.11 `WgRuntimeModule`

职责：

- 从数据库权威状态生成 WireGuard 目标状态。
- 从数据库权威状态生成 nftables 目标状态。
- 调用 wg-agent Unix socket。
- 保存采样结果。

Interface 草案：

```python
class WgRuntimeModule:
    def build_target_state(self) -> RuntimeTargetState: ...
    def apply_peer_for_device(self, device_id: UUID) -> None: ...
    def remove_peer_for_device(self, device_id: UUID) -> None: ...
    def reconcile(self) -> ReconcileResult: ...
    def sample_status(self) -> WgStatusSnapshot: ...
```

规则：

- 确认下载前 peer 不进入目标状态。
- active 设备进入目标状态。
- disabled/revoked/expired 设备不进入目标状态。
- reconcile 可以重建 peers 和 nftables。

### 5.12 `WgAgent`

职责：

- 监听 Unix socket。
- 执行 `wg`、`nft`、`sysctl`。
- 做宿主机健康检查。
- 不读数据库。

Interface：

```text
POST /peers/apply
POST /peers/remove
POST /firewall/apply
POST /reconcile
GET  /wg/status
GET  /health
```

规则：

- 只绑定 Unix socket。
- 不暴露给公网和 Nginx。
- 只管理 `yourvpn` nftables table。
- 不修改宿主机其它防火墙规则。
- 命令执行结果结构化返回。

### 5.13 `NotificationModule`

职责：

- SMTP 发送通知。
- SMTP 不可用时降级为后台复制链接。
- 记录投递结果。

Interface 草案：

```python
class NotificationModule:
    def notify(self, event: NotificationEvent) -> NotificationResult: ...
    def render_manual_link(self, event: NotificationEvent) -> ManualLink: ...
```

规则：

- 主流程不因 SMTP 不可用阻断。
- 降级结果为 `manual_link_required`。
- 后台详情页展示可复制链接和降级原因。
- 通知失败或降级进入审计日志或操作记录。

### 5.14 `AuditModule`

职责：

- 记录关键操作。
- 记录 before/after 摘要。
- 提供审计查询。

Interface 草案：

```python
class AuditModule:
    def record(self, event: AuditEvent) -> None: ...
    def list(self, query: AuditQuery) -> Page[AuditLog]: ...
```

必须记录：

- actor
- action
- target_type
- target_id
- before_json
- after_json
- IP
- user_agent
- created_at

### 5.15 `SecretModule`

职责：

- master key 加载。
- server private key 加密和解密。
- secret key version 预留。

Interface 草案：

```python
class SecretModule:
    def load_master_key(self) -> bytes: ...
    def encrypt_server_private_key(self, private_key: str) -> EncryptedSecret: ...
    def decrypt_server_private_key(self, secret_id: UUID) -> str: ...
```

规则：

- master key 不入库。
- 默认路径 `/etc/yourvpn/master.key`。
- 权限 `0600`。
- 支持 `YOURVPN_MASTER_KEY` 环境变量覆盖。
- 推荐 AES-256-GCM 或 XChaCha20-Poly1305。

## 6. 数据模型落地计划

### 6.1 表清单

V1 需要建表：

- `users`
- `user_identities`
- `applications`
- `approval_records`
- `devices`
- `user_access_groups`
- `device_access_groups`
- `install_packages`
- `access_groups`
- `access_group_routes`
- `traffic_snapshots`
- `jobs`
- `audit_logs`
- `server_secrets`
- `system_settings`
- `sessions`
- `password_tokens`
- `login_attempts`
- `worker_heartbeats`

### 6.2 关键约束

- `users.email` 唯一，允许手机号为空。
- `devices.public_key` 唯一。
- `devices.vpn_ip` 唯一。
- `user_access_groups(user_id, access_group_id)` 唯一。
- `device_access_groups(device_id, access_group_id)` 唯一。
- `access_groups.name` 唯一。
- `system_settings.key` 主键。
- `install_packages.device_id` 可以有历史记录，但同一设备同一时间只能有一个非终态 package。
- `jobs.status`、`run_after`、`locked_at` 建索引。
- `audit_logs.created_at` 建索引。
- `traffic_snapshots(device_id, sampled_at)` 建索引。

### 6.3 状态枚举

申请状态：

```text
submitted
approved
account_setup_pending
active
rejected
cancelled
disabled
expired
```

用户状态：

```text
pending_password
active
disabled
expired
```

设备状态：

```text
draft
pending_approval
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

安装包状态：

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

Job 状态：

```text
pending
running
succeeded
failed
cancelled
```

### 6.4 迁移顺序

1. 基础枚举和时间戳约定。
2. users、sessions、password_tokens、login_attempts。
3. access_groups、access_group_routes。
4. applications、approval_records。
5. devices、user_access_groups、device_access_groups。
6. install_packages。
7. jobs、worker_heartbeats。
8. audit_logs、traffic_snapshots。
9. server_secrets、system_settings。

## 7. API 开发计划

### 7.1 公共接口

- `GET /api/setup/status`
- `POST /api/setup`
- `POST /api/applications`

验收：

- 未初始化时 `/setup` 可用。
- 初始化后 `/setup` 禁止重复执行。
- 公开申请不需要登录。
- 公开申请有基础限流和输入校验。

### 7.2 认证接口

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/me`
- `POST /api/auth/password/setup`
- `POST /api/auth/password/reset`

验收：

- pending_password 用户不能正常登录，只能设置密码。
- token 过期后不可用。
- 登录失败触发限流和临时锁定。
- Cookie session 与 CSRF 生效。

### 7.3 用户门户接口

- `GET /api/me/devices`
- `POST /api/me/devices`
- `GET /api/me/packages/{id}`
- `GET /api/me/packages/{id}/download`
- `POST /api/me/packages/{id}/confirm-download`
- `POST /api/me/devices/{id}/report-lost`

验收：

- 用户只能看到自己的设备和安装包。
- 超过设备额度时拒绝创建设备。
- 下载窗口和次数限制正确。
- 确认下载后 artifact 删除，peer apply job 入队。

### 7.4 审批接口

- `GET /api/admin/applications`
- `GET /api/admin/applications/{id}`
- `POST /api/admin/applications/{id}/approve`
- `POST /api/admin/applications/{id}/reject`

验收：

- 审批员可审批普通访问组。
- 审批员不可授予高权限访问组。
- admin 可授予高权限访问组。
- 审批通过后创建用户、访问组授权、密码设置链接和通知事件。

### 7.5 管理接口

- `GET /api/admin/users`
- `GET /api/admin/users/{id}`
- `POST /api/admin/users/{id}/disable`
- `GET /api/admin/devices`
- `POST /api/admin/devices/{id}/revoke`
- `POST /api/admin/devices/{id}/reset`
- `GET /api/admin/access-groups`
- `POST /api/admin/access-groups`
- `PATCH /api/admin/access-groups/{id}`
- `POST /api/admin/access-groups/{id}/routes`
- `GET /api/admin/health`
- `GET /api/admin/audit-logs`

验收：

- `/api/admin/*` 全部经过 API 层 IP 白名单。
- 敏感操作有二次确认或重新输入密码入口。
- 审计日志可筛选 actor/action/target/time。

## 8. 前端开发计划

### 8.1 公共页面

- `/apply`：公开申请页。
- `/password/setup`：密码设置页。
- `/login`：登录页。

页面要求：

- 表单校验清晰。
- 申请成功不泄露审批状态细节。
- 密码设置 token 过期时给出明确状态。

### 8.2 用户门户

- `/portal/devices`：设备列表。
- `/portal/devices/new`：创建设备。
- `/portal/packages/:id`：安装包下载页。

页面要求：

- 展示设备状态、VPN IP、访问组、last handshake、rx/tx、endpoint。
- 下载页展示文件名、文件大小、SHA256、签名状态、过期时间、下载次数。
- 确认下载按钮需要明显的确认态。
- 确认下载后提示安装包无法再次下载。

### 8.3 管理后台

- `/admin/applications`：申请列表。
- `/admin/applications/:id`：审批详情。
- `/admin/users`：用户列表。
- `/admin/devices`：设备列表。
- `/admin/access-groups`：访问组和路由。
- `/admin/health`：系统健康。
- `/admin/audit-logs`：审计日志。

页面要求：

- 后台以表格和筛选为主。
- 高权限访问组有明显标识。
- SMTP 降级时显示可复制链接。
- 敏感操作需要二次确认。
- 健康页显示 wg-agent、worker、数据库、nftables、地址池、队列长度。

## 9. Worker 开发计划

### 9.1 Worker 运行模型

SQLite 默认单 Worker：

- 单进程轮询 pending jobs。
- claim job 时更新 `locked_at`、`locked_by`。
- 避免多进程并发写 SQLite。

MySQL 可少量并发 Worker：

- 使用行锁或乐观锁 claim job。
- job 幂等，允许失败重试。

### 9.2 Job 处理器

`build_installer`：

- 加载设备、用户、访问组、系统设置。
- 生成 keypair。
- 保存 public key。
- 生成 WireGuard INI 配置。
- 调用 `InstallerBuilder`。
- 删除临时 INI 配置。
- 保存 artifact metadata。
- 入队通知。

`send_notification`：

- 尝试 SMTP。
- SMTP 不可用或失败时生成 manual link。
- 保存投递结果。

`expire_install_package`：

- 找到过期且未确认 package。
- 删除 artifact。
- 标记 expired 或 artifact_deleted。

`sample_wg_status`：

- 调用 wg-agent `/wg/status`。
- 更新 devices latest 字段。
- 写 traffic_snapshots。

`reconcile_runtime_state`：

- 从数据库生成目标状态。
- 调用 wg-agent `/reconcile`。
- 记录结果。

`apply_peer`：

- 确认设备和 package 状态。
- 调用 wg-agent `/peers/apply`。
- 标记设备 active。

`remove_peer`：

- 调用 wg-agent `/peers/remove`。
- 标记设备 revoked/disabled。

`apply_firewall`：

- 生成访问组规则。
- 调用 wg-agent `/firewall/apply`。

## 10. wg-agent 开发计划

### 10.1 进程与权限

- systemd 管理。
- root 或具备必要 Linux capability。
- Unix socket 路径建议 `/run/yourvpn/wg-agent.sock`。
- socket 权限只允许 API/Worker 访问。
- 不读取数据库。

### 10.2 接口实现

`GET /health`：

- 返回进程状态、版本、当前用户、命令可用性。

`GET /wg/status`：

- 执行 `wg show`。
- 解析 peer public key、latest handshake、rx、tx、endpoint。

`POST /peers/apply`：

- 输入 peer public key、VPN IP、allowed IP。
- 执行 `wg set`。
- 返回命令结果。

`POST /peers/remove`：

- 输入 public key。
- 执行 `wg set peer remove`。

`POST /firewall/apply`：

- 输入完整 `yourvpn` table 目标规则。
- 原子方式替换专用 table。

`POST /reconcile`：

- 输入完整 peers 和 firewall target。
- 修正 WireGuard peers。
- 重建 `yourvpn` nftables table。

### 10.3 nftables 原则

- 只管理 `yourvpn` 专用 table。
- 不修改宿主机其它 table。
- NAT 和访问控制规则都由目标状态生成。
- 默认 SNAT/MASQUERADE。
- 高级模式可关闭 NAT，但 V1 UI 可以先隐藏。

## 11. 安装包构建计划

### 11.1 构建输入

- device id。
- user display name。
- device name。
- VPN IP。
- server public key。
- endpoint。
- access group compiled AllowedIPs。
- fixed WireGuard installer path。
- fixed WireGuard installer version。
- fixed WireGuard installer SHA256。
- tunnel name。
- self-extract installer output directory。
- package output directory。

### 11.2 构建步骤

1. 创建权限收紧的临时目录。
2. 生成客户端 keypair。
3. 保存 public key 到 `devices.public_key`。
4. 生成临时 WireGuard INI 配置文件，INI 内容包含 `[Interface]` 和 `[Peer]`。
5. 校验 WireGuard Windows 安装器 SHA256。
6. 生成自打包 manifest，声明 WireGuard 安装器、设备专属 INI、安装计划和清理策略。
7. 调用项目自带自打包程序生成单个自解压安装器产物。
8. 计算自解压产物 SHA256 和 file_size。
9. 写入 install_packages metadata，包括配置格式 `ini` 和 WireGuard 安装器版本。
10. 删除临时 INI。
11. 删除临时目录。

### 11.3 安装器行为

Windows 安装包执行：

- 检测 WireGuard 是否已安装。
- 未安装则运行内置 WireGuard 官方安装器。
- 释放设备专属 INI 到安装器临时目录或受控本地目录。
- 将释放出的 INI 设置为 WireGuard tunnel 配置。
- 设置完成后删除中间释放 INI；WireGuard 自身需要保留的配置副本由 WireGuard 管理。
- 安装结束页默认勾选立即连接 VPN。
- 用户可取消立即连接。

### 11.4 构建验收

- 产物可在 Windows 上运行。
- 未安装 WireGuard 时可安装官方 WireGuard。
- 已安装 WireGuard 时跳过官方安装器。
- INI 可被释放并设置为 WireGuard tunnel 配置。
- 临时 INI 不残留在构建临时目录。
- 安装器设置 tunnel 后，中间释放 INI 不残留在安装器临时目录。
- 客户端 private key 不在数据库。
- 下载确认后产物被删除。

## 12. 部署开发计划

### 12.1 systemd

服务：

- `yourvpn-api.service`
- `yourvpn-worker.service`
- `yourvpn-wg-agent.service`

要求：

- API 和 Worker 使用非 root 用户。
- wg-agent 使用 root 或必要 capability。
- 日志进入 journald。
- 服务失败自动重启。

### 12.2 Nginx

职责：

- 托管 Vue 静态文件。
- 反代 `/api` 到 FastAPI。
- HTTPS 预留。
- 不承担 V1 管理后台 IP 白名单的唯一安全职责。

### 12.3 安装脚本

脚本职责：

- 检测 Ubuntu/Debian 版本。
- 安装 `wireguard-tools`、`nftables`、`nginx`、Python 和自打包程序运行依赖。
- 创建 `yourvpn` 用户和目录。
- 初始化 `/var/lib/yourvpn`。
- 生成 master key。
- 初始化数据库。
- 生成或恢复 WireGuard server key。
- 配置 wg0。
- 安装 systemd 服务。
- 配置 Nginx。
- 启动服务。
- 输出后台地址和初次 setup URL。

### 12.4 目录建议

```text
/etc/yourvpn
/var/lib/yourvpn
/var/lib/yourvpn/artifacts
/var/lib/yourvpn/build-tmp
/var/lib/yourvpn/installers
/run/yourvpn
/var/log/yourvpn
```

权限原则：

- master key `0600`。
- artifacts 仅 API/Worker 可读写。
- build-tmp 权限收紧并定期清理。
- wg-agent socket 仅 API/Worker 所在组可访问。

## 13. 测试计划

### 13.1 单元测试

重点 Module：

- 状态机。
- 权限判断。
- 多访问组聚合。
- IP 分配。
- 下载窗口和下载次数。
- 密码复杂度。
- 登录限流。
- 审计事件生成。

### 13.2 集成测试

API：

- `/setup` 初始化。
- 公开申请。
- 审批通过。
- 审批拒绝。
- 密码设置。
- 用户登录。
- 设备创建。
- 安装包下载。
- 确认下载。
- 管理员重置设备。

Worker：

- job claim。
- job retry。
- build_installer fake builder。
- package expire。
- notification fallback。

wg-agent：

- fake command runner 测试命令生成。
- Unix socket contract 测试。
- nftables target render 测试。

### 13.3 端到端测试

最小闭环：

```text
setup admin
 -> submit application
 -> approve application
 -> setup password
 -> login user
 -> create device
 -> build package
 -> download package
 -> confirm download
 -> peer active
```

网络闭环：

```text
active device
 -> wg-agent apply peer
 -> wg status sampled
 -> traffic snapshot written
 -> health page shows data
```

安全闭环：

```text
private key generated
 -> public key saved
 -> device INI packed into self-extract installer
 -> temp INI deleted
 -> DB has no private key
 -> artifact deleted after confirm
```

### 13.4 数据库测试矩阵

SQLite：

- 默认开发和单机部署。
- 单 Worker。
- 迁移可运行。

MySQL：

- 迁移可运行。
- 少量并发 Worker claim job。
- 关键查询索引有效。

### 13.5 手动验收

Windows 安装包必须手动验证：

- Windows 10。
- Windows 11。
- 未安装 WireGuard。
- 已安装 WireGuard。
- 自解压安装器可释放设备专属 INI。
- 释放的 INI 可被设置为 WireGuard tunnel 配置。
- 普通用户权限。
- 需要管理员权限时提示合理。
- 安装后 tunnel 可用。
- 默认立即连接选项可用。

## 14. 里程碑与任务拆分

### M0 架构验证

目标：消除最大技术风险。

任务：

- M0-01 验证 Ubuntu/Debian 上项目自带自打包程序可运行。
- M0-02 生成最小自打包安装器产物。
- M0-03 固定 WireGuard Windows 安装器版本并记录 SHA256。
- M0-04 验证最小自解压包可内置 WireGuard 安装器和示例 INI。
- M0-05 验证 Unix socket FastAPI/worker 到 wg-agent 通信。
- M0-06 验证 `wg set` 添加和移除 peer。
- M0-07 验证 `wg show` 状态解析。
- M0-08 验证 nftables `yourvpn` table 创建和替换。
- M0-09 输出多访问组 AllowedIPs 和 nftables 生成规则样例。

完成标准：

- 每个高风险点有可运行 PoC。
- 失败边界和 fallback 写入开发备注。
- 确认 V1 不需要 Windows builder 才能推进。

### M1 工程骨架

目标：建立可持续开发的 monorepo。

任务：

- M1-01 创建 monorepo 目录。
- M1-02 初始化 Python 包管理。
- M1-03 初始化 `yourvpn-core`。
- M1-04 初始化 FastAPI app。
- M1-05 初始化 Worker app。
- M1-06 初始化 wg-agent app。
- M1-07 初始化 Vue + TypeScript app。
- M1-08 建立配置加载和环境变量约定。
- M1-09 建立统一日志格式。
- M1-10 建立 pytest、前端 lint/build。

完成标准：

- 本地可启动 API、Worker、wg-agent、Frontend。
- `/health` 可访问。
- 测试命令可运行。

### M2 数据模型与核心 Module

目标：完成数据库和业务核心。

任务：

- M2-01 建立 SQLAlchemy Base 和 Alembic。
- M2-02 创建 users/sessions/password_tokens/login_attempts。
- M2-03 创建 access_groups/access_group_routes。
- M2-04 创建 applications/approval_records。
- M2-05 创建设备与访问组关联表。
- M2-06 创建 install_packages。
- M2-07 创建 jobs/worker_heartbeats。
- M2-08 创建 audit_logs/traffic_snapshots。
- M2-09 创建 server_secrets/system_settings。
- M2-10 实现状态机 Module。
- M2-11 实现权限 Module。
- M2-12 实现多访问组聚合 Module。
- M2-13 实现 IP 分配 Module。
- M2-14 实现审计 Module。

完成标准：

- SQLite 迁移通过。
- MySQL 迁移通过。
- 核心 Module 单元测试覆盖主要规则。

### M3 初始化、认证与安全基础

目标：跑通首次 setup 和登录。

任务：

- M3-01 实现 `/api/setup/status`。
- M3-02 实现 `/api/setup`。
- M3-03 初始化第一个 admin。
- M3-04 Argon2id 密码哈希。
- M3-05 密码复杂度校验。
- M3-06 session cookie。
- M3-07 CSRF 防护。
- M3-08 登录/登出。
- M3-09 密码设置 token。
- M3-10 登录限流。
- M3-11 API 层 IP 白名单 middleware。
- M3-12 安全拒绝审计。

完成标准：

- admin 可初始化并登录。
- 初始化后 setup 不可重复。
- `/api/admin/*` 受 IP 白名单保护。

### M4 申请与审批闭环

目标：申请人可完成申请，审批后可登录。

任务：

- M4-01 公开申请接口。
- M4-02 公开申请页。
- M4-03 审批列表接口。
- M4-04 审批详情接口。
- M4-05 审批通过接口。
- M4-06 审批拒绝接口。
- M4-07 多访问组授权。
- M4-08 高权限访问组仅 admin 授权。
- M4-09 创建密码设置链接。
- M4-10 SMTP 通知。
- M4-11 SMTP 不可用时后台复制链接。
- M4-12 审批审计。

完成标准：

- 申请 -> 审批 -> 设置密码 -> 登录完整跑通。
- SMTP 不可用不阻断流程。

### M5 用户设备与安装包生命周期

目标：用 fake builder 先打通设备和下载状态机。

任务：

- M5-01 用户设备列表。
- M5-02 用户创建设备。
- M5-03 设备额度检查。
- M5-04 设备继承用户访问组。
- M5-05 VPN IP 分配。
- M5-06 创建 install_package。
- M5-07 fake builder job。
- M5-08 下载详情接口。
- M5-09 下载接口和下载次数。
- M5-10 确认下载接口。
- M5-11 确认后删除 artifact。
- M5-12 管理员重置设备。
- M5-13 管理员吊销设备。

完成标准：

- 不接真实自打包 Builder 也能跑通完整生命周期。
- 确认下载前 peer 不启用。
- 确认下载后生成 apply_peer job。

### M6 真实安装包构建

目标：接入 `SelfPackInstallerBuilder`。

任务：

- M6-01 定义 `InstallerBuilder` Interface。
- M6-02 实现 `SelfPackInstallerBuilder`。
- M6-03 渲染 WireGuard INI 配置。
- M6-04 生成自打包 manifest。
- M6-05 校验固定 WireGuard installer SHA256。
- M6-06 调用项目自带自打包程序。
- M6-07 计算产物 SHA256 和 file_size。
- M6-08 删除临时 INI。
- M6-09 构建失败重试。
- M6-10 下载页显示 signed_status。
- M6-11 Windows 手动安装验收，包括 INI 释放和 tunnel 设置。

完成标准：

- 能生成真实 Windows `.exe`。
- 客户端 private key 不入库。
- 临时 INI 构建后删除。
- 安装器能释放 INI 并设置为 WireGuard tunnel 配置。

### M7 wg-agent 与网络执行

目标：接入真实 WireGuard 和 nftables。

任务：

- M7-01 wg-agent Unix socket 服务。
- M7-02 `/health`。
- M7-03 `/wg/status`。
- M7-04 `/peers/apply`。
- M7-05 `/peers/remove`。
- M7-06 `/firewall/apply`。
- M7-07 `/reconcile`。
- M7-08 API/Worker wg-agent client。
- M7-09 active 设备生成目标状态。
- M7-10 多访问组生成 nftables 规则。
- M7-11 默认 SNAT/MASQUERADE。
- M7-12 流量采样 job。
- M7-13 健康页数据聚合。

完成标准：

- 下载确认前 peer 不在 WireGuard。
- 下载确认后 peer 被添加。
- revoke/reset 后旧 peer 被移除。
- reconcile 可恢复漂移。
- nftables 只管理 `yourvpn` table。

### M8 前端完整体验

目标：补齐 V1 可操作界面。

任务：

- M8-01 登录页。
- M8-02 公开申请页。
- M8-03 密码设置页。
- M8-04 用户设备列表页。
- M8-05 用户创建设备页。
- M8-06 安装包下载页。
- M8-07 申请审批列表。
- M8-08 申请审批详情。
- M8-09 用户管理页。
- M8-10 设备管理页。
- M8-11 访问组管理页。
- M8-12 系统健康页。
- M8-13 审计日志页。
- M8-14 SMTP 降级链接展示。

完成标准：

- V1 主流程可通过 UI 完成。
- 后台操作有明确状态和错误提示。
- 敏感操作有确认。

### M9 部署与运维

目标：单机可安装、可恢复。

任务：

- M9-01 systemd 服务文件。
- M9-02 Nginx 配置。
- M9-03 一键安装脚本。
- M9-04 创建系统用户和目录。
- M9-05 初始化 master key。
- M9-06 初始化数据库。
- M9-07 初始化 wg0。
- M9-08 安装固定 WireGuard Windows installer 到本地缓存。
- M9-09 配置自打包构建环境。
- M9-10 常规备份命令。
- M9-11 灾备备份说明。
- M9-12 恢复和 reconcile 命令。

完成标准：

- 干净 Ubuntu/Debian 主机可安装。
- 安装后可访问 setup。
- 服务重启后状态保持。

### M10 验收与加固

目标：达到 V1 发布条件。

任务：

- M10-01 PRD 18 条验收标准逐条验证。
- M10-02 SQLite/MySQL 基础测试矩阵。
- M10-03 状态机非法迁移测试。
- M10-04 权限边界测试。
- M10-05 安装包私钥安全测试。
- M10-06 wg-agent 不读数据库验证。
- M10-07 nftables 不改宿主机其它规则验证。
- M10-08 Windows 安装器手动验收。
- M10-09 安全配置检查。
- M10-10 release notes。

完成标准：

- V1 可发布。
- 已知限制清晰记录。

## 15. 推荐开发顺序

1. M0 必须先完成，避免后期被自打包程序或 WireGuard 系统能力卡住。
2. M1 和 M2 建立基础，优先保证核心 Module 可测试。
3. M3 和 M4 形成第一个业务闭环。
4. M5 使用 fake builder 跑通设备和安装包生命周期。
5. M6 接入真实自打包构建。
6. M7 接入真实 WireGuard 和 nftables。
7. M8 可从 M4 后并行推进，但以前端不要越过 API 契约为原则。
8. M9 在 M6/M7 稳定后开始收口。
9. M10 最后发布门禁。

## 16. 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| 自打包程序构建不稳定 | 安装包生成失败 | M0 做 PoC；构建器 Adapter 保持可替换 |
| Windows 安装行为和预期不一致 | 用户无法设置 tunnel | Windows 10/11 手动验收；安装脚本保持简单 |
| 客户端 private key 泄露 | 严重安全问题 | 不入库；临时 INI 目录权限收紧；构建后删除；确认下载后删除 artifact |
| wg-agent 权限过大 | 宿主机安全风险 | Unix socket；最小接口；结构化命令；只管理 `yourvpn` table |
| nftables 规则误伤宿主机 | 网络中断 | 只操作专用 table；M0/M7 做回滚验证 |
| SQLite 并发写冲突 | Worker 任务失败 | SQLite 默认单 Worker；MySQL 才允许少量并发 |
| SMTP 不可用 | 用户收不到链接 | 后台复制链接降级，不阻断流程 |
| 多访问组规则复杂 | AllowedIPs 或防火墙错误 | 先去重不做复杂优化；核心 Module 单测覆盖 |
| IP 白名单真实 IP 判断错误 | 管理后台被误放行或误拦截 | 只信任受控反代；部署文档明确 Nginx 配置 |

## 17. 发布门禁

V1 发布前必须满足：

- `/setup` 首次初始化可用，初始化后关闭。
- 公开申请可提交。
- 审批员可审批普通访问组。
- admin 可审批高权限访问组。
- 审批通过后用户可设置密码并登录。
- 用户可按额度创建 Windows 设备。
- 系统可异步生成 Windows 自打包安装器。
- 下载页展示文件名、大小、SHA256、签名状态、过期时间和下载次数。
- 下载确认前 peer 不启用。
- 下载确认后安装包产物删除，peer 启用。
- Windows 自解压安装包可安装 WireGuard 或检测已有安装，释放设备专属 INI，并设置为 WireGuard tunnel 配置。
- 默认勾选安装后立即连接 VPN。
- 后台能看到 last handshake 和流量。
- 多访问组可生成 AllowedIPs 和 nftables 规则。
- 默认 SNAT 可让客户端访问内网。
- 管理员可重置设备，旧 peer 吊销，新 key 生成。
- 审计日志记录关键操作。
- SQLite 默认可运行。
- MySQL 可通过部署配置启用。
- SMTP 不可用时后台复制链接可用。
- 客户端 private key 不入库。
- master key 不入库。

## 18. 后续文档建议

V1 开发过程中建议继续补充：

- `docs/api-contract.md`：API 请求/响应契约。
- `docs/database-schema.md`：数据库字段、索引、枚举。
- `docs/wg-agent-contract.md`：wg-agent Unix socket payload。
- `docs/installer-build.md`：自打包构建环境和 Windows 验收。
- `docs/deployment.md`：Ubuntu/Debian 安装和恢复。
- `docs/security-model.md`：密钥、权限、审计、IP 白名单。
