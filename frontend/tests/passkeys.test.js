import { test } from 'node:test'
import assert from 'node:assert/strict'

globalThis.sessionStorage = {
  getItem: () => null,
  setItem: () => {},
  removeItem: () => {},
}
globalThis.window = { isSecureContext: true, PublicKeyCredential: class {} }
const bytes = new Uint8Array([1, 2, 3])
const credential = {
  id: 'AQID', rawId: bytes, type: 'public-key',
  response: {
    clientDataJSON: bytes, attestationObject: bytes,
    authenticatorData: bytes, signature: bytes, userHandle: bytes,
    getTransports: () => ['internal'],
  },
  getClientExtensionResults: () => ({}),
}
let seenOptions
let seenBody
const authenticate = async ({ publicKey }) => { seenOptions = publicKey; return credential }
Object.defineProperty(globalThis, 'navigator', { value: {
  credentials: { create: authenticate, get: authenticate },
}, configurable: true })
globalThis.fetch = async (url, init) => {
  const data = url.endsWith('/options')
    ? { ticket: 'ticket', public_key: {
      challenge: 'AQID', user: { id: 'AQID' },
      excludeCredentials: [{ type: 'public-key', id: 'AQID' }],
    } }
    : { ok: true }
  if (url.endsWith('/verify')) seenBody = JSON.parse(init.body)
  return { ok: true, json: async () => ({ code: 0, data }) }
}
const { usePasskey, passkeysSupported } = await import('../src/passkeys.js')

test('registration converts binary options and sends credential JSON', async () => {
  assert.equal(passkeysSupported(), true)
  await usePasskey('register')
  assert.deepEqual(seenOptions.challenge, bytes)
  assert.deepEqual(seenOptions.user.id, bytes)
  assert.deepEqual(seenOptions.excludeCredentials[0].id, bytes)
  assert.equal(seenBody.ticket, 'ticket')
  assert.equal(seenBody.credential.response.attestationObject, 'AQID')
  assert.deepEqual(seenBody.credential.response.transports, ['internal'])
})
test('login sends signed assertion and user handle', async () => {
  await usePasskey('login')
  assert.equal(seenBody.credential.response.signature, 'AQID')
  assert.equal(seenBody.credential.response.userHandle, 'AQID')
  assert.equal(seenBody.credential.response.attestationObject, undefined)
})
test('cancellation leaves a recoverable error and insecure context is rejected', async () => {
  navigator.credentials.get = async () => { throw new DOMException('cancelled', 'NotAllowedError') }
  await assert.rejects(usePasskey('login'), /cancelled or timed out/)
  window.isSecureContext = false
  await assert.rejects(usePasskey('login'), /HTTPS or localhost/)
})
