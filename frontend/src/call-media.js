// Real media only: receive-only never requests a local hardware device.
export async function acquireCallMedia(mode, devices = globalThis.navigator?.mediaDevices) {
  if (mode === 'receive') return null
  if (!devices?.getUserMedia) throw new Error('Camera and microphone access requires localhost or HTTPS and a supported browser.')
  return devices.getUserMedia({ video: mode === 'camera', audio: true })
}

export function stopCallMedia(stream) {
  stream?.getTracks().forEach(track => track.stop())
}

export function callMediaError(error) {
  const messages = {
    NotReadableError: 'The camera or microphone could not be opened; it may be in use. Close other camera apps or choose Receive only on this side, then retry.',
    NotAllowedError: 'Camera or microphone permission was denied. Allow access in browser settings, or choose Receive only and retry.',
    NotFoundError: 'No suitable camera or microphone was found. Connect a device, choose Microphone only, or choose Receive only.',
    OverconstrainedError: 'The selected media device cannot meet the request. Choose another media mode and retry.',
    AbortError: 'Media capture was interrupted. Close other camera apps and retry, or choose Receive only.',
  }
  return messages[error.name] || error.message || 'Could not start the call. Retry or continue using text chat.'
}
