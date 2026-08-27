// ── Auditor API client (motor de auditoria: anexos → Excel → RIT) ──
// O backend-auditor NÃO tem autenticação (MVP lado a lado).
// Dev: fala com o proxy /api → localhost:8000/api.
// Prod: defina VITE_AUDITOR_URL (ex.: https://.../api).
const BASE = import.meta.env.VITE_AUDITOR_URL || '/api'

export const auditorApi = {
  base: BASE,

  // GET JSON
  async getJson(path) {
    const res = await fetch(`${BASE}${path}`)
    if (!res.ok) throw new Error(await extractError(res))
    return res.json()
  },

  // POST FormData → JSON
  async postForm(path, formData) {
    const res = await fetch(`${BASE}${path}`, { method: 'POST', body: formData })
    if (!res.ok) throw new Error(await extractError(res))
    return res.json()
  },

  // POST FormData → resposta bruta (blob / html / headers)
  async postFormRaw(path, formData) {
    const res = await fetch(`${BASE}${path}`, { method: 'POST', body: formData })
    if (!res.ok) throw new Error(await extractError(res))
    return res
  },
}

async function extractError(res) {
  try {
    const ct = res.headers.get('content-type') || ''
    if (ct.includes('application/json')) {
      const data = await res.json()
      return data.detail || JSON.stringify(data)
    }
    const txt = await res.text()
    return txt || res.statusText
  } catch {
    return res.statusText || 'Erro na requisição'
  }
}
