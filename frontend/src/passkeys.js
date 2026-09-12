import { authentication } from './api/client.js'

export function passkeysSupported() {
  return Boolean(window.isSecureContext && window.PublicKeyCredential && navigator.credentials)
}

function decode(value) {
  const raw = atob(value.replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (char) => char.charCodeAt(0))
}
function encode(value) {
  if (value == null) return null
  return btoa(String.fromCharCode(...new Uint8Array(value)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export async function usePasskey(kind) {
  if (!passkeysSupported()) throw new Error('Passkeys require HTTPS or localhost and a compatible browser.')
  const { ticket, public_key: options } = await authentication.passkeyOptions(kind)
  options.challenge = decode(options.challenge)
  if (options.user) options.user.id = decode(options.user.id)
  for (const field of ['excludeCredentials', 'allowCredentials']) {
    if (options[field]) options[field] = options[field].map((item) => ({ ...item, id: decode(item.id) }))
  }
  let credential
  try {
    credential = kind === 'register'
      ? await navigator.credentials.create({ publicKey: options })
      : await navigator.credentials.get({ publicKey: options })
  } catch (error) {
    if (error.name === 'NotAllowedError') throw new Error('Passkey request was cancelled or timed out. You can retry or use your password.')
    if (error.name === 'InvalidStateError') throw new Error('This passkey is already registered.')
    throw new Error('This device could not complete the passkey request. Try another device or use your password.')
  }
  if (!credential) throw new Error('No passkey was selected.')
  const response = { clientDataJSON: encode(credential.response.clientDataJSON) }
  if (kind === 'register') {
    response.attestationObject = encode(credential.response.attestationObject)
    response.transports = credential.response.getTransports?.() || []
  } else {
    response.authenticatorData = encode(credential.response.authenticatorData)
    response.signature = encode(credential.response.signature)
    response.userHandle = encode(credential.response.userHandle)
  }
  return authentication.passkeyVerify(kind, ticket, {
    id: credential.id, rawId: encode(credential.rawId), type: credential.type,
    response, clientExtensionResults: credential.getClientExtensionResults(),
  })
}
