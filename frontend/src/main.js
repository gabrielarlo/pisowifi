import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import HostRoot from './views/HostRoot.vue'
import AdminView from './views/AdminView.vue'
import PortalPreview from './views/PortalPreview.vue'
import { isGuestHost } from './utils/host.js'
import './style.css'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: HostRoot },
    { path: '/console', component: AdminView },
    { path: '/console/preview', component: PortalPreview },
    // Captive-portal checks open arbitrary paths (e.g. /hotspot-detect.html).
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  if (isGuestHost() && to.path.startsWith('/console')) return '/'
})

createApp(App).use(router).mount('#app')
