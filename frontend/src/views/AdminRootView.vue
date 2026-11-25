<script setup>
import { computed, onMounted, ref } from 'vue'
import { get } from '../api'
import { ADMIN_HOST } from '../utils/host.js'
import StatCard from '../components/StatCard.vue'

const stats = ref(null)
const error = ref('')
const loading = ref(false)
const updatedAt = ref('')
const token = ref(localStorage.getItem('piso-token') || '')
const user = ref(localStorage.getItem('piso-user') || '')

const hostLabel = computed(() => {
  try {
    const p = new URLSearchParams(window.location.search).get('host')
    if (p) return p
    return window.location.hostname || ADMIN_HOST
  } catch { return ADMIN_HOST }
})

function formatCurrency(v) {
  if (v == null || v === '—') return '—'
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString() : String(v)
}

async function load() {
  if (!token.value) return
  loading.value = true
  error.value = ''
  try {
    stats.value = await get('/api/admin/overview')
    updatedAt.value = new Date().toLocaleString()
  } catch (e) {
    if (e.status === 401) {
      stats.value = null
      error.value = 'Session expired — sign in again at /console.'
    } else error.value = e.message || 'Could not load status.'
  } finally {
    loading.value = false
  }
}

function signOut() {
  token.value = ''
  user.value = ''
  stats.value = null
  updatedAt.value = ''
  localStorage.removeItem('piso-token')
  localStorage.removeItem('piso-user')
}

onMounted(load)
</script>

<template>
  <div class="min-h-screen bg-slate-100">
    <header class="bg-slate-900 px-4 py-4 text-white">
      <div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
        <div class="flex min-w-0 items-center gap-3">
          <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/10 ring-1 ring-white/15" aria-hidden="true">
            <svg viewBox="0 0 24 24" class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l7 4v5c0 4-3 7-7 8-4-1-7-4-7-8V7l7-4z" /><path d="M9 12l2 2 4-4" /></svg>
          </div>
          <div class="min-w-0">
            <h1 class="truncate text-[15px] font-bold tracking-tight sm:text-lg">Piso WiFi · Admin</h1>
            <p class="flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
              <span class="inline-flex items-center rounded-full bg-white/10 px-2 py-0.5 font-mono text-[11px] text-slate-200 ring-1 ring-white/15">{{ hostLabel }}</span>
              <span class="hidden sm:inline">· read-only status</span>
              <span v-if="token && user" class="hidden sm:inline">· {{ user }}</span>
            </p>
          </div>
        </div>
        <div class="flex w-full shrink-0 items-center gap-2 sm:w-auto">
          <button v-if="token" class="min-h-11 rounded-lg border border-white/20 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-white/10" @click="signOut">Sign out</button>
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-6xl px-4 py-6">
      <div v-if="error" role="alert" class="mb-4 flex flex-col gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <p class="text-sm text-red-700">{{ error }}</p>
        <button v-if="token" class="min-h-11 shrink-0 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50" @click="load">Retry</button>
      </div>

      <!-- Unauthenticated -->
      <div v-if="!token" class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div class="border-b border-slate-100 bg-slate-50 px-6 py-4">
          <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">Admin network</p>
          <h2 class="mt-1 text-lg font-bold text-slate-900">Sign in to view system status</h2>
        </div>
        <div class="p-6 text-center">
          <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-900 text-white">
            <svg viewBox="0 0 24 24" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="11" width="18" height="10" rx="2" /><path d="M8 11V8a4 4 0 018 0v3" /><circle cx="12" cy="16" r="1.2" /></svg>
          </div>
          <h3 class="mt-4 text-sm font-semibold text-slate-900">Admin access only</h3>
          <p class="mx-auto mt-1.5 max-w-sm text-sm leading-relaxed text-slate-500">This page shows a live, read-only snapshot of the hotspot. Full controls — plans, vouchers, sessions and settings — live inside the console and are reachable only from this admin network.</p>
        </div>
      </div>

      <!-- Authenticated -->
      <div v-else class="space-y-4">
        <div class="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p class="text-xs font-semibold uppercase tracking-widest text-slate-500">System overview</p>
            <h2 class="mt-1 text-xl font-bold tracking-tight text-slate-900">Health at a glance</h2>
            <p class="mt-1 text-sm text-slate-500">Read-only. For changes, open the console — this page never mutates state.</p>
          </div>
          <div class="flex w-full items-center gap-2 sm:w-auto">
            <span v-if="updatedAt" class="hidden text-xs text-slate-500 sm:inline">Updated {{ updatedAt }}</span>
            <button class="flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50 sm:flex-none" :disabled="loading" @click="load">
              <svg v-if="loading" class="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" class="opacity-25"/><path d="M12 2a10 10 0 0110 10" stroke="currentColor" stroke-width="3" stroke-linecap="round" class="opacity-75"/></svg>
              <span>{{ loading ? 'Refreshing…' : 'Refresh' }}</span>
            </button>
          </div>
        </div>
        <p v-if="updatedAt" class="text-xs text-slate-500 sm:hidden">Updated {{ updatedAt }}</p>

        <!-- Skeleton -->
        <div v-if="loading && !stats" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div v-for="i in 4" :key="i" class="animate-pulse rounded-xl border border-slate-200 bg-white p-4">
            <div class="h-3 w-20 rounded bg-slate-200"></div>
            <div class="mt-4 h-8 w-24 rounded-lg bg-slate-200"></div>
          </div>
        </div>

        <div v-else class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="System status — active clients" :value="stats?.active_clients ?? '—'" tone="blue" />
        </div>

        <div class="grid gap-3 lg:grid-cols-5">
          <div class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm lg:col-span-3">
            <h3 class="text-sm font-semibold text-slate-900">Inside the console</h3>
            <p class="mt-1 text-sm leading-relaxed text-slate-500">Manage plans, generate vouchers, inspect sessions and transactions, change portal copy, and tune coin-slot hardware. Every mutating action asks for confirmation.</p>
            <ul class="mt-4 grid gap-2 text-sm text-slate-700 sm:grid-cols-2">
              <li class="flex gap-2"><span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600"></span><span>Plans & pricing</span></li>
              <li class="flex gap-2"><span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600"></span><span>Vouchers & codes</span></li>
              <li class="flex gap-2"><span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600"></span><span>Active sessions & revocation</span></li>
              <li class="flex gap-2"><span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-blue-600"></span><span>Portal & hardware settings</span></li>
            </ul>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-900 p-5 text-slate-100 lg:col-span-2">
            <h3 class="text-sm font-semibold text-white">About this page</h3>
            <p class="mt-2 text-sm leading-relaxed text-slate-300">You are on <span class="font-mono font-medium text-white">/</span> served only from <span class="font-mono">{{ hostLabel }}</span>. It renders the same status the console shows, but without any write controls — ideal for a quick health check or a wall display.</p>
            <p class="mt-3 text-xs leading-relaxed text-slate-400">Guest hosts (<span class="font-mono">10.0.0.1</span>, <span class="font-mono">captive.apple.com</span>) never see this view; they are served the captive portal instead.</p>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
