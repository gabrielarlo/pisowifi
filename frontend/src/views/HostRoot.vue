<script setup>
import { computed } from 'vue'
import PortalView from './PortalView.vue'
import AdminRootView from './AdminRootView.vue'
import { isAdminHost } from '../utils/host.js'

const admin = computed(() => isAdminHost())
</script>

<template>
  <AdminRootView v-if="admin" />
  <PortalView v-else />
</template>
