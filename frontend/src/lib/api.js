// ── Conciliador API client (login, prefeituras, conciliações RGF/RREO) ──
// Dev: fala com o proxy /conc → localhost:8001.
// Prod: defina VITE_CONCILIADOR_URL com a URL absoluta do backend.
const BASE = import.meta.env.VITE_CONCILIADOR_URL || '/conc'

const TOKEN_KEY = 'kora_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

function authHeaders(extra = {}) {
  const token = getToken()
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: authHeaders(options.headers),
  })

  if (res.status === 401) {
    clearToken()
    if (!window.location.pathname.startsWith('/login')) {
      window.location.href = '/login'
    }
    throw new Error('Sessão expirada')
  }

  return res
}

export const api = {
  base: BASE,

  get: (path) => request(path),

  post: (path, body) =>
    request(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  put: (path, body) =>
    request(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  patch: (path, body) =>
    request(path, {
      method: 'PATCH',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    }),

  delete: (path) => request(path, { method: 'DELETE' }),

  // FormData (upload): sem Content-Type, o browser define o boundary
  upload: (path, formData) =>
    request(path, { method: 'POST', body: formData }),
}

// Baixa uma resposta binária (blob) como arquivo
export async function downloadBlob(path, filename) {
  const res = await api.get(path)
  if (!res.ok) throw new Error('Falha no download')
  const blob = await res.blob()
  triggerDownload(blob, filename)
}

export function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
