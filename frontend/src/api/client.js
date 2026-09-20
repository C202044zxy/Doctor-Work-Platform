import { isScreenRefusal } from '../access.js'
import { accessToken, signOut } from '../session.js'
import { filenameFromDisposition } from './csv.js'
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
    // 403 is not an identity failure, so the session stays. Only the refusal that
    // names a missing permission replaces the screen; any other 403 is thrown, and
    // the caller shows it inline -- a senior who picks the wrong department has to
    // read "you cannot write patients in another department" on the form, not lose
    // the page they were working on.
    if (isScreenRefusal(response.status, error.message)) {
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

// T12 签收标准 2. Deliberately not `request()`: that one does `await response.json()`,
// and the export answers with a CSV file — so a rejected export would be parsed as
// JSON, found empty, and saved as a zero-byte `.csv`. The backend must return the file
// raw rather than in the envelope, which means every failure mode has to be handled
// here, including the one that looks like success: a 200 whose body is not a CSV.
async function download(path, params) {
  const token = accessToken()
  let response
  try {
    response = await fetch(`${BASE}${path}?${params}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
  } catch {
    throw new Error('Cannot reach the service. Is the backend running?')
  }

  if (!response.ok) {
    // The failure is JSON even though the success is not, so the reason still has to
    // be read as JSON.
    const body = await response.json().catch(() => null)
    const error = new Error(body?.message || `Export failed (${response.status})`)
    error.status = response.status
    // Same split as `request()`: a 401 that carried a token means the session ended,
    // and a 403 is a permission refusal that should keep the session and go explain
    // which permission is missing.
    if (response.status === 401 && token) {
      signOut()
      sessionLostHandler?.({ kind: 'session-lost', message: sessionLostCopy(error.message) })
    }
    if (response.status === 403) sessionLostHandler?.({ kind: 'forbidden' })
    throw error
  }

  // A 200 is not enough. Without this check, anything that answers 200 with the JSON
  // envelope — a proxy, a path that resolved somewhere else — would write an empty
  // file named `audit.csv`, and the export would look like it worked.
  const type = response.headers.get('content-type') ?? ''
  if (!type.startsWith('text/csv')) {
    throw new Error('The export answered with something that is not a CSV file.')
  }

  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  // The server owns the name because criterion 2 wants it to carry the time range; a
  // name assembled here could only be a second, worse guess at the same thing.
  link.download =
    filenameFromDisposition(response.headers.get('content-disposition')) ?? 'audit.csv'
  link.click()
  URL.revokeObjectURL(url)
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

// M5. The consultation module: its state machine, the materials its participants
// share, and the report that archives to the patient record.
//
// Everything goes through `request()` except the two calls whose answers are not
// the JSON envelope -- a file and an HTML sheet. Those are below, and each
// repeats the 401/403 handling `request()` does, because they cannot use it.
export const meetings = {
  async list({ status = '', patientNo = '', page = 1, size = 20 } = {}) {
    const params = new URLSearchParams({ page: String(page), size: String(size) })
    // An unused filter is left out rather than sent blank, for the reason
    // `patients.list` spells out: the server validates the ones it receives.
    if (status) params.set('status', status)
    if (patientNo) params.set('patient_no', patientNo)
    return request(`/meetings?${params}`)
  },

  async get(id) {
    return request(`/meetings/${id}`)
  },

  async create(payload) {
    return request('/meetings', json(payload))
  },

  async accept(id) { return request(`/meetings/${id}/accept`, json({})) },
  async decline(id) { return request(`/meetings/${id}/decline`, json({})) },
  async start(id) { return request(`/meetings/${id}/start`, json({})) },
  async complete(id) { return request(`/meetings/${id}/complete`, json({})) },

  // The invite picker's directory. `/api/users` exists in the contract but is
  // administrator-only, so it cannot feed a junior's picker (T30 S1 has a junior
  // initiate the consultation). This returns identity and department only.
  async doctors({ q = '', department = '', size = 50 } = {}) {
    const params = new URLSearchParams({ size: String(size) })
    if (q) params.set('q', q)
    if (department) params.set('department', department)
    return request(`/meetings/doctors?${params}`)
  },

  async materials(id) {
    return request(`/meetings/${id}/materials`)
  },

  async uploadMaterial(id, file) {
    // `form()` leaves Content-Type off on purpose so the browser can set the
    // multipart boundary.
    return request(`/meetings/${id}/materials`, form({ file }))
  },

  async report(id, version) {
    return request(`/meetings/${id}/report${version ? `?version=${version}` : ''}`)
  },

  async saveReport(id, payload) {
    return request(`/meetings/${id}/report`, json(payload))
  },
}

// The two M5 answers that are not the envelope. `request()` would `await
// response.json()` on them and report a parse failure that is not there, so the
// authorised fetch is repeated here -- including the 401 that ends a session and
// the 403 that is a permission refusal, which is the same split `download()` makes
// for the audit CSV.
async function fetchAuthorised(path) {
  const token = accessToken()
  let response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
  } catch {
    throw new Error('Cannot reach the service. Is the backend running?')
  }
  if (!response.ok) {
    // The failure is JSON even though the success is not.
    const body = await response.json().catch(() => null)
    const error = new Error(body?.message || `Request failed (${response.status})`)
    error.status = response.status
    if (response.status === 401 && token) {
      signOut()
      sessionLostHandler?.({ kind: 'session-lost', message: sessionLostCopy(error.message) })
    }
    throw error
  }
  return response
}

// T31. The server keeps the original filename -- it is the last place the Chinese
// name still exists intact -- so it is read back out of `Content-Disposition`
// rather than guessed from the numeric id in the URL.
export async function downloadMaterial(materialId) {
  const response = await fetchAuthorised(`/materials/${materialId}/download`)
  const name =
    filenameFromDisposition(response.headers.get('content-disposition')) ??
    `material-${materialId}`
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

// T32. The printable sheet is HTML rendered by the backend, so it is fetched with
// the token and written into a fresh window: neither `window.open(href)` nor an
// `<a href>` can carry an Authorization header, and the route is participants-only.
export async function openReportSheet(meetingId, version) {
  const response = await fetchAuthorised(
    `/meetings/${meetingId}/report/print${version ? `?version=${version}` : ''}`,
  )
  const html = await response.text()
  const sheet = window.open('', '_blank')
  if (!sheet) throw new Error('The print window was blocked. Allow pop-ups for this site.')
  sheet.document.write(html)
  sheet.document.close()
  sheet.focus()
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
    gender = '',
    admittedFrom = '',
    admittedTo = '',
    birthFrom = '',
    birthTo = '',
    allergenCodes = [],
    allergySeverity = [],
    phone = '',
    idCard = '',
    groupId = null,
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
    // A blank `gender` would be a 422 rather than "no filter": the server tells the
    // two apart by the parameter being absent, which is why none of these are sent
    // empty.
    if (gender) params.set('gender', gender)
    if (birthFrom) params.set('birth_from', birthFrom)
    if (birthTo) params.set('birth_to', birthTo)
    symptomTags.forEach((tag) => params.append('symptom_tags', tag))
    // Repeatable, so any of several codes matches. The local names are plural for
    // that reason; `allergen` and `allergy_severity` are the names on the wire.
    allergenCodes.forEach((code) => params.append('allergen', code))
    allergySeverity.forEach((severity) => params.append('allergy_severity', severity))
    // Exact matches against the blind index kept beside the ciphertext, so the whole
    // number is what finds a patient and a prefix is not a hit.
    if (phone) params.set('phone', phone)
    if (idCard) params.set('id_card', idCard)
    // 0 is a legal id, so this one is compared against null instead of truthiness.
    if (groupId !== null && groupId !== undefined && groupId !== '') {
      params.set('group_id', String(groupId))
    }
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

// T17's group filter needs the groups to filter by. The management screen (create,
// rename, members) is not built, so this is the one read the list uses; the server
// answers with the caller's own department only, which is why the options and the
// filter agree without the client checking anything.
export const patientGroups = {
  async list() {
    return request('/patient-groups')
  },
}

// One builder for the list and the export, because criterion 2's "the CSV agrees with
// the list" is only true if both ask the same question — two builders would agree on
// the day they were written and drift after.
//
// An unused optional filter is left out rather than sent blank, for the reason
// `patients.list` spells out: `from=` is not a date-time, so the server rejects the
// entire request with 422 and the page reports a failure that is not there. `from` and
// `to` are the two that cannot survive a blank, and they are the two that are blank by
// default.
function auditParams(filters, { paged }) {
  const params = new URLSearchParams()
  if (paged) {
    params.set('page', String(filters.page ?? 1))
    params.set('size', String(filters.size ?? 20))
  }
  if (filters.userId !== null && filters.userId !== undefined && filters.userId !== '') {
    params.set('user_id', String(filters.userId))
  }
  if (filters.action) params.set('action', filters.action)
  if (filters.objectType) params.set('object_type', filters.objectType)
  if (filters.from) params.set('from', filters.from)
  if (filters.to) params.set('to', filters.to)
  return params
}

// T12. Admin-only on the server. The client's copy of that rule is `MODULE_ROLES.audit`
// in `access.js`, and it is only the menu — scenario S2 checks that the API refuses a
// senior even when the menu is bypassed.
export const audit = {
  async list(filters = {}) {
    return request(`/audit-logs?${auditParams(filters, { paged: true })}`)
  },

  // The same conditions without pagination: the file covers everything the filter
  // matched rather than the page that happens to be on screen.
  async exportCsv(filters = {}) {
    return download('/audit-logs/export', auditParams(filters, { paged: false }))
  },
}

// M6. Vitals, health plans, reminder rules and their log, assessments.
//
// Every call here is real: the module has a full backend, so there is no mock
// path and no switch to fall back to. An unused filter is left out rather than
// sent blank, for the reason `patients.list` spells out -- `from=` is not a
// date, and the server rejects the whole request with 422 rather than ignoring it.
export const vitals = {
  // `sign_type` and the two instants are optional here; the trend endpoint below
  // requires all three, which is why they are separate builders.
  async list(patientNo, { signType = '', from = '', to = '', page = 1, size = 20 } = {}) {
    const params = new URLSearchParams({ page: String(page), size: String(size) })
    if (signType) params.set('sign_type', signType)
    if (from) params.set('from', from)
    if (to) params.set('to', to)
    return request(`/patients/${encodeURIComponent(patientNo)}/vitals?${params}`)
  },

  // `from` and `to` are dates, not instants: the server treats `to` as the whole
  // day, so a caller does not have to work out 23:59 itself.
  async trend(patientNo, { signType, from, to }) {
    const params = new URLSearchParams({ sign_type: signType, from, to })
    return request(`/patients/${encodeURIComponent(patientNo)}/vitals/trend?${params}`)
  },

  async create(patientNo, payload) {
    return request(`/patients/${encodeURIComponent(patientNo)}/vitals`, json(payload))
  },
}

export const healthPlans = {
  async list({ patientNo = '', page = 1, size = 20 } = {}) {
    const params = new URLSearchParams({ page: String(page), size: String(size) })
    if (patientNo) params.set('patient_no', patientNo)
    return request(`/health-plans?${params}`)
  },

  async get(id) {
    return request(`/health-plans/${id}`)
  },

  async create(payload) {
    return request('/health-plans', json(payload))
  },

  // The body is the full write shape, `patient_no` included: the contract gives
  // this route no partial-update schema, so a status change resends the plan.
  async update(id, payload) {
    return request(`/health-plans/${id}`, send('PATCH', payload))
  },
}

export const reminderRules = {
  async list(patientNo = '') {
    return request(`/reminder-rules${patientNo ? `?patient_no=${encodeURIComponent(patientNo)}` : ''}`)
  },

  async create(payload) {
    return request('/reminder-rules', json(payload))
  },

  // Partial: `{ active: false }` alone is a complete request.
  async update(id, payload) {
    return request(`/reminder-rules/${id}`, send('PATCH', payload))
  },
}

export const reminders = {
  // Reading this list clears the red dot for the entries it returns.
  async list({ patientNo = '', done, unreadOnly, page = 1, size = 20 } = {}) {
    const params = new URLSearchParams({ page: String(page), size: String(size) })
    if (patientNo) params.set('patient_no', patientNo)
    if (done !== undefined && done !== null) params.set('done', String(done))
    if (unreadOnly) params.set('unread_only', 'true')
    return request(`/reminders?${params}`)
  },

  async unreadCount() {
    return request('/reminders/unread-count')
  },

  async markDone(id) {
    return request(`/reminders/${id}/done`, json({}))
  },
}

export const assessments = {
  async list(patientNo) {
    return request(`/patients/${encodeURIComponent(patientNo)}/assessments`)
  },

  async get(id) {
    return request(`/assessments/${id}`)
  },

  async create(patientNo, payload) {
    return request(`/patients/${encodeURIComponent(patientNo)}/assessments`, json(payload))
  },

  // A revision writes a new row: the reply is version + 1, and the assessment it
  // replaces stays readable.
  async revise(id, payload) {
    return request(`/assessments/${id}`, send('PATCH', payload))
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

// M4 uses the shared authenticated fetch client and the canonical API contract.
export const emr = {
  get: (path) => request(path),
  post: (path, body = {}) => request(path, json(body)),
  patch: (path, body) => request(path, send('PATCH', body)),
}
