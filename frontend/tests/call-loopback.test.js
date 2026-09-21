import test from 'node:test'
import assert from 'node:assert/strict'
import { connectLoopback } from '../src/call-loopback.js'

class FakeStream {
  constructor() { this.tracks = [] }
  addTrack(track) { this.tracks.push(track) }
}

// `log` records the order two peers are driven in; `early` records every candidate
// that reached a peer with no remote description yet. The module swallows a rejected
// addIceCandidate, so `early` is what catches a regression in the buffering -- an
// empty `log` entry alone would look identical to a candidate that never arrived.
function fakePeers(log, early, { autoConnect = true, fail = false } = {}) {
  const made = []
  class FakePeer {
    constructor(config) {
      this.config = config
      this.connectionState = 'new'
      this.listeners = new Set()
      this.closed = false
      made.push(this)
    }
    addEventListener(type, listener) { this.listeners.add(listener) }
    removeEventListener(type, listener) { this.listeners.delete(listener) }
    addTrack(track, stream) { log.push('addTrack'); this.sent = { track, stream } }
    async createOffer() { log.push('createOffer'); return { type: 'offer', sdp: 'offer-sdp' } }
    async createAnswer() { log.push('createAnswer'); return { type: 'answer', sdp: 'answer-sdp' } }
    async setLocalDescription(description) {
      log.push(`setLocal:${description.type}`)
      this.localDescription = description
      // Gathering starts here, which is exactly how a candidate ends up in flight
      // before the far side has a remote description.
      this.onicecandidate?.({ candidate: { candidate: `${description.type}-candidate` } })
    }
    async setRemoteDescription(description) {
      log.push(`setRemote:${description.type}`)
      this.remoteDescription = description
      if (description.type === 'answer' && autoConnect) this.settle(fail ? 'failed' : 'connected')
    }
    async addIceCandidate(candidate) {
      if (!this.remoteDescription) {
        early.push(`${candidate.candidate}-too-early`)
        throw new Error('addIceCandidate before setRemoteDescription')
      }
      log.push(`ice:${candidate.candidate}`)
    }
    settle(connectionState) {
      this.connectionState = connectionState
      for (const listener of [...this.listeners]) listener({ type: 'connectionstatechange' })
    }
    close() { this.closed = true; this.connectionState = 'closed' }
  }
  return { FakePeer, made }
}

function fakeCamera() {
  return { getTracks: () => [{ kind: 'video' }, { kind: 'audio' }] }
}

const tick = () => new Promise(resolve => setTimeout(resolve, 0))

test('both peers exchange a description and the camera goes to the outgoing one', async () => {
  const log = [], early = []
  const { FakePeer, made } = fakePeers(log, early)
  const result = await connectLoopback(fakeCamera(), { Peer: FakePeer, Stream: FakeStream })

  assert.deepEqual(log, [
    'addTrack', 'addTrack',
    'createOffer', 'setLocal:offer', 'setRemote:offer', 'ice:offer-candidate',
    'createAnswer', 'setLocal:answer', 'setRemote:answer', 'ice:answer-candidate',
  ])
  assert.equal(made.length, 2)
  assert.deepEqual(made[0].config, { iceServers: [] })
  assert.equal(made[0].sent.stream.getTracks().length, 2)
  assert.deepEqual(early, [])
  assert.ok(result.remote instanceof FakeStream)
})

test('a candidate in flight before the far side is ready is held, not dropped', async () => {
  const log = [], early = []
  const { FakePeer } = fakePeers(log, early)
  await connectLoopback(fakeCamera(), { Peer: FakePeer, Stream: FakeStream })

  // Nothing may be offered to a peer that has no remote description yet.
  assert.deepEqual(early, [])
  // Each candidate arrives after the description it needed, not before it.
  assert.deepEqual(log.filter(entry => entry.startsWith('ice:')), [
    'ice:offer-candidate',
    'ice:answer-candidate',
  ])
  assert.ok(log.indexOf('ice:offer-candidate') > log.indexOf('setRemote:offer'))
  assert.ok(log.indexOf('ice:answer-candidate') > log.indexOf('setRemote:answer'))
})

test('the remote stream collects the tracks the far side sends', async () => {
  const log = [], early = []
  const { FakePeer, made } = fakePeers(log, early)
  const result = await connectLoopback(fakeCamera(), { Peer: FakePeer, Stream: FakeStream })

  made[1].ontrack({ track: 'incoming-video' })
  assert.deepEqual(result.remote.tracks, ['incoming-video'])
})

test('it resolves only once the connection is really up', async () => {
  const log = [], early = []
  const { FakePeer, made } = fakePeers(log, early, { autoConnect: false })
  let settled = false
  const pending = connectLoopback(fakeCamera(), { Peer: FakePeer, Stream: FakeStream })
    .then(value => { settled = true; return value })

  await tick()
  assert.equal(settled, false, 'reported success while still connecting')
  assert.equal(made[0].connectionState, 'new')

  made[0].settle('connected')
  assert.ok((await pending).remote instanceof FakeStream)
})

test('a connection that fails rejects and closes both peers', async () => {
  const log = [], early = []
  const { FakePeer, made } = fakePeers(log, early, { fail: true })
  await assert.rejects(
    connectLoopback(fakeCamera(), { Peer: FakePeer, Stream: FakeStream }),
    /loopback connection failed/,
  )
  // A half-wired pair would leave the camera light on with nothing to hang up.
  assert.deepEqual(made.map(peer => peer.closed), [true, true])
})

test('closing the loopback closes both peers', async () => {
  const log = [], early = []
  const { FakePeer, made } = fakePeers(log, early)
  const result = await connectLoopback(fakeCamera(), { Peer: FakePeer, Stream: FakeStream })

  result.close()
  assert.deepEqual(made.map(peer => peer.closed), [true, true])
})

test('a browser without WebRTC is refused rather than left half-started', async () => {
  await assert.rejects(
    connectLoopback(fakeCamera(), { Peer: null, Stream: FakeStream }),
    /does not support WebRTC/,
  )
})
