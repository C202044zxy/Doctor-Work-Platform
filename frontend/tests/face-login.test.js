import test from 'node:test'
import assert from 'node:assert/strict'
import { loginWithPhoto } from '../src/face-login.js'

test('a database account outside the demo roster sends its photo to backend login', async () => {
  const bytes = new Uint8Array([255, 216, 255, 217])
  const photo = new Blob([bytes], { type: 'image/jpeg' })
  const session = { access_token: 'backend-token', user: { username: 'C202044zxy' } }
  const authentication = {
    async faceLogin(username, image) {
      assert.equal(username, 'C202044zxy')
      assert.equal(image, `data:image/jpeg;base64,${Buffer.from(bytes).toString('base64')}`)
      return session
    },
  }
  assert.equal(await loginWithPhoto(authentication, 'C202044zxy', photo), session)
})

test('missing, invalid, and oversized photos do not send a login request', async () => {
  for (const photo of [null, new Blob([]), new Blob(['png'], { type: 'image/png' }),
    new Blob([new Uint8Array(2 * 1024 * 1024 + 1)], { type: 'image/jpeg' })]) {
    await assert.rejects(loginWithPhoto({}, 'user', photo), /photo/i)
  }
})

test('backend account rejection is shown instead of a demo roster error', async () => {
  const authentication = {
    async faceLogin() { throw new Error('User is unavailable or disabled') },
  }
  await assert.rejects(
    loginWithPhoto(authentication, 'missing', new Blob(['jpeg'], { type: 'image/jpeg' })),
    /User is unavailable or disabled/,
  )
})
