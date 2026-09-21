<script setup>
import { computed, nextTick, onUnmounted, ref } from 'vue'
import { connectLoopback } from '../call-loopback.js'
import { acquireCallMedia, callMediaError, stopCallMedia } from '../call-media.js'

const props = defineProps({ sendSignal: { type: Function, required: true }, enabled: Boolean })
const emit = defineEmits(['finished'])
const state = ref('idle'), error = ref(''), caller = ref('')
const localVideo = ref(null), remoteVideo = ref(null)
const mediaMode = ref('camera')
let pc, loop, stream, callId, offer, timer, version = 0, candidates = [], localCandidates = [], described = false

const statusText = computed(() => {
  if (state.value === 'incoming') return `${caller.value} is calling`
  if (state.value === 'loopback') return 'Loopback on this computer — your camera is connected to you. No call was placed and nothing was recorded.'
  return `Video: ${state.value}`
})

function signal(type, data = {}) {
  props.sendSignal(type, { call_id: callId, ...data })
}

function reset(message = '') {
  version++
  clearTimeout(timer)
  if (pc) {
    pc.ontrack = null
    pc.onicecandidate = null
    pc.onconnectionstatechange = null
    pc.close()
    pc = null
  }
  if (loop) {
    loop.close()
    loop = null
  }
  stopCallMedia(stream)
  stream = null
  if (localVideo.value) localVideo.value.srcObject = null
  if (remoteVideo.value) remoteVideo.value.srcObject = null
  callId = null
  offer = null
  candidates = []
  localCandidates = []
  described = false
  state.value = 'idle'
  error.value = message
}

function finish(type = 'call_end') {
  if (callId) {
    try { signal(type) } catch { /* Server closes the call when the socket disappears. */ }
  }
  reset()
}

function callTimeout(phase) {
  clearTimeout(timer)
  const message = phase === 'ringing'
    ? 'No answer within 60 seconds. Ask the other participant to open this room and answer.'
    : phase === 'preparing'
      ? 'Camera or microphone setup timed out. Check the permission prompt, or choose Receive only and retry.'
      : 'Media connection timed out. Check device permissions and the network; for a single computer choose Receive only on one side.'
  timer = setTimeout(() => { finish(); error.value = message }, phase === 'ringing' ? 62000 : 47000)
}

async function acquire(expected) {
  const acquired = await acquireCallMedia(mediaMode.value)
  if (expected !== version) {
    stopCallMedia(acquired)
    return false
  }
  stream = acquired
  await nextTick()
  if (localVideo.value) localVideo.value.srcObject = stream
  return true
}

async function prepare(expected) {
  if (!await acquire(expected)) return false
  // Same-machine/LAN baseline. No third-party STUN/TURN account is silently used.
  pc = new RTCPeerConnection({ iceServers: [] })
  const tracks = stream?.getTracks() || []
  tracks.forEach(track => pc.addTrack(track, stream))
  // Request incoming tracks even when this side has no local devices.
  for (const kind of ['audio', 'video']) {
    if (!tracks.some(track => track.kind === kind)) pc.addTransceiver(kind, { direction: 'recvonly' })
  }
  pc.onicecandidate = event => {
    if (event.candidate && callId) {
      if (!described) { localCandidates.push(event.candidate.toJSON()); return }
      try { signal('ice_candidate', { candidate: event.candidate.toJSON() }) }
      catch { reset('Signaling disconnected. Reopen the call after reconnecting.') }
    }
  }
  pc.ontrack = async event => {
    await nextTick()
    if (expected === version && remoteVideo.value) remoteVideo.value.srcObject = event.streams[0]
  }
  pc.onconnectionstatechange = () => {
    if (!pc || expected !== version) return
    if (pc.connectionState === 'connected') {
      state.value = 'connected'
      clearTimeout(timer)
      try { signal('call_connected') } catch { reset('Signaling disconnected.') }
    } else if (['failed', 'closed'].includes(pc.connectionState)) {
      finish()
      error.value = 'Media connection failed. Continue using text chat.'
    } else if (pc.connectionState === 'disconnected') {
      clearTimeout(timer)
      timer = setTimeout(() => finish(), 10000)
    }
  }
  return true
}

// A same-page loopback, for showing a connected video pane on one computer. It is
// deliberately outside the signaling path: the server refuses an offer whenever no
// other connection is in the room (`backend/app/calls.py`), and satisfying that check
// with nobody there would mean the server pretending to have a peer. So this sends no
// offer and no `call_id` is set, which is also why nothing lands in the call history
// or the audit trail -- no call happened, only a real local media path.
async function startLoopback() {
  if (!props.enabled || state.value !== 'idle' || mediaMode.value === 'receive') return
  error.value = ''
  state.value = 'preparing'
  const expected = ++version
  callTimeout('preparing')
  try {
    if (!await acquire(expected)) return
    const established = await connectLoopback(stream)
    if (expected !== version) {
      established.close()
      return
    }
    loop = established
    state.value = 'loopback'
    clearTimeout(timer)
    await nextTick()
    if (remoteVideo.value) remoteVideo.value.srcObject = loop.remote
  } catch (err) {
    if (expected === version) { finish(); error.value = callMediaError(err) }
  }
}

async function start() {
  if (!props.enabled || state.value !== 'idle') return
  error.value = ''
  callId = crypto.randomUUID()
  state.value = 'preparing'
  const expected = ++version
  callTimeout('preparing')
  try {
    if (!await prepare(expected)) return
    const description = await pc.createOffer()
    if (expected !== version) return
    await pc.setLocalDescription(description)
    if (expected !== version) return
    signal('call_offer', { sdp: description.sdp })
    described = true
    for (const candidate of localCandidates) signal('ice_candidate', { candidate })
    localCandidates = []
    state.value = 'calling'
    callTimeout('ringing')
  } catch (err) {
    if (expected === version) { finish(); error.value = callMediaError(err) }
  }
}

async function accept() {
  if (state.value !== 'incoming') return
  state.value = 'connecting'
  const expected = version
  callTimeout('connecting')
  try {
    signal('call_accept')
    if (!await prepare(expected)) return
    await pc.setRemoteDescription({ type: 'offer', sdp: offer })
    if (expected !== version) return
    for (const candidate of candidates) await pc.addIceCandidate(candidate)
    candidates = []
    const description = await pc.createAnswer()
    if (expected !== version) return
    await pc.setLocalDescription(description)
    if (expected !== version) return
    signal('call_answer', { sdp: description.sdp })
    callTimeout('connecting')
    described = true
    for (const candidate of localCandidates) signal('ice_candidate', { candidate })
    localCandidates = []
  } catch (err) {
    if (expected === version) { finish(); error.value = callMediaError(err) }
  }
}

async function receive(type, data) {
  if (type === 'call_offer') {
    if (state.value !== 'idle') return
    callId = data.call_id
    offer = data.sdp
    caller.value = data.sender_name
    error.value = ''
    state.value = 'incoming'
    callTimeout('ringing')
    return
  }
  if (!callId || data.call_id !== callId) return
  const expected = version
  try {
    if (type === 'call_accept' && pc) {
      state.value = 'connecting'
      callTimeout('connecting')
    } else if (type === 'call_answer' && pc) {
      state.value = 'connecting'
      callTimeout('connecting')
      await pc.setRemoteDescription({ type: 'answer', sdp: data.sdp })
      if (expected !== version) return
      for (const candidate of candidates) await pc.addIceCandidate(candidate)
      candidates = []
    } else if (type === 'ice_candidate' && data.candidate) {
      if (pc?.remoteDescription) await pc.addIceCandidate(data.candidate)
      else candidates.push(data.candidate)
    } else if (type === 'call_end') {
      const timedOut = data.reason === 'timeout'
      const message = timedOut
        ? (['incoming', 'calling'].includes(state.value)
          ? 'No answer within 60 seconds. Ask the other participant to open this room and answer.'
          : 'Media connection timed out. Check device permissions and the network; try Receive only on one side.')
        : `Call ended: ${data.reason}.`
      reset(message)
      emit('finished')
    }
  } catch (err) {
    if (expected === version) { finish(); error.value = callMediaError(err) }
  }
}

defineExpose({ receive, finish, disconnected: () => reset('Connection lost. The call has ended.'), failed: data => {
  if (data.call_id && data.call_id !== callId) return
  finish()
  error.value = data.message
} })
onUnmounted(() => finish())
</script>

<template>
  <section class="video-call" aria-label="Video call">
    <label class="media-mode">
      Local media
      <select v-model="mediaMode" aria-label="Local media" :disabled="!['idle', 'incoming'].includes(state)">
        <option value="camera">Camera and microphone</option>
        <option value="audio">Microphone only</option>
        <option value="receive">Receive only (no devices)</option>
      </select>
    </label>
    <p v-if="mediaMode === 'receive'">Receive only: your camera and microphone stay off. You can watch and hear the other participant.</p>
    <p v-else>Testing on one computer? Choose Receive only on the other side to avoid competing for the same camera.</p>
    <el-button v-if="state === 'idle'" :disabled="!enabled" @click="start">Start video call</el-button>
    <el-button v-if="state === 'idle'" class="loopback" :disabled="!enabled || mediaMode === 'receive'" @click="startLoopback">Test on this computer (loopback)</el-button>
    <p v-if="state === 'idle' && mediaMode !== 'receive'" class="loopback-note">
      Loopback skips the check that the other participant is online, and connects your own camera
      back to you: the picture is real, the other party is not. It places no call and writes nothing
      to the call history. Its audio stays muted on this page to avoid feedback.
    </p>
    <template v-if="state !== 'idle'">
      <p>{{ statusText }}</p>
      <el-button v-if="state === 'incoming'" type="primary" @click="accept">Answer</el-button>
      <el-button @click="finish(state === 'incoming' ? 'call_reject' : 'call_end')">{{ state === 'incoming' ? 'Decline' : state === 'loopback' ? 'Stop loopback' : 'Hang up' }}</el-button>
      <div class="videos">
        <div><small>{{ mediaMode === 'receive' ? 'Local camera and microphone off' : mediaMode === 'audio' ? 'Microphone only — camera off' : 'You (muted preview)' }}</small><video ref="localVideo" autoplay playsinline muted /></div>
        <div><small>{{ state === 'loopback' ? 'Loopback — the same camera again' : 'Other participant' }}</small><video ref="remoteVideo" autoplay playsinline controls :muted="state === 'loopback'" /></div>
      </div>
    </template>
    <p v-if="error" role="status">{{ error }}</p>
  </section>
</template>

<style scoped>
.video-call{border-top:1px solid #dce6e3;padding:12px 0}.videos{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}video{display:block;width:100%;max-height:220px;background:#182724;border-radius:8px}.video-call p{font-size:13px}
.media-mode{display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:8px}.media-mode select{max-width:100%;padding:6px;border:1px solid #dce6e3;border-radius:6px}
.loopback{margin-left:8px}.loopback-note{color:#5b6b68;margin:6px 0 0;max-width:62ch}
</style>
