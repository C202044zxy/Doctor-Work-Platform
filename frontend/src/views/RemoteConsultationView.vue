<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Download, Plus, Printer, Refresh, UploadFilled } from '@element-plus/icons-vue'
import {
  downloadMaterial,
  meetings as meetingsApi,
  openReportSheet,
  patients as patientsApi,
  users as usersApi,
} from '../api/client'
import { initials } from '../people'
import { currentUserId } from '../session'
import { MEETING, meetingParticipant, meetingState } from '../room.js'
import RoomPanel from '../components/RoomPanel.vue'

// T30/T31/T32. Four states, one branch, and the two things that leave the
// module: the temporary grant every invitation creates, and the report that is
// archived into the patient record.
//
// This screen used to render `meeting` from api/demo-data.js. That data carried
// an `archived` state the contract does not have -- what gets archived is the
// *report* -- and a "renew access" button for a grant the server owns. Both are
// gone: the expiry belongs to the API, and nothing here can extend it.

const PAGE_SIZE = 20

// The machine in order. `declined` is a branch off `requested`, not a step on
// the way to `completed`, so it is a notice rather than a fifth dot.
const STAGES = [
  { key: 'requested', label: 'Requested' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'completed', label: 'Completed' },
]

// Severity stops at `warn`: red is reserved for allergy and safety, and an
// invitation that was declined is neither.
const STATUS = {
  requested: { label: 'Awaiting reply', severity: 'warn' },
  accepted: { label: 'Accepted', severity: 'ok' },
  in_progress: { label: 'In progress', severity: 'ok' },
  completed: { label: 'Completed', severity: 'info' },
  declined: { label: 'Declined', severity: 'warn' },
}

const me = currentUserId

const rows = ref([])
const total = ref(0)
const page = ref(1)
const listLoading = ref(false)
const listError = ref('')
const statusFilter = ref('')
const patientNoFilter = ref('')

const selectedId = ref(null)
const detail = ref(null)
const detailLoading = ref(false)
const detailError = ref('')

const materials = ref([])
const materialsError = ref('')
const uploading = ref(false)

const report = ref(null)
const reportError = ref('')
const reportMissing = ref(false)
const reportVersion = ref(null)
const latestVersion = ref(null)

const acting = ref(false)
const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const form = reactive({
  patientNo: '',
  participantIds: [],
  purpose: '',
  title: '',
  scheduledAt: null,
})
const patientOptions = ref([])
const patientLoading = ref(false)
const doctorOptions = ref([])
const doctorLoading = ref(false)

const editorOpen = ref(false)
const saving = ref(false)
const editorError = ref('')
const draft = reactive({ opinions: {}, conclusion: '' })
// `created_at` and friends are UTC instants; the reader is not. The same helper
// the audit log uses, so two screens never disagree about what 14:05 means.
function stamp(value) {
  if (!value) return ''
  const at = new Date(value)
  if (Number.isNaN(at.getTime())) return value
  const pad = (number) => String(number).padStart(2, '0')
  return (
    `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}` +
    ` ${pad(at.getHours())}:${pad(at.getMinutes())}`
  )
}

function statusOf(meeting) {
  return STATUS[meeting?.status] ?? { label: meeting?.status ?? '', severity: 'info' }
}

function size(bytes) {
  if (!bytes) return '0 KB'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// The badge in front of a shared file. The extension is what a reader scans for,
// and printing it beats an icon legend they would have to learn.
function extOf(filename) {
  const ext = (filename || '').split('.').pop()
  return ext && ext !== filename ? ext.slice(0, 4).toUpperCase() : 'FILE'
}

function invitationOf(meeting) {
  return meeting?.participants.find((person) => person.user_id === me.value) ?? null
}

const experts = computed(() => detail.value?.participants ?? [])

function nameOf(userId) {
  return experts.value.find((person) => person.user_id === userId)?.name ?? `#${userId}`
}

const invitation = computed(() => invitationOf(detail.value))
// Answerable while the meeting is still waiting on someone. Once it has started
// or completed the branch is closed, and the API answers 409 if it is tried.
const invited = computed(
  () =>
    invitation.value?.status === 'invited' &&
    ['requested', 'accepted'].includes(detail.value?.status),
)
const initiator = computed(() => detail.value?.initiator_id === me.value)
// Who is in the room, in the server's sense: the initiator plus every invited expert,
// a declined invitation included -- `meetingParticipant` is the same rule the meeting
// module already uses for materials and reports. The room is mounted on it, so a
// reader the meeting was not shared with never opens a socket at all.
const isParticipant = computed(() => meetingParticipant(detail.value, me.value))
const canStart = computed(() => initiator.value && detail.value?.status === 'accepted')
const canComplete = computed(() => initiator.value && detail.value?.status === 'in_progress')
const canWriteReport = computed(() => detail.value?.status === 'completed')
const stageIndex = computed(() => {
  const index = STAGES.findIndex((stage) => stage.key === detail.value?.status)
  return index === -1 ? 0 : index
})
// The invitation box is built from the same page of the list the screen shows,
// so it never disagrees with the table beside it.
const pendingInvitations = computed(() =>
  rows.value.filter(
    (row) =>
      invitationOf(row)?.status === 'invited' && ['requested', 'accepted'].includes(row.status),
  ),
)
// Versions run 1..n with no gaps, so the picker is derived from the newest one
// instead of asking for a list the contract does not publish.
const versionOptions = computed(() =>
  latestVersion.value
    ? Array.from({ length: latestVersion.value }, (_, index) => latestVersion.value - index)
    : [],
)
const nextStep = computed(() => {
  const meeting = detail.value
  if (!meeting) return ''
  if (meeting.status === 'declined') {
    return 'Every invited expert declined. The state machine has no step after this one.'
  }
  if (invited.value) return 'This invitation is waiting for your answer.'
  if (meeting.status === 'requested') {
    return 'Waiting for the invited experts. The first acceptance moves the consultation on.'
  }
  if (meeting.status === 'accepted') {
    return initiator.value
      ? 'Everyone is ready — start the consultation when you are.'
      : 'The initiator starts the consultation.'
  }
  if (meeting.status === 'in_progress') {
    return 'Share what the experts need, then complete the consultation to unlock the report.'
  }
  return report.value
    ? 'The report is archived to the patient record; print it for the signed sheet.'
    : 'Write the report: one line per expert plus the joint conclusion.'
})
const reportHint = computed(() => {
  if (!detail.value) return ''
  if (detail.value.status !== 'completed') {
    return 'A report can be written only once the consultation is completed.'
  }
  return report.value
    ? 'Saving again writes a new version; the earlier text stays readable.'
    : 'Nothing is written yet.'
})
function rowClass({ row }) {
  return row.id === selectedId.value ? 'row-active' : ''
}

function selectRow(row) {
  open(row.id)
}

function stageAt(key) {
  const meeting = detail.value
  if (!meeting) return '—'
  const at = {
    requested: meeting.created_at,
    // The contract records no acceptance timestamp: `accepted` names the state
    // the first acceptance produced, and that is all it claims.
    accepted: null,
    in_progress: meeting.started_at,
    completed: meeting.completed_at,
  }[key]
  return at ? stamp(at) : '—'
}

async function load() {
  listLoading.value = true
  listError.value = ''
  try {
    const result = await meetingsApi.list({
      status: statusFilter.value || '',
      patientNo: patientNoFilter.value.trim(),
      page: page.value,
      size: PAGE_SIZE,
    })
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    listError.value = error.message
    rows.value = []
    total.value = 0
  } finally {
    listLoading.value = false
  }
}

function search() {
  page.value = 1
  return load()
}

function changePage(next) {
  page.value = next
  return load()
}

async function loadMaterials() {
  materialsError.value = ''
  try {
    materials.value = await meetingsApi.materials(selectedId.value)
  } catch (error) {
    materials.value = []
    materialsError.value = error.message
  }
}

async function loadReport() {
  reportError.value = ''
  reportMissing.value = false
  try {
    report.value = await meetingsApi.report(selectedId.value, reportVersion.value || undefined)
    if (!reportVersion.value) latestVersion.value = report.value.version
  } catch (error) {
    report.value = null
    // 404 is the ordinary "not written yet" answer, not a failure to report.
    if (error.status === 404) {
      reportMissing.value = true
      if (!reportVersion.value) latestVersion.value = null
    } else {
      reportError.value = error.message
    }
  }
}

async function loadDetail() {
  detailError.value = ''
  detailLoading.value = true
  try {
    detail.value = await meetingsApi.get(selectedId.value)
  } catch (error) {
    detail.value = null
    detailError.value = error.message
  } finally {
    detailLoading.value = false
  }
  if (!detail.value) return
  // The detail answered, so the caller is a participant and both sub-resources
  // are theirs to read -- asking for them as a stranger would be a 403.
  await Promise.all([loadMaterials(), loadReport()])
}

// The room publishes a `status` frame whenever the meeting moves, and the move can be
// someone else's -- an expert watching the initiator start the consultation. The record
// is re-read without the loading state, because blanking the detail would unmount the
// very room that just received the frame.
async function refreshDetail() {
  try {
    detail.value = await meetingsApi.get(selectedId.value)
  } catch {
    // The frame already carried the new state, so a failed re-read is not worth
    // replacing what the screen shows.
  }
}

async function onRoomStatus() {
  await refreshDetail()
  await load()
}

function open(id) {
  selectedId.value = id
  detail.value = null
  detailError.value = ''
  materials.value = []
  materialsError.value = ''
  report.value = null
  reportError.value = ''
  reportMissing.value = false
  reportVersion.value = null
  latestVersion.value = null
  return loadDetail()
}
async function answer(action, meetingId = selectedId.value) {
  if (!meetingId) return
  acting.value = true
  try {
    await (action === 'accept'
      ? meetingsApi.accept(meetingId)
      : meetingsApi.decline(meetingId))
    ElMessage.success(action === 'accept' ? 'Invitation accepted.' : 'Invitation declined.')
    await load()
    if (meetingId === selectedId.value) await loadDetail()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    acting.value = false
  }
}

async function progress(action) {
  if (action === 'complete') {
    try {
      await ElMessageBox.confirm(
        'Completing unlocks the report. The temporary grants keep running until they expire on their own — completing does not revoke them.',
        'Complete the consultation',
        { confirmButtonText: 'Complete', cancelButtonText: 'Cancel' },
      )
    } catch {
      return
    }
  }
  acting.value = true
  try {
    detail.value =
      action === 'start'
        ? await meetingsApi.start(selectedId.value)
        : await meetingsApi.complete(selectedId.value)
    ElMessage.success(action === 'start' ? 'Consultation started.' : 'Consultation completed.')
    await load()
    await loadReport()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    acting.value = false
  }
}

// el-upload's `:http-request` hook: the component owns the picker, the client
// owns the request, so the multipart call is the same one the rest of the app
// makes rather than a second upload path.
async function uploadMaterial(options) {
  uploading.value = true
  materialsError.value = ''
  try {
    await meetingsApi.uploadMaterial(selectedId.value, options.file)
    options.onSuccess()
    await loadMaterials()
    ElMessage.success('File shared with the participants.')
  } catch (error) {
    materialsError.value = error.message
    options.onError(error)
  } finally {
    uploading.value = false
  }
}

async function download(material) {
  try {
    await downloadMaterial(material.id)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function printReport() {
  try {
    await openReportSheet(selectedId.value, reportVersion.value || undefined)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function openEditor() {
  draft.opinions = {}
  // One line per invited expert, pre-filled from the version being replaced, so
  // a new version is an edit rather than a retype.
  for (const person of experts.value) draft.opinions[person.user_id] = ''
  for (const opinion of report.value?.expert_opinions ?? []) {
    draft.opinions[opinion.expert_id] = opinion.opinion
  }
  draft.conclusion = report.value?.conclusion ?? ''
  editorError.value = ''
  editorOpen.value = true
}

async function saveReport() {
  editorError.value = ''
  const expertOpinions = experts.value
    .filter((person) => (draft.opinions[person.user_id] ?? '').trim() !== '')
    .map((person) => ({
      expert_id: person.user_id,
      expert_name: person.name,
      opinion: draft.opinions[person.user_id].trim(),
    }))
  if (!expertOpinions.length) {
    editorError.value = 'Record at least one expert opinion.'
    return
  }
  if (!draft.conclusion.trim()) {
    editorError.value = 'Write the conclusion.'
    return
  }

  saving.value = true
  try {
    report.value = await meetingsApi.saveReport(selectedId.value, {
      expert_opinions: expertOpinions,
      conclusion: draft.conclusion.trim(),
      status: 'final',
    })
    latestVersion.value = report.value.version
    reportVersion.value = null
    reportMissing.value = false
    editorOpen.value = false
    ElMessage.success(`Report v${report.value.version} archived to the patient record.`)
  } catch (error) {
    editorError.value = error.message
  } finally {
    saving.value = false
  }
}

function openCreate() {
  form.patientNo = ''
  form.participantIds = []
  form.purpose = ''
  form.title = ''
  form.scheduledAt = null
  createError.value = ''
  createOpen.value = true
  if (!patientOptions.value.length) loadPatients('')
  if (!doctorOptions.value.length) loadDoctors('')
}

async function loadPatients(query) {
  patientLoading.value = true
  try {
    const result = await patientsApi.list({ name: query ?? '', page: 1, size: 20 })
    patientOptions.value = result.items
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    patientLoading.value = false
  }
}

// T30 S1 has a junior physician start the consultation, so the picker cannot be an
// administrator-only read. M1-07 opened `GET /api/users` for exactly this: any
// signed-in caller, every department, with the contact fields on the rows withheld
// from everyone without `user.manage`. `status=active` moves the filter that used to
// be the server's private promise onto the contract — and the server applies it, so
// `total` stays honest while this list is narrowed by `q`.
async function loadDoctors(query) {
  doctorLoading.value = true
  try {
    const result = await usersApi.list({ q: query ?? '', status: 'active', size: 100 })
    doctorOptions.value = result.items
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    doctorLoading.value = false
  }
}

async function create() {
  createError.value = ''
  if (!form.patientNo) {
    createError.value = 'Choose a patient.'
    return
  }
  if (!form.participantIds.length) {
    createError.value = 'Invite at least one expert.'
    return
  }
  if (!form.purpose.trim()) {
    createError.value = 'The purpose is required — send the invitation with one.'
    return
  }

  creating.value = true
  try {
    const created = await meetingsApi.create({
      patient_no: form.patientNo,
      participant_ids: form.participantIds,
      purpose: form.purpose.trim(),
      title: form.title.trim() || null,
      // A Date goes over the wire as its ISO instant, which is what the
      // contract's aware datetime wants; omitted, the service stores now.
      scheduled_at: form.scheduledAt ? new Date(form.scheduledAt) : null,
    })
    createOpen.value = false
    page.value = 1
    await load()
    await open(created.id)
    ElMessage.success('Consultation requested. Each invited expert holds a 24-hour grant.')
  } catch (error) {
    createError.value = error.message
  } finally {
    creating.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page page-wide">
    <header class="screen-bar">
      <div>
        <h2 class="screen-title">Remote Consultation</h2>
        <p class="screen-sub">
          <span><span class="data">{{ total }}</span> consultations in scope</span>
          <span>An invitation opens a 24-hour window on one patient</span>
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="listLoading" @click="load">Refresh</el-button>
        <el-button type="primary" :icon="Plus" @click="openCreate">New consultation</el-button>
      </div>
    </header>

    <div class="split">
      <div class="stack">
        <!-- The list ---------------------------------------------------------- -->
        <section class="panel">
          <header class="panel-head">
            <h3>Consultations</h3>
            <span class="panel-count data">{{ total }}</span>
            <span class="panel-tail">Started by you, and invitations to you</span>
          </header>

          <div class="toolbar">
            <div class="filters">
              <el-select
                v-model="statusFilter"
                class="filter-status"
                clearable
                placeholder="Any status"
                :disabled="listLoading"
                @change="search"
              >
                <el-option
                  v-for="(meta, key) in STATUS"
                  :key="key"
                  :label="meta.label"
                  :value="key"
                />
              </el-select>
              <el-input
                v-model="patientNoFilter"
                class="filter-no"
                placeholder="Patient number"
                clearable
                :disabled="listLoading"
                @keyup.enter="search"
                @clear="search"
              />
              <el-button :loading="listLoading" @click="search">Search</el-button>
            </div>
          </div>

          <p class="panel-note">
            Filtering by patient number widens the list to that patient's consultations —
            it is how a colleague reads the archived report back out of the patient
            record. Outside your department the answer is an empty page, not an error.
          </p>

          <div v-if="listError" class="load-error">
            <div>
              <p class="load-error-title">Could not load the consultations</p>
              <p class="load-error-detail">{{ listError }}</p>
            </div>
            <el-button :icon="Refresh" :loading="listLoading" @click="load">Try again</el-button>
          </div>

          <el-table
            v-else
            v-loading="listLoading"
            :data="rows"
            class="table"
            :row-class-name="rowClass"
            @row-click="selectRow"
          >
            <el-table-column label="Ref" width="104">
              <template #default="{ row }">
                <span class="ref data">RC-{{ String(row.id).padStart(5, '0') }}</span>
              </template>
            </el-table-column>
            <el-table-column label="Patient" width="124">
              <template #default="{ row }">
                <span class="data">{{ row.patient_no }}</span>
              </template>
            </el-table-column>
            <el-table-column label="Purpose" min-width="200">
              <template #default="{ row }">
                <span class="purpose">{{ row.purpose }}</span>
              </template>
            </el-table-column>
            <el-table-column label="Status" width="140">
              <template #default="{ row }">
                <span class="chip" :data-severity="statusOf(row).severity">
                  {{ statusOf(row).label }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="Scheduled" width="156">
              <template #default="{ row }">
                <span class="data scheduled">{{ stamp(row.scheduled_at) }}</span>
              </template>
            </el-table-column>
            <template #empty>
              <div class="empty-state">
                <p class="empty">
                  No consultations yet. Start one and the invited expert finds it in their
                  invitation box.
                </p>
                <el-button :icon="Plus" @click="openCreate">New consultation</el-button>
              </div>
            </template>
          </el-table>

          <footer v-if="total > PAGE_SIZE" class="pager">
            <el-pagination
              layout="prev, pager, next"
              :current-page="page"
              :page-size="PAGE_SIZE"
              :total="total"
              @current-change="changePage"
            />
          </footer>
        </section>

        <!-- The detail -------------------------------------------------------- -->
        <section v-if="detailLoading" class="panel">
          <p class="empty">Loading the consultation…</p>
        </section>

        <section v-else-if="detail" class="panel">
          <header class="panel-head">
            <span class="ref data">RC-{{ String(detail.id).padStart(5, '0') }}</span>
            <span class="chip" :data-severity="statusOf(detail).severity">
              {{ statusOf(detail).label }}
            </span>
            <span class="panel-tail">{{ detail.title }}</span>
          </header>

          <div class="panel-body detail-grid">
            <dl class="facts">
              <div>
                <dt>Patient</dt>
                <dd class="data">{{ detail.patient_no }}</dd>
              </div>
              <div>
                <dt>Requested by</dt>
                <dd>{{ detail.initiator_name }}</dd>
              </div>
              <div class="wide">
                <dt>Purpose</dt>
                <dd>{{ detail.purpose }}</dd>
              </div>
              <div>
                <dt>Scheduled</dt>
                <dd class="data">{{ stamp(detail.scheduled_at) }}</dd>
              </div>
              <div>
                <dt>Requested</dt>
                <dd class="data">{{ stamp(detail.created_at) }}</dd>
              </div>
              <div v-if="detail.started_at">
                <dt>Started</dt>
                <dd class="data">{{ stamp(detail.started_at) }}</dd>
              </div>
              <div v-if="detail.completed_at">
                <dt>Completed</dt>
                <dd class="data">{{ stamp(detail.completed_at) }}</dd>
              </div>
            </dl>

            <ol class="states">
              <li
                v-for="(stage, index) in STAGES"
                :key="stage.key"
                class="state"
                :data-position="
                  index < stageIndex ? 'done' : index === stageIndex ? 'current' : 'ahead'
                "
              >
                <span class="state-mark" aria-hidden="true">
                  <el-icon v-if="index < stageIndex"><Check /></el-icon>
                </span>
                <span class="state-label">{{ stage.label }}</span>
                <span
                  class="state-at data"
                  :class="{ 'is-empty': stageAt(stage.key) === '—' }"
                >
                  {{ stageAt(stage.key) }}
                </span>
              </li>
            </ol>
          </div>

          <div v-if="detail.status === 'declined'" class="panel-body">
            <p class="notice" data-severity="warn">
              <span>
                Every invited expert declined. The consultation keeps this record; it
                cannot be started.
              </span>
            </p>
          </div>

          <footer class="panel-foot actions">
            <p class="next-step">{{ nextStep }}</p>
            <div class="page-actions">
              <template v-if="invited">
                <el-button :loading="acting" @click="answer('decline')">Decline</el-button>
                <el-button type="primary" :loading="acting" @click="answer('accept')">
                  Accept invitation
                </el-button>
              </template>
              <el-button v-if="canStart" type="primary" :loading="acting" @click="progress('start')">
                Start consultation
              </el-button>
              <el-button
                v-if="canComplete"
                type="primary"
                :loading="acting"
                @click="progress('complete')"
              >
                Complete consultation
              </el-button>
            </div>
          </footer>
        </section>

        <section v-else-if="detailError" class="panel">
          <div class="load-error">
            <div>
              <p class="load-error-title">Could not load the consultation</p>
              <p class="load-error-detail">{{ detailError }}</p>
            </div>
            <el-button :icon="Refresh" @click="loadDetail">Try again</el-button>
          </div>
        </section>

        <section v-else class="panel">
          <div class="empty-state">
            <p class="empty">
              Pick a consultation to see its participants, the material it shares and the
              report it archives.
            </p>
          </div>
        </section>

        <!-- The room ---------------------------------------------------------- -->
        <!-- M5's conversation is M3's room: one socket, one panel. It closes for
             writing when the meeting completes, and its history outlives the call. -->
        <section v-if="detail && isParticipant" class="panel">
          <header class="panel-head">
            <h3>Consultation room</h3>
            <span class="panel-count data">{{ meetingState(detail.status) }}</span>
            <span class="panel-tail">Text, images and a video call between the participants</span>
          </header>

          <!-- No note above the panel: the room says its own state, and a second
               paragraph saying it again would only be able to disagree. -->
          <div class="panel-body">
            <RoomPanel
              :kind="MEETING"
              :room-id="detail.id"
              :status="detail.status"
              :participant="isParticipant"
              @status="onRoomStatus"
              @message="load"
              @sync="refreshDetail"
            />
          </div>
        </section>

        <!-- Shared material --------------------------------------------------- -->
        <section v-if="detail" class="panel">
          <header class="panel-head">
            <h3>Shared material</h3>
            <span class="panel-count data">{{ materials.length }}</span>
            <span class="panel-tail">PDF, images and documents, up to 10 MB</span>
          </header>

          <div class="toolbar">
            <el-upload
              :http-request="uploadMaterial"
              :show-file-list="false"
              :disabled="uploading"
              accept=".pdf,.txt,.doc,.docx,.png,.jpg,.jpeg,.webp"
            >
              <el-button :icon="UploadFilled" :loading="uploading">Share a file</el-button>
            </el-upload>
            <span class="toolbar-note">
              Only this consultation's participants can list or download what is shared
              here — the refusal is the server's, not a hidden button's.
            </span>
          </div>

          <ul v-if="materials.length" class="materials">
            <li v-for="material in materials" :key="material.id" class="material">
              <span class="file-kind" aria-hidden="true">{{ extOf(material.filename) }}</span>
              <div class="material-main">
                <span class="material-name">{{ material.filename }}</span>
                <span class="material-meta data">
                  {{ size(material.size_bytes) }} · {{ material.uploaded_by_name }} ·
                  {{ stamp(material.uploaded_at) }}
                </span>
              </div>
              <el-button link :icon="Download" @click="download(material)">Download</el-button>
            </li>
          </ul>
          <p v-else class="empty">Nothing has been shared yet.</p>

          <p v-if="materialsError" class="form-error">{{ materialsError }}</p>
        </section>

        <!-- The report -------------------------------------------------------- -->
        <section v-if="detail" class="panel">
          <header class="panel-head">
            <h3>Consultation report</h3>
            <span v-if="latestVersion" class="panel-count data">v{{ latestVersion }}</span>
            <span class="panel-tail">
              <el-select
                v-model="reportVersion"
                class="version-picker"
                placeholder="Newest version"
                clearable
                @change="loadReport"
              >
                <el-option
                  v-for="version in versionOptions"
                  :key="version"
                  :label="`Version ${version}`"
                  :value="version"
                />
              </el-select>
            </span>
          </header>

          <div v-if="report" class="panel-body report">
            <p class="report-meta">
              <span class="chip" data-severity="info">{{ report.status }}</span>
              <span>Version <span class="data">{{ report.version }}</span></span>
              <span>Written by {{ report.created_by_name }}</span>
              <span class="data">{{ stamp(report.created_at) }}</span>
            </p>

            <h4 class="report-heading">Expert opinions ({{ report.expert_opinions.length }})</h4>
            <ul class="opinions">
              <li
                v-for="opinion in report.expert_opinions"
                :key="opinion.expert_id"
                class="opinion"
              >
                <div class="who">
                  <span class="who-badge" aria-hidden="true">
                    {{ initials(opinion.expert_name || nameOf(opinion.expert_id)) }}
                  </span>
                  <span class="who-text">
                    <span class="who-name">
                      {{ opinion.expert_name || nameOf(opinion.expert_id) }}
                    </span>
                  </span>
                </div>
                <p class="opinion-text">{{ opinion.opinion }}</p>
              </li>
            </ul>

            <h4 class="report-heading">Conclusion</h4>
            <p class="report-conclusion">{{ report.conclusion }}</p>
          </div>

          <div v-else-if="reportError" class="panel-body">
            <p class="form-error">{{ reportError }}</p>
          </div>

          <p v-else class="empty">
            {{
              reportMissing
                ? 'No report has been written for this consultation yet.'
                : 'Choose a version to read.'
            }}
          </p>

          <footer class="panel-foot actions">
            <p class="next-step">{{ reportHint }}</p>
            <div class="page-actions">
              <el-button v-if="canWriteReport" type="primary" @click="openEditor">
                {{ report ? 'Write a new version' : 'Write the report' }}
              </el-button>
              <el-button v-if="report" :icon="Printer" @click="printReport">
                Print preview
              </el-button>
            </div>
          </footer>
        </section>
      </div>

      <!-- The rail ------------------------------------------------------------ -->
      <aside class="stack">
        <section class="panel">
          <header class="panel-head">
            <h3>Invitation box</h3>
            <span class="panel-count data">{{ pendingInvitations.length }}</span>
          </header>

          <ul v-if="pendingInvitations.length" class="invites">
            <li v-for="row in pendingInvitations" :key="row.id" class="invite">
              <div class="invite-head">
                <span class="ref data">RC-{{ String(row.id).padStart(5, '0') }}</span>
                <span class="chip" data-severity="warn">Awaiting your answer</span>
              </div>
              <p class="invite-purpose">{{ row.purpose }}</p>
              <p class="invite-meta">
                <span class="data">{{ row.patient_no }}</span>
                · from {{ row.initiator_name }}
                · <span class="data">{{ stamp(row.scheduled_at) }}</span>
              </p>
              <div class="invite-actions">
                <el-button size="small" :loading="acting" @click="answer('decline', row.id)">
                  Decline
                </el-button>
                <el-button
                  size="small"
                  type="primary"
                  :loading="acting"
                  @click="answer('accept', row.id)"
                >
                  Accept
                </el-button>
              </div>
            </li>
          </ul>
          <p v-else class="empty">No invitation is waiting for an answer.</p>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Participants</h3>
            <span v-if="detail" class="panel-count data">{{ experts.length + 1 }}</span>
          </header>

          <template v-if="detail">
            <ul class="people">
              <li class="person">
                <div class="who">
                  <span class="who-badge" data-tone="teal" aria-hidden="true">
                    {{ initials(detail.initiator_name) }}
                  </span>
                  <span class="who-text">
                    <span class="who-name">{{ detail.initiator_name }}</span>
                    <span class="who-meta">Initiator</span>
                  </span>
                </div>
                <span class="chip" data-severity="info">Requested</span>
              </li>
              <li v-for="person in experts" :key="person.user_id" class="person">
                <div class="who">
                  <span class="who-badge" aria-hidden="true">{{ initials(person.name) }}</span>
                  <span class="who-text">
                    <span class="who-name">{{ person.name }}</span>
                    <span class="who-meta">{{ person.department }}</span>
                  </span>
                </div>
                <span class="chip" :data-severity="person.status === 'accepted' ? 'ok' : 'info'">
                  {{ person.status }}
                </span>
              </li>
            </ul>

            <div class="panel-body">
              <p class="notice" data-severity="info">
                <span>
                  Inviting an expert creates a temporary grant on
                  <span class="data">{{ detail.patient_no }}</span> until
                  <span class="data">{{ stamp(detail.scheduled_at) }}</span> plus 24 hours.
                  It expires on its own — nothing on this screen extends or revokes it.
                </span>
              </p>
            </div>
          </template>

          <p v-else class="empty">Pick a consultation to see who is taking part.</p>
        </section>
      </aside>
    </div>

    <el-dialog v-model="createOpen" title="New consultation" width="560px">
      <label class="field">
        <span class="field-label">Patient</span>
        <el-select
          v-model="form.patientNo"
          class="full"
          filterable
          remote
          reserve-keyword
          :remote-method="loadPatients"
          :loading="patientLoading"
          placeholder="Search by name"
        >
          <el-option
            v-for="patient in patientOptions"
            :key="patient.patient_no"
            :label="`${patient.patient_no} · ${patient.name}`"
            :value="patient.patient_no"
          />
        </el-select>
        <p class="field-hint">
          Only patients inside your own scope are listed; an out-of-scope number is
          refused by the service.
        </p>
      </label>

      <label class="field">
        <span class="field-label">Invited experts</span>
        <el-select
          v-model="form.participantIds"
          class="full"
          multiple
          filterable
          remote
          reserve-keyword
          :remote-method="loadDoctors"
          :loading="doctorLoading"
          placeholder="Search physicians"
        >
          <el-option
            v-for="doctor in doctorOptions"
            :key="doctor.id"
            :label="`${doctor.name} · ${doctor.title} · ${doctor.department}`"
            :value="doctor.id"
          />
        </el-select>
        <p class="field-hint">
          Each invited expert receives a temporary grant on the patient, valid until the
          scheduled time plus 24 hours. You cannot invite yourself.
        </p>
      </label>

      <label class="field">
        <span class="field-label">Purpose</span>
        <el-input
          v-model="form.purpose"
          type="textarea"
          :rows="3"
          maxlength="400"
          show-word-limit
          placeholder="What should the experts weigh in on?"
        />
      </label>

      <label class="field">
        <span class="field-label">Title (optional)</span>
        <el-input
          v-model="form.title"
          maxlength="200"
          placeholder="Left blank, the purpose becomes the title"
        />
      </label>

      <label class="field">
        <span class="field-label">Scheduled time (optional)</span>
        <el-date-picker
          v-model="form.scheduledAt"
          class="full"
          type="datetime"
          placeholder="Left blank, the service stores now"
        />
      </label>

      <p v-if="createError" class="form-error" role="alert">{{ createError }}</p>

      <template #footer>
        <el-button :disabled="creating" @click="createOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="creating" @click="create">Send invitation</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editorOpen" title="Consultation report" width="640px">
      <p class="field-hint editor-hint">
        Saving writes a new version; the text above stays readable. A blank line is left
        out of the report rather than stored empty.
      </p>

      <label v-for="person in experts" :key="person.user_id" class="field">
        <span class="field-label">{{ person.name }} · {{ person.department }}</span>
        <el-input
          v-model="draft.opinions[person.user_id]"
          type="textarea"
          :rows="3"
          maxlength="2000"
        />
      </label>

      <label class="field">
        <span class="field-label">Conclusion</span>
        <el-input v-model="draft.conclusion" type="textarea" :rows="4" maxlength="2000" />
      </label>

      <p v-if="editorError" class="form-error" role="alert">{{ editorError }}</p>

      <template #footer>
        <el-button :disabled="saving" @click="editorOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="saveReport">
          Save as a new version
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<!-- Page furniture (.page, .split, .panel, .who, .ref, .notice, .chip, .field,
     .empty, .muted) lives in src/style.css; only what is specific to this screen
     is here. -->
<style scoped>
/* The tab strip above this screen already prints "Consultations", so this page
   states its own name at section weight instead of opening a second heading
   directly under the first. */
.screen-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 14px;
  margin-bottom: 18px;
  border-bottom: 1px solid var(--line);
}

.screen-title {
  font-size: 17px;
  letter-spacing: -0.01em;
}

.screen-sub {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin: 5px 0 0;
  font-size: 12.5px;
  color: var(--ink-2);
}

.screen-sub > span + span::before {
  margin-right: 14px;
  color: var(--ink-3);
  content: '\00b7';
}

/* List --------------------------------------------------------------------- */

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.filter-status {
  width: 176px;
}

.filter-no {
  width: 168px;
}

.table {
  width: 100%;
}

/* Every row opens the detail below it, so it has to look like something that
   can be opened. */
.table :deep(tbody tr) {
  cursor: pointer;
}

/* Denser than the library default: the list is a picker, not the page. */
.table :deep(.el-table__cell) {
  padding: 9px 0;
}

/* The highlighted row is the one the detail below belongs to; the edge bar is
   the same marker the sidebar uses for the current screen. */
.table :deep(.row-active) td.el-table__cell {
  background: var(--teal-soft);
}

.table :deep(.row-active) td.el-table__cell:first-child {
  box-shadow: inset 3px 0 0 var(--teal);
}

.purpose {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Sized so that "2026-09-18 11:49" never wraps into two lines mid-table. */
.scheduled {
  white-space: nowrap;
}

.empty-state {
  padding: 26px 20px;
  text-align: center;
}

.empty-state .empty {
  padding: 0 0 12px;
}

/* Detail ------------------------------------------------------------------- */

/* The facts of the meeting on the left, the state machine down the right. */
.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 240px;
  gap: 2px 32px;
  align-items: start;
}

.facts {
  margin: 0;
}

.facts > div {
  display: flex;
  gap: 12px;
  align-items: baseline;
  justify-content: space-between;
  padding: 9px 0;
  border-bottom: 1px solid var(--line-2);
}

.facts > div:last-child {
  border-bottom: 0;
}

.facts dt {
  font-size: 13px;
  color: var(--ink-2);
}

.facts dd {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  text-align: right;
}

/* The purpose is a sentence rather than a value: it takes the full width and
   the paragraph's own alignment. */
.facts > div.wide {
  display: block;
}

.facts > div.wide dd {
  margin-top: 4px;
  font-weight: 400;
  text-align: left;
  white-space: pre-wrap;
}

.states {
  padding: 4px 0 0;
  margin: 0;
  list-style: none;
}

.state {
  position: relative;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr);
  column-gap: 11px;
  padding-bottom: 16px;
}

.state:last-child {
  padding-bottom: 0;
}

/* The rail hangs off the row rather than the marker, so it runs between the
   dots instead of around them. */
.state::before {
  position: absolute;
  top: 17px;
  bottom: -2px;
  left: 6px;
  width: 2px;
  content: '';
  background: var(--line);
}

.state:last-child::before {
  display: none;
}

.state[data-position='done']::before {
  background: var(--ok);
}

.state-mark {
  display: grid;
  grid-row: span 2;
  place-items: center;
  width: 14px;
  height: 14px;
  margin-top: 4px;
  font-size: 9px;
  color: #fff;
  background: var(--line);
  border-radius: 50%;
}

.state[data-position='done'] .state-mark {
  background: var(--ok);
}

.state[data-position='current'] .state-mark {
  background: var(--teal);
  box-shadow: 0 0 0 3px var(--teal-soft);
}

.state-label {
  font-size: 13px;
  color: var(--ink-3);
}

.state[data-position='done'] .state-label {
  color: var(--ink-2);
}

.state[data-position='current'] .state-label {
  font-weight: 600;
  color: var(--ink);
}

.state-at {
  font-size: 12px;
  color: var(--ink-3);
}

/* The contract records no acceptance time (M5-01), so that step shows the same
   dash the API does -- quieter than a date it does not have. */
.state-at.is-empty {
  color: var(--line);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}

.next-step {
  flex: 1 1 320px;
  margin: 0;
  font-size: 13px;
  color: var(--ink-2);
}

/* Rail and report ---------------------------------------------------------- */

.materials,
.invites,
.people,
.opinions {
  padding: 0;
  margin: 0;
  list-style: none;
}

.material,
.person {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--line-2);
}

.material:last-child,
.person:last-child {
  border-bottom: 0;
}

.material-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

/* The extension in front of a shared file: enough to tell a photograph from a
   scan without an icon set. */
.file-kind {
  flex: none;
  width: 40px;
  padding: 3px 0;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--ink-2);
  text-align: center;
  letter-spacing: 0.04em;
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  border-radius: 4px;
}

.material-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.material-meta {
  font-size: 12px;
  color: var(--ink-3);
}

/* One card per invitation, inset from the panel so the rail reads as a set of
   things waiting for an answer rather than as a list. */
.invites {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
}

.invite {
  padding: 12px 14px;
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}

.invite-head {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.invite-purpose {
  margin: 8px 0 5px;
  font-size: 13.5px;
  line-height: 1.45;
}

.invite-meta {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--ink-3);
}

.invite-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.version-picker {
  width: 168px;
}

.report-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: center;
  margin: 0 0 6px;
  font-size: 12.5px;
  color: var(--ink-2);
}

.opinion {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 14px 0;
  border-bottom: 1px solid var(--line-2);
}

.opinion:last-child {
  border-bottom: 0;
}

.opinion-text,
.report-conclusion {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.55;
  white-space: pre-wrap;
}

/* The conclusion is the sentence the report exists for, so it gets a block of
   its own instead of being the last paragraph in the stack. */
.report-heading {
  margin: 16px 0 7px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-2);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.report-conclusion {
  padding: 12px 14px;
  background: var(--surface-2);
  border-left: 3px solid var(--teal);
  border-radius: 0 var(--radius) var(--radius) 0;
}

/* The editor opens with a sentence about versioning; it needs the same gap
   below it that a field has. */
.editor-hint {
  margin: 0 0 18px;
}

/* T30's second scenario stops the service and expects "load failed, click to
   retry" rather than a spinner that never resolves. */
.load-error {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  margin: 0;
  background: var(--alert-soft);
}

.load-error-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--alert-dark);
}

.load-error-detail {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--ink-2);
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding: 14px 20px;
  border-top: 1px solid var(--line-2);
}

@media (max-width: 1100px) {
  .detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 900px) {
  .filter-status,
  .filter-no {
    width: 100%;
  }
}
</style>
