<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { accessToken } from '../session'
import { work, mergeMessages } from '../api/work'
import ChatImage from '../components/ChatImage.vue'
import ConsultationVideo from '../components/ConsultationVideo.vue'
import { useRoute, useRouter } from 'vue-router'
import { Picture } from '@element-plus/icons-vue'
import { usePatientSearch } from '../patient-search'

const rooms = ref([]), status = ref('waiting'), patientNo = ref(''), error = ref('')
const room = ref(null), messages = ref([]), text = ref(''), pending = ref([])
const connected = ref(false), more = ref(false), busy = ref(false), scroller = ref(null)
const page = ref(1), total = ref(0)
const route = useRoute()
const router = useRouter()
const video = ref(null), calls = ref([]), callPage = ref(1), callTotal = ref(0)
const loading = ref(false), historyLoading = ref(false)
const imageInput = ref(null)
const { patients, searching, searchError, searchPatients, stopSearch } = usePatientSearch(work)
let listVersion = 0
let socket, retryTimer, generation = 0, disposed = false
const writable = computed(() => room.value?.status === 'active' && room.value?.is_participant)
const time = value => value ? new Date(value).toLocaleString() : '—'

function applyRoom(row) {
  // A delayed HTTP read must not overwrite the terminal WebSocket state.
  if (room.value?.id === row.id && room.value.status === 'ended' && row.status !== 'ended') return
  room.value = row
  if (status.value !== row.status) { status.value = row.status; page.value = 1 }
}

async function refresh() {
  const version = ++listVersion
  loading.value = true
  error.value = ''
  try {
    const data = await work(`/consultations?${new URLSearchParams({ status: status.value, page: page.value, size: 20, ...(patientNo.value ? { patient_no: patientNo.value.trim() } : {}) })}`)
    if (version === listVersion) { rooms.value = data.items; total.value = data.total }
  } catch (err) { error.value = err.message }
  finally { if (version === listVersion) loading.value = false }
}
function sendSignal(type, data) {
  if (!connected.value || socket?.readyState !== WebSocket.OPEN) throw new Error('Signaling is offline')
  socket.send(JSON.stringify({ type, data }))
}
async function loadCalls() {
  const version = generation
  try {
    const result = await work(`/consultations/${room.value.id}/calls?page=${callPage.value}&size=10`)
    if (version === generation) { calls.value = result.items; callTotal.value = result.total }
  } catch (err) { if (version === generation) error.value = err.message }
}
async function create() {
  if (!patientNo.value) return
  busy.value = true; error.value = ''
  try {
    await work('/consultations', 'POST', { patient_no: patientNo.value.trim() })
    status.value = 'waiting'; page.value = 1; await refresh()
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
function stopSocket() {
  clearTimeout(retryTimer)
  if (socket) { socket.onclose = null; socket.close(); socket = null }
  connected.value = false
}
async function add(rows) {
  messages.value = mergeMessages(messages.value, rows)
  const ids = new Set(rows.map(row => row.client_id).filter(Boolean))
  pending.value = pending.value.filter(row => !ids.has(row.client_id))
}
async function backfill(id, version) {
  let after = messages.value.at(-1)?.id || 0
  while (generation === version) {
    const data = await work(`/consultations/${id}/messages?after_id=${after}&size=100`)
    if (generation !== version) return
    await add(data.items)
    if (data.items.length < 100) break
    after = data.items.at(-1).id
  }
}
function connect(id, version) {
  if (disposed || version !== generation) return
  const url = new URL(`/ws/chat/${id}`, location.href)
  url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  url.searchParams.set('token', accessToken())
  const ws = new WebSocket(url); socket = ws
  ws.onopen = async () => {
    if (version !== generation) return ws.close()
    connected.value = true
    try {
      const current = await work(`/consultations/${id}`)
      if (version !== generation) return
      applyRoom(current)
      await refresh()
      await backfill(id, version)
      await loadCalls()
    } catch (err) { if (version === generation) error.value = err.message }
  }
  ws.onmessage = async event => {
    if (version !== generation) return
    const data = JSON.parse(event.data)
    if (data.type.startsWith('call_') || data.type === 'ice_candidate') await video.value?.receive(data.type, data.data)
    if (data.type === 'call_end') await loadCalls()
    if (data.type === 'ping') ws.send(JSON.stringify({ type: 'pong', data: {} }))
    if (data.type === 'message') { await add([data.data]); await bottom(); refresh() }
    if (data.type === 'status') { applyRoom(data.data); refresh() }
    if (data.type === 'error') {
      error.value = data.data.message
      if (data.data.event_type?.startsWith('call_') || data.data.event_type === 'ice_candidate') video.value?.failed(data.data)
      const row = pending.value.find(row => row.client_id === data.data.client_id)
      if (row) row.failed = true
    }
  }
  ws.onclose = event => {
    if (version !== generation || disposed) return
    connected.value = false
    video.value?.disconnected()
    pending.value.forEach(row => { row.failed = true })
    if (event.code === 1008) { error.value = 'Session expired or room access denied. Sign in again or choose another room.'; return }
    retryTimer = setTimeout(() => connect(id, version), 2000)
  }
}
async function open(row) {
  video.value?.finish()
  stopSocket(); const version = ++generation
  historyLoading.value = true
  calls.value = []; callPage.value = 1; callTotal.value = 0
  applyRoom(row)
  messages.value = []; pending.value = []; error.value = ''; more.value = false
  router.replace({ query: { ...route.query, room: row.id } })
  refresh()
  try {
    const data = await work(`/consultations/${row.id}/messages?size=20`)
    if (version !== generation) return
    await add(data.items); more.value = data.total > data.items.length
    if (row.is_participant) connect(row.id, version)
    await loadCalls(); await bottom()
  } catch (err) { if (version === generation) error.value = err.message }
  finally { if (version === generation) historyLoading.value = false }
}
async function older() {
  if (!more.value || busy.value || !messages.value.length) return
  busy.value = true; const version = generation; const height = scroller.value?.scrollHeight || 0
  try {
    const data = await work(`/consultations/${room.value.id}/messages?before_id=${messages.value[0].id}&size=20`)
    if (version !== generation) return
    await add(data.items); more.value = data.total > data.items.length
    await nextTick(); if (scroller.value) scroller.value.scrollTop += scroller.value.scrollHeight - height
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
async function bottom() { await nextTick(); if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight }
async function move(row, action) {
  busy.value = true; error.value = ''
  try {
    const changed = await work(`/consultations/${row.id}/${action}`, 'POST', {})
    status.value = changed.status; page.value = 1; await refresh(); await open(changed)
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
async function deliver(row) {
  const version = generation, roomId = room.value.id
  row.failed = false
  try {
    if (connected.value && socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'message', data: { content: row.content, image_url: row.image_url, client_id: row.client_id } }))
      setTimeout(() => { if (pending.value.includes(row)) row.failed = true }, 8000)
    } else {
      const saved = await work(`/consultations/${roomId}/messages`, 'POST', { content: row.content, image_url: row.image_url, client_id: row.client_id })
      if (generation !== version) return
      await add([saved]); refresh()
    }
  } catch (err) { if (generation === version) { row.failed = true; error.value = err.message } }
  await bottom()
}
async function send(image_url = null) {
  if (!writable.value || (!text.value.trim() && !image_url)) return
  const row = { client_id: crypto.randomUUID(), content: text.value.trim(), image_url, failed: false }
  pending.value.push(row); text.value = ''; await deliver(row)
}
async function upload(event) {
  const file = event.target.files[0]; event.target.value = ''
  if (!file) return
  if (!writable.value || busy.value) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) { error.value = 'Choose a JPEG, PNG, or WebP image'; return }
  if (file.size > 5 * 1024 * 1024) { error.value = 'Image exceeds the 5MB limit'; return }
  const version = generation
  busy.value = true
  try {
    const form = new FormData(); form.append('file', file)
    const result = await work('/uploads/images', 'POST', form)
    if (version === generation) await send(result.url)
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
onMounted(async () => {
  await refresh()
  if (route.query.room) {
    try { await open(await work(`/consultations/${route.query.room}`)) }
    catch (err) { error.value = err.message }
  }
})
onUnmounted(() => { stopSearch(); video.value?.finish(); disposed = true; generation++; stopSocket() })
</script>
<template>
  <section class="consult-work">
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <div class="toolbar">
      <router-link :to="{ name: 'consultations', query: { ...route.query, view: 'records' } }">Search consultation records</router-link>
      <el-select v-model="patientNo" filterable remote clearable :remote-method="searchPatients" :loading="searching" placeholder="Search patient name" aria-label="Search patient name" no-data-text="No matching patients" no-match-text="No matching patients" loading-text="Searching patients…" class="patient-picker" @change="page = 1; refresh()">
        <el-option v-for="patient in patients" :key="patient.patient_no" :value="patient.patient_no" :label="`${patient.name} · ${patient.patient_no}`">
          <span>{{ patient.name }}</span><span class="patient-number">{{ patient.patient_no }}</span>
        </el-option>
      </el-select>
      <el-button @click="page = 1; refresh()">Search</el-button>
      <el-button type="primary" :disabled="!patientNo || busy" @click="create">New consultation</el-button>
    </div>
    <p v-if="searchError" role="alert" class="error">{{ searchError }}</p>
    <div class="columns">
      <aside class="panel">
        <el-radio-group v-model="status" @change="page = 1; refresh()"><el-radio-button value="waiting">Waiting</el-radio-button><el-radio-button value="active">Active</el-radio-button><el-radio-button value="ended">Ended</el-radio-button></el-radio-group>
        <p v-if="loading" role="status">Loading consultations…</p>
        <p v-else-if="!rooms.length" class="muted">No consultations in this view.</p>
        <article v-for="item in rooms" :key="item.id" :class="['room', { selected: room?.id === item.id }]">
          <button class="room-open" @click="open(item)"><strong>{{ item.patient_name }}</strong> · {{ item.patient_no }}<p>{{ item.last_message || 'No messages yet' }}</p><small>Session #{{ item.id }} · Created {{ time(item.created_at) }}</small><small v-if="item.started_at"> · Started {{ time(item.started_at) }}</small></button>
          <el-button v-if="item.status === 'waiting'" size="small" :disabled="busy" @click="move(item, 'accept')">Accept</el-button>
          <small v-if="item.ended_at">Ended {{ time(item.ended_at) }}</small>
        </article>
        <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next" @current-change="refresh" />
      </aside>
      <section class="panel chat">
        <template v-if="room">
          <header><div><strong>{{ room.patient_name }} · Session #{{ room.id }}</strong><p class="muted">{{ room.status }} · {{ !room.is_participant ? 'Record access — read only' : connected ? 'Connected' : 'Offline — reconnecting / HTTP fallback' }}</p><p class="muted">Created {{ time(room.created_at) }} · Started {{ time(room.started_at) }}<span v-if="room.ended_at"> · Ended {{ time(room.ended_at) }}</span></p></div><el-button v-if="writable" :disabled="busy" @click="move(room, 'end')">End consultation</el-button></header>
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
          <p v-if="!writable" class="muted">This conversation is read-only.</p>
          <ConsultationVideo ref="video" :enabled="writable && connected" :send-signal="sendSignal" @finished="loadCalls" />
          <details><summary>Call history ({{ callTotal }})</summary>
            <p v-if="!calls.length">No finished calls.</p>
            <p v-for="call in calls" :key="call.id">{{ time(call.started_at) }} → {{ time(call.ended_at) }} · {{ call.duration_seconds }}s connected · {{ call.end_reason }}</p>
            <el-pagination v-model:current-page="callPage" :total="callTotal" :page-size="10" layout="prev, next" @current-change="loadCalls" />
          </details>
        </template>
        <p v-else class="muted">Choose a consultation to view its conversation.</p>
      </section>
    </div>
  </section>
</template>
<style scoped>
.toolbar{flex-wrap:wrap}.patient-picker{width:320px;max-width:100%}.patient-number{float:right;margin-left:20px;color:var(--ink-2,#657871);font-size:12px}.composer .el-input{flex:1;min-width:120px}.composer{flex-wrap:wrap}
.toolbar,.composer,header{display:flex;gap:12px;align-items:center;margin-bottom:18px}header{justify-content:space-between}.columns{display:grid;grid-template-columns:minmax(320px,1fr) 2fr;gap:20px}.panel{background:var(--surface,#fff);border:1px solid var(--line,#ddd);border-radius:12px;padding:20px;min-width:0}.room{padding:14px 0;border-bottom:1px solid #e5eceb}.room.selected{background:#edf6f3}.room-open{border:0;background:none;cursor:pointer;text-align:left;width:100%;font:inherit}.room p,.bubble p{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}.messages{height:48vh;min-height:260px;overflow:auto}.bubble{padding:12px;margin:12px 0;background:#eef6f4;border-radius:10px}.bubble small,.muted{color:#657871}.pending{opacity:.7}.error{color:#a42222} @media(max-width:950px){.columns{grid-template-columns:1fr}}
</style>
