<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

type View = 'apply' | 'password' | 'login' | 'portal' | 'admin' | 'setup'
type AdminSection = 'approvals' | 'users' | 'devices' | 'access' | 'health' | 'audit'

interface ApiError {
  code: string
  message: string
}

interface Me {
  user_id: string
  email: string
  display_name: string
  role: string
}

interface ApplicationSummary {
  id: string
  email: string
  display_name: string
  requested_device_count: number
  status: string
  created_at: string
}

interface ApplicationDetail extends ApplicationSummary {
  phone: string | null
  reason: string | null
  submitted_ip: string | null
  submitted_user_agent: string | null
  updated_at: string
  approval_records: Array<{
    id: string
    action: string
    actor_user_id: string | null
    approved_device_limit: number | null
    reason: string | null
    created_user_id: string | null
    created_at: string
  }>
}

interface AccessGroup {
  id: string
  name: string
  description: string | null
  is_high_privilege: boolean
  enabled: boolean
}

interface AccessGroupDetail extends AccessGroup {
  routes: Array<{
    id: string
    cidr: string
    description: string | null
    enabled: boolean
  }>
}

interface DevicePackage {
  id: string
  device_id: string
  status: string
  file_name: string | null
  sha256: string | null
  file_size: number | null
  signed_status: string
  config_format: string
  download_attempts: number
  max_download_attempts: number
  download_expires_at: string | null
  confirmed_at: string | null
  artifact_deleted_at: string | null
  can_download: boolean
}

interface PortalDevice {
  id: string
  name: string
  status: string
  public_key: string | null
  vpn_ip: string
  latest_handshake_at: string | null
  latest_endpoint: string | null
  rx_bytes: number
  tx_bytes: number
  current_package: DevicePackage | null
}

interface AdminDevice extends PortalDevice {
  user_id: string
  user_email: string | null
  user_display_name: string | null
  revoked_at: string | null
}

interface AdminUser {
  id: string
  email: string
  display_name: string
  phone: string | null
  role: string
  status: string
  approved_device_limit: number
  expires_at: string | null
  created_at: string
  device_count: number
}

interface AuditLog {
  id: string
  actor_user_id: string | null
  actor_type: string
  action: string
  target_type: string
  target_id: string | null
  before_json: Record<string, unknown> | null
  after_json: Record<string, unknown> | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

interface RuntimeHealth {
  status: string
  database: { status: string }
  jobs: { pending: number }
  runtime: {
    active_devices: number
    target_devices: number
    wg_interface: string
    nft_table_name: string
  }
  wg_agent: Record<string, unknown>
}

const view = ref<View>('apply')
const adminSection = ref<AdminSection>('approvals')
const me = ref<Me | null>(null)
const csrfToken = ref('')
const notice = ref('')
const busy = ref(false)

const applications = ref<ApplicationSummary[]>([])
const activeApplicationId = ref('')
const applicationDetail = ref<ApplicationDetail | null>(null)
const accessGroups = ref<AccessGroup[]>([])
const users = ref<AdminUser[]>([])
const userLimitDrafts = reactive<Record<string, number>>({})
const devices = ref<PortalDevice[]>([])
const adminDevices = ref<AdminDevice[]>([])
const auditLogs = ref<AuditLog[]>([])
const runtimeHealth = ref<RuntimeHealth | null>(null)
const setupUrl = ref('')
const routeViews = new Set<View>(['setup', 'apply', 'login', 'password', 'portal', 'admin'])

const applyForm = reactive({
  email: '',
  display_name: '',
  phone: '',
  reason: '',
  requested_device_count: 1,
})

const setupForm = reactive({
  email: '',
  display_name: '',
  password: '',
})

const loginForm = reactive({
  email: '',
  password: '',
})

const passwordForm = reactive({
  token: '',
  password: '',
})

const approveForm = reactive({
  approved_device_limit: 1,
  access_group_ids: [] as string[],
  reason: '',
})

const rejectForm = reactive({
  reason: '',
})

const deviceForm = reactive({
  name: '',
})

const accessGroupForm = reactive({
  name: '',
  description: '',
  is_high_privilege: false,
  enabled: true,
  route_cidr: '',
  route_description: '',
})

const pendingApplications = computed(() =>
  applications.value.filter((application) => application.status === 'submitted'),
)

const canUseAdmin = computed(() => me.value?.role === 'admin' || me.value?.role === 'approver')

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { headers: optionHeaders, ...fetchOptions } = options
  const response = await fetch(path, {
    ...fetchOptions,
    credentials: 'include',
    headers: {
      'content-type': 'application/json',
      ...(optionHeaders ?? {}),
    },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const error = body as ApiError | null
    throw new Error(error?.message || `Request failed: ${response.status}`)
  }
  return body as T
}

function setNotice(message: string) {
  notice.value = message
}

function formatBytes(value: number | null): string {
  if (value === null) return '-'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function shortSha(value: string | null): string {
  return value ? `${value.slice(0, 12)}...` : '-'
}

function formatDate(value: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

async function withBusy(action: () => Promise<void>) {
  busy.value = true
  notice.value = ''
  try {
    await action()
  } catch (error) {
    notice.value = error instanceof Error ? error.message : '操作失败'
  } finally {
    busy.value = false
  }
}

async function completeSetup() {
  await withBusy(async () => {
    await api('/api/setup', {
      method: 'POST',
      body: JSON.stringify(setupForm),
    })
    Object.assign(setupForm, { email: '', display_name: '', password: '' })
    view.value = 'login'
    setNotice('初始化完成')
  })
}

async function submitApplication() {
  await withBusy(async () => {
    await api('/api/applications', {
      method: 'POST',
      body: JSON.stringify({
        ...applyForm,
        phone: applyForm.phone || null,
        reason: applyForm.reason || null,
      }),
    })
    Object.assign(applyForm, {
      email: '',
      display_name: '',
      phone: '',
      reason: '',
      requested_device_count: 1,
    })
    setNotice('申请已提交')
  })
}

async function login() {
  await withBusy(async () => {
    const result = await api<{ csrf_token: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify(loginForm),
    })
    csrfToken.value = result.csrf_token
    me.value = await api<Me>('/api/me')
    view.value = 'portal'
    await loadDevices()
    setNotice('已登录')
  })
}

async function logout() {
  if (!csrfToken.value) return
  await withBusy(async () => {
    await api('/api/auth/logout', {
      method: 'POST',
      headers: { 'x-csrf-token': csrfToken.value },
    })
    csrfToken.value = ''
    me.value = null
    devices.value = []
    view.value = 'login'
    setNotice('已退出')
  })
}

async function setupPassword() {
  await withBusy(async () => {
    await api('/api/auth/password/setup', {
      method: 'POST',
      body: JSON.stringify(passwordForm),
    })
    passwordForm.token = ''
    passwordForm.password = ''
    setNotice('密码已设置')
  })
}

async function loadDevices() {
  devices.value = await api<PortalDevice[]>('/api/me/devices')
}

async function createDevice() {
  await withBusy(async () => {
    await api('/api/me/devices', {
      method: 'POST',
      headers: { 'x-csrf-token': csrfToken.value },
      body: JSON.stringify(deviceForm),
    })
    deviceForm.name = ''
    await loadDevices()
    setNotice('设备已创建')
  })
}

function downloadPackage(packageId: string) {
  window.open(`/api/me/packages/${packageId}/download`, '_blank', 'noopener')
}

async function confirmPackage(packageId: string) {
  await withBusy(async () => {
    await api(`/api/me/packages/${packageId}/confirm-download`, {
      method: 'POST',
      headers: { 'x-csrf-token': csrfToken.value },
    })
    await loadDevices()
    setNotice('下载已确认')
  })
}

async function reportLost(deviceId: string) {
  await withBusy(async () => {
    await api(`/api/me/devices/${deviceId}/report-lost`, {
      method: 'POST',
      headers: { 'x-csrf-token': csrfToken.value },
    })
    await loadDevices()
    setNotice('已上报丢失')
  })
}

async function loadAdminSection(section = adminSection.value) {
  if (!canUseAdmin.value) return
  adminSection.value = section
  if (section === 'approvals') {
    const [applicationRows, groupRows] = await Promise.all([
      api<ApplicationSummary[]>('/api/admin/applications'),
      api<AccessGroup[]>('/api/admin/access-groups'),
    ])
    applications.value = applicationRows
    accessGroups.value = groupRows.filter((group) => group.enabled)
    if (!applicationDetail.value && applicationRows.length > 0) {
      await selectApplication(applicationRows[0].id)
    }
  }
  if (section === 'users') {
    users.value = await api<AdminUser[]>('/api/admin/users')
    for (const user of users.value) {
      userLimitDrafts[user.id] = user.approved_device_limit
    }
  }
  if (section === 'devices') {
    adminDevices.value = await api<AdminDevice[]>('/api/admin/devices')
  }
  if (section === 'access') {
    accessGroups.value = await api<AccessGroup[]>('/api/admin/access-groups')
  }
  if (section === 'health') {
    runtimeHealth.value = await api<RuntimeHealth>('/api/admin/runtime/health')
  }
  if (section === 'audit') {
    auditLogs.value = await api<AuditLog[]>('/api/admin/audit-logs?limit=100')
  }
}

async function openAdmin(section: AdminSection = 'approvals') {
  view.value = 'admin'
  await withBusy(async () => {
    await loadAdminSection(section)
  })
}

async function updateUserDeviceLimit(user: AdminUser) {
  await withBusy(async () => {
    const updated = await api<AdminUser>(`/api/admin/users/${user.id}`, {
      method: 'PATCH',
      headers: { 'x-csrf-token': csrfToken.value },
      body: JSON.stringify({
        approved_device_limit: userLimitDrafts[user.id] ?? user.approved_device_limit,
      }),
    })
    users.value = users.value.map((item) => item.id === updated.id ? updated : item)
    userLimitDrafts[updated.id] = updated.approved_device_limit
    setNotice('用户设备额度已更新')
  })
}

async function selectApplication(applicationId: string) {
  activeApplicationId.value = applicationId
  applicationDetail.value = await api<ApplicationDetail>(`/api/admin/applications/${applicationId}`)
  approveForm.approved_device_limit = applicationDetail.value.requested_device_count
  approveForm.access_group_ids = []
  approveForm.reason = ''
  rejectForm.reason = ''
  setupUrl.value = ''
}

function toggleAccessGroup(id: string) {
  if (approveForm.access_group_ids.includes(id)) {
    approveForm.access_group_ids = approveForm.access_group_ids.filter((value) => value !== id)
  } else {
    approveForm.access_group_ids = [...approveForm.access_group_ids, id]
  }
}

async function approveApplication() {
  if (!applicationDetail.value) return
  await withBusy(async () => {
    const result = await api<{ setup_url: string, notification_status: string }>(
      `/api/admin/applications/${applicationDetail.value?.id}/approve`,
      {
        method: 'POST',
        headers: { 'x-csrf-token': csrfToken.value },
        body: JSON.stringify(approveForm),
      },
    )
    setupUrl.value = result.setup_url
    applicationDetail.value = null
    await loadAdminSection('approvals')
    setNotice(result.notification_status === 'sent' ? '审批已通过' : '审批已通过，密码链接可复制')
  })
}

async function rejectApplication() {
  if (!applicationDetail.value) return
  await withBusy(async () => {
    await api(`/api/admin/applications/${applicationDetail.value?.id}/reject`, {
      method: 'POST',
      headers: { 'x-csrf-token': csrfToken.value },
      body: JSON.stringify(rejectForm),
    })
    applicationDetail.value = null
    await loadAdminSection('approvals')
    setNotice('已拒绝申请')
  })
}

async function copySetupUrl() {
  if (!setupUrl.value) return
  await navigator.clipboard.writeText(setupUrl.value)
  setNotice('链接已复制')
}

async function resetAdminDevice(deviceId: string) {
  if (!window.confirm('确认重置这台设备？旧安装包将失效。')) return
  await withBusy(async () => {
    await api(`/api/admin/devices/${deviceId}/reset`, {
      method: 'POST',
      headers: { 'x-csrf-token': csrfToken.value },
    })
    await loadAdminSection('devices')
    setNotice('设备已重置')
  })
}

async function revokeAdminDevice(deviceId: string) {
  if (!window.confirm('确认吊销这台设备？运行态 peer 将被移除。')) return
  await withBusy(async () => {
    await api(`/api/admin/devices/${deviceId}/revoke`, {
      method: 'POST',
      headers: { 'x-csrf-token': csrfToken.value },
    })
    await loadAdminSection('devices')
    setNotice('设备已吊销')
  })
}

async function createAccessGroup() {
  await withBusy(async () => {
    const routes = accessGroupForm.route_cidr
      ? [{ cidr: accessGroupForm.route_cidr, description: accessGroupForm.route_description || null }]
      : []
    await api<AccessGroupDetail>('/api/admin/access-groups', {
      method: 'POST',
      headers: { 'x-csrf-token': csrfToken.value },
      body: JSON.stringify({
        name: accessGroupForm.name,
        description: accessGroupForm.description || null,
        is_high_privilege: accessGroupForm.is_high_privilege,
        enabled: accessGroupForm.enabled,
        routes,
      }),
    })
    Object.assign(accessGroupForm, {
      name: '',
      description: '',
      is_high_privilege: false,
      enabled: true,
      route_cidr: '',
      route_description: '',
    })
    await loadAdminSection('access')
    setNotice('访问组已创建')
  })
}

function viewFromRouteName(routeName: string): View | null {
  return routeViews.has(routeName as View) ? routeName as View : null
}

function viewFromPath(pathname: string): View | null {
  const firstSegment = pathname.replace(/^\/+|\/+$/g, '').split('/')[0] ?? ''
  if (!firstSegment) {
    return null
  }
  if (firstSegment === 'password') {
    return 'password'
  }
  return viewFromRouteName(firstSegment)
}

onMounted(() => {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('token')
  if (token) {
    passwordForm.token = token
    view.value = 'password'
    return
  }
  const hash = window.location.hash.replace('#', '')
  const hashView = viewFromRouteName(hash)
  if (hashView) {
    view.value = hashView
    return
  }
  const pathView = viewFromPath(window.location.pathname)
  if (pathView) {
    view.value = pathView
  }
})
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div class="brand">
        <strong>WirePortal</strong>
        <span v-if="me">{{ me.display_name }} · {{ me.role }}</span>
      </div>
      <nav aria-label="primary">
        <button
          :class="{ active: view === 'apply' }"
          @click="view = 'apply'"
        >
          申请
        </button>
        <button
          :class="{ active: view === 'password' }"
          @click="view = 'password'"
        >
          密码
        </button>
        <button
          :class="{ active: view === 'login' }"
          @click="view = 'login'"
        >
          登录
        </button>
        <button
          :class="{ active: view === 'portal' }"
          :disabled="!me"
          @click="view = 'portal'; loadDevices()"
        >
          设备
        </button>
        <button
          :class="{ active: view === 'admin' }"
          :disabled="!canUseAdmin"
          @click="openAdmin()"
        >
          管理
        </button>
        <button
          v-if="me"
          @click="logout"
        >
          退出
        </button>
      </nav>
    </header>

    <p
      v-if="notice"
      class="notice"
    >
      {{ notice }}
    </p>

    <section
      v-if="view === 'setup'"
      class="workspace narrow"
    >
      <form
        class="panel"
        @submit.prevent="completeSetup"
      >
        <h1>首次初始化</h1>
        <label>邮箱<input
          v-model="setupForm.email"
          type="email"
          required
        ></label>
        <label>姓名<input
          v-model="setupForm.display_name"
          required
          maxlength="160"
        ></label>
        <label>密码<input
          v-model="setupForm.password"
          type="password"
          required
          minlength="8"
        ></label>
        <button
          class="primary"
          :disabled="busy"
        >
          创建管理员
        </button>
      </form>
    </section>

    <section
      v-if="view === 'apply'"
      class="workspace two-column"
    >
      <form
        class="panel"
        @submit.prevent="submitApplication"
      >
        <h1>VPN 申请</h1>
        <label>邮箱<input
          v-model="applyForm.email"
          type="email"
          required
        ></label>
        <label>姓名<input
          v-model="applyForm.display_name"
          required
          maxlength="160"
        ></label>
        <label>手机<input
          v-model="applyForm.phone"
          maxlength="64"
        ></label>
        <label>设备数<input
          v-model.number="applyForm.requested_device_count"
          type="number"
          min="1"
          max="3"
        ></label>
        <label>理由<textarea
          v-model="applyForm.reason"
          maxlength="2000"
        /></label>
        <button
          class="primary"
          :disabled="busy"
        >
          提交申请
        </button>
      </form>

      <section class="panel compact">
        <h2>申请状态</h2>
        <div class="metric">
          <span>单次设备数</span><strong>1-3</strong>
        </div>
        <div class="metric">
          <span>审批后</span><strong>设置密码</strong>
        </div>
        <div class="metric">
          <span>安装包</span><strong>登录后下载</strong>
        </div>
      </section>
    </section>

    <section
      v-if="view === 'password'"
      class="workspace narrow"
    >
      <form
        class="panel"
        @submit.prevent="setupPassword"
      >
        <h1>设置密码</h1>
        <label>Token<input
          v-model="passwordForm.token"
          required
        ></label>
        <label>新密码<input
          v-model="passwordForm.password"
          type="password"
          required
          minlength="8"
        ></label>
        <button
          class="primary"
          :disabled="busy"
        >
          保存密码
        </button>
      </form>
    </section>

    <section
      v-if="view === 'login'"
      class="workspace narrow"
    >
      <form
        class="panel"
        @submit.prevent="login"
      >
        <h1>登录</h1>
        <label>邮箱<input
          v-model="loginForm.email"
          type="email"
          required
        ></label>
        <label>密码<input
          v-model="loginForm.password"
          type="password"
          required
        ></label>
        <button
          class="primary"
          :disabled="busy"
        >
          登录
        </button>
      </form>
    </section>

    <section
      v-if="view === 'portal'"
      class="workspace two-column"
    >
      <section class="panel">
        <div class="panel-header">
          <h1>我的设备</h1>
          <button
            type="button"
            @click="loadDevices"
          >
            刷新
          </button>
        </div>

        <form
          class="inline-form"
          @submit.prevent="createDevice"
        >
          <label>设备名称<input
            v-model="deviceForm.name"
            required
            maxlength="160"
          ></label>
          <button
            class="primary"
            :disabled="busy"
          >
            新建
          </button>
        </form>

        <article
          v-for="device in devices"
          :key="device.id"
          class="device-row"
        >
          <div>
            <strong>{{ device.name }}</strong>
            <span>{{ device.vpn_ip }} · {{ device.status }}</span>
          </div>
          <div class="device-actions">
            <button
              v-if="device.current_package"
              :disabled="!device.current_package.can_download"
              @click="downloadPackage(device.current_package.id)"
            >
              下载
            </button>
            <button
              v-if="device.current_package"
              :disabled="!device.current_package.can_download"
              @click="confirmPackage(device.current_package.id)"
            >
              确认
            </button>
            <button @click="reportLost(device.id)">
              丢失
            </button>
          </div>
        </article>
        <p
          v-if="devices.length === 0"
          class="empty"
        >
          暂无设备
        </p>
      </section>

      <section class="panel compact">
        <h2>安装包</h2>
        <div
          v-for="device in devices"
          :key="`${device.id}-package`"
          class="metric stacked"
        >
          <span>{{ device.name }}</span>
          <strong>{{ device.current_package?.status || '-' }}</strong>
          <small>签名: {{ device.current_package?.signed_status || '-' }}</small>
          <small>文件: {{ device.current_package?.file_name || '-' }}</small>
          <small>大小: {{ formatBytes(device.current_package?.file_size ?? null) }}</small>
          <small>SHA256: {{ shortSha(device.current_package?.sha256 ?? null) }}</small>
        </div>
      </section>
    </section>

    <section
      v-if="view === 'admin'"
      class="workspace admin-layout"
    >
      <aside class="panel side-nav">
        <button
          :class="{ active: adminSection === 'approvals' }"
          @click="openAdmin('approvals')"
        >
          审批
        </button>
        <button
          :class="{ active: adminSection === 'users' }"
          @click="openAdmin('users')"
        >
          用户
        </button>
        <button
          :class="{ active: adminSection === 'devices' }"
          @click="openAdmin('devices')"
        >
          设备
        </button>
        <button
          :class="{ active: adminSection === 'access' }"
          @click="openAdmin('access')"
        >
          访问组
        </button>
        <button
          :class="{ active: adminSection === 'health' }"
          @click="openAdmin('health')"
        >
          健康
        </button>
        <button
          :class="{ active: adminSection === 'audit' }"
          @click="openAdmin('audit')"
        >
          审计
        </button>
      </aside>

      <section
        v-if="adminSection === 'approvals'"
        class="panel"
      >
        <div class="panel-header">
          <h1>申请审批</h1>
          <button @click="loadAdminSection('approvals')">
            刷新
          </button>
        </div>
        <div class="split">
          <div>
            <button
              v-for="application in pendingApplications"
              :key="application.id"
              class="row-button"
              :class="{ active: activeApplicationId === application.id }"
              @click="selectApplication(application.id)"
            >
              <span>{{ application.display_name }}</span>
              <strong>{{ application.requested_device_count }} 台</strong>
            </button>
            <p
              v-if="pendingApplications.length === 0"
              class="empty"
            >
              暂无待审批申请
            </p>
          </div>

          <div
            v-if="applicationDetail"
            class="detail-pane"
          >
            <h2>{{ applicationDetail.display_name }}</h2>
            <dl class="detail-list">
              <div><dt>邮箱</dt><dd>{{ applicationDetail.email }}</dd></div>
              <div><dt>状态</dt><dd>{{ applicationDetail.status }}</dd></div>
              <div><dt>设备数</dt><dd>{{ applicationDetail.requested_device_count }}</dd></div>
              <div><dt>理由</dt><dd>{{ applicationDetail.reason || '-' }}</dd></div>
            </dl>

            <form
              class="stack-form"
              @submit.prevent="approveApplication"
            >
              <label>批准设备数<input
                v-model.number="approveForm.approved_device_limit"
                type="number"
                min="1"
                max="10"
              ></label>
              <fieldset>
                <legend>访问组</legend>
                <label
                  v-for="group in accessGroups"
                  :key="group.id"
                  class="check-row"
                >
                  <input
                    type="checkbox"
                    :checked="approveForm.access_group_ids.includes(group.id)"
                    @change="toggleAccessGroup(group.id)"
                  >
                  <span>{{ group.name }}</span>
                  <strong v-if="group.is_high_privilege">高权限</strong>
                </label>
              </fieldset>
              <label>备注<input v-model="approveForm.reason"></label>
              <button
                class="primary"
                :disabled="busy"
              >
                通过
              </button>
            </form>

            <form
              class="stack-form muted-form"
              @submit.prevent="rejectApplication"
            >
              <label>拒绝原因<input v-model="rejectForm.reason"></label>
              <button
                class="danger"
                :disabled="busy"
              >
                拒绝
              </button>
            </form>
          </div>
        </div>
        <div
          v-if="setupUrl"
          class="copy-block"
        >
          <input
            :value="setupUrl"
            readonly
          >
          <button @click="copySetupUrl">
            复制
          </button>
        </div>
      </section>

      <section
        v-if="adminSection === 'users'"
        class="panel"
      >
        <div class="panel-header">
          <h1>用户管理</h1>
          <button @click="loadAdminSection('users')">
            刷新
          </button>
        </div>
        <article
          v-for="user in users"
          :key="user.id"
          class="data-row user-row"
        >
          <div>
            <strong>{{ user.display_name }}</strong>
            <span>{{ user.email }}</span>
          </div>
          <div class="badges">
            <span>{{ user.role }}</span>
            <span>{{ user.status }}</span>
            <span>{{ user.device_count }}/{{ user.approved_device_limit }}</span>
          </div>
          <div class="inline-actions">
            <label>设备额度<input
              v-model.number="userLimitDrafts[user.id]"
              type="number"
              min="0"
              max="10"
            ></label>
            <button
              :disabled="busy || me?.role !== 'admin'"
              @click="updateUserDeviceLimit(user)"
            >
              保存
            </button>
          </div>
        </article>
      </section>

      <section
        v-if="adminSection === 'devices'"
        class="panel"
      >
        <div class="panel-header">
          <h1>设备管理</h1>
          <button @click="loadAdminSection('devices')">
            刷新
          </button>
        </div>
        <article
          v-for="device in adminDevices"
          :key="device.id"
          class="device-row"
        >
          <div>
            <strong>{{ device.name }}</strong>
            <span>{{ device.user_email || device.user_id }} · {{ device.vpn_ip }} · {{ device.status }}</span>
            <small>{{ device.current_package?.file_name || '-' }}</small>
          </div>
          <div class="device-actions">
            <button @click="resetAdminDevice(device.id)">
              重置
            </button>
            <button
              class="danger"
              @click="revokeAdminDevice(device.id)"
            >
              吊销
            </button>
          </div>
        </article>
      </section>

      <section
        v-if="adminSection === 'access'"
        class="workspace-grid"
      >
        <section class="panel">
          <div class="panel-header">
            <h1>访问组</h1>
            <button @click="loadAdminSection('access')">
              刷新
            </button>
          </div>
          <article
            v-for="group in accessGroups"
            :key="group.id"
            class="data-row"
          >
            <div>
              <strong>{{ group.name }}</strong>
              <span>{{ group.description || '-' }}</span>
            </div>
            <div class="badges">
              <span>{{ group.enabled ? '启用' : '停用' }}</span>
              <span v-if="group.is_high_privilege">高权限</span>
            </div>
          </article>
        </section>
        <form
          class="panel stack-form"
          @submit.prevent="createAccessGroup"
        >
          <h2>新建访问组</h2>
          <label>名称<input
            v-model="accessGroupForm.name"
            required
            maxlength="120"
          ></label>
          <label>描述<input
            v-model="accessGroupForm.description"
            maxlength="2000"
          ></label>
          <label>路由 CIDR<input
            v-model="accessGroupForm.route_cidr"
            placeholder="10.20.0.0/16"
          ></label>
          <label>路由说明<input v-model="accessGroupForm.route_description"></label>
          <label class="switch-row"><input
            v-model="accessGroupForm.is_high_privilege"
            type="checkbox"
          >高权限</label>
          <label class="switch-row"><input
            v-model="accessGroupForm.enabled"
            type="checkbox"
          >启用</label>
          <button
            class="primary"
            :disabled="busy"
          >
            创建
          </button>
        </form>
      </section>

      <section
        v-if="adminSection === 'health'"
        class="panel"
      >
        <div class="panel-header">
          <h1>系统健康</h1>
          <button @click="loadAdminSection('health')">
            刷新
          </button>
        </div>
        <div
          v-if="runtimeHealth"
          class="metric-grid"
        >
          <div class="metric stacked">
            <span>总状态</span><strong>{{ runtimeHealth.status }}</strong>
          </div>
          <div class="metric stacked">
            <span>数据库</span><strong>{{ runtimeHealth.database.status }}</strong>
          </div>
          <div class="metric stacked">
            <span>待处理任务</span><strong>{{ runtimeHealth.jobs.pending }}</strong>
          </div>
          <div class="metric stacked">
            <span>运行设备</span><strong>{{ runtimeHealth.runtime.active_devices }}</strong>
          </div>
          <div class="metric stacked">
            <span>目标设备</span><strong>{{ runtimeHealth.runtime.target_devices }}</strong>
          </div>
          <div class="metric stacked">
            <span>接口/Table</span><strong>{{ runtimeHealth.runtime.wg_interface }} / {{ runtimeHealth.runtime.nft_table_name }}</strong>
          </div>
        </div>
        <pre v-if="runtimeHealth">{{ JSON.stringify(runtimeHealth.wg_agent, null, 2) }}</pre>
      </section>

      <section
        v-if="adminSection === 'audit'"
        class="panel"
      >
        <div class="panel-header">
          <h1>审计日志</h1>
          <button @click="loadAdminSection('audit')">
            刷新
          </button>
        </div>
        <article
          v-for="row in auditLogs"
          :key="row.id"
          class="data-row"
        >
          <div>
            <strong>{{ row.action }}</strong>
            <span>{{ row.target_type }} · {{ row.target_id || '-' }}</span>
          </div>
          <div class="audit-meta">
            <span>{{ row.actor_type }}</span>
            <span>{{ formatDate(row.created_at) }}</span>
          </div>
        </article>
      </section>
    </section>
  </main>
</template>
