// Thin wrapper over the FastAPI service. Every JSON response carries the contract
// envelope { code, message, data } — code 0 on success, the HTTP status otherwise —
// so this unwraps `data` and surfaces `message` as a thrown Error. Callers only ever
// deal with data or an exception.
//
// Task T07 swaps this for an axios instance with request and response interceptors
// (attaching the bearer token, redirecting on 401). The function signatures here are
// written to survive that swap unchanged.

const BASE = '/api'

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE}${path}`, options)
  } catch {
    throw new Error('Cannot reach the service. Is the backend running?')
  }

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(body?.message || `Request failed (${response.status})`)
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