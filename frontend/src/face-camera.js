export function stopCamera(stream) {
  stream?.getTracks().forEach((track) => track.stop())
}

// §4.4: `getUserMedia` is asynchronous and its outcome is the user's to decide,
// so the three failures it actually produces each need their own words — §7 checks
// denial, absence and "already in use" separately, and they have different fixes.
const CAMERA_ERRORS = {
  NotAllowedError: 'Camera permission was denied. Allow camera access in the browser settings and retry.',
  SecurityError: 'Camera permission was denied. Allow camera access in the browser settings and retry.',
  NotFoundError: 'No camera was found on this device.',
  DevicesNotFoundError: 'No camera was found on this device.',
  NotReadableError: 'The camera is already in use by another program. Close it and retry.',
  TrackStartError: 'The camera is already in use by another program. Close it and retry.',
  OverconstrainedError: 'No camera on this device can produce a usable image.',
}

export async function openCamera() {
  if (!globalThis.navigator?.mediaDevices?.getUserMedia) {
    throw new Error('Camera access requires HTTPS or localhost and a compatible browser.')
  }
  try {
    return await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
  } catch (error) {
    throw new Error(
      CAMERA_ERRORS[error.name] ?? 'Could not open the camera. Check that it is connected and available.',
    )
  }
}

// §4.4: the long edge is capped at 640 so the JPEG stays well inside the 2 MB the
// enrolment endpoint accepts, whatever the camera reports.
function drawFrame(video) {
  if (!video?.videoWidth || !video?.videoHeight || video.readyState < 2) {
    throw new Error('Camera is not ready. Wait for the preview and retry.')
  }
  const canvas = document.createElement('canvas')
  const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight))
  canvas.width = Math.round(video.videoWidth * scale)
  canvas.height = Math.round(video.videoHeight * scale)
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvas
}

export function capturePhoto(video) {
  return drawFrame(video).toDataURL('image/jpeg', 0.85)
}

// §4.4 asks for `toBlob`, not `toDataURL`: the frame goes straight into a
// multipart body, and base64-encoding a full-size frame on the main thread is
// what makes these pages stutter.
export function captureBlob(video) {
  const canvas = drawFrame(video)
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('Could not encode the photo. Try again.'))),
      'image/jpeg',
      0.85,
    )
  })
}
