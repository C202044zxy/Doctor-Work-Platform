// CameraCapture emits a JPEG Blob; the backend accepts a base64 JPEG data URL.
export async function loginWithPhoto(authentication, username, photo) {
  if (!photo?.size) throw new Error('Take a photo first.')
  if (photo.type !== 'image/jpeg' || photo.size > 2 * 1024 * 1024) {
    throw new Error('Use a JPEG photo under 2 MB.')
  }
  const bytes = new Uint8Array(await photo.arrayBuffer())
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return authentication.faceLogin(username, `data:image/jpeg;base64,${btoa(binary)}`)
}
