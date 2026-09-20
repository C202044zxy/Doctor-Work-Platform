import test from 'node:test'
import assert from 'node:assert/strict'
import { acquireCallMedia, callMediaError, stopCallMedia } from '../src/call-media.js'

test('receive-only works without media devices and never requests permission', async () => {
  assert.equal(await acquireCallMedia('receive', undefined), null)
  assert.equal(await acquireCallMedia('receive', { getUserMedia: () => { throw new Error('Device in use') } }), null)
})

test('microphone-only does not open the camera; device errors are actionable', async () => {
  let constraints
  const devices = { getUserMedia: async value => { constraints = value; return 'stream' } }
  assert.equal(await acquireCallMedia('audio', devices), 'stream')
  assert.deepEqual(constraints, { video: false, audio: true })
  await acquireCallMedia('camera', devices)
  assert.deepEqual(constraints, { video: true, audio: true })
  assert.match(callMediaError({ name: 'NotReadableError' }), /Receive only/)
  assert.match(callMediaError({ name: 'NotAllowedError' }), /permission was denied/)
})

test('hangup stops every acquired track, including audio', () => {
  const stopped = []
  stopCallMedia({ getTracks: () => ['audio', 'video'].map(kind => ({ stop: () => stopped.push(kind) })) })
  stopCallMedia(null)
  assert.deepEqual(stopped, ['audio', 'video'])
})
