<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { get, post, getDevMac, setDevMac } from '../api'
import ConfirmDialog from '../components/ConfirmDialog.vue'

const config = ref({ hotspot_name: 'Piso WiFi', terms: '', currency: 'PHP', coin_value: '1', plans: [] })
const coins = ref(0)
const balanceMac = ref('')
const session = ref(null)
const voucher = ref('')
const error = ref('')
const now = ref(Date.now())
const confirm = ref(null)
const devMac = ref(getDevMac())
const isDev = import.meta.env.DEV

let timers = []
const remaining = computed(() => {
  if (!session.value?.expires_at) return 0
  return Math.max(0, Math.ceil((new Date(session.value.expires_at).getTime() - now.value) / 1000))
})
const clock = computed(() => {
  const m = Math.floor(remaining.value / 60)
  const s = remaining.value % 60
  return `${m}:${String(s).padStart(2, '0')}`
})

async function refreshConfig() {
  try { config.value = await get('/api/portal/config') } catch (e) { error.value = e.message }
}
async function refreshStatus() {
  try { session.value = (await get('/api/portal/status')).session } catch (e) { error.value = e.message }
}
async function refreshCoins() {
  try {
    const r = await get('/api/portal/coins')
    coins.value = r.coins
    balanceMac.value = r.mac
  } catch (e) { error.value = e.message }
}

function askBuy(plan) {
  error.value = ''
  confirm.value = {
    title: `Buy ${plan.name}?`,
    message: `This will use ${plan.coins_required} coin(s) from your balance and start your session immediately.`,
    confirmLabel: 'Buy now',
    run: async () => { await post('/api/portal/purchase', { plan_id: plan.id }); await refreshStatus(); await refreshCoins() },
  }
}
function askRedeem() {
  error.value = ''
  const code = voucher.value.trim().toUpperCase()
  if (!code) { error.value = 'Enter a voucher code first.'; return }
  confirm.value = {
    title: `Redeem ${code}?`,
    message: 'This voucher will be used immediately to start your session.',
    confirmLabel: 'Redeem',
    run: async () => { await post('/api/portal/redeem', { code }); voucher.value = ''; await refreshStatus() },
  }
}
async function runConfirm() {
  const c = confirm.value
  confirm.value = null
  if (!c) return
  try { await c.run() } catch (e) { error.value = e.message }
}
async function logout() {
  error.value = ''
  try { await post('/api/portal/logout'); await refreshStatus() } catch (e) { error.value = e.message }
}
function changeDevMac(value) {
  devMac.value = value
  setDevMac(value)
  refreshStatus(); refreshCoins()
}

onMounted(() => {
  refreshConfig(); refreshStatus(); refreshCoins()
  timers.push(setInterval(() => { now.value = Date.now() }, 1000))
  timers.push(setInterval(refreshCoins, 5000))
  timers.push(setInterval(refreshStatus, 30000))
})
onUnmounted(() => timers.forEach(clearInterval))
</script>

<template>
  <div class="min-h-screen bg-gradient-to-b from-sky-50 to-slate-100">
    <header class="bg-blue-700 px-4 py-5 text-white shadow">
      <div class="mx-auto flex max-w-2xl items-center justify-between gap-3">
        <div class="min-w-0">
          <h1 class="truncate text-xl font-bold">{{ config.hotspot_name }}</h1>
          <p class="text-xs text-blue-100">Pay as you go internet</p>
        </div>
        <router-link to="/console" class="min-h-11 shrink-0 rounded-lg border border-white/40 px-3 py-2 text-sm font-medium hover:bg-white/10">Console</router-link>
      </div>
    </header>

    <main class="mx-auto max-w-2xl space-y-4 px-4 py-6">
      <div v-if="isDev" class="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
        <label class="block font-medium">Simulate device (dev only)</label>
        <select :value="devMac" class="mt-1 min-h-11 w-full rounded border-amber-300 bg-white px-2 text-sm" @change="changeDevMac($event.target.value)">
          <option value="aa:bb:cc:dd:ee:01">Device 1</option>
          <option value="aa:bb:cc:dd:ee:02">Device 2</option>
        </select>
      </div>

      <div v-if="error" role="alert" class="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">{{ error }}</div>

      <section v-if="session?.active" class="rounded-2xl bg-white p-6 text-center shadow-sm">
        <p class="text-sm text-slate-500">Your session is active</p>
        <p class="mt-2 text-5xl font-bold tabular-nums text-blue-700">{{ clock }}</p>
        <p class="mt-1 text-xs text-slate-500">Time remaining · connected as {{ balanceMac }}</p>
        <button class="mt-5 min-h-11 w-full rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 sm:w-auto" @click="logout">End session</button>
      </section>

      <section class="rounded-2xl bg-white p-5 shadow-sm">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="text-xs font-medium uppercase tracking-wide text-slate-500">Your coin balance</p>
            <p class="mt-1 text-3xl font-bold text-slate-900">{{ coins }} <span class="text-base font-medium text-slate-500">coin(s)</span></p>
          </div>
          <div class="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">Live</div>
        </div>
        <p class="mt-2 text-xs text-slate-500">Insert a coin at the slot to add credit. The counter updates automatically.</p>
      </section>

      <section v-if="!session?.active">
        <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">Choose your time</h2>
        <div class="grid gap-3 sm:grid-cols-2">
          <div v-for="plan in config.plans" :key="plan.id" class="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 class="text-lg font-bold text-slate-900">{{ plan.name }}</h3>
            <p class="mt-1 text-sm text-slate-500">{{ plan.duration_minutes }} minutes of internet</p>
            <p class="mt-3 text-sm font-semibold text-blue-700">{{ plan.coins_required }} coin(s) <span class="font-normal text-slate-400">· {{ config.currency }} {{ plan.price }}</span></p>
            <button class="mt-4 min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50" :disabled="coins < plan.coins_required" @click="askBuy(plan)">
              {{ coins < plan.coins_required ? 'Not enough coins' : 'Buy now' }}
            </button>
          </div>
        </div>
      </section>

      <section v-if="!session?.active" class="rounded-2xl bg-white p-5 shadow-sm">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-600">Have a voucher?</h2>
        <div class="mt-3 flex flex-col gap-2 sm:flex-row">
          <input v-model="voucher" placeholder="Enter code" class="min-h-11 w-full rounded-lg border border-slate-300 px-3 text-sm uppercase" @keyup.enter="askRedeem" />
          <button class="min-h-11 w-full rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-900 sm:w-auto" @click="askRedeem">Redeem</button>
        </div>
      </section>

      <p class="px-2 text-center text-xs text-slate-500">{{ config.terms }}</p>
    </main>

    <ConfirmDialog
      :open="!!confirm"
      :title="confirm?.title || ''"
      :message="confirm?.message || ''"
      :confirm-label="confirm?.confirmLabel || 'Confirm'"
      @confirm="runConfirm"
      @cancel="confirm = null"
    />
  </div>
</template>
