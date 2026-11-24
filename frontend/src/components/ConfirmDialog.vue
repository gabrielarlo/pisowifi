<script setup>
defineProps({
  open: Boolean,
  title: { type: String, default: 'Please confirm' },
  message: { type: String, default: '' },
  confirmLabel: { type: String, default: 'Confirm' },
  danger: Boolean,
})
const emit = defineEmits(['confirm', 'cancel'])
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4" @click.self="emit('cancel')">
      <div class="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl" role="dialog" aria-modal="true">
        <h2 class="text-lg font-semibold text-slate-900">{{ title }}</h2>
        <p v-if="message" class="mt-2 text-sm text-slate-600">{{ message }}</p>
        <div class="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-end">
          <button class="min-h-11 w-full rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 sm:w-auto" @click="emit('cancel')">Cancel</button>
          <button
            class="min-h-11 w-full rounded-lg px-4 py-2 text-sm font-semibold text-white sm:w-auto"
            :class="danger ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'"
            @click="emit('confirm')"
          >{{ confirmLabel }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
