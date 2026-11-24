export function isGuestHost() {
  const h = window.location.hostname.toLowerCase()
  return h === 'captive.apple.com' || h === '10.0.0.1'
}

export function isAdminHost() {
  return window.location.hostname === '192.168.100.27'
}
