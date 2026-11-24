<script setup>
defineProps({
  columns: { type: Array, required: true }, // [{ key, label }]
  rows: { type: Array, required: true },
  empty: { type: String, default: 'Nothing here yet.' },
})
</script>

<template>
  <div>
    <!-- Cards on phones -->
    <div class="space-y-3 md:hidden">
      <div v-if="!rows.length" class="rounded-xl border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500">{{ empty }}</div>
      <div v-for="(row, i) in rows" :key="row.id ?? i" class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div v-for="col in columns" :key="col.key" class="flex min-w-0 items-start justify-between gap-3 border-b border-slate-100 py-1.5 last:border-0">
          <span class="shrink-0 text-xs font-medium text-slate-500">{{ col.label }}</span>
          <span class="min-w-0 truncate text-right text-sm text-slate-800">
            <slot :name="'cell-' + col.key" :row="row" :value="row[col.key]">{{ row[col.key] ?? '—' }}</slot>
          </span>
        </div>
      </div>
    </div>

    <!-- Table on desktop -->
    <div class="hidden overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm md:block">
      <table class="w-full text-left text-sm">
        <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th v-for="col in columns" :key="col.key" class="px-4 py-3 font-medium">{{ col.label }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-if="!rows.length"><td :colspan="columns.length" class="px-4 py-8 text-center text-slate-500">{{ empty }}</td></tr>
          <tr v-for="(row, i) in rows" :key="row.id ?? i" class="hover:bg-slate-50">
            <td v-for="col in columns" :key="col.key" class="max-w-56 truncate px-4 py-3 text-slate-800">
              <slot :name="'cell-' + col.key" :row="row" :value="row[col.key]">{{ row[col.key] ?? '—' }}</slot>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
