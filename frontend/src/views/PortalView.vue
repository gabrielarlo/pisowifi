<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { get, post, getDevMac, setDevMac } from '../api'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import DataTable from '../components/DataTable.vue'

const config = ref({ hotspot_name: 'Piso WiFi', terms: '', currency: 'PHP', coin_value: '1', coin_countdown: 60, banner_subtitle: 'Pay as you go internet', banner_bg: '#1d4ed8', banner_fg: '#ffffff', plans: [] })
const coins = ref(0)
const balanceMac = ref('')
const session = ref(null)
const voucher = ref('')
const error = ref('')
const now = ref(Date.now())
const confirm = ref(null)
const devMac = ref(getDevMac())
const isDev = import.meta.env.DEV

// Insert coin flow — timeout managed by admin via config.coin_countdown
// Coins are only credited while an explicit Insert Coin claim is active on the backend.
// Without an active claim the slot must ignore pulses (see POST /api/portal/coin-start).
const showCoinPanel = ref(false)
const coinCountdown = ref(10)
// Per-insert session counter — resets on each Insert click to avoid confusion.
// Total balance stays in `coins`; this shows what was dropped in *this* window.
// Remaining time (session) persists separately and is not reset.
const insertedThisSession = ref(0)
let baseCoins = 0
const getCoinTimeout = () => Number(config.value.coin_countdown) || 60
let coinTimer = null
let coinKeepalive = null
function startCountdown() {
  clearInterval(coinTimer)
  coinCountdown.value = getCoinTimeout()
  coinTimer = setInterval(() => {
    coinCountdown.value--
    if (coinCountdown.value <= 0) {
      clearInterval(coinTimer)
      coinTimer = null
      // Auto-close claim when countdown expires — slot becomes inactive
      if (showCoinPanel.value) donePaying()
    }
  }, 1000)
}
function resetCountdown() {
  startCountdown()
}
async function keepCoinClaimAlive() {
  try { await post('/api/portal/coin-start') } catch { /* ignore — panel still shows countdown */ }
}
async function openCoinPanel() {
  baseCoins = Number(coins.value) || 0
  insertedThisSession.value = 0
  showCoinPanel.value = true
  startCountdown()
  await keepCoinClaimAlive()
  clearInterval(coinKeepalive)
  // Heartbeat while panel is open so slot stays enabled until user is done
  coinKeepalive = setInterval(keepCoinClaimAlive, 8000)
}
async function donePaying() {
  showCoinPanel.value = false
  clearInterval(coinTimer)
  coinTimer = null
  clearInterval(coinKeepalive)
  coinKeepalive = null
  try { await post('/api/portal/coin-stop') } catch { /* ignore */ }
}
watch(coins, (n, o) => {
  if (showCoinPanel.value) {
    insertedThisSession.value = Math.max(0, (Number(n) || 0) - baseCoins)
    if (n > (o ?? 0)) resetCountdown()
  }
})

let timers = []
const remaining = computed(() => {
  if (!session.value) return 0
  // Paused sessions report frozen remaining_seconds from backend
  if (session.value.paused) return session.value.remaining_seconds || session.value.paused_remaining || 0
  if (!session.value.expires_at) return 0
  return Math.max(0, Math.ceil((new Date(session.value.expires_at).getTime() - now.value) / 1000))
})
const clock = computed(() => {
  const m = Math.floor(remaining.value / 60)
  const s = remaining.value % 60
  return `${m}:${String(s).padStart(2, '0')}`
})
const isConnected = computed(() => !!session.value?.active && !session.value?.paused && remaining.value > 0)
const isPaused = computed(() => !!session.value?.paused && (session.value?.remaining_seconds || session.value?.paused_remaining || 0) > 0)
const coinValuesDisplay = computed(() => {
  const raw = config.value.coin_value || '1,5,10,20'
  return raw.split(',').map(s => s.trim()).filter(Boolean).join(', ')
})
const isMacError = computed(() => error.value.includes('Cannot determine') || error.value.includes('AP must be in bridge mode'))
const voucherError = ref('')

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
  voucherError.value = ''
  confirm.value = {
    title: `Buy ${plan.name}?`,
    message: `This will use ${plan.coins_required} coin(s) from your balance and start your session immediately.`,
    confirmLabel: 'Buy now',
    run: async () => { await post('/api/portal/purchase', { plan_id: plan.id }); await refreshStatus(); await refreshCoins() },
  }
}
function askRedeem() {
  error.value = ''
  voucherError.value = ''
  const code = voucher.value.trim().toUpperCase()
  if (!code) { voucherError.value = 'Enter a voucher code first.'; return }
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
onUnmounted(() => {
  timers.forEach(clearInterval)
  clearInterval(coinTimer)
  clearInterval(coinKeepalive)
})

const rateColumns = [
  { key: 'name', label: 'Plan' },
  { key: 'duration_minutes', label: 'Duration' },
  { key: 'price', label: 'Price' },
]
</script>

<template>
  <div class="min-h-screen bg-gradient-to-b from-sky-50 via-slate-50 to-slate-100">
    <header :style="{ backgroundColor: config.banner_bg || '#1d4ed8', color: config.banner_fg || '#ffffff' }" class="px-4 py-5 shadow">
      <div class="mx-auto max-w-2xl px-1">
        <h1 class="truncate text-xl font-bold tracking-tight">{{ config.hotspot_name }}</h1>
        <p class="mt-0.5 text-xs opacity-80">{{ config.banner_subtitle || 'Pay as you go internet' }}</p>
      </div>
    </header>

    <main class="mx-auto max-w-2xl space-y-4 px-4 py-6">
      <div v-if="isDev" class="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
        <label for="dev-mac" class="block font-medium">Simulate device (dev only)</label>
        <select id="dev-mac" :value="devMac" class="mt-1 min-h-11 w-full rounded-lg border border-amber-300 bg-white px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400" @change="changeDevMac($event.target.value)">
          <option value="aa:bb:cc:dd:ee:01">Device 1</option>
          <option value="aa:bb:cc:dd:ee:02">Device 2</option>
        </select>
      </div>

      <div v-if="error" role="alert" aria-live="assertive" class="rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">{{ error }}</div>

      <!-- Connection status + remaining time -->
      <section aria-labelledby="connection-heading" class="overflow-hidden rounded-2xl border bg-white shadow-sm" :class="isConnected ? 'border-emerald-200' : isPaused ? 'border-amber-200' : 'border-slate-200'">
        <div class="flex items-center justify-between gap-3 px-5 py-4" :class="isConnected ? 'bg-emerald-50/70' : isPaused ? 'bg-amber-50/70' : 'bg-slate-50'">
          <div class="min-w-0">
            <h2 id="connection-heading" class="flex items-center gap-2 text-sm font-semibold" :class="isConnected ? 'text-emerald-800' : isPaused ? 'text-amber-800' : 'text-slate-700'">
              <span class="inline-flex h-2.5 w-2.5 shrink-0 rounded-full" :class="isConnected ? 'bg-emerald-500' : isPaused ? 'bg-amber-500' : 'bg-slate-400'" aria-hidden="true"></span>
              {{ isConnected ? 'Connected' : isPaused ? 'Paused' : 'Not connected' }}
            </h2>
            <p class="mt-1 truncate text-xs text-slate-500">
              <span v-if="balanceMac">Device {{ balanceMac }}</span>
              <span v-else>Checking device…</span>
              <span v-if="isConnected"> · expires {{ new Date(session.expires_at).toLocaleTimeString() }}</span>
              <span v-else-if="isPaused"> · {{ clock }} remaining — reconnect to resume</span>
            </p>
          </div>
          <button v-if="isConnected" type="button" class="shrink-0 inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-bold text-white shadow-sm hover:bg-emerald-700" @click="window.close(); setTimeout(() => location.href='http://captive.apple.com/hotspot-detect.html', 300)"><svg viewBox="0 0 24 24" class="h-3.5 w-3.5" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 13l4 4L19 7"/></svg> Done</button>
          <span v-else class="shrink-0 rounded-full px-3 py-1 text-xs font-semibold" :class="isPaused ? 'bg-amber-500 text-white' : 'bg-slate-200 text-slate-700'">{{ isPaused ? 'Paused' : 'Idle' }}</span>
        </div>
        <div v-if="isConnected" class="px-5 py-6 text-center">
          <p class="text-xs font-medium uppercase tracking-widest text-slate-500">Remaining time</p>
          <p class="mt-2 text-5xl font-bold tabular-nums tracking-tight text-blue-700" aria-live="polite">{{ clock }}</p>
          <p class="mt-1 text-xs text-slate-500">Time left on this session</p>
          <button type="button" class="mt-5 min-h-11 w-full rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:w-auto" @click="logout">End session</button>
        </div>
        <div v-else-if="isPaused" class="px-5 py-6 text-center">
          <p class="text-xs font-medium uppercase tracking-widest text-amber-600">Session paused</p>
          <p class="mt-2 text-5xl font-bold tabular-nums tracking-tight text-amber-600" aria-live="polite">{{ clock }}</p>
          <p class="mt-1 text-xs text-slate-500">Disconnected from AP or power interruption — time is frozen.</p>
          <p class="mt-1 text-xs text-slate-500">Reconnect to the WiFi and this page will auto-resume.</p>
        </div>
        <div v-else class="px-5 py-5">
          <p class="text-sm text-slate-600">Insert a coin or redeem a voucher to go online.</p>
          <p class="mt-1 text-xs text-slate-500">Your remaining time will appear here once connected.</p>
        </div>
      </section>

      <!-- Insert coin — wider button, counter + countdown only after click -->
      <section aria-labelledby="coin-heading" class="rounded-2xl border-2 border-blue-600 bg-white p-5 shadow-sm">
        <div class="flex items-center justify-between gap-3">
          <h2 id="coin-heading" class="text-sm font-bold text-slate-900">Insert coin</h2>
          <span class="shrink-0 rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">Live</span>
        </div>
        <p class="mt-1 text-xs text-slate-500">Big button — tap to start paying, then drop coins. Counter appears after you tap.</p>
        <p class="mt-1 text-xs font-medium text-slate-600">Accepts: {{ coinValuesDisplay }} PHP coins</p>

        <button v-if="!showCoinPanel" type="button" :disabled="isMacError" class="mt-4 flex min-h-16 w-full items-center justify-center gap-3 rounded-xl bg-blue-600 px-6 py-4 text-base font-bold text-white shadow-sm hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed" @click="openCoinPanel">
          <span class="flex h-8 w-8 items-center justify-center rounded-full bg-white/20" aria-hidden="true">
            <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="8"/><path d="M12 8v8M9 10h6"/></svg>
          </span>
          {{ isMacError ? 'Device not ready' : 'Insert coin' }}
        </button>
        <p v-if="isMacError" class="mt-2 text-center text-xs font-medium text-amber-600">Waiting for device to be detected — reconnect to WiFi or wait for ARP.</p>

        <div v-if="showCoinPanel" class="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4">
          <div class="flex flex-wrap items-baseline justify-between gap-3">
            <p class="text-sm font-semibold text-blue-900">Inserted: <span class="text-2xl font-bold tabular-nums">{{ insertedThisSession }}</span> <span class="text-sm font-medium text-blue-700">coin(s)</span> <span class="ml-2 text-xs font-normal text-blue-700/70">in this insert</span></p>
            <p v-if="balanceMac" class="text-xs text-blue-700/70">{{ balanceMac }}</p>
          </div>
          <p class="mt-1 text-xs text-blue-700/60">Remaining time keeps running — this counter resets to 0 each time you tap Insert.</p>
          <div class="mt-3 flex items-center gap-2">
            <p class="text-xs font-medium text-blue-800">Time to insert next coin:</p>
            <p class="rounded-full bg-white px-3 py-1 text-sm font-bold tabular-nums text-blue-700 ring-1 ring-blue-200" aria-live="polite">{{ coinCountdown }}s</p>
          </div>
          <p class="mt-1 text-xs text-blue-800/70">Countdown resets to {{ getCoinTimeout() }}s every time a coin is detected.</p>
          <button type="button" class="mt-4 min-h-11 w-full rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-2" @click="donePaying">Done Paying</button>
        </div>
        <p v-else class="mt-2 text-center text-xs text-slate-400">Tap the big button above to reveal your coin counter and timer.</p>
      </section>

      <!-- Smaller voucher -->
      <section v-if="!isConnected" aria-labelledby="voucher-heading" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 id="voucher-heading" class="text-sm font-semibold text-slate-900">Have a voucher?</h2>
        <p class="mt-1 text-xs text-slate-500">Smaller, secondary action — use a code instead of coins.</p>
        <form class="mt-3 flex flex-col gap-2 sm:flex-row" @submit.prevent="askRedeem">
          <label for="voucher-code" class="sr-only">Voucher code</label>
          <input id="voucher-code" v-model="voucher" :disabled="isMacError" placeholder="Enter code" autocomplete="off" autocorrect="off" autocapitalize="characters" spellcheck="false" inputmode="text" enterkeyhint="done" aria-describedby="voucher-help voucher-error" class="min-h-11 w-full rounded-xl border border-slate-300 px-3 text-sm uppercase tracking-wide placeholder:normal-case focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed" @keyup.enter="askRedeem" />
          <button type="submit" :disabled="isMacError" class="min-h-11 w-full rounded-xl bg-slate-800 px-4 py-2.5 text-sm font-semibold text-white hover:bg-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-800 focus-visible:ring-offset-2 sm:w-auto sm:px-6 disabled:opacity-50 disabled:cursor-not-allowed">{{ isMacError ? 'Waiting…' : 'Use voucher' }}</button>
        </form>
        <p id="voucher-help" class="mt-2 text-xs text-slate-500">Codes are case-insensitive. One use only.</p>
        <p v-if="voucherError" id="voucher-error" role="alert" class="mt-2 text-sm text-red-600">{{ voucherError }}</p>
      </section>

      <!-- WiFi rates — table at bottom (managed on admin) -->
      <section v-if="!isConnected" aria-labelledby="rates-heading" class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
        <h2 id="rates-heading" class="text-sm font-semibold text-slate-900">WiFi rates</h2>
        <p class="mt-1 text-xs text-slate-500">Managed in Console → Plans. Choose a rate after inserting coins.</p>
        <div v-if="config.plans.length === 0" class="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">No rates configured yet.</div>
        <DataTable
          v-else
          class="mt-4"
          :columns="rateColumns"
          :rows="config.plans.map(p => ({ ...p, priceLabel: `${config.currency} ${p.price}` }))"
          empty="No rates."
        >
          <template #cell-duration_minutes="{ value }">{{ value }} min</template>
          <template #cell-price="{ row }">{{ row.priceLabel }}</template>
        </DataTable>
      </section>

      <!-- Banner -->
      <section aria-label="Hotspot banner" class="overflow-hidden rounded-2xl bg-slate-900 px-5 py-5 text-white shadow-sm">
        <p class="text-xs font-semibold uppercase tracking-widest text-slate-400">You’re at</p>
        <p class="mt-1 truncate text-xl font-bold tracking-tight">{{ config.hotspot_name }}</p>
        <p v-if="config.terms" class="mt-2 text-sm leading-relaxed text-slate-300">{{ config.terms }}</p>
        <p v-else class="mt-2 text-sm text-slate-400">Welcome — enjoy your stay.</p>
      </section>
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
