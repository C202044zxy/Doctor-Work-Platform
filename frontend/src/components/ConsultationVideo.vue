<script setup>
import { nextTick, onUnmounted, ref } from 'vue'

const props = defineProps({ sendSignal: { type: Function, required: true }, enabled: Boolean })
const emit = defineEmits(['finished'])
const state = ref('idle'), error = ref(''), caller = ref('')
const localVideo = ref(null), remoteVideo = ref(null)
let pc, stream, callId, offer, timer, version = 0, candidates = [], localCandidates = [], described = false

function signal(type, data = {}) {
  props.sendSignal(type, { call_id: callId, ...data })
}

function reset(message = '') {
  version++
  clearTimeout(timer)
  if (pc) {
    pc.onicecandidate = null
    pc.onconnectionstatechange = null
    pc.close()
    pc = null
  }
  stream?.getTracks().forEach(track => track.stop())
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

function ringTimeout() {
  timer = setTimeout(() => {
    finish()
    error.value = 'Call timed out. Continue using text chat.'
  }, 27000)
}

async function prepare(expected) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('Camera access requires localhost or HTTPS and a supported browser.')
  }
  const acquired = await navigator.mediaDevices.getUserMedia({ video: true, audio: true })
  if (expected !== version) {
    acquired.getTracks().forEach(track => track.stop())
    return false
  }
  stream = acquired
  // Same-machine/LAN baseline. No third-party STUN/TURN account is silently used.
  pc = new RTCPeerConnection({ iceServers: [] })
  stream.getTracks().forEach(track => pc.addTrack(track, stream))
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
  await nextTick()
  if (localVideo.value) localVideo.value.srcObject = stream
  return true
}

async function start() {
  if (!props.enabled || state.value !== 'idle') return
  error.value = ''
  callId = crypto.randomUUID()
  state.value = 'preparing'
  const expected = ++version
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
    ringTimeout()
  } catch (err) {
    if (expected === version) { finish(); error.value = err.message }
  }
}

async function accept() {
  if (state.value !== 'incoming') return
  state.value = 'connecting'
  const expected = version
  try {
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
    described = true
    for (const candidate of localCandidates) signal('ice_candidate', { candidate })
    localCandidates = []
  } catch (err) {
    if (expected === version) { finish(); error.value = err.message }
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
    ringTimeout()
    return
  }
  if (!callId || data.call_id !== callId) return
  const expected = version
  try {
    if (type === 'call_answer' && pc) {
      state.value = 'connecting'
      await pc.setRemoteDescription({ type: 'answer', sdp: data.sdp })
      if (expected !== version) return
      for (const candidate of candidates) await pc.addIceCandidate(candidate)
      candidates = []
    } else if (type === 'ice_candidate' && data.candidate) {
      if (pc?.remoteDescription) await pc.addIceCandidate(data.candidate)
      else candidates.push(data.candidate)
    } else if (type === 'call_end') {
      reset(`Call ended: ${data.reason}.`)
      emit('finished')
    }
  } catch (err) {
    if (expected === version) { finish(); error.value = err.message }
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
    <el-button v-if="state === 'idle'" :disabled="!enabled" @click="start">Start video call</el-button>
    <template v-else>
      <p>{{ state === 'incoming' ? `${caller} is calling` : `Video: ${state}` }}</p>
      <el-button v-if="state === 'incoming'" type="primary" @click="accept">Answer</el-button>
      <el-button @click="finish(state === 'incoming' ? 'call_reject' : 'call_end')">{{ state === 'incoming' ? 'Decline' : 'Hang up' }}</el-button>
      <div class="videos">
        <div><small>You (muted preview)</small><video ref="localVideo" autoplay playsinline muted /></div>
        <div><small>Other participant</small><video ref="remoteVideo" autoplay playsinline controls /></div>
      </div>
    </template>
    <p v-if="error" role="status">{{ error }}</p>
  </section>
</template>

<style scoped>
.video-call{border-top:1px solid #dce6e3;padding:12px 0}.videos{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px}video{display:block;width:100%;max-height:220px;background:#182724;border-radius:8px}.video-call p{font-size:13px}
</style>
