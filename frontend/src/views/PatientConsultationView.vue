<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { work } from '../api/work'
import RoomPanel from '../components/RoomPanel.vue'
import { useRoute, useRouter } from 'vue-router'
import { usePatientSearch } from '../patient-search'
import { CONSULTATION } from '../room.js'

const rooms = ref([]), status = ref('waiting'), patientNo = ref(''), error = ref('')
const room = ref(null), busy = ref(false)
const connected = ref(false)
const page = ref(1), total = ref(0)
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const { patients, searching, searchError, searchPatients, stopSearch } = usePatientSearch(work)
let listVersion = 0
const writable = computed(() => room.value?.status === 'active' && room.value?.is_participant)
const time = value => value ? new Date(value).toLocaleString() : '\u2014'

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

async function create() {
  if (!patientNo.value) return
  busy.value = true; error.value = ''
  try {
    await work('/consultations', 'POST', { patient_no: patientNo.value.trim() })
    status.value = 'waiting'; page.value = 1; await refresh()
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}

// The conversation itself belongs to RoomPanel, which follows `room.id` -- history,
// sends, uploads, the video pane and the call log. What stays here is the room's own
// record: which consultations exist, who is in this one, and the buttons that move it.
async function open(row) {
  applyRoom(row)
  router.replace({ query: { ...route.query, room: row.id } })
  await refresh()
}

// The panel asks for this each time its socket opens: a status that moved while that
// connection was closed is in no frame it will ever receive.
async function sync() {
  if (!room.value) return
  try { applyRoom(await work(`/consultations/${room.value.id}`)); await refresh() }
  catch (err) { error.value = err.message }
}

function onStatus(payload) {
  applyRoom(payload)
  refresh()
}

async function move(row, action) {
  busy.value = true; error.value = ''
  try {
    const changed = await work(`/consultations/${row.id}/${action}`, 'POST', {})
    status.value = changed.status; page.value = 1; await refresh(); applyRoom(changed)
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
onUnmounted(() => stopSearch())
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
          <RoomPanel
            :kind="CONSULTATION"
            :room-id="room.id"
            :status="room.status"
            :participant="room.is_participant"
            @status="onStatus"
            @message="refresh"
            @sync="sync"
            @connected="connected = $event"
          />
        </template>
        <p v-else class="muted">Choose a consultation to view its conversation.</p>
      </section>
    </div>
  </section>
</template>
<style scoped>
.toolbar{flex-wrap:wrap}.patient-picker{width:320px;max-width:100%}.patient-number{float:right;margin-left:20px;color:var(--ink-2,#657871);font-size:12px}
.toolbar,header{display:flex;gap:12px;align-items:center;margin-bottom:18px}header{justify-content:space-between}.columns{display:grid;grid-template-columns:minmax(320px,1fr) 2fr;gap:20px}.panel{background:var(--surface,#fff);border:1px solid var(--line,#ddd);border-radius:12px;padding:20px;min-width:0}.room{padding:14px 0;border-bottom:1px solid #e5eceb}.room.selected{background:#edf6f3}.room-open{border:0;background:none;cursor:pointer;text-align:left;width:100%;font:inherit}.room p{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}.muted{color:#657871}.error{color:#a42222} @media(max-width:950px){.columns{grid-template-columns:1fr}}
</style>
