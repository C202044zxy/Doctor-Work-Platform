<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Printer, Refresh } from '@element-plus/icons-vue'
import { meetings as meetingsApi, openReportSheet, patients as patientsApi } from '../api/client'
import { currentUserId } from '../session'
import PatientHealth from '../components/PatientHealth.vue'

// M2-04 owns the patient detail page. M5 needs exactly one thing on it: T32
// archives the consultation report into the patient record, and M5-T7 reads it
// back from the "会诊记录" tab. So the page is the identity header plus that tab
// -- histories, groups and the allergy editor are M2-04's to build, and leaving
// them absent is honest where a half-built version would not be.
//
// The tab's data path is `GET /api/meetings?patient_no=…`: without the patient
// filter the list would only return meetings the caller attended, which is
// precisely the audience the tab is not for.
//
// M6 adds a second tab, the same `PatientHealth` panels that the Health
// Management screen shows. It is `lazy`, so a visit that only wants the
// consultation records does not pay for five health requests.

const props = defineProps({ patientNo: { type: String, required: true } })

const router = useRouter()

const STATUS = {
  requested: { label: 'Awaiting reply', severity: 'warn' },
  accepted: { label: 'Accepted', severity: 'ok' },
  in_progress: { label: 'In progress', severity: 'ok' },
  completed: { label: 'Completed', severity: 'info' },
  declined: { label: 'Declined', severity: 'warn' },
}

const patient = ref(null)
const patientError = ref('')
const loadingPatient = ref(false)

// One entry per consultation: the meeting, and the report read out of it.
const records = ref([])
const recordsError = ref('')
const loadingRecords = ref(false)

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

// Printing is participants-only on the server, and a colleague from the same
// department reads this tab without having attended. Offering the button to
// someone the service refuses would be a lie the 403 tells on us.
function isParticipant(meeting) {
  return (
    meeting.initiator_id === currentUserId.value ||
    meeting.participants.some((person) => person.user_id === currentUserId.value)
  )
}

function versionsOf(row) {
  const top = row.latest ?? row.report?.version ?? 1
  return Array.from({ length: top }, (_, index) => top - index)
}

// An opinion carries a name only if one was sent with it; falling back to the
// participant list keeps a report written by an older client readable.
function nameOf(meeting, userId) {
  return (
    meeting.participants.find((person) => person.user_id === userId)?.name ?? `#${userId}`
  )
}

async function loadPatient() {
  loadingPatient.value = true
  patientError.value = ''
  try {
    patient.value = await patientsApi.get(props.patientNo)
  } catch (error) {
    patientError.value = error.message
    patient.value = null
  } finally {
    loadingPatient.value = false
  }
}

async function loadReport(row) {
  row.error = ''
  row.missing = false
  try {
    row.report = await meetingsApi.report(row.meeting.id, row.version || undefined)
    // Only the versionless read tells us which version is the newest.
    if (!row.version) row.latest = row.report.version
  } catch (error) {
    row.report = null
    // 404 is the ordinary "not written yet" answer, not a failure to report.
    if (error.status === 404) row.missing = true
    else row.error = error.message
  }
}

async function loadRecords() {
  loadingRecords.value = true
  recordsError.value = ''
  try {
    const page = await meetingsApi.list({ patientNo: props.patientNo, size: 50 })
    records.value = page.items.map((meeting) => ({
      meeting,
      report: null,
      missing: false,
      error: '',
      version: null,
      latest: null,
    }))
  } catch (error) {
    recordsError.value = error.message
    records.value = []
  } finally {
    loadingRecords.value = false
  }
  // The report is a sub-resource, so it is one read per consultation.
  await Promise.all(records.value.map((row) => loadReport(row)))
}

async function print(row) {
  try {
    await openReportSheet(row.meeting.id, row.version || undefined)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function backToDirectory() {
  router.push({ name: 'patients' })
}

watch(
  () => props.patientNo,
  () => {
    loadPatient()
    loadRecords()
  },
)

onMounted(() => {
  loadPatient()
  loadRecords()
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-heading">{{ patient?.name || patientNo }}</h2>
        <p class="page-sub">
          <span class="data">{{ patientNo }}</span>
          <span v-if="patient">{{ patient.department }}</span>
          <span v-if="patient">{{ patient.gender }}</span>
          <span v-if="patient?.admitted_at">Admitted {{ patient.admitted_at }}</span>
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Refresh" :loading="loadingPatient" @click="loadPatient">
          Refresh
        </el-button>
        <el-button link @click="backToDirectory">Back to the directory</el-button>
      </div>
    </header>

    <div v-if="patientError" class="load-error">
      <div>
        <p class="load-error-title">Could not load the patient</p>
        <p class="load-error-detail">{{ patientError }}</p>
      </div>
      <el-button :icon="Refresh" :loading="loadingPatient" @click="loadPatient">
        Try again
      </el-button>
    </div>

    <el-tabs v-else class="tabs">
      <el-tab-pane label="Consultation records">
        <div v-if="recordsError" class="load-error">
          <div>
            <p class="load-error-title">Could not load the consultation records</p>
            <p class="load-error-detail">{{ recordsError }}</p>
          </div>
          <el-button :icon="Refresh" :loading="loadingRecords" @click="loadRecords">
            Try again
          </el-button>
        </div>

        <p v-else-if="loadingRecords && !records.length" class="empty">
          Loading the consultation records…
        </p>

        <section v-else-if="records.length" class="panel">
          <header class="panel-head">
            <h3>Consultations</h3>
            <span class="panel-count data">{{ records.length }}</span>
            <span class="panel-tail">A report is archived here when the meeting closes</span>
          </header>

          <article v-for="row in records" :key="row.meeting.id" class="record">
            <header class="record-head">
              <span class="data">RC-{{ String(row.meeting.id).padStart(5, '0') }}</span>
              <span class="chip" :data-severity="statusOf(row.meeting).severity">
                {{ statusOf(row.meeting).label }}
              </span>
              <span class="muted data">{{ stamp(row.meeting.scheduled_at) }}</span>
            </header>

            <p class="record-purpose">{{ row.meeting.purpose }}</p>
            <p class="record-people muted">
              {{ row.meeting.initiator_name }} with
              {{ row.meeting.participants.map((person) => person.name).join(', ') }}
            </p>

            <p v-if="row.error" class="form-error">{{ row.error }}</p>
            <p v-else-if="row.missing" class="muted">
              No report has been written for this consultation yet.
            </p>

            <template v-else-if="row.report">
              <div class="record-report-head">
                <span class="muted">
                  Version <span class="data">{{ row.report.version }}</span> ·
                  {{ row.report.status }} · written by
                  {{ row.report.created_by_name }} ·
                  <span class="data">{{ stamp(row.report.created_at) }}</span>
                </span>
                <el-select
                  v-model="row.version"
                  class="version-picker"
                  placeholder="Newest version"
                  clearable
                  @change="loadReport(row)"
                >
                  <el-option
                    v-for="version in versionsOf(row)"
                    :key="version"
                    :label="`Version ${version}`"
                    :value="version"
                  />
                </el-select>
              </div>

              <ul class="opinions">
                <li
                  v-for="opinion in row.report.expert_opinions"
                  :key="opinion.expert_id"
                  class="opinion"
                >
                  <span class="opinion-author">
                    {{ opinion.expert_name || nameOf(row.meeting, opinion.expert_id) }}
                  </span>
                  <p class="opinion-text">{{ opinion.opinion }}</p>
                </li>
              </ul>

              <h4 class="report-heading">Conclusion</h4>
              <p class="report-conclusion">{{ row.report.conclusion }}</p>

              <div v-if="isParticipant(row.meeting)" class="record-actions">
                <el-button size="small" :icon="Printer" @click="print(row)">
                  Print preview
                </el-button>
              </div>
              <p v-else class="muted record-note">
                Printing belongs to the participants; the report itself is readable
                because the patient is in your department.
              </p>
            </template>
          </article>
        </section>

        <p v-else class="empty">
          No consultation has been held for this patient. Once one is written up, its
          report appears here.
        </p>

        <p class="muted tabs-note">
          Histories, groups and the allergy editor belong to the patient detail task
          (M2-04) and are not built here.
        </p>
      </el-tab-pane>

      <el-tab-pane label="Health data" lazy>
        <PatientHealth :patient-no="patientNo" :patient-name="patient?.name || ''" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<!-- Page furniture (.page, .panel, .chip, .empty, .muted) lives in src/style.css;
     only what is specific to this screen is here. -->
<style scoped>
.tabs-note {
  margin: 18px 0 0;
  font-size: 12.5px;
}

/* Each consultation is one block rather than a table row: the report underneath
   it is prose, and prose does not belong in a cell. */
.record {
  padding: 16px 20px;
  border-bottom: 1px solid var(--line-2);
}

.record:last-child {
  border-bottom: 0;
}

.record-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.record-purpose {
  margin: 10px 0 4px;
  font-size: 13.5px;
  white-space: pre-wrap;
}

.record-people {
  margin: 0;
  font-size: 12.5px;
}

.record-report-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  margin-top: 12px;
  font-size: 12.5px;
  border-top: 1px solid var(--line-2);
}

.version-picker {
  width: 168px;
}

.opinions {
  padding: 0;
  margin: 8px 0 0;
  list-style: none;
}

.opinion {
  padding: 8px 0;
  border-bottom: 1px solid var(--line-2);
}

.opinion:last-child {
  border-bottom: 0;
}

.opinion-author {
  font-size: 13px;
  font-weight: 600;
}

.opinion-text,
.report-conclusion {
  margin: 5px 0 0;
  font-size: 13.5px;
  line-height: 1.55;
  white-space: pre-wrap;
}

.report-heading {
  margin: 12px 0 0;
  font-size: 13px;
  color: var(--ink-2);
}

.report-conclusion {
  margin-top: 6px;
}

.record-actions {
  margin-top: 12px;
}

.record-note {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.5;
}

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
</style>
