// Thin wrapper over the FastAPI service. The backend answers success payloads
// as { data: ... } and errors as { error: { message: ... } }; this unwraps the
// first and surfaces the second as a thrown Error, so callers only ever deal
// with data or an exception.
//
// Task T07 swaps this for an axios instance with request and response
// interceptors (attaching the bearer token, redirecting on 401). The function
// signatures here are written to survive that swap unchanged.

const BASE = '/api'

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, options)
  } catch {
    throw new Error('Cannot reach the service. Is the backend running?')
  }

  const body = response.status === 204 ? null : await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(body?.error?.message || `Request failed (${response.status})`)
  }
  return body
}

function json(body) {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export const health = {
  async ready() {
    return request('/health/ready')
  },
}

export const departments = {
  async list() {
    const body = await request('/departments')
    return body.data
  },
}

export const patients = {
  async list({ q = '', offset = 0, limit = 20 } = {}) {
    const params = new URLSearchParams({ q, offset: String(offset), limit: String(limit) })
    return request(`/patients?${params}`)
  },

  async get(id) {
    const body = await request(`/patients/${id}`)
    return body.data
  },

  async create(payload) {
    const body = await request('/patients', json(payload))
    return body.data
  },

  async remove(id) {
    return request(`/patients/${id}`, { method: 'DELETE' })
  },
}
