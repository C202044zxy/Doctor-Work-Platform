// The mock in src/api/mock-auth.js is what the T41/T42 pages actually talk to
// until B and D land, so its refusals are the ones the UI has to render: the
// cooldown, the attempt counter, the lockout, the face mismatch. `retry_after`
// and `remain` in particular are read by SmsCodeInput, and a rename here would
// silently turn "resend in 42s" into a button that looks clickable but is not.
//
// The mock reads the clock through Date.now(), so a single virtual clock makes
// the 300s expiry and the 600s lock deterministic instead of merely slow. Its
// per-number state is module-private and there is no reset, so each of the three
// roster numbers is spent on the scenario it is cut out for, in order.
import test from 'node:test'
import assert from 'node:assert/strict'

import { face, maskPhone, sms } from '../src/api/mock-auth.js'
import { simulatedActions, simulatedRows } from '../src/api/mock-audit.js'

let clock = Date.UTC(2026, 8, 13, 8, 0, 0)
const realNow = Date.now
Date.now = () => clock
const advance = (ms) => { clock += ms }

const realInfo = console.info
console.info = () => {}
globalThis.URL.createObjectURL = () => 'blob:stub'
globalThis.URL.revokeObjectURL = () => {}

// Same fake canvas as face-hash.test.js: `pattern` is the image, and two photos
// are the same picture exactly when their patterns match.
globalThis.document = {
  createElement: () => {
    const canvas = { width: 0, height: 0, source: null }
    canvas.getContext = () => ({
      drawImage: (source) => { canvas.source = source },
      getImageData: () => {
        const data = new Uint8ClampedArray(9 * 8 * 4)
        for (let index = 0; index < 72; index += 1) {
          const value = (index + canvas.source.pattern) % 2 === 0 ? 255 : 0
          data[index * 4] = value
          data[index * 4 + 1] = value
          data[index * 4 + 2] = value
          data[index * 4 + 3] = 255
        }
        return { data }
      },
    })
    return canvas
  },
}
globalThis.createImageBitmap = async (blob) => ({ pattern: blob.pattern ?? 0, close() {} })

test.after(() => {
  Date.now = realNow
  console.info = realInfo
})

const blob = (size = 1024, pattern = 0) => ({ size, pattern })

// §3.5 判据②: the code is not in the response, so this is the *only* way to
// learn it — which is the property the acceptance criterion is checking for.
function codeFromAudit() {
  const row = simulatedRows.value.find((entry) => entry.action === 'POST /api/auth/sms/send')
  return /code=(\d{6})/.exec(row.detail)[1]
}

test('maskPhone keeps the head and tail only', () => {
  assert.equal(maskPhone('13800138000'), '138****8000')
})

test('send rejects a malformed number and an unregistered one', async () => {
  await assert.rejects(sms.send({ phone: '12345' }), (error) => error.status === 422)
  await assert.rejects(sms.send({ phone: '13900000009' }), (error) => error.status === 404)
})

test('send returns the cooldown and a masked number, and the code only via the audit trail', async () => {
  const before = simulatedRows.value.length
  const result = await sms.send({ phone: '13800138000', scene: 'login' })

  assert.equal(result.cooldown, 60)
  assert.equal(result.mock, true)
  assert.equal(result.masked_phone, '138****8000')
  // §1.2 names handing the code back to the caller as the fake-implementation
  // signature, so its absence is the assertion, not an oversight.
  assert.equal('debug_code' in result, false)
  assert.equal('code' in result, false)

  assert.equal(simulatedRows.value.length, before + 1)
  const row = simulatedRows.value[0]
  assert.equal(row.action, 'POST /api/auth/sms/send')
  assert.equal(row.target, '138****8000')
  assert.match(row.detail, /code=\d{6}/)
  // The row is what the audit page's action filter offers.
  assert.ok(simulatedActions.value.includes('POST /api/auth/sms/send'))
})

// 13800138001 — the cooldown, then the happy path through it.
test('a second send inside the cooldown reports the remaining seconds', async () => {
  const phone = '13800138001'
  await sms.send({ phone })
  advance(20_000)
  await assert.rejects(sms.send({ phone }), (error) => {
    // SmsCodeInput restores its countdown from this field, not from storage.
    assert.equal(error.status, 429)
    assert.equal(error.data.retry_after, 40)
    return true
  })
})

test('the cooldown lifts, and the fresh code signs in once', async () => {
  const phone = '13800138001'
  advance(40_001)
  await sms.send({ phone })

  const data = await sms.verify({ phone, code: codeFromAudit(), scene: 'mfa' })
  assert.equal(data.user.username, 'dr_li')
  assert.equal(data.scene, 'mfa')

  // Single-use: the second attempt finds no live code.
  await assert.rejects(sms.verify({ phone, code: codeFromAudit() }), (error) => error.status === 400)
})

// 13800138002 — the attempt counter and the lock, then the code's own lifetime.
test('a wrong code counts down, then locks the number', async () => {
  const phone = '13800138002'
  await sms.send({ phone })
  const code = codeFromAudit()
  const wrong = code === '000000' ? '111111' : '000000'

  for (let remaining = 4; remaining >= 1; remaining -= 1) {
    await assert.rejects(sms.verify({ phone, code: wrong }), (error) => {
      assert.equal(error.status, 400)
      assert.equal(error.data.remain, remaining)
      return true
    })
  }

  await assert.rejects(sms.verify({ phone, code: wrong }), (error) => error.status === 423)
  // The lock outlives the code it was earned with: a correct code is refused too.
  await assert.rejects(sms.verify({ phone, code }), (error) => error.status === 423)
  await assert.rejects(sms.send({ phone }), (error) => error.status === 423)
})

test('the lock lifts after ten minutes, and a code past five is refused', async () => {
  const phone = '13800138002'
  advance(700_000)
  await sms.send({ phone })

  const code = codeFromAudit()
  advance(300_001)
  await assert.rejects(sms.verify({ phone, code }), (error) => {
    assert.equal(error.status, 400)
    assert.match(error.message, /expired/i)
    return true
  })
})

test('enrolment needs a known account and a non-empty photo', async () => {
  await assert.rejects(face.enroll(blob(), 'nobody'), (error) => error.status === 403)
  await assert.rejects(face.enroll(blob(0), 'dr_li'), (error) => error.status === 400)
  await assert.rejects(face.enroll(blob(3 * 1024 * 1024), 'dr_li'), (error) => error.status === 400)
})

test('enrolment records the ref and the change detail, never a path', async () => {
  const { face_image_ref: ref, enrolled_at: enrolledAt } = await face.enroll(blob(2048, 7), 'dr_li')
  assert.match(ref, /^f_[0-9a-f]{8}$/)
  assert.ok(enrolledAt)

  const row = simulatedRows.value[0]
  assert.equal(row.action, 'POST /api/auth/face/enroll')
  assert.equal(row.target, ref)
  assert.match(row.detail, /ref=f_[0-9a-f]{8}/)
  // §4.5 判据⑨: the value-change detail, and no filesystem path anywhere in it.
  assert.match(row.detail, /face_image_ref \(none\) -> f_/)
  assert.doesNotMatch(row.detail, /uploads|\/|\.jpg/)
})

test('the face image is readable by its owner and an admin, and nobody else', async () => {
  const [ref] = simulatedRows.value
    .filter((row) => row.action === 'POST /api/auth/face/enroll')
    .map((row) => row.target)

  assert.equal(await face.image(ref, 'dr_li'), 'blob:stub')
  assert.equal(await face.image(ref, 'admin_zhang'), 'blob:stub')

  // §4.5 判据⑤ — someone else's token.
  await assert.rejects(face.image(ref, 'dr_wang'), (error) => error.status === 403)
  // §4.5 判据④ — no token at all.
  await assert.rejects(face.image(ref, undefined), (error) => error.status === 403)
  await assert.rejects(face.image(ref, 'nobody'), (error) => error.status === 403)
  await assert.rejects(face.image('f_00000000', 'dr_li'), (error) => error.status === 404)
})

test('a matching photo passes and an unmatched one fails', async () => {
  await assert.rejects(face.verify('nobody', blob()), (error) => error.status === 404)
  await assert.rejects(face.verify('dr_wang', blob()), (error) => error.status === 400)

  const data = await face.verify('dr_li', blob(1024, 7))
  assert.equal(data.user.username, 'dr_li')
  assert.equal(data.mock, true)
  assert.ok(data.score > 0.5 && data.score <= 1)

  // §4.5 判据⑥ — a different face, which is the whole reason for the hash.
  await assert.rejects(face.verify('dr_li', blob(1024, 8)), (error) => {
    assert.equal(error.status, 401)
    // §4.3.3 第 5 步: the message must not leak a similarity figure.
    assert.doesNotMatch(error.message, /\d/)
    return true
  })
})

test('repeated unmatched photos lock face sign-in', async () => {
  // An even pattern against the odd one enrolled above, so the hashes really do
  // differ rather than happening to collide.
  const wrong = blob(1024, 100)

  // The counter is module state with no reset, and the test above already
  // recorded one mismatch against dr_li — so the limit is reached on the fourth
  // attempt here, not the fifth.
  const statuses = []
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await face.verify('dr_li', wrong).then(
      () => statuses.push(200),
      (error) => statuses.push(error.status),
    )
  }
  assert.deepEqual(statuses, [401, 401, 401, 401, 423])

  // §4.5 判据⑥: the lock refuses the owner's own photo too.
  await assert.rejects(face.verify('dr_li', blob(1024, 7)), (error) => error.status === 423)
})
