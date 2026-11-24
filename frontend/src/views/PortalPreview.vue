<script setup>
import { computed, ref } from 'vue'
import { getDevMac, setDevMac } from '../api'

const presets = [
  { id: 'phone', label: 'Phone', width: 390, height: 844 },
  { id: 'tablet', label: 'Tablet', width: 768, height: 1024 },
  { id: 'desktop', label: 'Desktop', width: 1200, height: 900 },
]
const preset = ref(presets[0])
const refreshKey = ref(0)
const devMac = ref(getDevMac())
const isDev = import.meta.env.DEV
const portalUrl = import.meta.env.VITE_PORTAL_URL || (isDev ? '/' : '/preview-portal/')
const src = computed(() => portalUrl)

function changeMac(value) {
  devMac.value = value
  setDevMac(value)
  refreshKey.value++
}
</script>

<template>
  <div class="min-h-screen bg-slate-100">
    <header class="bg-slate-900 px-4 py-4 text-white">
      <div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
        <div class="min-w-0">
          <h1 class="truncate text-lg font-bold">Portal preview</h1>
          <p class="text-xs text-slate-400">Live view of the guest captive portal</p>
        </div>
        <router-link to="/console" class="min-h-11 rounded-lg border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800">Back to console</router-link>
      </div>
    </header>

    <main class="mx-auto max-w-6xl space-y-4 px-4 py-5">
      <div class="flex flex-wrap gap-2" aria-label="Viewport presets">
        <button
          v-for="p in presets" :key="p.id"
          class="min-h-11 rounded-lg px-3 py-2 text-sm font-medium"
          :class="preset.id === p.id ? 'bg-blue-600 text-white' : 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50'"
          @click="preset = p"
        >{{ p.label }}</button>
        <button class="min-h-11 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="refreshKey++">Refresh</button>
      </div>

      <div v-if="isDev" class="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
        <label class="block font-medium">Simulate device (dev only)</label>
        <select :value="devMac" class="mt-1 min-h-11 w-full rounded border-amber-300 bg-white px-2 text-sm" @change="changeMac($event.target.value)">
          <option value="aa:bb:cc:dd:ee:01">Device 1</option>
          <option value="aa:bb:cc:dd:ee:02">Device 2</option>
        </select>
      </div>

      <div class="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
        <div class="mb-3 flex items-center justify-between gap-2 text-xs text-slate-500">
          <span class="truncate">{{ preset.label }} · {{ preset.width }}×{{ preset.height }}</span>
          <span class="shrink-0">{{ src }}</span>
        </div>
        <div class="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <iframe
            :key="refreshKey"
            :src="src"
            title="Captive portal preview"
            class="block border-0"
            :style="{ width: 'min(' + preset.width + 'px, 100%)', height: preset.height + 'px' }"
          />
        </div>
      </div>
      <p class="text-xs text-slate-500">On the device this is served through the console's own origin, so no direct route to 10.0.0.1 is needed.</p>
    </main>
  </div>
</template>
