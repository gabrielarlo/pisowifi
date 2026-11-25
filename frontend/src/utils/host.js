function hostParam() {
  // Dev-only override for preview/testing — never trust query param in prod
  if (!import.meta.env.DEV) return ''
  try {
    const q = new URLSearchParams(window.location.search).get('host')?.toLowerCase() || ''
    if (q) return q
    const ls = localStorage.getItem('piso-force-host')?.toLowerCase() || ''
    if (ls) return ls
    return ''
  } catch { return '' }
}

export function isGuestHost() {
  const p = hostParam()
  if (p) return p === 'captive.apple.com' || p === '10.0.0.1'
  const h = window.location.hostname.toLowerCase()
  return h === 'captive.apple.com' || h === '10.0.0.1'
}

export const ADMIN_HOST = '192.168.100.27'

export function isAdminHost() {
  const p = hostParam()
  if (p) return p === ADMIN_HOST
  return window.location.hostname.toLowerCase() === ADMIN_HOST
}
