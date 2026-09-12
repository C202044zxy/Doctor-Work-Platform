import test from 'node:test'
import assert from 'node:assert/strict'
import { capturePhoto, openCamera, stopCamera } from '../src/face-camera.js'

test('opens video only and stops tracks', async () => {
  let stopped = false
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
    mediaDevices: { getUserMedia: async (options) => {
      assert.equal(options.audio, false)
      return { getTracks: () => [{ stop: () => { stopped = true } }] }
    } }
  } })
  stopCamera(await openCamera())
  assert.equal(stopped, true)
  stopCamera(null)
})

test('denial and unsupported browser errors', async () => {
  navigator.mediaDevices.getUserMedia = async () => { throw { name: 'NotAllowedError' } }
  await assert.rejects(openCamera(), /permission was denied/)
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {} })
  await assert.rejects(openCamera(), /HTTPS or localhost/)
})

test('capture waits for video and creates bounded JPEG', () => {
  assert.throws(() => capturePhoto({ videoWidth: 0 }), /not ready/)
  const video = { videoWidth: 1920, videoHeight: 1080, readyState: 2 }
  globalThis.document = { createElement: () => ({
    getContext: () => ({ drawImage: (source, x, y, width, height) => {
      assert.equal(source, video)
      assert.equal(width, 640)
      assert.equal(height, 360)
    } }),
    toDataURL: (type) => { assert.equal(type, 'image/jpeg'); return 'photo' }
  }) }
  assert.equal(capturePhoto(video), 'photo')
})
