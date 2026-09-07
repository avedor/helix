const DEVICE_ID_KEY = 'helix.device_id'

declare global {
  interface Navigator {
    userAgentData?: { platform?: string }
  }
}

export function deviceId(): string {
  if (typeof window === 'undefined') return ''
  let id = window.localStorage.getItem(DEVICE_ID_KEY)
  if (!id) {
    id = typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `web-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`
    window.localStorage.setItem(DEVICE_ID_KEY, id)
  }
  return id
}

export function deviceKind(): string {
  return 'web'
}

function browserName(ua: string): string {
  if (/Edg\//.test(ua)) return 'Edge'
  if (/Firefox\//.test(ua)) return 'Firefox'
  if (/OPR\//.test(ua)) return 'Opera'
  if (/Chrome\//.test(ua)) return 'Chrome'
  if (/Safari\//.test(ua) && !/Chrom(e|ium)/.test(ua)) return 'Safari'
  return 'Browser'
}

export function deviceName(): string {
  if (typeof window === 'undefined') return 'Helix web'
  const os = navigator.userAgentData?.platform || navigator.platform || 'Web'
  return `${browserName(navigator.userAgent)} · ${os}`
}

export function deviceHeaders(): Record<string, string> {
  const id = deviceId()
  if (!id) return {}
  return {
    'X-Helix-Device-Id': id,
    'X-Helix-Device-Name': deviceName(),
    'X-Helix-Device-Kind': deviceKind(),
  }
}