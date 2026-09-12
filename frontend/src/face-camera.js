export function stopCamera(stream) {
  stream?.getTracks().forEach((track) => track.stop())
}

export async function openCamera() {
  if (!globalThis.navigator?.mediaDevices?.getUserMedia) {
    throw new Error('Camera access requires HTTPS or localhost and a compatible browser.')
  }
  try {
    return await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
  } catch (error) {
    if (error.name === 'NotAllowedError') throw new Error('Camera permission was denied. Allow camera access and retry.')
    throw new Error('Could not open the camera. Check that it is connected and available.')
  }
}

export function capturePhoto(video) {
  if (!video?.videoWidth || !video?.videoHeight || video.readyState < 2) {
    throw new Error('Camera is not ready. Wait for the preview and retry.')
  }
  const canvas = document.createElement('canvas')
  const scale = Math.min(1, 640 / Math.max(video.videoWidth, video.videoHeight))
  canvas.width = Math.round(video.videoWidth * scale)
  canvas.height = Math.round(video.videoHeight * scale)
  canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', 0.85)
}
