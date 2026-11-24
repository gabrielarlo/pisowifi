<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  tone: { type: String, default: 'blue' },
})
const tones = {
  blue: 'bg-blue-50 text-blue-700',
  green: 'bg-emerald-50 text-emerald-700',
  amber: 'bg-amber-50 text-amber-700',
  slate: 'bg-slate-100 text-slate-700',
}
</script>

<template>
  <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
    <div class="text-xs font-medium uppercase tracking-wide text-slate-500">{{ label }}</div>
    <div class="mt-2 inline-flex rounded-lg px-2 py-1 text-2xl font-bold" :class="tones[tone] || tones.blue">{{ value }}</div>
  </div>
</template>
