<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { accessToken } from '../session'
import { mergeMessages, work } from '../api/work'
import ChatImage from './ChatImage.vue'
import ConsultationVideo from './ConsultationVideo.vue'
import { Picture } from '@element-plus/icons-vue'
import {
  confirmPending,
  imageProblem,
  liveFrame,
  messageBody,
  roomKey,
  roomNotice,
  roomPaths,
  roomWritable,
} from '../room.js'

// One conversation, rendered for both kinds of room.
//
// M3's patient consultation and M5's remote consultation talk over the same socket --
// `/ws/chat/{room_id}`, spelled in `src/room.js` -- so they render this component rather
// than two: history with cursor paging, the optimistic composer, image upload, the 1:1
// video pane and the call log. What stays with the screen around it is the room's own
// record: the patient, the participants and the buttons that move the state machine.
// `status`, `message` and `sync` are emitted so that record can follow events here,
// and `connected` carries the socket's own state for the header that reports it.
const props = defineProps({
  kind: { type: String, default: 'consultation' },
  roomId: { type: [Number, String], default: null },
  // The room's lifecycle status as the screen read it. A `status` frame from the socket
  // supersedes it while one is held: a meeting is started from another session, and this
  // side would otherwise keep offering a composer the server has already refused.
  status: { type: String, default: '' },
  // Whether this reader is in the room at all. The server decides this too -- the socket
  // and both history reads refuse a non-participant -- but asking first is what keeps a
  // record-only view from opening a connection it would only lose.
  participant: Boolean,
})
const emit = defineEmits(['status', 'message', 'sync', 'connected'])

const messages = ref([]), text = ref(''), pending = ref([])
const connected = ref(false), more = ref(false), busy = ref(false), scroller = ref(null)
const historyLoading = ref(false), error = ref(''), live = ref(null)
const video = ref(null), calls = ref([]), callPage = ref(1), callTotal = ref(0)
const imageInput = ref(null)
let socket, retryTimer, generation = 0, disposed = false

const paths = computed(() => roomPaths(props.kind, props.roomId))
const current = computed(() => live.value?.status ?? props.status)
const writable = computed(() => props.participant && roomWritable(props.kind, current.value))
// Read-only is not one thing: an ended consultation, a meeting nobody has started and
// a completed one each get their own sentence, so the disabled composer explains itself.
const notice = computed(() => roomNotice(props.kind, current.value))
const time = value => (value ? new Date(value).toLocaleString() : '—')

// The video pane signals over the chat socket, so it borrows this connection instead of
// opening one of its own.
function sendSignal(type, data) {
  if (!connected.value || socket?.readyState !== WebSocket.OPEN) throw new Error('Signaling is offline')
  socket.send(JSON.stringify({ type, data }))
}

async function loadCalls() {
  const version = generation
  try {
    const result = await work(`${paths.value.calls}?page=${callPage.value}&size=10`)
    if (version === generation) { calls.value = result.items; callTotal.value = result.total }
  } catch (err) { if (version === generation) error.value = err.message }
}

async function add(rows) {
  messages.value = mergeMessages(messages.value, rows)
  pending.value = confirmPending(pending.value, rows)
}

// Everything sent while the socket was down. Paging forward by id rather than by time is
// what makes a reconnect land without duplicates.
async function backfill(version) {
  let after = messages.value.at(-1)?.id || 0
  while (generation === version) {
    const data = await work(`${paths.value.messages}?after_id=${after}&size=100`)
    if (generation !== version) return
    await add(data.items)
    if (data.items.length < 100) break
    after = data.items.at(-1).id
  }
}

function stopSocket() {
  clearTimeout(retryTimer)
  if (socket) { socket.onclose = null; socket.close(); socket = null; emit('connected', false) }
  connected.value = false
}

function connect(version) {
  if (disposed || version !== generation || !props.roomId) return
  const url = new URL(`/ws/chat/${roomKey(props.kind, props.roomId)}`, location.href)
  url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('token', accessToken())
  const ws = new WebSocket(url); socket = ws
  ws.onopen = async () => {
    if (version !== generation) return ws.close()
    connected.value = true; emit('connected', true)
    // The screen owns the room's record, and this is the moment re-reading it is worth
    // it: the socket has just opened after being closed, and whatever moved while it was
    // down is in no frame this connection will ever see.
    emit('sync')
    try { await backfill(version); await loadCalls() }
    catch (err) { if (version === generation) error.value = err.message }
  }
  ws.onmessage = async event => {
    if (version !== generation) return
    const data = JSON.parse(event.data)
    if (data.type.startsWith('call_') || data.type === 'ice_candidate') await video.value?.receive(data.type, data.data)
    if (data.type === 'call_end') await loadCalls()
    if (data.type === 'ping') ws.send(JSON.stringify({ type: 'pong', data: {} }))
    if (data.type === 'message') { await add([data.data]); await bottom(); emit('message', data.data) }
    if (data.type === 'status') { live.value = liveFrame(data.data) || live.value; emit('status', data.data) }
    if (data.type === 'error') {
      error.value = data.data.message
      if (data.data.event_type?.startsWith('call_') || data.data.event_type === 'ice_candidate') video.value?.failed(data.data)
      const row = pending.value.find(row => row.client_id === data.data.client_id)
      if (row) row.failed = true
    }
  }
  ws.onclose = event => {
    if (version !== generation || disposed) return
    connected.value = false; emit('connected', false)
    video.value?.disconnected()
    pending.value.forEach(row => { row.failed = true })
    if (event.code === 1008) { error.value = 'Session expired or room access denied. Sign in again or choose another room.'; return }
    retryTimer = setTimeout(() => connect(version), 2000)
  }
}

async function open() {
  video.value?.finish()
  stopSocket()
  const version = ++generation
  calls.value = []; callPage.value = 1; callTotal.value = 0
  messages.value = []; pending.value = []; error.value = ''; more.value = false
  live.value = null
  if (!props.roomId) return
  historyLoading.value = true
  try {
    const data = await work(`${paths.value.messages}?size=20`)
    if (version !== generation) return
    await add(data.items); more.value = data.total > data.items.length
    if (props.participant) connect(version)
    await loadCalls(); await bottom()
  } catch (err) { if (version === generation) error.value = err.message }
  finally { if (version === generation) historyLoading.value = false }
}

async function older() {
  if (!more.value || busy.value || !messages.value.length) return
  busy.value = true; const version = generation; const height = scroller.value?.scrollHeight || 0
  try {
    const data = await work(`${paths.value.messages}?before_id=${messages.value[0].id}&size=20`)
    if (version !== generation) return
    await add(data.items); more.value = data.total > data.items.length
    await nextTick(); if (scroller.value) scroller.value.scrollTop += scroller.value.scrollHeight - height
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}

async function bottom() { await nextTick(); if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight }

async function deliver(row) {
  const version = generation
  row.failed = false
  try {
    if (connected.value && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'message', data: messageBody(row) }))
      // The socket does not acknowledge a message by itself, so an unanswered send is
      // the only sign that it did not arrive -- which is what the retry button is for.
      setTimeout(() => { if (pending.value.includes(row)) row.failed = true }, 8000)
    } else {
      const saved = await work(paths.value.messages, 'POST', messageBody(row))
      if (generation !== version) return
      await add([saved]); emit('message', saved)
    }
  } catch (err) { if (generation === version) { row.failed = true; error.value = err.message } }
  await bottom()
}

async function send(imageUrl = null) {
  if (!writable.value || (!text.value.trim() && !imageUrl)) return
  const row = { client_id: crypto.randomUUID(), content: text.value.trim(), image_url: imageUrl, failed: false }
  pending.value.push(row); text.value = ''; await deliver(row)
}

async function upload(event) {
  const file = event.target.files[0]; event.target.value = ''
  if (!file) return
  if (!writable.value || busy.value) return
  const problem = imageProblem(file)
  if (problem) { error.value = problem; return }
  const version = generation
  busy.value = true
  try {
    const form = new FormData(); form.append('file', file)
    const result = await work('/uploads/images', 'POST', form)
    if (version === generation) await send(result.url)
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}

// A different room is a different conversation: the history, the call log and the socket
// all belong to the id, so a new one closes the old room and opens the new.
watch(() => props.roomId, open, { immediate: true })
// A reader who joins later -- the assistant whose waiting consultation was accepted, the
// expert who answers an invitation while this screen is open -- connects without a reload.
watch(() => props.participant, participant => { if (participant && !socket) connect(generation) })
onUnmounted(() => { video.value?.finish(); disposed = true; generation++; stopSocket() })
</script>

<template>
  <section class="room-chat">
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <div ref="scroller" class="messages" role="log" aria-live="polite" @scroll="scroller.scrollTop < 30 && older()">
      <el-button v-if="more" :loading="busy" @click="older">Load earlier messages</el-button>
      <p v-if="historyLoading" role="status">Loading messages…</p>
      <p v-else-if="!messages.length" class="muted">No messages yet.</p>
      <article v-for="message in messages" :key="message.id" class="bubble"><strong>{{ message.sender_name }}</strong><small> {{ time(message.sent_at) }} · Delivered</small><p>{{ message.content }}</p><ChatImage v-if="message.image_url" :url="message.image_url" /></article>
      <article v-for="message in pending" :key="message.client_id" class="bubble pending"><p>{{ message.content || 'Image attachment' }}</p><span>{{ message.failed ? 'Not confirmed' : 'Sending…' }}</span><el-button v-if="message.failed && writable" size="small" @click="deliver(message)">Retry</el-button></article>
    </div>
    <form class="composer" @submit.prevent="send()">
      <el-input v-model="text" :disabled="!writable" placeholder="Write a message" maxlength="10000" />
      <el-button native-type="submit" type="primary" :disabled="!writable || !text.trim()">Send</el-button>
      <el-button native-type="button" :icon="Picture" :disabled="!writable || busy" @click="imageInput?.click()">Upload image</el-button>
      <input ref="imageInput" hidden aria-label="Upload chat image" type="file" accept="image/jpeg,image/png,image/webp" :disabled="!writable || busy" @change="upload" />
    </form>
    <p v-if="!writable" class="muted">{{ notice }}</p>
    <ConsultationVideo ref="video" :enabled="writable && connected" :send-signal="sendSignal" @finished="loadCalls" />
    <details><summary>Call history ({{ callTotal }})</summary>
      <p v-if="!calls.length" class="muted">No finished calls.</p>
      <p v-for="call in calls" :key="call.id">{{ time(call.started_at) }} · {{ time(call.ended_at) }} · {{ call.duration_seconds }}s connected · {{ call.end_reason }}</p>
      <el-pagination v-model:current-page="callPage" :total="callTotal" :page-size="10" layout="prev, next" @current-change="loadCalls" />
    </details>
  </section>
</template>
<style scoped>
.room-chat{min-width:0}.composer{display:flex;gap:12px;align-items:center;margin:12px 0;flex-wrap:wrap}.composer .el-input{flex:1;min-width:120px}.messages{height:48vh;min-height:260px;overflow:auto}.bubble{padding:12px;margin:12px 0;background:#eef6f4;border-radius:10px}.bubble p{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}.bubble small,.muted{color:#657871}.pending{opacity:.7}.error{color:#a42222}details{margin-top:12px}details summary{cursor:pointer;color:#657871}
</style>
