<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { get, post, put, del } from '../api'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import StatCard from '../components/StatCard.vue'
import DataTable from '../components/DataTable.vue'

const token = ref(localStorage.getItem('piso-token') || '')
const username = ref(localStorage.getItem('piso-user') || 'admin')
const loginForm = reactive({ username: 'admin', password: '' })
const loginError = ref('')
const error = ref('')
const notice = ref('')
const confirm = ref(null)
const stats = ref({})
const vouchers = ref([])
const sessions = ref([])
const devices = ref([])
const plans = ref([])
const transactions = ref([])
const coinEvents = ref([])
const settings = reactive({ hotspot_name: '', terms: '', currency: '', coin_value: '', coin_countdown: 60, banner_subtitle: '', banner_bg: '#1d4ed8', banner_fg: '#ffffff', session_pause_enabled: '1' })
const coinOptions = [1, 5, 10, 20]
const hardware = reactive({ coin_pulse_pin: 3, relay_pin: 11, gpio_enabled: false, relay_active: false })
const qos = reactive({ qos_enabled: true, qos_per_guest_down_mbps: 10, qos_per_guest_up_mbps: 10, qos_global_down_mbps: 320, qos_global_up_mbps: 320 })
const qosClients = ref([])
const qosHistory = ref([])
const voucherForm = reactive({ count: '', duration_minutes: '', price: '' })
const generatedCodes = ref([])
const planForm = reactive({ id: null, name: '', duration_minutes: '', price: '', active: true, qos_down_mbps: null, qos_up_mbps: null })
const passwordForm = reactive({ old_password: '', new_password: '', new_password_confirm: '', new_username: '' })
const sidebarOpen = ref(false)
const version = ref('')
const isDefaultPassword = ref(false)
const backupStatus = ref('')
const restoreStatus = ref('')
const restoreFileName = ref('')

const sections = [
  ['overview', 'Overview'],
  ['vouchers', 'Vouchers'],
  ['sessions', 'Sessions'],
  ['plans', 'Plans'],
  ['transactions', 'Transactions'],
  ['coins', 'Coin events'],
  ['settings', 'Settings'],
  ['network', 'Network'],
  ['hardware', 'Hardware'],
  ['password', 'Account'],
  ['backup', 'Backup'],
]
const VALID_SECTIONS = new Set(sections.map(s => s[0]))
const STORAGE_KEY = 'piso-console-section'

function initialSection() {
  try {
    const qp = new URLSearchParams(window.location.search).get('s')
    if (qp && VALID_SECTIONS.has(qp)) return qp
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && VALID_SECTIONS.has(saved)) return saved
  } catch { /* ignore */ }
  return 'overview'
}

const section = ref(initialSection())
const activeLabel = computed(() => sections.find(s => s[0] === section.value)?.[1] ?? 'Overview')
const enabledCoins = computed(() => (settings.coin_value || '').split(',').map(s => s.trim()).filter(Boolean))
function isCoinEnabled(v) { return enabledCoins.value.includes(String(v)) }
function toggleCoin(v) {
  const s = String(v)
  let vals = enabledCoins.value.slice()
  if (vals.includes(s)) vals = vals.filter(x => x !== s)
  else vals.push(s)
  vals.sort((a, b) => Number(a) - Number(b))
  settings.coin_value = vals.join(',')
}
const sessionPauseEnabled = computed({
  get: () => String(settings.session_pause_enabled ?? '1') !== '0',
  set: (v) => { settings.session_pause_enabled = v ? '1' : '0' },
})

watch(section, (v) => {
  try {
    localStorage.setItem(STORAGE_KEY, v)
    const url = new URL(window.location.href)
    url.searchParams.set('s', v)
    history.replaceState(null, '', url.toString())
  } catch { /* ignore */ }
})

let qosPoll = null
async function pollQosTick() {
  if (section.value !== 'network' || !token.value) return
  try {
    const c = await get('/api/admin/qos/clients')
    qosClients.value = c.clients || []
  } catch {}
  try { qosHistory.value = await get('/api/admin/qos/history?limit=30') } catch {}
}
function startQosPoll() {
  stopQosPoll()
  if (section.value === 'network' && token.value) {
    pollQosTick()
    qosPoll = setInterval(pollQosTick, 3000)
  }
}
function stopQosPoll() {
  if (qosPoll) { clearInterval(qosPoll); qosPoll = null }
}
watch(section, () => { if (section.value === 'network') startQosPoll(); else stopQosPoll() })
watch(token, () => { if (section.value === 'network' && token.value) startQosPoll(); else if (!token.value) stopQosPoll() })

async function login() {
  loginError.value = ''
  try {
    const r = await post('/api/auth/login', loginForm)
    token.value = r.token
    username.value = r.username
    localStorage.setItem('piso-token', r.token)
    localStorage.setItem('piso-user', r.username)
    load()
  } catch (e) { loginError.value = e.message }
}
function logout() {
  token.value = ''
  version.value = ''
  localStorage.removeItem('piso-token')
  localStorage.removeItem('piso-user')
}
async function checkDefaultPassword() {
  if (!token.value) { isDefaultPassword.value = false; return }
  try {
    const r = await get('/api/admin/password-status')
    isDefaultPassword.value = !!r.is_default
  } catch { /* ignore */ }
}
async function load() {
  error.value = ''
  try { version.value = (await get('/api/admin/version')).version || '' } catch { /* version is optional */ }
  try {
    if (section.value === 'overview') stats.value = await get('/api/admin/overview')
    if (section.value === 'vouchers') vouchers.value = await get('/api/admin/vouchers')
    if (section.value === 'sessions') sessions.value = await get('/api/admin/sessions')
    if (section.value === 'sessions') { try { devices.value = await get('/api/admin/devices') } catch {} }
    if (section.value === 'plans') plans.value = await get('/api/admin/plans')
    if (section.value === 'transactions') transactions.value = await get('/api/admin/transactions')
    if (section.value === 'coins') coinEvents.value = await get('/api/admin/coins')
    if (section.value === 'settings') Object.assign(settings, await get('/api/admin/settings'))
    if (section.value === 'network') {
      Object.assign(qos, await get('/api/admin/qos'))
      try {
        const c = await get('/api/admin/qos/clients')
        qosClients.value = c.clients || []
        // keep qos in sync if backend returned it
        if (c.qos) Object.assign(qos, c.qos)
      } catch {}
      try { qosHistory.value = await get('/api/admin/qos/history?limit=30') } catch { qosHistory.value = [] }
    }
    if (section.value === 'hardware') Object.assign(hardware, await get('/api/admin/hardware'))
  } catch (e) { error.value = e.message }
  checkDefaultPassword()
}
function choose(id) {
  if (!VALID_SECTIONS.has(id)) return
  section.value = id
  notice.value = ''
  sidebarOpen.value = false
  load()
}

function ask(title, message, label, run, danger = false) {
  error.value = ''
  confirm.value = { title, message, label, run, danger }
}
async function runConfirm() {
  const c = confirm.value
  confirm.value = null
  if (!c) return
  try { await c.run(); await load() } catch (e) { error.value = e.message }
}
function urlDate(value) { return value ? new Date(value).toLocaleString() : '—' }
function displayForMinutes(m) {
  const n = Number(m)
  if (!Number.isFinite(n)) return String(m)
  if (n < 60) return `${n} minutes`
  if (n % 60 === 0) return n === 60 ? '1 hour' : `${n/60} hours`
  const h = Math.floor(n / 60)
  const rem = n % 60
  return `${h}h ${rem}m`
}

function askGenerate() {
  const c = Number(voucherForm.count)
  const m = Number(voucherForm.duration_minutes)
  const p = Number(voucherForm.price)
  if (!Number.isFinite(c) || c < 1 || c > 100) { error.value = 'Count must be 1–100.'; return }
  if (!Number.isFinite(m) || m < 1) { error.value = 'Minutes is required (≥1).'; return }
  if (!Number.isFinite(p) || p < 0) { error.value = 'Price is required (≥0).'; return }
  ask('Generate vouchers?', `${c} code(s) for ${m} minutes at ${p} each.`, 'Generate', async () => {
    const r = await post('/api/admin/vouchers/generate', { count: c, duration_minutes: m, price: p })
    generatedCodes.value = r.codes
  })
}
function askDeleteVoucher(row) {
  ask('Delete voucher?', `Code ${row.code} will be removed and can no longer be redeemed.`, 'Delete', () => del(`/api/admin/vouchers/${row.id}`), true)
}
function askRevoke(row) {
  ask('Revoke session?', `Internet access for ${row.mac} will stop immediately.`, 'Revoke', () => post(`/api/admin/sessions/${row.id}/revoke`), true)
}
function editPlan(row) { Object.assign(planForm, { id: row.id, name: row.name, duration_minutes: row.duration_minutes, price: row.price, active: !!row.active, qos_down_mbps: row.qos_down_mbps ?? null, qos_up_mbps: row.qos_up_mbps ?? null }) }
function resetPlan() { Object.assign(planForm, { id: null, name: '', duration_minutes: '', price: '', active: true, qos_down_mbps: null, qos_up_mbps: null }) }
function askSavePlan() {
  const price = Number(planForm.price)
  const duration = Number(planForm.duration_minutes)
  if (!Number.isFinite(duration) || duration < 1) { error.value = 'Minutes is required (≥1).'; return }
  if (!Number.isFinite(price) || price < 0) { error.value = 'Price is required (≥0).'; return }
  const name = displayForMinutes(duration)
  const toIntOrNull = v => (v === '' || v == null ? null : Number(v))
  const qDown = toIntOrNull(planForm.qos_down_mbps)
  const qUp = toIntOrNull(planForm.qos_up_mbps)
  if (qDown !== null && (!Number.isFinite(qDown) || qDown < 1 || qDown > 1000)) { error.value = 'Down override must be 1–1000 Mbps or empty.'; return }
  if (qUp !== null && (!Number.isFinite(qUp) || qUp < 1 || qUp > 1000)) { error.value = 'Up override must be 1–1000 Mbps or empty.'; return }
  const body = { name, duration_minutes: duration, coins_required: price, price, active: !!planForm.active, qos_down_mbps: qDown, qos_up_mbps: qUp }
  ask(planForm.id ? 'Update plan?' : 'Add plan?', `${name} — ${duration} min for ${settings.currency || 'PHP'} ${price}.`, 'Save', async () => {
    if (planForm.id) await put(`/api/admin/plans/${planForm.id}`, body)
    else await post('/api/admin/plans', body)
    resetPlan()
  })
}
function askDeletePlan(row) {
  ask('Delete plan?', `${row.name} will be removed from the portal.`, 'Delete', () => del(`/api/admin/plans/${row.id}`), true)
}
function askSettings() {
  ask('Save settings?', 'These values appear on the customer portal immediately.', 'Save', async () => {
    await put('/api/admin/settings', settings)
    notice.value = 'Settings saved.'
  })
}
function askHardware() {
  ask('Save hardware settings?', 'Coin pulse and relay pins use physical header numbers. Incorrect wiring can damage the board.', 'Save', async () => {
    await put('/api/admin/hardware', { ...hardware, coin_pulse_pin: Number(hardware.coin_pulse_pin), relay_pin: Number(hardware.relay_pin) })
    notice.value = 'Hardware settings saved.'
  })
}
function askQos() {
  ask('Save network / QoS settings?', `Per-guest ${qos.qos_per_guest_down_mbps}/${qos.qos_per_guest_up_mbps} Mbps down/up, global ${qos.qos_global_down_mbps}/${qos.qos_global_up_mbps} Mbps. Clients are shaped on guest0.`, 'Save', async () => {
    await put('/api/admin/qos', { qos_enabled: !!qos.qos_enabled, qos_per_guest_down_mbps: Number(qos.qos_per_guest_down_mbps), qos_per_guest_up_mbps: Number(qos.qos_per_guest_up_mbps), qos_global_down_mbps: Number(qos.qos_global_down_mbps), qos_global_up_mbps: Number(qos.qos_global_up_mbps) })
    notice.value = 'Network settings saved — device applies on next sync (≤10s).'
  })
}
function askPassword() {
  error.value = ''
  const hasPw = !!passwordForm.new_password
  const hasUser = !!passwordForm.new_username.trim()
  if (!hasPw && !hasUser) { error.value = 'Enter a new username or a new password.'; return }
  if (hasPw && passwordForm.new_password.length < 6) { error.value = 'New password must be at least 6 characters.'; return }
  if (hasPw && passwordForm.new_password !== passwordForm.new_password_confirm) { error.value = 'New passwords do not match.'; return }
  if (hasUser && !/^[a-zA-Z0-9._-]{3,32}$/.test(passwordForm.new_username.trim())) { error.value = 'Username: 3–32 chars, letters/numbers/._- only.'; return }
  const newUser = hasUser ? passwordForm.new_username.trim() : ''
  const summary = [
    hasUser ? `Username → ${newUser}` : null,
    hasPw ? 'Password will be changed' : null,
  ].filter(Boolean).join(' · ')
  ask('Save account changes?', summary || 'Your new credentials will be used for all future logins.', 'Save changes', async () => {
    const payload = { old_password: passwordForm.old_password }
    if (hasUser) payload.new_username = newUser
    if (hasPw) { payload.new_password = passwordForm.new_password; payload.new_password_confirm = passwordForm.new_password_confirm }
    const r = await post('/api/auth/change-password', payload)
    if (r.token) { token.value = r.token; localStorage.setItem('piso-token', r.token) }
    if (r.username) { username.value = r.username; localStorage.setItem('piso-user', r.username); passwordForm.new_username = r.username }
    passwordForm.old_password = ''
    passwordForm.new_password = ''
    passwordForm.new_password_confirm = ''
    notice.value = 'Account updated.'
    checkDefaultPassword()
  })
}

async function downloadBackup() {
  error.value = ''
  backupStatus.value = ''
  try {
    const data = await get('/api/admin/backup')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    const stamp = (data.meta && data.meta.created_at ? data.meta.created_at.slice(0, 10) : new Date().toISOString().slice(0, 10))
    a.href = url
    a.download = `pisowifi-backup-${stamp}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
    backupStatus.value = `Backup downloaded — ${Object.keys(data.tables || {}).length} tables, ${Object.values(data.tables || {}).reduce((n, v) => n + (Array.isArray(v) ? v.length : 0), 0)} rows.`
  } catch (e) { error.value = e.message }
}

function onRestoreFilePicked(e) {
  const f = e.target.files && e.target.files[0]
  if (!f) return
  restoreFileName.value = f.name
  restoreStatus.value = ''
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const parsed = JSON.parse(reader.result)
      // keep in element for later confirm
      e.target._parsedBackup = parsed
    } catch (err) {
      error.value = 'Invalid backup file — not valid JSON.'
      e.target.value = ''
      restoreFileName.value = ''
    }
  }
  reader.readAsText(f)
}

function askRestore() {
  const input = document.getElementById('restore-file-input')
  const parsed = input && input._parsedBackup
  if (!parsed || !parsed.tables) { error.value = 'Pick a valid backup .json file first.'; return }
  const tables = parsed.tables
  const rows = Object.values(tables).reduce((n, v) => n + (Array.isArray(v) ? v.length : 0), 0)
  const summary = `${Object.keys(tables).length} tables, ${rows} rows. ` +
    'This will REPLACE all current data (plans, vouchers, sessions, transactions, settings). Current data cannot be undone without another backup.'
  ask('Restore from backup?', summary, 'Restore', async () => {
    const r = await post('/api/admin/restore', parsed)
    restoreStatus.value = `Restore complete — ${r.rows} rows across ${r.restored_tables.length} tables. Reloading…`
    // Admin user may have been restored to a different password — force re-login if token invalid
    setTimeout(() => { load(); checkDefaultPassword(); }, 600)
    if (input) { input.value = ''; input._parsedBackup = null; restoreFileName.value = '' }
  }, true)
}

watch(username, (v) => { if (!passwordForm.new_username) passwordForm.new_username = v }, { immediate: true })
watch(token, (v) => { if (v && !passwordForm.new_username) passwordForm.new_username = username.value })

onMounted(() => {
  // keep URL in sync on first paint
  try {
    const url = new URL(window.location.href)
    if (VALID_SECTIONS.has(section.value)) url.searchParams.set('s', section.value)
    history.replaceState(null, '', url.toString())
  } catch { /* ignore */ }
  passwordForm.new_username = username.value || passwordForm.new_username
  if (token.value) {
    load().then(() => { if (section.value === 'network') startQosPoll() })
  }
})
onUnmounted(() => stopQosPoll())
</script>

<template>
  <!-- Login -->
  <div v-if="!token" class="flex min-h-screen items-center justify-center bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 px-4 py-8">
    <form class="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl ring-1 ring-black/5 sm:p-7" @submit.prevent="login">
      <div class="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-slate-900 text-white">
        <svg viewBox="0 0 24 24" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l7 4v5c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z"/><path d="M9 12l2 2 4-4"/></svg>
      </div>
      <h1 class="mt-4 text-center text-xl font-bold tracking-tight text-slate-900">Piso WiFi · Console</h1>
      <p class="mt-1 text-center text-sm text-slate-500">Sign in to manage your hotspot.</p>
      <div v-if="loginError" role="alert" class="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">{{ loginError }}</div>
      <label class="mt-5 block text-sm font-medium text-slate-700">Username</label>
      <input v-model="loginForm.username" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3.5 text-sm shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" autocomplete="username" placeholder="admin" />
      <label class="mt-3.5 block text-sm font-medium text-slate-700">Password</label>
      <input v-model="loginForm.password" type="password" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3.5 text-sm shadow-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" autocomplete="current-password" placeholder="••••••••" />
      <button class="mt-6 inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600">Sign in</button>
      <router-link to="/" class="mt-3 block text-center text-sm font-medium text-slate-500 hover:text-slate-700">Back to portal →</router-link>
      <p class="mt-4 text-center text-xs text-slate-400">Your last console tab is remembered — reload returns you there.</p>
    </form>
  </div>

  <!-- Console -->
  <div v-else class="min-h-screen bg-slate-100">
    <!-- Top bar -->
    <header class="sticky top-0 z-20 border-b border-slate-800 bg-slate-900 text-white">
      <div class="mx-auto flex h-14 max-w-[1400px] items-center justify-between gap-3 px-4">
        <div class="flex min-w-0 items-center gap-3">
          <button class="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/15 bg-white/5 hover:bg-white/10 lg:hidden" aria-label="Open navigation" @click="sidebarOpen = !sidebarOpen">
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
          </button>
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/15" aria-hidden="true">
            <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l7 4v5c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z"/><path d="M9 12l2 2 4-4"/></svg>
          </div>
          <div class="min-w-0">
            <div class="flex min-w-0 items-baseline gap-1.5">
              <p class="truncate text-sm font-bold tracking-tight sm:text-[15px]">Piso WiFi · Console</p>
              <span v-if="version" class="shrink-0 text-xs font-normal text-slate-400">v{{ version }}</span>
            </div>
            <p class="hidden truncate text-xs text-slate-400 sm:block">Signed in as <span class="font-medium text-slate-200">{{ username }}</span> · <span class="text-slate-400">{{ activeLabel }}</span></p>
          </div>
        </div>
        <div class="flex shrink-0 items-center gap-2">
          <span class="hidden items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-xs font-medium text-slate-200 ring-1 ring-white/15 sm:inline-flex"><span class="h-2 w-2 rounded-full bg-emerald-400"></span>Admin</span>
          <router-link to="/console/preview" class="hidden min-h-9 items-center rounded-lg border border-white/15 px-3 text-sm font-medium text-slate-200 hover:bg-white/10 sm:inline-flex">Preview</router-link>
          <router-link to="/" class="hidden min-h-9 items-center rounded-lg border border-white/15 px-3 text-sm font-medium text-slate-200 hover:bg-white/10 sm:inline-flex">Portal</router-link>
          <!-- mobile quick links -->
          <router-link to="/console/preview" class="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-white/15 sm:hidden" aria-label="Preview"><svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/></svg></router-link>
          <button class="inline-flex min-h-9 items-center rounded-lg bg-white px-3.5 text-sm font-semibold text-slate-900 hover:bg-slate-100" @click="logout">Sign out</button>
        </div>
      </div>
    </header>

    <div class="mx-auto flex max-w-[1400px]">
      <!-- Sidebar desktop -->
      <aside class="hidden w-[272px] shrink-0 border-r border-slate-200 bg-white lg:block">
        <div class="sticky top-14 flex h-[calc(100vh-3.5rem)] flex-col overflow-y-auto">
          <nav class="p-3" aria-label="Console navigation">
            <p class="px-3 pb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-400">Manage</p>
            <button
              v-for="[id, label] in sections.slice(0,6)" :key="id"
              class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition"
              :class="section === id ? 'bg-slate-900 text-white shadow-sm' : 'text-slate-700 hover:bg-slate-100'"
              @click="choose(id)"
            >
              <span class="flex h-7 w-7 items-center justify-center rounded-lg text-xs" :class="section===id ? 'bg-white/15' : 'bg-slate-100'">
                <svg v-if="id==='overview'" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>
                <svg v-else-if="id==='vouchers'" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 10h10M7 15h6"/></svg>
                <svg v-else-if="id==='sessions'" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="8" r="4"/><path d="M4 20a8 8 0 0116 0"/></svg>
                <svg v-else-if="id==='plans'" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M8 14l2 2 6-6"/></svg>
                <svg v-else-if="id==='transactions'" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M4 12h16M4 17h16"/></svg>
                <svg v-else-if="id==='coins'" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="7"/><path d="M12 8v8M9 10h6M9 14h6"/></svg>
                <span v-else>•</span>
              </span>
              {{ label }}
            </button>
            <p class="mt-5 px-3 pb-2 text-[11px] font-semibold uppercase tracking-widest text-slate-400">System</p>
            <button
              v-for="[id, label] in sections.slice(6)" :key="id"
              class="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm font-medium transition"
              :class="section === id ? 'bg-slate-900 text-white shadow-sm' : 'text-slate-700 hover:bg-slate-100'"
              @click="choose(id)"
            >
              <span class="flex h-7 w-7 items-center justify-center rounded-lg text-xs" :class="section===id ? 'bg-white/15' : 'bg-slate-100'">
                <svg v-if="id==='settings'" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 15a3 3 0 100-6 3 3 0 000 6z"/><path d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a1.5 1.5 0 01-2.1 2.1l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.6V21a1.5 1.5 0 01-3 0v-.4a1.7 1.7 0 00-1-1.6 1.7 1.7 0 00-1.9.3l-.1.1a1.5 1.5 0 01-2.1-2.1l.1-.1A1.7 1.7 0 004.6 15a1.7 1.7 0 00-1.6-1V12a1.7 1.7 0 001.6-1A1.7 1.7 0 004.9 9l-.1-.1A1.5 1.5 0 017 6.8l.1.1A1.7 1.7 0 009 7.2 1.7 1.7 0 0010 5.6V5a1.5 1.5 0 013 0v.6a1.7 1.7 0 001 1.6 1.7 1.7 0 001.9-.3l.1-.1A1.5 1.5 0 0119.4 9l-.1.1A1.7 1.7 0 0019 11a1.7 1.7 0 001.6 1v2a1.7 1.7 0 00-1.2 1z"/></svg>
                <svg v-else-if="id==='network'" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h18M12 3v18"/><circle cx="12" cy="12" r="3"/><path d="M16 8l3-3M8 16l-3 3M16 16l3 3M8 8L5 5"/></svg>
                <svg v-else-if="id==='hardware'" viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 7V5a1 1 0 011-1h2"/><path d="M17 7V5a1 1 0 00-1-1h-2"/></svg>
                <svg v-else viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M8 11V8a4 4 0 118 0v3"/><circle cx="12" cy="16" r="1.2"/></svg>
              </span>
              {{ label }}
            </button>
          </nav>
          <div class="mt-auto border-t border-slate-100 p-4">
            <div class="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
              <p class="text-xs font-semibold text-slate-700">Need help?</p>
              <p class="mt-1 text-xs leading-relaxed text-slate-500">Plans, vouchers and portal copy are saved instantly. Hardware changes need correct pin wiring.</p>
              <router-link to="/" class="mt-2 inline-flex text-xs font-medium text-blue-600 hover:underline">Open portal →</router-link>
            </div>
          </div>
        </div>
      </aside>

      <!-- Mobile drawer -->
      <div v-if="sidebarOpen" class="fixed inset-0 z-30 lg:hidden" role="dialog" aria-modal="true">
        <div class="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" @click="sidebarOpen=false"></div>
        <aside class="absolute inset-y-0 left-0 flex w-[300px] max-w-[85vw] flex-col bg-white shadow-xl">
          <div class="flex h-14 items-center justify-between border-b border-slate-200 px-4">
            <p class="text-sm font-bold text-slate-900">Navigation</p>
            <button class="flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200" aria-label="Close navigation" @click="sidebarOpen=false"><svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
          </div>
          <nav class="flex-1 overflow-y-auto p-3">
            <button
              v-for="[id, label] in sections" :key="id"
              class="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-medium"
              :class="section === id ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-100'"
              @click="choose(id)"
            >{{ label }}</button>
          </nav>
        </aside>
      </div>

      <!-- Content -->
      <main class="min-w-0 flex-1">
        <div class="px-4 py-4 sm:px-6 sm:py-6">
          <!-- Breadcrumb + alerts -->
          <div class="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-sm">
              <span class="text-slate-400">Console</span>
              <span class="text-slate-300">/</span>
              <span class="font-semibold text-slate-900">{{ activeLabel }}</span>
              <span class="hidden items-center gap-1 rounded-full bg-slate-900 px-2 py-0.5 text-xs font-medium text-white sm:inline-flex">{{ section }}</span>
            </div>
            <p class="text-xs text-slate-400 sm:text-right">Reload keeps your last tab — stored locally &amp; in the URL <span class="font-mono">?s={{ section }}</span></p>
          </div>

          <div v-if="error" role="alert" class="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{{ error }}</div>
          <div v-if="notice" class="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ notice }}</div>
          <div v-if="isDefaultPassword" role="alert" class="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <span><span class="font-semibold">Default password in use</span> — you're still on <span class="font-mono">admin / admin@123</span>. Change it in Account.</span>
            <button class="inline-flex min-h-9 items-center rounded-lg bg-amber-900 px-3 text-sm font-semibold text-white hover:bg-amber-800" @click="choose('password')">Change now</button>
          </div>

          <!-- Overview -->
          <section v-if="section === 'overview'" class="space-y-4">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900 sm:text-xl">Overview</h2>
              <p class="mt-1 text-sm text-slate-500">Live snapshot of the hotspot — revenue, clients and vouchers.</p>
            </div>
            <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard label="Active clients" :value="stats.active_clients ?? '—'" tone="blue" />
              <StatCard label="Revenue today" :value="stats.revenue_today ?? '—'" tone="green" />
              <StatCard label="Vouchers used" :value="stats.vouchers_used ?? '—'" tone="amber" />
              <StatCard label="Coins outstanding" :value="stats.coins_outstanding ?? '—'" tone="slate" />
              <StatCard label="Guests seen" :value="stats.guests_total ?? '—'" tone="slate" />
            </div>
            <div class="grid gap-3 lg:grid-cols-3">
              <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-2">
                <h3 class="text-sm font-semibold text-slate-900">What you can do here</h3>
                <p class="mt-1 text-sm leading-relaxed text-slate-500">Use the sidebar to generate vouchers, manage time plans, inspect sessions, review transactions and tune portal or coin-slot settings. Every mutating action asks for confirmation.</p>
                <ul class="mt-4 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
                  <li class="flex gap-2"><span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600"></span>Generate &amp; delete vouchers</li>
                  <li class="flex gap-2"><span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600"></span>Revoke sessions instantly</li>
                  <li class="flex gap-2"><span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600"></span>Create plans (name auto-generates)</li>
                  <li class="flex gap-2"><span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600"></span>Save portal &amp; hardware settings</li>
                </ul>
              </div>
              <div class="rounded-2xl bg-slate-900 p-5 text-slate-100">
                <h3 class="text-sm font-semibold text-white">Tip</h3>
                <p class="mt-2 text-sm leading-relaxed text-slate-300">Your tab is remembered. Share a link like <span class="font-mono text-white">/console?s=sessions</span> — it opens directly on that section.</p>
                <p class="mt-3 text-xs leading-relaxed text-slate-400">On phones, tap the ☰ menu in the header to switch sections.</p>
              </div>
            </div>
          </section>

          <!-- Vouchers -->
          <section v-if="section === 'vouchers'" class="space-y-4">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900">Vouchers</h2>
              <p class="mt-1 text-sm text-slate-500">Create batches of codes for customers to redeem.</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
              <h3 class="text-sm font-semibold text-slate-900">Generate vouchers</h3>
              <div class="mt-3 grid gap-3 sm:grid-cols-3">
                <label class="text-sm font-medium text-slate-700">Count<input v-model.number="voucherForm.count" type="number" min="1" max="100" placeholder="" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
                <label class="text-sm font-medium text-slate-700">Minutes<input v-model.number="voucherForm.duration_minutes" type="number" min="1" placeholder="" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
                <label class="text-sm font-medium text-slate-700">Price<input v-model.number="voucherForm.price" type="number" min="0" placeholder="" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
              </div>
              <button class="mt-4 inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 sm:w-auto" @click="askGenerate">Generate</button>
              <div v-if="generatedCodes.length" class="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3.5 text-sm text-emerald-800">
                <p class="font-semibold">New codes</p>
                <p class="mt-1 break-all font-mono text-sm">{{ generatedCodes.join(', ') }}</p>
              </div>
            </div>
            <DataTable :columns="[{key:'code',label:'Code'},{key:'duration_minutes',label:'Minutes'},{key:'status',label:'Status'},{key:'created_at',label:'Created'},{key:'actions',label:''}]" :rows="vouchers" empty="No vouchers generated yet.">
              <template #cell-created_at="{ value }">{{ urlDate(value) }}</template>
              <template #cell-actions="{ row }">
                <button v-if="row.status === 'unused'" class="inline-flex min-h-9 items-center rounded-lg border border-red-200 bg-white px-3 text-sm font-medium text-red-600 hover:bg-red-50" @click="askDeleteVoucher(row)">Delete</button>
                <span v-else class="text-slate-400">—</span>
              </template>
            </DataTable>
          </section>

          <!-- Sessions -->
          <section v-if="section === 'sessions'" class="space-y-4">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900">Sessions</h2>
              <p class="mt-1 text-sm text-slate-500">Active and recent internet sessions by device.</p>
            </div>
            <DataTable :columns="[{key:'mac',label:'Device'},{key:'source',label:'Source'},{key:'expires_at',label:'Expires'},{key:'status',label:'Status'},{key:'actions',label:''}]" :rows="sessions.map(s => ({...s, status: s.paused ? 'paused' : s.active ? 'active' : 'expired'}))" empty="No sessions yet.">
              <template #cell-expires_at="{ value }">{{ urlDate(value) }}</template>
              <template #cell-status="{ value }"><span class="inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold" :class="value==='active' ? 'bg-emerald-100 text-emerald-700' : value==='paused' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100 text-slate-500'">{{ value==='active' ? 'Active' : value==='paused' ? 'Paused' : 'Expired' }}</span></template>
              <template #cell-actions="{ row }">
                <button v-if="row.active || row.paused" class="inline-flex min-h-9 items-center rounded-lg border border-red-200 bg-white px-3 text-sm font-medium text-red-600 hover:bg-red-50" @click="askRevoke(row)">Revoke</button>
                <span v-else class="text-slate-400">—</span>
              </template>
            </DataTable>
            <div class="mt-6">
              <h3 class="text-sm font-semibold text-slate-900">Connected guests (incl. idle — no voucher/coin needed)</h3>
              <p class="mt-1 text-sm text-slate-500">Every device seen on the portal, even without a paid session.</p>
              <DataTable class="mt-3" :columns="[{key:'mac',label:'Device'},{key:'ip',label:'IP'},{key:'last_seen',label:'Last seen'},{key:'hits',label:'Hits'}]" :rows="devices" empty="No guests seen yet.">
                <template #cell-last_seen="{ value }">{{ urlDate(value) }}</template>
              </DataTable>
            </div>
          </section>

          <!-- Plans -->
          <section v-if="section === 'plans'" class="space-y-4">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900">Plans</h2>
              <p class="mt-1 text-sm text-slate-500">Time bundles shown on the portal — price in PHP, name auto-generates from minutes.</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
              <h3 class="text-sm font-semibold text-slate-900">{{ planForm.id ? 'Edit plan' : 'Add plan' }}</h3>
              <div class="mt-3 grid gap-3 sm:grid-cols-2">
                <label class="text-sm font-medium text-slate-700">Price (PHP)<input v-model.number="planForm.price" type="number" min="0" placeholder="" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
                <label class="text-sm font-medium text-slate-700">Minutes<input v-model.number="planForm.duration_minutes" type="number" min="1" placeholder="" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
              </div>
              <p class="mt-2 text-xs text-slate-500">Preview: <span class="font-medium text-slate-700">{{ planForm.duration_minutes !== '' && planForm.duration_minutes !== null ? displayForMinutes(planForm.duration_minutes) : '—' }}</span> → {{ planForm.price !== '' && planForm.price !== null ? Number(planForm.price) : '—' }} PHP</p>
              <div class="mt-3 grid gap-3 sm:grid-cols-2">
                <label class="text-sm font-medium text-slate-700">Per-guest down override (Mbps, empty = use global 10)<input v-model="planForm.qos_down_mbps" type="number" min="1" max="1000" placeholder="" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
                <label class="text-sm font-medium text-slate-700">Per-guest up override (Mbps, empty = use global 10)<input v-model="planForm.qos_up_mbps" type="number" min="1" max="1000" placeholder="" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
              </div>
              <p class="mt-1 text-xs text-slate-500">Leave empty to use Network defaults (10/10). Set e.g. 20 for a premium plan.</p>
              <label class="mt-3 flex items-center gap-2 text-sm font-medium text-slate-700"><input v-model="planForm.active" type="checkbox" class="h-5 w-5 rounded border-slate-300 text-blue-600" /> Active on portal</label>
              <div class="mt-4 flex flex-col gap-2 sm:flex-row">
                <button class="inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700" @click="askSavePlan">Save plan</button>
                <button v-if="planForm.id" class="inline-flex min-h-11 items-center justify-center rounded-xl border border-slate-300 bg-white px-5 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="resetPlan">Cancel edit</button>
              </div>
            </div>
            <DataTable :columns="[{key:'price',label:'Price'},{key:'duration_minutes',label:'Minutes'},{key:'display',label:'Display'},{key:'qos',label:'QoS (down/up)'},{key:'actions',label:''}]" :rows="plans.map(p => ({ ...p, display: displayForMinutes(p.duration_minutes), qos: (p.qos_down_mbps || p.qos_up_mbps) ? `${p.qos_down_mbps ?? '—'}/${p.qos_up_mbps ?? '—'} Mbps` : `default` }))" empty="No plans.">
              <template #cell-actions="{ row }">
                <div class="flex gap-2">
                  <button class="inline-flex min-h-9 items-center rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="editPlan(row)">Edit</button>
                  <button class="inline-flex min-h-9 items-center rounded-lg border border-red-200 bg-white px-3 text-sm font-medium text-red-600 hover:bg-red-50" @click="askDeletePlan(row)">Delete</button>
                </div>
              </template>
            </DataTable>
          </section>

          <!-- Transactions -->
          <section v-if="section === 'transactions'" class="space-y-4">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900">Transactions</h2>
              <p class="mt-1 text-sm text-slate-500">All purchases — voucher and coin combined.</p>
            </div>
            <DataTable :columns="[{key:'mac',label:'Device'},{key:'method',label:'Method'},{key:'amount',label:'Amount'},{key:'created_at',label:'When'}]" :rows="transactions" empty="No transactions yet.">
              <template #cell-created_at="{ value }">{{ urlDate(value) }}</template>
            </DataTable>
          </section>

          <!-- Coin events -->
          <section v-if="section === 'coins'" class="space-y-4">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900">Coin events</h2>
              <p class="mt-1 text-sm text-slate-500">Pulses reported by coind.</p>
            </div>
            <DataTable :columns="[{key:'mac',label:'Device'},{key:'delta',label:'Coins'},{key:'created_at',label:'When'}]" :rows="coinEvents" empty="No coin pulses yet.">
              <template #cell-delta="{ value }"><span class="font-mono font-medium" :class="value>0 ? 'text-emerald-700' : 'text-slate-700'">{{ value > 0 ? '+' : '' }}{{ value }}</span></template>
              <template #cell-created_at="{ value }">{{ urlDate(value) }}</template>
            </DataTable>
          </section>

          <!-- Settings -->
          <section v-if="section === 'settings'" class="space-y-4">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 class="text-lg font-bold tracking-tight text-slate-900">Portal settings</h2>
                <p class="mt-1 text-sm text-slate-500">Organized by area — changes appear on the portal immediately after saving.</p>
              </div>
              <button class="inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700" @click="askSettings">Save settings</button>
            </div>

            <div class="grid gap-4 lg:max-w-3xl">
              <!-- Identity -->
              <div class="rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div class="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
                  <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                    <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 5a12 12 0 00-8 4 12 12 0 008 7 12 12 0 008-7 12 12 0 00-8-4z"/><circle cx="12" cy="12" r="2.5"/></svg>
                  </span>
                  <div>
                    <h3 class="text-sm font-semibold text-slate-900">Hotspot identity</h3>
                    <p class="text-xs text-slate-500">Name and welcome copy shown on the captive portal.</p>
                  </div>
                </div>
                <div class="space-y-4 p-5">
                  <label class="block text-sm font-medium text-slate-700">Hotspot name<input v-model="settings.hotspot_name" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" placeholder="Piso WiFi" /></label>
                  <label class="block text-sm font-medium text-slate-700">Terms / welcome message<span class="ml-2 text-xs font-normal text-slate-400">Displayed under the plans</span><textarea v-model="settings.terms" rows="3" class="mt-1.5 w-full rounded-xl border border-slate-300 px-3.5 py-2.5 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" placeholder="Welcome! Choose a plan to start."></textarea></label>
                </div>
              </div>

              <!-- Payments -->
              <div class="rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div class="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
                  <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600">
                    <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="7"/><path d="M12 8v8M9 10h6M9 14h6"/></svg>
                  </span>
                  <div>
                    <h3 class="text-sm font-semibold text-slate-900">Payments & coins</h3>
                    <p class="text-xs text-slate-500">Currency, accepted denominations and countdown.</p>
                  </div>
                </div>
                <div class="space-y-4 p-5">
                  <div class="grid gap-4 sm:grid-cols-2">
                    <label class="block text-sm font-medium text-slate-700">Currency<input v-model="settings.currency" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" placeholder="PHP" /></label>
                    <label class="block text-sm font-medium text-slate-700">Insert coin countdown (seconds, 5–120)<input v-model.number="settings.coin_countdown" type="number" min="5" max="120" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm shadow-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
                  </div>
                  <div>
                    <p class="text-sm font-medium text-slate-700">Accepted coins (PHP)</p>
                    <p class="mt-1 text-xs text-slate-500">Tap to enable/disable — hardware ignores disabled denominations.</p>
                    <div class="mt-2 flex flex-wrap gap-2">
                      <button v-for="c in coinOptions" :key="c" type="button" class="inline-flex min-h-11 items-center gap-1.5 rounded-full px-4 py-2 text-sm font-medium ring-1" :class="isCoinEnabled(c) ? 'bg-slate-900 text-white ring-slate-900' : 'bg-white text-slate-600 ring-slate-300 hover:bg-slate-50'" @click="toggleCoin(c)">{{ c }} PHP <span v-if="isCoinEnabled(c)">✓</span><span v-else>＋</span></button>
                    </div>
                    <label class="mt-3 block">
                      <span class="text-xs font-medium text-slate-600">Raw value (comma-separated)</span>
                      <input v-model="settings.coin_value" placeholder="1,5,10,20" class="mt-1.5 min-h-10 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" />
                    </label>
                  </div>
                </div>
              </div>

              <!-- Session continuity -->
              <div class="rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div class="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
                  <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-50 text-amber-600">
                    <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="7"/><path d="M12 7v3l2 2"/><path d="M8 14l4 0"/></svg>
                  </span>
                  <div class="flex-1">
                    <h3 class="text-sm font-semibold text-slate-900">Session continuity</h3>
                    <p class="text-xs text-slate-500">Freeze time when disconnected or on power loss — auto-resume on reconnect.</p>
                  </div>
                  <label class="relative inline-flex cursor-pointer items-center">
                    <input v-model="sessionPauseEnabled" type="checkbox" class="peer sr-only" />
                    <div class="h-7 w-12 rounded-full bg-slate-200 peer-checked:bg-blue-600 after:absolute after:left-[2px] after:top-[2px] after:h-6 after:w-6 after:rounded-full after:bg-white after:shadow after:transition-all peer-checked:after:translate-x-5"></div>
                  </label>
                </div>
                <div class="p-5">
                  <div class="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p class="text-sm font-medium" :class="sessionPauseEnabled ? 'text-slate-900' : 'text-slate-500'">{{ sessionPauseEnabled ? 'Pause enabled' : 'Pause disabled' }}</p>
                      <p class="mt-1 max-w-md text-xs leading-relaxed text-slate-500">When ON: OPI power interruption pauses all active sessions; AP disconnect (no heartbeat &gt;90 s) pauses that device. Time is frozen and auto-resumed on next portal poll. When OFF: sessions keep counting down even while offline.</p>
                    </div>
                    <span class="inline-flex rounded-full px-2.5 py-1 text-xs font-semibold" :class="sessionPauseEnabled ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'">{{ sessionPauseEnabled ? 'ON' : 'OFF' }}</span>
                  </div>
                  <label class="mt-4 flex items-center gap-2.5 text-sm text-slate-600"><input v-model="sessionPauseEnabled" type="checkbox" class="h-5 w-5 rounded border-slate-300 text-blue-600" /> Enable pause &amp; auto-resume</label>
                </div>
              </div>

              <!-- Banner -->
              <div class="rounded-2xl border border-slate-200 bg-white shadow-sm">
                <div class="flex items-center gap-3 border-b border-slate-100 px-5 py-4">
                  <span class="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-50 text-violet-600">
                    <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="18" height="18" rx="2.5"/><path d="M3 9h18M9 21V9"/></svg>
                  </span>
                  <div>
                    <h3 class="text-sm font-semibold text-slate-900">Portal banner</h3>
                    <p class="text-xs text-slate-500">Top bar that customers see on the portal.</p>
                  </div>
                </div>
                <div class="space-y-4 p-5">
                  <label class="block text-sm font-medium text-slate-700">Banner subtitle<input v-model="settings.banner_subtitle" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" placeholder="Pay as you go internet" /></label>
                  <div class="grid gap-4 sm:grid-cols-2">
                    <label class="block text-sm font-medium text-slate-700">Background color<input v-model="settings.banner_bg" type="color" class="mt-1.5 h-11 w-full rounded-xl border border-slate-300 p-1" /></label>
                    <label class="block text-sm font-medium text-slate-700">Text color<input v-model="settings.banner_fg" type="color" class="mt-1.5 h-11 w-full rounded-xl border border-slate-300 p-1" /></label>
                  </div>
                  <div class="rounded-xl border border-slate-200 bg-slate-50 p-3">
                    <p class="text-xs font-medium text-slate-600">Live preview</p>
                    <div class="mt-2 flex flex-wrap items-center gap-2 rounded-lg px-3 py-2.5 ring-1 ring-black/5" :style="{ backgroundColor: settings.banner_bg || '#1d4ed8', color: settings.banner_fg || '#ffffff' }">
                      <span class="text-sm font-bold">{{ settings.hotspot_name || 'Piso WiFi' }}</span>
                      <span class="text-xs opacity-90">{{ settings.banner_subtitle || 'Pay as you go internet' }}</span>
                    </div>
                  </div>
                </div>
              </div>

              <div class="flex flex-col gap-2 sm:flex-row sm:justify-end">
                <button class="inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700" @click="askSettings">Save settings</button>
              </div>
            </div>
          </section>

          <!-- Network / QoS -->
          <section v-if="section === 'network'" class="max-w-3xl space-y-4">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 class="text-lg font-bold tracking-tight text-slate-900">Network · QoS</h2>
                <p class="mt-1 text-sm text-slate-500">Admin-managed shaping on <span class="font-mono">guest0</span>. All guests share the <span class="font-mono">{{ qos.qos_global_down_mbps }}/{{ qos.qos_global_up_mbps }} Mbps</span> global pool; each guest is isolated to <span class="font-mono">{{ qos.qos_per_guest_down_mbps }}/{{ qos.qos_per_guest_up_mbps }} Mbps</span> (HTB per-IP). Device polls <span class="font-mono">/api/internal/qos-clients</span> every ~10 s.</p>
              </div>
              <button class="inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700" @click="askQos">Save network settings</button>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <label class="flex items-center gap-2.5 text-sm font-medium text-slate-700"><input v-model="qos.qos_enabled" type="checkbox" class="h-5 w-5 rounded border-slate-300 text-blue-600" /> QoS shaping enabled</label>
              <p class="mt-1 text-xs text-slate-500">When off, the device removes all <span class="font-mono">tc</span> limits on next sync.</p>
              <div class="mt-4 grid gap-3 sm:grid-cols-2">
                <label class="text-sm font-medium text-slate-700">Per-guest download (Mbps)<input v-model.number="qos.qos_per_guest_down_mbps" type="number" min="1" max="1000" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
                <label class="text-sm font-medium text-slate-700">Per-guest upload (Mbps)<input v-model.number="qos.qos_per_guest_up_mbps" type="number" min="1" max="1000" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
                <label class="text-sm font-medium text-slate-700">Global download (Mbps) — shared pool<input v-model.number="qos.qos_global_down_mbps" type="number" min="1" max="10000" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
                <label class="text-sm font-medium text-slate-700">Global upload (Mbps) — shared pool<input v-model.number="qos.qos_global_up_mbps" type="number" min="1" max="10000" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
              </div>
              <p class="mt-3 text-xs text-slate-500">Defaults: 10 / 10 per guest, 320 / 320 global — the global HTB parent caps aggregate, each per-IP leaf is isolated (tc u32 dst/src).</p>
              <button class="mt-5 inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700" @click="askQos">Save network settings</button>
            </div>
            <!-- Active shaping -->
            <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div class="flex items-center justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold text-slate-900">Active shaping</h3>
                  <p class="text-xs text-slate-500">Per-IP HTB leaves under the shared global parent. Plan overrides apply per client. <span class="inline-flex items-center gap-1 font-medium text-emerald-600"><span class="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse"></span>Live • auto-refresh 3s</span></p>
                </div>
                <button class="inline-flex min-h-9 items-center rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="pollQosTick">Refresh</button>
              </div>
              <div class="mt-3">
                <DataTable :columns="[{key:'ip',label:'IP'},{key:'mac',label:'MAC'},{key:'down_mbps',label:'Down'},{key:'up_mbps',label:'Up'},{key:'plan_id',label:'Plan'}]" :rows="qosClients" empty="No active shaped clients (no sessions with IP).">
                  <template #cell-down_mbps="{ value }"><span class="font-mono text-xs">{{ value }} Mbps</span></template>
                  <template #cell-up_mbps="{ value }"><span class="font-mono text-xs">{{ value }} Mbps</span></template>
                  <template #cell-plan_id="{ value }"><span class="text-xs text-slate-600">{{ value ?? 'default' }}</span></template>
                </DataTable>
                <p class="mt-2 text-xs text-slate-500">Global pool: <span class="font-mono">{{ qos.qos_global_down_mbps }}/{{ qos.qos_global_up_mbps }} Mbps</span> shared — sum of leaves cannot exceed this. Shown rates are the <span class="font-mono">tc htb ceil</span> per leaf.</p>
              </div>
            </div>
            <!-- Bandwidth history (graphs) -->
            <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold text-slate-900">Bandwidth history</h3>
                  <p class="text-xs text-slate-500">Samples posted by <span class="font-mono">pisowifi-qos</span> via <span class="font-mono">POST /api/internal/bandwidth-report</span> (tc counters). Last {{ qosHistory.length }} samples. <span class="font-medium text-emerald-600">Live • 3s</span></p>
                </div>
                <button class="inline-flex min-h-9 items-center rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="pollQosTick">Refresh</button>
              </div>
              <div v-if="!qosHistory.length" class="mt-3 rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-center text-sm text-slate-500">No samples yet — history appears after the device reports. On-device, <span class="font-mono">qos.sh</span> can POST every 30 s.</div>
              <div v-else class="mt-3 overflow-x-auto">
                <!-- simple bar graph using divs, no extra deps -->
                <div class="flex items-end gap-1" style="height: 84px">
                  <div v-for="s in [...qosHistory].reverse().slice(0, 30)" :key="s.id" class="flex-1 flex flex-col items-center gap-1" :title="`${urlDate(s.recorded_at)} — rx ${s.rx_bytes} tx ${s.tx_bytes}`">
                    <div class="w-full rounded-t bg-blue-600" :style="{ height: Math.max(4, Math.min(64, Math.log10((s.rx_bytes + s.tx_bytes + 1)) * 12)) + 'px' }"></div>
                    <span class="hidden text-[10px] leading-none text-slate-400 sm:block">{{ new Date(s.recorded_at).toLocaleTimeString() }}</span>
                  </div>
                </div>
                <p class="mt-2 text-xs text-slate-500">Raw bytes per sample (log scale). Recent 30 samples.</p>
              </div>
              <DataTable class="mt-3" :columns="[{key:'recorded_at',label:'When'},{key:'mac',label:'MAC'},{key:'ip',label:'IP'},{key:'rx_bytes',label:'RX'},{key:'tx_bytes',label:'TX'}]" :rows="qosHistory.slice(0,20)" empty="No history rows.">
                <template #cell-recorded_at="{ value }">{{ urlDate(value) }}</template>
              </DataTable>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
              <p class="font-semibold text-slate-700">How per-MAC isolation works</p>
              <p class="mt-1 leading-relaxed"><span class="font-mono">guest0</span> root HTB <span class="font-mono">1:1</span> @ {{ qos.qos_global_down_mbps }} Mbps, each IP <span class="font-mono">10.0.0.x</span> gets leaf <span class="font-mono">1:octet</span> @ per-guest (or per-plan) Mbps with <span class="font-mono">u32 dst</span> filter; upload via <span class="font-mono">ifb0</span> <span class="font-mono">2:1</span> @ {{ qos.qos_global_up_mbps }} with <span class="font-mono">u32 src</span>. All leaves share the global parent — true shared pool, not per-guest sum.</p>
            </div>
          </section>

          <!-- Hardware -->
          <section v-if="section === 'hardware'" class="max-w-2xl space-y-4">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900">Hardware</h2>
              <p class="mt-1 text-sm text-slate-500">Physical header pin numbers. Defaults: pulse #3, relay #11.</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="text-sm font-medium text-slate-700">Coin pulse pin<input v-model.number="hardware.coin_pulse_pin" type="number" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
                <label class="text-sm font-medium text-slate-700">Relay pin<input v-model.number="hardware.relay_pin" type="number" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" /></label>
              </div>
              <label class="mt-4 flex items-center gap-2.5 text-sm font-medium text-slate-700"><input v-model="hardware.gpio_enabled" type="checkbox" class="h-5 w-5 rounded border-slate-300 text-blue-600" /> GPIO coin slot enabled</label>
              <label class="mt-2.5 flex items-center gap-2.5 text-sm font-medium text-slate-700"><input v-model="hardware.relay_active" type="checkbox" class="h-5 w-5 rounded border-slate-300 text-blue-600" /> Relay inhibit active</label>
              <button class="mt-5 inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700" @click="askHardware">Save hardware settings</button>
            </div>
            <div class="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <p class="font-semibold">Wiring warning</p>
              <p class="mt-1 leading-relaxed">Never feed 12 V into a GPIO pin. Use a normally-open coinslot with a pull-up/voltage divider so the signal stays at or below 3.3 V, and share ground between the board, coinslot and relay.</p>
            </div>
          </section>

          <!-- Account / Password -->
          <section v-if="section === 'password'" class="max-w-xl space-y-4">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900">Account</h2>
              <p class="mt-1 text-sm text-slate-500">Change your username and/or password. Current password is required for any change.</p>
            </div>
            <div v-if="isDefaultPassword" role="alert" class="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              <span class="font-semibold">You're using the default password</span> — <span class="font-mono">admin@123</span>. Please set a strong password before exposing the console on your LAN.
            </div>
            <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <label class="block text-sm font-medium text-slate-700">Username<input v-model="passwordForm.new_username" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" placeholder="admin" autocomplete="username" />
                <span class="mt-1 block text-xs font-normal text-slate-500">3–32 chars: letters, numbers, dot, dash, underscore. Signed in as <span class="font-medium text-slate-700">{{ username }}</span></span>
              </label>
              <label class="mt-4 block text-sm font-medium text-slate-700">Current password<input v-model="passwordForm.old_password" type="password" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" autocomplete="current-password" /></label>
              <label class="mt-4 block text-sm font-medium text-slate-700">New password (min 6 chars, leave blank to keep)<input v-model="passwordForm.new_password" type="password" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" autocomplete="new-password" /></label>
              <label class="mt-4 block text-sm font-medium text-slate-700">Confirm new password<input v-model="passwordForm.new_password_confirm" type="password" class="mt-1.5 min-h-11 w-full rounded-xl border border-slate-300 px-3.5 text-sm focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20" autocomplete="new-password" />
                <span v-if="passwordForm.new_password && passwordForm.new_password_confirm && passwordForm.new_password !== passwordForm.new_password_confirm" class="mt-1 block text-xs font-medium text-red-600">Passwords do not match</span>
                <span v-else-if="passwordForm.new_password && passwordForm.new_password_confirm && passwordForm.new_password === passwordForm.new_password_confirm" class="mt-1 block text-xs font-medium text-emerald-600">Passwords match</span>
              </label>
              <button class="mt-5 inline-flex min-h-11 items-center justify-center rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:opacity-50" :disabled="!!(passwordForm.new_password && passwordForm.new_password !== passwordForm.new_password_confirm)" @click="askPassword">Save changes</button>
              <p class="mt-2 text-xs text-slate-500">Tip: you can change just the username, just the password, or both at once.</p>
            </div>
          </section>

          <!-- Backup & Restore -->
          <section v-if="section === 'backup'" class="max-w-3xl space-y-4">
            <div>
              <h2 class="text-lg font-bold tracking-tight text-slate-900">Backup &amp; Restore</h2>
              <p class="mt-1 text-sm text-slate-500">Download a JSON backup of all data (settings, plans, vouchers, sessions, transactions, coins, bandwidth) or restore from a previous file. Restoring replaces all current data.</p>
            </div>
            <div v-if="backupStatus" class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ backupStatus }}</div>
            <div v-if="restoreStatus" class="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700">{{ restoreStatus }}</div>
            <div class="grid gap-4 sm:grid-cols-2">
              <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div class="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                  <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 15V3"/><path d="M7 10l5 5 5-5"/><path d="M3 17v2a2 2 0 002 2h14a2 2 0 002-2v-2"/></svg>
                </div>
                <h3 class="mt-3 text-sm font-semibold text-slate-900">Download backup</h3>
                <p class="mt-1 text-xs leading-relaxed text-slate-500">Saves a <span class="font-mono">pisowifi-backup-YYYY-MM-DD.json</span> file with every table. Keep it safe — it contains voucher codes and password hashes.</p>
                <button class="mt-4 inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-slate-800 sm:w-auto" @click="downloadBackup">Download backup</button>
              </div>
              <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
                <div class="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-50 text-amber-600">
                  <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3v12"/><path d="M7 8l5-5 5 5"/><path d="M3 17v2a2 2 0 002 2h14a2 2 0 002-2v-2"/></svg>
                </div>
                <h3 class="mt-3 text-sm font-semibold text-slate-900">Restore from file</h3>
                <p class="mt-1 text-xs leading-relaxed text-slate-500">Pick a backup <span class="font-mono">.json</span> you downloaded. You’ll be asked to confirm — the current DB is replaced atomically.</p>
                <label class="mt-4 block">
                  <span class="sr-only">Choose backup file</span>
                  <input id="restore-file-input" type="file" accept=".json,application/json" class="block w-full text-sm file:mr-3 file:rounded-lg file:border file:border-slate-300 file:bg-white file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-slate-50" @change="onRestoreFilePicked" />
                </label>
                <p v-if="restoreFileName" class="mt-2 text-xs text-slate-600">Selected: <span class="font-mono font-medium">{{ restoreFileName }}</span></p>
                <button class="mt-3 inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-amber-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-amber-700 disabled:opacity-50 sm:w-auto" :disabled="!restoreFileName" @click="askRestore">Restore</button>
                <p class="mt-2 text-xs text-slate-500">If the backup has a different admin password, you’ll need to sign in again with that password.</p>
              </div>
            </div>
            <div class="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <p class="font-semibold">Be careful</p>
              <p class="mt-1 leading-relaxed">Restore wipes the current database first, then inserts the backup. If the backup is corrupt the operation is rolled back. Always download a fresh backup before restoring.</p>
            </div>
          </section>
        </div>
      </main>
    </div>

    <ConfirmDialog
      :open="!!confirm"
      :title="confirm?.title || ''"
      :message="confirm?.message || ''"
      :confirm-label="confirm?.label || 'Confirm'"
      :danger="!!confirm?.danger"
      @confirm="runConfirm"
      @cancel="confirm = null"
    />
  </div>
</template>
