const DEV_MAC_KEY = 'piso-dev-mac'

export function getDevMac() {
  return import.meta.env.DEV ? (localStorage.getItem(DEV_MAC_KEY) || '') : ''
}

export function setDevMac(mac) {
  if (import.meta.env.DEV) localStorage.setItem(DEV_MAC_KEY, mac)
}

function headers(extra = {}) {
  const h = { 'Content-Type': 'application/json', ...extra }
  const token = localStorage.getItem('piso-token')
  if (token) h.Authorization = `Bearer ${token}`
  const devMac = getDevMac()
  if (devMac) h['X-Dev-Mac'] = devMac
  return h
}

export async function api(path, options = {}) {
  const res = await fetch(path, { ...options, headers: headers(options.headers) })
  let data
  try { data = await res.json() } catch { data = {} }
  if (!res.ok) {
    const message = typeof data.detail === 'string'
      ? data.detail
      : Array.isArray(data.detail)
        ? data.detail.map(d => d.msg).join(', ')
        : `Request failed (${res.status})`
    const error = new Error(message)
    error.status = res.status
    throw error
  }
  return data
}

export const get = path => api(path)
export const post = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body ?? {}) })
export const put = (path, body) => api(path, { method: 'PUT', body: JSON.stringify(body ?? {}) })
export const del = path => api(path, { method: 'DELETE' })
