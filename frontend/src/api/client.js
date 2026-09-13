import { accessToken, signOut } from '../session.js'
import { sms as mockSms, face as mockFace } from './mock-auth.js'

const BASE = '/api'

// One switch left, and it covers exactly one thing: `/api/auth/sms/*` and
// `/api/auth/face/*` are specified in `T41短信登录与T42人脸识别-任务详设.md` and
// nobody has written them, so there is nothing to call. Turning this off would
// break those screens rather than fix them.
//
// The patients mock is gone. `GET /api/patients` is real and matches the
// contract, so a second code path through the list was a second thing to keep
// correct for no demonstrated benefit — and the one it was hiding was a real
// bug: the mock treated a blank date as "no filter" while the service rejects
// one with 422. Judging by the demo rather than by the doc, real wins.
export const USE_MOCK_AUTH = true

// T07 签收标准 2 and 场景 S2 both hinge on telling these apart. The server's four
// 401s are distinguishable, but its `message` is written for developers and the
// repo rule is that it never reaches a reader — so the copy below is the client's
// own. "You signed out elsewhere" and "your token aged out" call for different
// next steps, so they cannot collapse into one string.
const SESSION_LOST = [
  [/invalidated by logout/i, 'You were signed out. Sign in again to continue.'],
  [/expired/i, 'Your session has expired. Sign in again.'],
  [/unavailable or disabled/i, 'This account is no longer active. Contact an administrator.'],
  [/missing access token/i, 'Sign in to continue.'],
]

function sessionLostCopy(message) {
  for (const [pattern, copy] of SESSION_LOST) if (pattern.test(message)) return copy
  return 'Your session is no longer valid. Sign in again.'
}

// Set by the router, which owns navigation. Kept as a callback rather than an
// import because the router already imports this module.
let sessionLostHandler = null
export function setSessionLostHandler(handler) {
  sessionLostHandler = handler
}

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
    const error = new Error(body?.message || `Request failed (${response.status})`)
    error.status = response.status
    // §3.4 restores the resend countdown from a rejected send's `retry_after`,
    // and §4.3.1's attempt counter rides along the same way. Keeping `data` on
    // the error is what makes both possible without parsing the message text.
    error.data = body?.data ?? null

    // A 401 on a request that carried a token means the session ended. A 401 on
    // one that did not is the sign-in endpoints rejecting a credential, and those
    // belong inline on the form — tearing the session down there would wipe the
    // very message the reader needs.
    if (response.status === 401 && token) {
      signOut()
      sessionLostHandler?.({ kind: 'session-lost', message: sessionLostCopy(error.message) })
    }
    // 403 is a permission refusal, not an identity one: keep the session and send
    // the reader to the page that explains which permission is missing.
    if (response.status === 403) {
      sessionLostHandler?.({ kind: 'forbidden' })
    }
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

// multipart/form-data: the browser sets the boundary, so Content-Type is left off
// on purpose. §4.3.1 posts the enrolment and the verification photos this way.
function form(fields) {
  const body = new FormData()
  Object.entries(fields).forEach(([key, value]) => body.append(key, value))
  return { method: 'POST', body }
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
  // T15. `symptom_tags` is plural and repeatable on purpose: the contract says a
  // client sending the singular `symptom_tag` gets no filtering at all rather
  // than an error, so a typo here would look like "no patients match".
  async list({
    name = '',
    patientNo = '',
    symptomTags = [],
    department = '',
    admittedFrom = '',
    admittedTo = '',
    page = 1,
    size = 20,
  } = {}) {
    // Only the conditions that were actually given. An unused optional filter
    // must be left out, not sent blank: `admitted_from=` is not a date, so the
    // server rejects the entire request with 422 and the page shows "could not
    // load" while nothing is actually wrong. `admitted_from` and `admitted_to`
    // are the two that cannot survive a blank, but they are the two that are
    // blank by default, so this broke every load rather than an edge case.
    const params = new URLSearchParams({ page: String(page), size: String(size) })
    if (name) params.set('name', name)
    if (patientNo) params.set('patient_no', patientNo)
    if (department) params.set('department', department)
    if (admittedFrom) params.set('admitted_from', admittedFrom)
    if (admittedTo) params.set('admitted_to', admittedTo)
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
  signup(details) { return request('/auth/signup', json(details)) },
  verifySignup(ticket, code) { return request('/auth/signup/verify', json({ ticket, code })) },
  login: (username, password) => request('/auth/login', json({ username, password })),
  sendCode: (ticket) => request('/auth/send-code', json({ ticket })),
  verifyCode: (ticket, code) => request('/auth/verify-code', json({ ticket, code })),
  me: () => request('/me'),
  logout: () => request('/auth/logout', json({})),

  // T05's own face route, which the server implements today with `match_face()`
  // returning True. T42 replaces it with `/auth/face/verify` below; this one and
  // backend/app/face_login.py should be deleted together once that lands.
  faceLogin: (username, photo) => request('/auth/face/login', json({ username, photo })),

  // --- T41 (§3.3.1) -------------------------------------------------------
  // The send response carries `cooldown` / `mock` / `masked_phone` and nothing
  // else — §1.2 calls handing the code back to the caller the signature of a fake
  // implementation. Reading it is the audit page's job (§3.5 判据②).
  smsSend: (phone, scene = 'login') => (USE_MOCK_AUTH
    ? mockSms.send({ phone, scene })
    : request('/auth/sms/send', json({ phone, scene }))),

  smsVerify: (phone, code, scene = 'login') => (USE_MOCK_AUTH
    ? mockSms.verify({ phone, code, scene })
    : request('/auth/sms/verify', json({ phone, code, scene }))),

  // --- T42 (§4.3.1) -------------------------------------------------------
  // `actingUsername` is read by the mock only; the real request carries the image
  // and lets the bearer token identify the subject.
  faceEnroll: (image, actingUsername) => (USE_MOCK_AUTH
    ? mockFace.enroll(image, actingUsername)
    : request('/auth/face/enroll', form({ image }))),

  faceVerify: (username, image) => (USE_MOCK_AUTH
    ? mockFace.verify(username, image)
    : request('/auth/face/verify', form({ username, image }))),
}

// §4.3.1 ③ — the enrolment thumbnail. Deliberately not `request()`: the response
// is image bytes, not the JSON envelope, and an `<img src>` cannot carry the
// bearer header, so the bytes are fetched by hand and handed back as an object
// URL. Every failure mode (401 without a token, 403 for someone else's ref, 404
// for an unknown or malformed ref) therefore has to be handled here.
export async function faceImageUrl(ref, actingUsername) {
  if (USE_MOCK_AUTH) return mockFace.image(ref, actingUsername)
  const token = accessToken()
  const response = await fetch(`${BASE}/auth/face/image/${encodeURIComponent(ref)}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!response.ok) {
    const error = new Error(
      response.status === 403
        ? 'Not allowed to view this face image.'
        : 'Face image is not available.',
    )
    error.status = response.status
    throw error
  }
  return URL.createObjectURL(await response.blob())
}
