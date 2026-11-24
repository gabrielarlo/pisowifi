<script setup>
import { onMounted, ref } from 'vue'
import { get } from '../api'
import StatCard from '../components/StatCard.vue'

const stats = ref(null)
const error = ref('')
const token = ref(localStorage.getItem('piso-token') || '')

async function load() {
  if (!token.value) return
  try {
    stats.value = await get('/api/admin/overview')
  } catch (e) {
    if (e.status === 401) stats.value = null
    else error.value = e.message
  }
}

onMounted(load)
</script>

<template>
  <div class="min-h-screen bg-slate-100">
    <header class="bg-slate-900 px-4 py-4 text-white">
      <div class="mx-auto flex max-w-6xl items-center justify-between gap-3">
        <div class="min-w-0">
          <h1 class="truncate text-lg font-bold">Piso WiFi · Admin</h1>
          <p class="text-xs text-slate-400">192.168.100.27 · system status</p>
        </div>
        <button v-if="token" class="min-h-11 rounded-lg border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800" @click="token=''; localStorage.removeItem('piso-token'); localStorage.removeItem('piso-user'); stats=null">Sign out</button>
      </div>
    </header>

    <main class="mx-auto max-w-6xl px-4 py-6">
      <div v-if="error" role="alert" class="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">{{ error }}</div>

      <div v-if="!token" class="rounded-xl border border-slate-200 bg-white p-6 text-center">
        <p class="text-sm font-medium text-slate-700">Admin access only</p>
        <p class="mt-1 text-sm text-slate-500">Sign in at <span class="font-mono font-semibold">/console</span> to view system status.</p>
      </div>

      <div v-else class="space-y-4">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="System status — active clients" :value="stats?.active_clients ?? '—'" tone="blue" />
        </div>
        <p class="text-sm text-slate-500">Full controls are available at <span class="font-mono">/console</span> (admin network only).</p>
      </div>
    </main>
  </div>
</template>
