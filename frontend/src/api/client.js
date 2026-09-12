import { accessToken, signOut } from '../session.js'

const BASE = '/api'

async function request(path, options = {}) {
  const token = accessToken()
  options.headers = { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) }
  let response
  try {
    response = await fetch(`${BASE}${path}`, options)
  } catch {
    throw new Error('Cannot reach the service. Is the backend running?')
  }

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    if (response.status === 401 && token) {
      signOut()
      window.location.assign('/login')
    }
    const error = new Error(body?.message || `Request failed (${response.status})`)
    error.status = response.status
    throw error
  }
  return body?.data
}

function send(method, body) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
}

function json(body) {
  return send('POST', body)
}

export const health = {
  async ready() {
    // /api/health is T03's endpoint and answers with the dependency report itself,
    // not the { code, message, data } envelope.
    const response = await fetch(`${BASE}/health/ready`)
    return response.json()
  },
}

export const departments = {
  async list() {
    return request('/departments')
  },
}

export const allergens = {
  async list() {
    return request('/allergens')
  },
}

export const patients = {
  async list({ name = '', patientNo = '', symptomTags = [], page = 1, size = 20 } = {}) {
    const params = new URLSearchParams({
      name,
      patient_no: patientNo,
      page: String(page),
      size: String(size),
    })
    symptomTags.forEach((tag) => params.append('symptom_tags', tag))
    return request(`/patients?${params}`)
  },

  async get(patientNo) {
    return request(`/patients/${encodeURIComponent(patientNo)}`)
  },

  async create(payload) {
    return request('/patients', json(payload))
  },

  async remove(patientNo) {
    return request(`/patients/${encodeURIComponent(patientNo)}`, { method: 'DELETE' })
  },

  allergies: {
    async list(patientNo) {
      return request(`/patients/${encodeURIComponent(patientNo)}/allergies`)
    },

    async create(patientNo, payload) {
      return request(`/patients/${encodeURIComponent(patientNo)}/allergies`, json(payload))
    },

    async update(id, payload) {
      return request(`/allergies/${id}`, send('PATCH', payload))
    },

    async remove(id) {
      return request(`/allergies/${id}`, { method: 'DELETE' })
    },
  },
}

export const authentication = {
  login: (username, password) => request('/auth/login', json({ username, password })),
  sendCode: (ticket) => request('/auth/send-code', json({ ticket })),
  verifyCode: (ticket, code) => request('/auth/verify-code', json({ ticket, code })),
  me: () => request('/me'),
  logout: () => request('/auth/logout', json({})),
  passkeyOptions: (kind) => request(`/auth/passkeys/${kind}/options`, json({})),
  passkeyVerify: (kind, ticket, credential) => request(`/auth/passkeys/${kind}/verify`, json({ ticket, credential })),
}
