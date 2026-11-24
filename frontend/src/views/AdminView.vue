<script setup>
import { onMounted, reactive, ref } from 'vue'
import { get, post, put, del } from '../api'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import StatCard from '../components/StatCard.vue'
import DataTable from '../components/DataTable.vue'

const token = ref(localStorage.getItem('piso-token') || '')
const username = ref(localStorage.getItem('piso-user') || 'admin')
const loginForm = reactive({ username: 'admin', password: '' })
const loginError = ref('')
const section = ref('overview')
const error = ref('')
const notice = ref('')
const confirm = ref(null)
const stats = ref({})
const vouchers = ref([])
const sessions = ref([])
const plans = ref([])
const transactions = ref([])
const coinEvents = ref([])
const settings = reactive({ hotspot_name: '', terms: '', currency: '', coin_value: '' })
const hardware = reactive({ coin_pulse_pin: 3, relay_pin: 11, gpio_enabled: false, relay_active: false })
const voucherForm = reactive({ count: 1, duration_minutes: 30, price: 10 })
const generatedCodes = ref([])
const planForm = reactive({ id: null, name: '', duration_minutes: 30, coins_required: 1, price: 10, active: true })
const passwordForm = reactive({ old_password: '', new_password: '' })

const sections = [
  ['overview', 'Overview'], ['vouchers', 'Vouchers'], ['sessions', 'Sessions'],
  ['plans', 'Plans'], ['transactions', 'Transactions'], ['coins', 'Coin events'],
  ['settings', 'Settings'], ['hardware', 'Hardware'], ['password', 'Password'],
]

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
  localStorage.removeItem('piso-token')
  localStorage.removeItem('piso-user')
}
async function load() {
  error.value = ''
  try {
    if (section.value === 'overview') stats.value = await get('/api/admin/overview')
    if (section.value === 'vouchers') vouchers.value = await get('/api/admin/vouchers')
    if (section.value === 'sessions') sessions.value = await get('/api/admin/sessions')
    if (section.value === 'plans') plans.value = await get('/api/admin/plans')
    if (section.value === 'transactions') transactions.value = await get('/api/admin/transactions')
    if (section.value === 'coins') coinEvents.value = await get('/api/admin/coins')
    if (section.value === 'settings') Object.assign(settings, await get('/api/admin/settings'))
    if (section.value === 'hardware') Object.assign(hardware, await get('/api/admin/hardware'))
  } catch (e) { error.value = e.message }
}
function choose(id) { section.value = id; notice.value = ''; load() }

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

function askGenerate() {
  ask('Generate vouchers?', `${voucherForm.count} code(s) for ${voucherForm.duration_minutes} minutes at ${voucherForm.price} each.`, 'Generate', async () => {
    const r = await post('/api/admin/vouchers/generate', voucherForm)
    generatedCodes.value = r.codes
  })
}
function askDeleteVoucher(row) {
  ask('Delete voucher?', `Code ${row.code} will be removed and can no longer be redeemed.`, 'Delete', () => del(`/api/admin/vouchers/${row.id}`), true)
}
function askRevoke(row) {
  ask('Revoke session?', `Internet access for ${row.mac} will stop immediately.`, 'Revoke', () => post(`/api/admin/sessions/${row.id}/revoke`), true)
}
function editPlan(row) { Object.assign(planForm, row) }
function resetPlan() { Object.assign(planForm, { id: null, name: '', duration_minutes: 30, coins_required: 1, price: 10, active: true }) }
function askSavePlan() {
  const body = { name: planForm.name, duration_minutes: Number(planForm.duration_minutes), coins_required: Number(planForm.coins_required), price: Number(planForm.price), active: !!planForm.active }
  ask(planForm.id ? 'Update plan?' : 'Add plan?', `${body.name} — ${body.duration_minutes} min for ${body.coins_required} coin(s).`, 'Save', async () => {
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
function askPassword() {
  ask('Change password?', 'Your new password will be used for all future logins.', 'Change password', async () => {
    await post('/api/auth/change-password', passwordForm)
    passwordForm.old_password = ''
    passwordForm.new_password = ''
    notice.value = 'Password changed.'
  })
}

onMounted(() => { if (token.value) load() })
</script>

<template>
  <div class="min-h-screen bg-slate-100">
    <!-- Login -->
    <div v-if="!token" class="flex min-h-screen items-center justify-center px-4">
      <form class="w-full max-w-sm rounded-2xl bg-white p-6 shadow-sm" @submit.prevent="login">
        <h1 class="text-2xl font-bold text-slate-900">Admin console</h1>
        <p class="mt-1 text-sm text-slate-500">Sign in to configure your hotspot.</p>
        <div v-if="loginError" role="alert" class="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{{ loginError }}</div>
        <label class="mt-4 block text-sm font-medium text-slate-700">Username</label>
        <input v-model="loginForm.username" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" autocomplete="username" />
        <label class="mt-3 block text-sm font-medium text-slate-700">Password</label>
        <input v-model="loginForm.password" type="password" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" autocomplete="current-password" />
        <button class="mt-5 min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700">Sign in</button>
        <router-link to="/" class="mt-3 block text-center text-sm text-blue-600 hover:underline">Back to portal</router-link>
      </form>
    </div>

    <!-- Console -->
    <div v-else>
      <header class="bg-slate-900 px-4 py-4 text-white">
        <div class="mx-auto flex max-w-6xl items-center justify-between gap-3">
          <div class="min-w-0">
            <h1 class="truncate text-lg font-bold">Piso WiFi · Admin</h1>
            <p class="text-xs text-slate-400">Signed in as {{ username }}</p>
          </div>
          <div class="flex shrink-0 gap-2">
            <router-link to="/console/preview" class="min-h-11 rounded-lg border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800">Preview</router-link>
            <router-link to="/" class="min-h-11 rounded-lg border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800">Portal</router-link>
            <button class="min-h-11 rounded-lg border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800" @click="logout">Sign out</button>
          </div>
        </div>
      </header>

      <div class="mx-auto max-w-6xl px-4 py-4">
        <div v-if="error" role="alert" class="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">{{ error }}</div>
        <div v-if="notice" class="mb-4 rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ notice }}</div>

        <nav class="mb-5 flex flex-wrap gap-2" aria-label="Admin sections">
          <button v-for="[id, label] in sections" :key="id" class="min-h-11 rounded-lg px-3 py-2 text-sm font-medium" :class="section === id ? 'bg-blue-600 text-white' : 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50'" @click="choose(id)">{{ label }}</button>
        </nav>

        <!-- Overview -->
        <section v-if="section === 'overview'" class="space-y-4">
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Active clients" :value="stats.active_clients ?? '—'" tone="blue" />
            <StatCard label="Revenue today" :value="stats.revenue_today ?? '—'" tone="green" />
            <StatCard label="Vouchers used" :value="stats.vouchers_used ?? '—'" tone="amber" />
            <StatCard label="Coins outstanding" :value="stats.coins_outstanding ?? '—'" tone="slate" />
          </div>
          <p class="text-sm text-slate-500">Configure plans, vouchers and hardware from the tabs above.</p>
        </section>

        <!-- Vouchers -->
        <section v-if="section === 'vouchers'" class="space-y-4">
          <div class="rounded-xl border border-slate-200 bg-white p-4">
            <h2 class="font-semibold text-slate-800">Generate vouchers</h2>
            <div class="mt-3 grid gap-3 sm:grid-cols-3">
              <label class="text-sm text-slate-600">Count<input v-model.number="voucherForm.count" type="number" min="1" max="100" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
              <label class="text-sm text-slate-600">Minutes<input v-model.number="voucherForm.duration_minutes" type="number" min="1" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
              <label class="text-sm text-slate-600">Price<input v-model.number="voucherForm.price" type="number" min="0" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
            </div>
            <button class="mt-4 min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 sm:w-auto" @click="askGenerate">Generate</button>
            <div v-if="generatedCodes.length" class="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
              <p class="font-medium">New codes</p>
              <p class="mt-1 break-all font-mono">{{ generatedCodes.join(', ') }}</p>
            </div>
          </div>
          <DataTable :columns="[{key:'code',label:'Code'},{key:'duration_minutes',label:'Minutes'},{key:'status',label:'Status'},{key:'created_at',label:'Created'},{key:'actions',label:''}]" :rows="vouchers" empty="No vouchers generated yet.">
            <template #cell-created_at="{ value }">{{ urlDate(value) }}</template>
            <template #cell-actions="{ row }">
              <button v-if="row.status === 'unused'" class="min-h-11 text-sm font-medium text-red-600 hover:underline" @click="askDeleteVoucher(row)">Delete</button>
              <span v-else class="text-slate-400">—</span>
            </template>
          </DataTable>
        </section>

        <!-- Sessions -->
        <section v-if="section === 'sessions'">
          <DataTable :columns="[{key:'mac',label:'Device'},{key:'source',label:'Source'},{key:'expires_at',label:'Expires'},{key:'active',label:'Active'},{key:'actions',label:''}]" :rows="sessions" empty="No sessions yet.">
            <template #cell-expires_at="{ value }">{{ urlDate(value) }}</template>
            <template #cell-active="{ value }">{{ value ? 'Yes' : 'No' }}</template>
            <template #cell-actions="{ row }">
              <button v-if="row.active" class="min-h-11 text-sm font-medium text-red-600 hover:underline" @click="askRevoke(row)">Revoke</button>
              <span v-else class="text-slate-400">—</span>
            </template>
          </DataTable>
        </section>

        <!-- Plans -->
        <section v-if="section === 'plans'" class="space-y-4">
          <div class="rounded-xl border border-slate-200 bg-white p-4">
            <h2 class="font-semibold text-slate-800">{{ planForm.id ? 'Edit plan' : 'Add plan' }}</h2>
            <div class="mt-3 grid gap-3 sm:grid-cols-2">
              <label class="text-sm text-slate-600">Name<input v-model="planForm.name" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
              <label class="text-sm text-slate-600">Minutes<input v-model.number="planForm.duration_minutes" type="number" min="1" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
              <label class="text-sm text-slate-600">Coins<input v-model.number="planForm.coins_required" type="number" min="1" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
              <label class="text-sm text-slate-600">Price<input v-model.number="planForm.price" type="number" min="0" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
            </div>
            <label class="mt-3 flex items-center gap-2 text-sm text-slate-600"><input v-model="planForm.active" type="checkbox" class="h-5 w-5" /> Active on portal</label>
            <div class="mt-4 flex flex-col gap-2 sm:flex-row">
              <button class="min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 sm:w-auto" @click="askSavePlan">Save plan</button>
              <button v-if="planForm.id" class="min-h-11 w-full rounded-lg border border-slate-300 px-4 py-2 text-sm sm:w-auto" @click="resetPlan">Cancel edit</button>
            </div>
          </div>
          <DataTable :columns="[{key:'name',label:'Name'},{key:'duration_minutes',label:'Minutes'},{key:'coins_required',label:'Coins'},{key:'price',label:'Price'},{key:'actions',label:''}]" :rows="plans" empty="No plans.">
            <template #cell-actions="{ row }">
              <div class="flex gap-3">
                <button class="min-h-11 text-sm font-medium text-blue-600 hover:underline" @click="editPlan(row)">Edit</button>
                <button class="min-h-11 text-sm font-medium text-red-600 hover:underline" @click="askDeletePlan(row)">Delete</button>
              </div>
            </template>
          </DataTable>
        </section>

        <!-- Transactions -->
        <section v-if="section === 'transactions'">
          <DataTable :columns="[{key:'mac',label:'Device'},{key:'method',label:'Method'},{key:'amount',label:'Amount'},{key:'created_at',label:'When'}]" :rows="transactions" empty="No transactions yet.">
            <template #cell-created_at="{ value }">{{ urlDate(value) }}</template>
          </DataTable>
        </section>

        <!-- Coin events -->
        <section v-if="section === 'coins'">
          <DataTable :columns="[{key:'mac',label:'Device'},{key:'delta',label:'Coins'},{key:'created_at',label:'When'}]" :rows="coinEvents" empty="No coin pulses yet.">
            <template #cell-delta="{ value }">{{ value > 0 ? '+' : '' }}{{ value }}</template>
            <template #cell-created_at="{ value }">{{ urlDate(value) }}</template>
          </DataTable>
        </section>

        <!-- Settings -->
        <section v-if="section === 'settings'" class="max-w-2xl rounded-xl border border-slate-200 bg-white p-5">
          <h2 class="font-semibold text-slate-800">Portal settings</h2>
          <label class="mt-4 block text-sm text-slate-600">Hotspot name<input v-model="settings.hotspot_name" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
          <label class="mt-3 block text-sm text-slate-600">Terms / welcome message<textarea v-model="settings.terms" rows="3" class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"></textarea></label>
          <div class="mt-3 grid gap-3 sm:grid-cols-2">
            <label class="text-sm text-slate-600">Currency<input v-model="settings.currency" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
            <label class="text-sm text-slate-600">Coin value<input v-model="settings.coin_value" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
          </div>
          <button class="mt-5 min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 sm:w-auto" @click="askSettings">Save settings</button>
        </section>

        <!-- Hardware -->
        <section v-if="section === 'hardware'" class="max-w-2xl space-y-4">
          <div class="rounded-xl border border-slate-200 bg-white p-5">
            <h2 class="font-semibold text-slate-800">Hardware settings</h2>
            <p class="mt-1 text-sm text-slate-500">Physical header pin numbers. Defaults: coin pulse #3 (PA12), relay #11 (PA1).</p>
            <div class="mt-4 grid gap-3 sm:grid-cols-2">
              <label class="text-sm text-slate-600">Coin pulse pin (3, 5 or 11)<input v-model.number="hardware.coin_pulse_pin" type="number" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
              <label class="text-sm text-slate-600">Relay pin (3, 5 or 11)<input v-model.number="hardware.relay_pin" type="number" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
            </div>
            <label class="mt-3 flex items-center gap-2 text-sm text-slate-600"><input v-model="hardware.gpio_enabled" type="checkbox" class="h-5 w-5" /> GPIO coin slot enabled</label>
            <label class="mt-2 flex items-center gap-2 text-sm text-slate-600"><input v-model="hardware.relay_active" type="checkbox" class="h-5 w-5" /> Relay inhibit active</label>
            <button class="mt-5 min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 sm:w-auto" @click="askHardware">Save hardware settings</button>
          </div>
          <div class="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-800">
            <p class="font-semibold">Wiring warning</p>
            <p class="mt-1">Never feed 12 V into a GPIO pin. Use a normally-open coinslot with a pull-up/voltage divider so the signal stays at or below 3.3 V, and share ground between the board, coinslot and relay.</p>
          </div>
        </section>

        <!-- Password -->
        <section v-if="section === 'password'" class="max-w-2xl rounded-xl border border-slate-200 bg-white p-5">
          <h2 class="font-semibold text-slate-800">Change admin password</h2>
          <label class="mt-4 block text-sm text-slate-600">Current password<input v-model="passwordForm.old_password" type="password" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
          <label class="mt-3 block text-sm text-slate-600">New password (min 6 chars)<input v-model="passwordForm.new_password" type="password" class="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3" /></label>
          <button class="mt-5 min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 sm:w-auto" @click="askPassword">Change password</button>
        </section>
      </div>
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
