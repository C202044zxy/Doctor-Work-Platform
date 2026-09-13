// Front-end stand-in for the T41 / T42 endpoints while B (SMS) and D (face)
// build them. The shapes here follow
// `T41短信登录与T42人脸识别-任务详设.md` §3.3.1 and §4.3.1 exactly, so the day the
// real endpoints answer, the switch in client.js is the only change.
//
// This mirrors the arrangement the backend is meant to have, it does not replace
// it: the real switch is SMS_PROVIDER / FACE_PROVIDER in .env, and the provider
// there is the thing that refuses to touch the network. Delete this file once
// `/api/auth/sms/*` and `/api/auth/face/*` exist.

import { hashBlob, hashDistance, HASH_BITS, MAX_DISTANCE } from '../face-hash.js'
import { record } from './mock-audit.js'

export const SIMULATED = { sms: true, face: true }

const CODE_TTL_MS = 300_000 // §3.3.2: vc:code TTL 300s, same as T06
const COOLDOWN_MS = 60_000
const DAILY_LIMIT = 10
const MAX_ATTEMPTS = 5
const LOCK_MS = 600_000
const PHONE_PATTERN = /^1[3-9]\d{9}$/
const NO_MATCH = 'No enrolled face matched. Adjust the lighting and try again.'

// phone -> { code, cooldownUntil, attempts, lockUntil, sentToday }
const codes = new Map()
// username -> { ref, url, hash, enrolledAt }
const faces = new Map()
// username -> { failures, lockUntil } — §4.3.3【校验】第 1 步复用同一套失败计数
const faceFailures = new Map()

export function maskPhone(phone) {
  return `${phone.slice(0, 3)}****${phone.slice(-4)}`
}

function fail(status, message, data = null) {
  const error = new Error(message)
  error.status = status
  error.data = data
  return error
}

function account(phone) {
  return codes.get(phone) ?? { attempts: 0, sentToday: 0 }
}

export const sms = {
  // §3.3.1 ① — 404 when the number is not registered, 429 for the 60s cooldown
  // and for the daily cap. The demo roster is the §0.4 sign-off accounts.
  //
  // The response is exactly `cooldown` / `mock` / `masked_phone`, as §3.3.1
  // specifies. The code is *not* here: §1.2 lists handing it back to the caller
  // as the way to get judged a fake implementation. It goes to the audit trail
  // instead, which is what §3.5 判据② checks and what the §6.2 script reads
  // aloud.
  async send({ phone, scene = 'login' }) {
    if (!PHONE_PATTERN.test(phone)) throw fail(422, 'Enter a valid mobile number.', null)

    const current = account(phone)
    const now = Date.now()
    if (current.lockUntil > now) {
      throw fail(423, 'Too many incorrect codes. The account is locked for 10 minutes.', null)
    }
    if (current.cooldownUntil > now) {
      const retryAfter = Math.ceil((current.cooldownUntil - now) / 1000)
      throw fail(429, `Please retry in about ${retryAfter} seconds.`, { retry_after: retryAfter })
    }

    const user = ROSTER[phone]
    if (!user) throw fail(404, 'That mobile number is not registered.', null)
    if (current.sentToday >= DAILY_LIMIT) {
      throw fail(429, 'Daily limit reached for this number.', null)
    }

    // secrets.randbelow server-side (§3.3.4 第 3 步 禁止 random.randint); the
    // browser equivalent is the CSPRNG behind getRandomValues.
    const code = String(crypto.getRandomValues(new Uint32Array(1))[0] % 1_000_000).padStart(6, '0')
    codes.set(phone, {
      ...current,
      code,
      codeIssuedAt: now,
      cooldownUntil: now + COOLDOWN_MS,
      sentToday: current.sentToday + 1,
    })

    // What MockSMSProvider does server-side: write the code to a log instead of
    // sending it, and let the audit trail carry it. Both lines below stand in for
    // `INSERT sms_log` (§3.3.4 第 6 步) and the T11 middleware (第 8 步).
    console.info(`[simulated SMS][${scene}] -> ${maskPhone(phone)} | code ${code}`)
    record({
      action: 'POST /api/auth/sms/send',
      actor: user.username,
      target: maskPhone(phone),
      detail: `Simulated send, no gateway called. scene=${scene} provider=mock is_mock=1 code=${code}`,
    })

    return { cooldown: COOLDOWN_MS / 1000, mock: SIMULATED.sms, masked_phone: maskPhone(phone) }
  },

  // §3.3.1 ② — 400 wrong/expired, 423 after five wrong. §3.3.4 第 1 步 requires
  // "no such code" and "wrong code" to be reported separately; merging them shows
  // a bogus attempt count to anyone whose code simply expired.
  async verify({ phone, code, scene = 'login' }) {
    const current = account(phone)
    const now = Date.now()
    if (current.lockUntil > now) {
      const minutes = Math.ceil((current.lockUntil - now) / 60_000)
      throw fail(423, `Too many incorrect codes. The account is locked for ${minutes} minutes.`, null)
    }
    if (!current.code || now - current.codeIssuedAt > CODE_TTL_MS) {
      throw fail(400, 'That code has expired. Request a new one.', null)
    }
    if (current.code !== String(code).trim()) {
      const attempts = current.attempts + 1
      codes.set(phone, { ...current, attempts })
      if (attempts >= MAX_ATTEMPTS) {
        codes.set(phone, { ...current, attempts: 0, lockUntil: now + LOCK_MS, code: null })
        throw fail(423, 'Too many incorrect codes. The account is locked for 10 minutes.', null)
      }
      throw fail(400, `Incorrect code. ${MAX_ATTEMPTS - attempts} attempts remaining.`, {
        remain: MAX_ATTEMPTS - attempts,
      })
    }

    codes.set(phone, { ...current, code: null, attempts: 0 })
    const user = ROSTER[phone]
    record({
      action: 'POST /api/auth/sms/verify',
      actor: user.username,
      target: maskPhone(phone),
      detail: `Simulated verification passed. scene=${scene}. No session was issued: scene=mfa's sign-in shape is still open (§8 item 4).`,
    })
    return { user: { ...user }, simulated: true, scene }
  },
}

export const face = {
  // §4.3.1 ① — multipart `image`, ≤2MB. Repeat enrolment overwrites.
  //
  // `actingUsername` is an artefact of the mock: the real endpoint reads the
  // subject from the bearer token, so the caller only sends the image. The mock
  // has no token to read, so the page tells it who is enrolling.
  async enroll(blob, actingUsername) {
    if (!blob || !blob.size) throw fail(400, 'Upload a JPG or PNG photo under 2 MB.', null)
    if (blob.size > 2 * 1024 * 1024) {
      throw fail(400, 'Upload a JPG or PNG photo under 2 MB.', null)
    }
    const username = actingUsername
    const user = ROSTER_BY_USERNAME[username]
    if (!user) throw fail(403, 'Not allowed to enrol this face.', null)

    const hash = await hashBlob(blob)
    const previous = faces.get(username)
    if (previous) URL.revokeObjectURL(previous.url)
    const ref = `f_${crypto.getRandomValues(new Uint32Array(1))[0].toString(16).padStart(8, '0').slice(0, 8)}`
    const enrolledAt = new Date().toISOString()
    faces.set(username, { ref, url: URL.createObjectURL(blob), hash, enrolledAt })
    faceFailures.delete(username)

    // §4.5 判据⑨: the record names the ref, never a path, and carries the
    // old_ref → new_ref change detail.
    record({
      action: 'POST /api/auth/face/enroll',
      actor: username,
      target: ref,
      detail: `ref=${ref} size=${blob.size} changed: face_image_ref ${previous?.ref ?? '(none)'} -> ${ref}`,
    })

    return { face_image_ref: ref, enrolled_at: enrolledAt, simulated: true }
  },

  // §4.3.1 ② — multipart `username` + `image`. The comparison is a real dHash
  // Hamming distance (§2 冲突 1 方案 A), so "a different face is refused" is
  // demonstrable; only the provider that would do it in production is absent.
  async verify(username, blob) {
    const user = ROSTER_BY_USERNAME[username]
    if (!user) throw fail(404, 'No such user.', null)

    const failure = faceFailures.get(username) ?? { failures: 0 }
    if (failure.lockUntil > Date.now()) {
      throw fail(423, 'Too many failed attempts. Sign in with your password instead.', null)
    }

    const entry = faces.get(username)
    if (!entry) {
      throw fail(400, 'This account has no enrolled face. Sign in with a password and enrol one first.', null)
    }
    if (!blob?.size) throw fail(401, NO_MATCH, null)

    const distance = hashDistance(await hashBlob(blob), entry.hash)
    const score = Math.max(0, 1 - distance / HASH_BITS)
    if (distance > MAX_DISTANCE) {
      const failures = failure.failures + 1
      faceFailures.set(username, {
        failures: failures >= MAX_ATTEMPTS ? 0 : failures,
        lockUntil: failures >= MAX_ATTEMPTS ? Date.now() + LOCK_MS : 0,
      })
      // §4.3.3 第 5 步: the audit record may hold the score; the 401 message must
      // not, because a number there is something an attacker can probe against.
      record({
        action: 'POST /api/auth/face/verify',
        actor: username,
        target: entry.ref,
        outcome: 'failure',
        severity: 'warn',
        detail: `ref=${entry.ref} distance=${distance}/${HASH_BITS} score=${score.toFixed(2)} match=false`,
      })
      throw fail(401, NO_MATCH, null)
    }

    faceFailures.delete(username)
    record({
      action: 'POST /api/auth/face/verify',
      actor: username,
      target: entry.ref,
      detail: `ref=${entry.ref} distance=${distance}/${HASH_BITS} score=${score.toFixed(2)} match=true`,
    })
    return { user: { ...user }, score, mock: SIMULATED.face, simulated: true }
  },

  // §4.3.1 ③ — controlled read: the owner or an admin, nothing else. The extra
  // `actingUsername` stands in for the bearer token the real endpoint reads, and
  // leaving it off is exactly the "no token" case 判据④ exercises.
  async image(ref, actingUsername) {
    for (const [owner, entry] of faces) {
      if (entry.ref !== ref) continue
      const viewer = ROSTER_BY_USERNAME[actingUsername]
      if (viewer?.title !== 'admin' && actingUsername !== owner) {
        throw fail(403, 'Not allowed to view this face image.', null)
      }
      return entry.url
    }
    throw fail(404, 'Face image not found.', null)
  },
}

// The §0.4 sign-off roster, which is who the demo signs in as.
const ROSTER = {
  '13800138000': { id: 1, username: 'admin_zhang', name: 'Zhang Wei', title: 'admin', department: 'General Medicine' },
  '13800138001': { id: 2, username: 'dr_li', name: 'Li Na', title: 'senior', department: 'Cardiology' },
  '13800138002': { id: 3, username: 'dr_wang', name: 'Wang Lei', title: 'junior', department: 'General Medicine' },
}

const ROSTER_BY_USERNAME = Object.fromEntries(
  Object.values(ROSTER).map((user) => [user.username, user]),
)
