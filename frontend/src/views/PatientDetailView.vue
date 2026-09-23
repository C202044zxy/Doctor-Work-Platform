<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Printer, Refresh } from '@element-plus/icons-vue'
import {
  allergens as allergensApi,
  meetings as meetingsApi,
  openReportSheet,
  patients as patientsApi,
} from '../api/client'
import { currentUserId } from '../session'
import { allergySeverity, dateLabel, sexAge, timelineOf } from '../patient-record'
import { initials } from '../people'
import PatientHealth from '../components/PatientHealth.vue'

// M2-04 owns the patient detail page; M5 and M6 each borrow a tab.
//
// M5 needs exactly one thing here: T32 archives the consultation report into the
// patient record, and M5-T7 reads it back from the "Consultation records" tab.
// Its data path is `GET /api/meetings?patient_no=…` -- without the patient filter
// the list would only return meetings the caller attended, which is precisely the
// audience that tab is not for.
//
// M6 adds the Health data tab, the same `PatientHealth` panels the Health
// Management screen shows. It is `lazy`, so a visit that only wants the records
// does not pay for five health requests.
//
// M2's own parts are the face sheet above the tabs -- the allergy warning the
// directory only badges, the groups and tags this patient carries, and the
// editor for both allergies and history -- plus the history timeline itself and
// the identity block in the page head: the initials badge the consultation
// screens draw a person with, the sex and age as `patient-record.js` shapes them,
// and the two masked identifiers, which the detail payload has always carried and
// this page never showed.
//
// The timeline reads `patient.histories`, not
// `GET /api/patients/{patient_no}/histories`. One reader on the server produces
// both and has already ordered them newest onset first with the undated entries
// last, so a second request would fetch the same rows to get the same order, and
// leave the page with two lists to keep in step after every edit. A write re-reads
// this one detail response, which refreshes the timeline, the directory's red
// allergy badge and the warning bar together.
//
// The dates are formatted in `patient-record.js`: `onset_date` is a date-only
// string, and `new Date('2019-05-01')` is UTC midnight, which renders a day early
// for anyone west of Greenwich.

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

// --- the face sheet --------------------------------------------------------

const allergens = ref([])

const allergies = computed(() => patient.value?.allergies ?? [])
const groups = computed(() => patient.value?.groups ?? [])
const severity = computed(() => allergySeverity(allergies.value))

const SEVERITY_RANK = { severe: 0, moderate: 1, mild: 2 }

// The banner is read at a glance, so the entry that changes what may be
// prescribed goes first rather than wherever the record happened to be written.
const rankedAllergies = computed(() =>
  [...allergies.value].sort(
    (left, right) => (SEVERITY_RANK[left.severity] ?? 3) - (SEVERITY_RANK[right.severity] ?? 3),
  ),
)

// The dictionary supplies the display name. A code a clinic added itself is not in
// it and is shown as it was recorded, which is what the dictionary endpoint does
// for the picker too.
function allergenLabel(code) {
  return allergens.value.find((item) => item.code === code)?.name ?? code
}

// --- allergy editor --------------------------------------------------------

const allergyDialogOpen = ref(false)
const allergySaving = ref(false)
const allergyError = ref('')
const allergyForm = reactive({
  id: null,
  allergen: '',
  allergyType: 'drug',
  severity: 'mild',
  recordedAt: '',
  reaction: '',
})

function openAllergy(row = null) {
  allergyForm.id = row?.id ?? null
  allergyForm.allergen = row?.allergen ?? ''
  allergyForm.allergyType = row?.allergy_type ?? 'drug'
  allergyForm.severity = row?.severity ?? 'mild'
  allergyForm.recordedAt = row?.recorded_at ?? ''
  allergyForm.reaction = row?.reaction ?? ''
  allergyError.value = ''
  allergyDialogOpen.value = true
}

async function saveAllergy() {
  allergyError.value = ''
  if (!allergyForm.allergen.trim()) {
    allergyError.value = 'Choose a code from the dictionary or type one.'
    return
  }
  if (!allergyForm.recordedAt) {
    allergyError.value = 'Enter the date the allergy was recorded.'
    return
  }

  allergySaving.value = true
  try {
    const payload = {
      allergen: allergyForm.allergen.trim(),
      allergy_type: allergyForm.allergyType,
      severity: allergyForm.severity,
      recorded_at: allergyForm.recordedAt,
      // Omitted rather than sent blank: the column is nullable, and a blank
      // string is not the same record as no reaction at all.
      ...(allergyForm.reaction.trim() ? { reaction: allergyForm.reaction.trim() } : {}),
    }
    const wasEdit = Boolean(allergyForm.id)
    if (wasEdit) await patientsApi.allergies.update(allergyForm.id, payload)
    else await patientsApi.allergies.create(props.patientNo, payload)
    allergyDialogOpen.value = false
    // Everything on the page is derived from this one response -- the bar, the
    // list and the count -- so it is re-read rather than patched in place.
    await loadPatient()
    ElMessage.success(wasEdit ? 'Allergy updated.' : 'Allergy recorded.')
  } catch (error) {
    // 403 from another department's patient, 422 from a bad severity: both are
    // messages for the form, not reasons to lose the page behind it.
    allergyError.value = error.message
  } finally {
    allergySaving.value = false
  }
}

async function removeAllergy(row) {
  try {
    await ElMessageBox.confirm(
      `Remove the ${allergenLabel(row.allergen)} allergy? The audit trail keeps the name of what was removed.`,
      'Remove allergy',
      { confirmButtonText: 'Remove', cancelButtonText: 'Cancel', type: 'warning' },
    )
  } catch {
    return // dismissed
  }

  try {
    await patientsApi.allergies.remove(row.id)
    await loadPatient()
    ElMessage.success('Allergy removed.')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

// --- history timeline ------------------------------------------------------

const timeline = computed(() => timelineOf(patient.value?.histories))

const historyDialogOpen = ref(false)
const historySaving = ref(false)
const historyError = ref('')
const historyForm = reactive({ id: null, diagnosis: '', onsetDate: '', notes: '' })

function openHistory(entry = null) {
  historyForm.id = entry?.id ?? null
  historyForm.diagnosis = entry?.diagnosis ?? ''
  // '' is what the picker means by "no date", and it is what the server stores:
  // an entry without one is kept and sorted to the bottom of the timeline.
  historyForm.onsetDate = entry?.onset_date ?? ''
  historyForm.notes = entry?.notes ?? ''
  historyError.value = ''
  historyDialogOpen.value = true
}

async function saveHistory() {
  historyError.value = ''
  if (!historyForm.diagnosis.trim()) {
    historyError.value = 'Enter the diagnosis.'
    return
  }

  historySaving.value = true
  try {
    // `onset_date` is sent as an explicit null when the picker is cleared, because
    // that is how a wrong date comes back off an entry -- leaving the key out
    // would keep the date already stored.
    const payload = {
      diagnosis: historyForm.diagnosis.trim(),
      onset_date: historyForm.onsetDate || null,
      notes: historyForm.notes,
    }
    const wasEdit = Boolean(historyForm.id)
    if (wasEdit) await patientsApi.histories.update(historyForm.id, payload)
    else await patientsApi.histories.create(props.patientNo, payload)
    historyDialogOpen.value = false
    await loadPatient()
    ElMessage.success(wasEdit ? 'History entry updated.' : 'History entry added.')
  } catch (error) {
    historyError.value = error.message
  } finally {
    historySaving.value = false
  }
}

async function removeHistory(entry) {
  try {
    await ElMessageBox.confirm(
      `Delete the “${entry.diagnosis}” entry? The audit trail keeps the diagnosis and date of what was removed.`,
      'Delete history entry',
      { confirmButtonText: 'Delete', cancelButtonText: 'Cancel', type: 'warning' },
    )
  } catch {
    return // dismissed
  }

  try {
    await patientsApi.histories.remove(entry.id)
    await loadPatient()
    ElMessage.success('History entry deleted.')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

watch(
  () => props.patientNo,
  () => {
    loadPatient()
    loadRecords()
  },
)

onMounted(async () => {
  loadPatient()
  loadRecords()
  try {
    allergens.value = await allergensApi.list()
  } catch {
    // The picker accepts a typed code either way, so a missing dictionary costs
    // the display names and nothing else. `allergenLabel` falls back to the code.
  }
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <!-- The head answers who the page is about before the face sheet answers
           what not to do to them: the same identity block the directory and the
           consultation screens draw, then the facts the record carries. -->
      <div class="head-id">
        <span v-if="patient?.name" class="who-badge" aria-hidden="true">
          {{ initials(patient.name) }}
        </span>
        <div>
          <h2 class="page-heading">{{ patient?.name || patientNo }}</h2>
          <p class="page-sub">
            <span class="data">{{ patientNo }}</span>
            <span v-if="patient">{{ sexAge(patient) }}</span>
            <span v-if="patient">{{ patient.department }}</span>
            <!-- The same formatter the history timeline uses, so the two dates
                 on this page are not written two different ways. -->
            <span v-if="patient?.admitted_at" class="head-fact">
              <span class="sub-label">Admitted</span>
              <span class="data">{{ dateLabel(patient.admitted_at) }}</span>
            </span>
          </p>
          <!-- The service masks both identifiers before they leave it; showing
               them masked is what lets a reader confirm this is the right Zhang
               Wei without a number anyone could dial. A record that carries
               neither shows no line at all rather than a row of dashes. -->
          <p v-if="patient?.phone_masked || patient?.id_card_masked" class="page-sub">
            <span v-if="patient.phone_masked" class="head-fact">
              <span class="sub-label">Phone</span>
              <span class="data">{{ patient.phone_masked }}</span>
            </span>
            <span v-if="patient.id_card_masked" class="head-fact">
              <span class="sub-label">National ID</span>
              <span class="data">{{ patient.id_card_masked }}</span>
            </span>
          </p>
        </div>
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

    <!-- The face sheet and the tabs both depend on the same read, so each carries
         its own condition rather than nesting one inside the other. `loadPatient`
         clears `patient` on failure, which is what keeps the sheet out of the way
         when the error line is what belongs on screen. -->
    <section v-if="patient" class="panel face-sheet">
      <!-- The design system spends red on one thing: "Red means allergy.
           Nothing else in the interface is red." So the bar appears only when
           there is an allergy to warn about, and a patient with none gets a
           quiet sentence rather than a calm version of the same alarm. -->
      <div v-if="severity !== 'info'" class="notice" :data-severity="severity">
        <div>
          <strong>
            {{ severity === 'alert' ? 'Severe allergy on record' : 'Allergies on record' }}
          </strong>
          <p class="notice-body">
            {{
              rankedAllergies
                .map((row) => `${allergenLabel(row.allergen)} (${row.severity})`)
                .join(' · ')
            }}
          </p>
        </div>
      </div>
      <p v-else class="muted face-none">No allergy has been recorded for this patient.</p>

      <div class="face-rows">
        <div>
          <span class="field-label">Symptom tags</span>
          <p class="face-chips">
            <span v-for="tag in patient.symptom_tags" :key="tag" class="tag">{{ tag }}</span>
            <span v-if="!patient.symptom_tags?.length" class="muted">None recorded.</span>
          </p>
        </div>
        <div>
          <span class="field-label">Groups</span>
          <p class="face-chips">
            <span v-for="group in groups" :key="group.id" class="chip" data-severity="info">
              {{ group.name }} {{ group.member_count }}
            </span>
            <span v-if="!groups.length" class="muted">Not in a group.</span>
          </p>
        </div>
      </div>
    </section>

    <el-tabs v-if="!patientError" class="tabs">
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
      </el-tab-pane>

      <el-tab-pane label="Medical history">
        <section class="panel">
          <header class="panel-head">
            <h3>Medical history</h3>
            <span class="panel-count data">{{ timeline.length }}</span>
            <span class="panel-tail">
              <el-button link :icon="Plus" @click="openHistory()">Add an entry</el-button>
            </span>
          </header>

          <!-- Newest onset first, undated last: that order is the server's, and
               `timelineOf` deliberately does not repeat the rule. -->
          <ul v-if="timeline.length" class="timeline">
            <li
              v-for="entry in timeline"
              :key="entry.id"
              class="timeline-entry"
              :data-severity="entry.undated ? 'info' : 'ok'"
            >
              <div class="timeline-head">
                <span class="timeline-when data">{{ entry.onsetLabel }}</span>
                <span class="timeline-diagnosis">{{ entry.diagnosis }}</span>
                <span class="timeline-actions">
                  <el-button link @click="openHistory(entry)">Edit</el-button>
                  <el-button link @click="removeHistory(entry)">Delete</el-button>
                </span>
              </div>
              <p v-if="entry.notes" class="timeline-notes">{{ entry.notes }}</p>
            </li>
          </ul>

          <p v-else class="empty">
            No history recorded. An entry needs only a diagnosis — a date can be added
            later, and one never recorded is kept at the foot of the timeline.
          </p>
        </section>
      </el-tab-pane>

      <el-tab-pane label="Health data" lazy>
        <PatientHealth :patient-no="patientNo" :patient-name="patient?.name || ''" />
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="allergyDialogOpen" title="Allergy record" width="600px">
      <p class="dialog-note">
        The warning bar, the directory badge and the prescription check all read this
        one list, so what is saved here is what every screen acts on.
      </p>

      <label class="field">
        <span class="field-label">Allergen</span>
        <el-select
          v-model="allergyForm.allergen"
          class="full"
          filterable
          allow-create
          default-first-option
          placeholder="Code"
        >
          <el-option
            v-for="item in allergens"
            :key="item.code"
            :label="`${item.name} · ${item.code}`"
            :value="item.code"
          />
        </el-select>
      </label>

      <div class="field-row">
        <label class="field">
          <span class="field-label">Type</span>
          <el-select v-model="allergyForm.allergyType" class="full">
            <el-option label="Drug" value="drug" />
            <el-option label="Food" value="food" />
            <el-option label="Other" value="other" />
          </el-select>
        </label>

        <label class="field">
          <span class="field-label">Severity</span>
          <el-select v-model="allergyForm.severity" class="full">
            <el-option label="Mild" value="mild" />
            <el-option label="Moderate" value="moderate" />
            <el-option label="Severe" value="severe" />
          </el-select>
        </label>
      </div>

      <div class="field-row">
        <label class="field">
          <span class="field-label">Recorded</span>
          <el-date-picker
            v-model="allergyForm.recordedAt"
            class="full"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="Required"
          />
        </label>

        <label class="field">
          <span class="field-label">Reaction</span>
          <el-input v-model="allergyForm.reaction" maxlength="255" placeholder="Optional" />
        </label>
      </div>

      <p v-if="allergyError" class="form-error">{{ allergyError }}</p>

      <template #footer>
        <el-button @click="allergyDialogOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="allergySaving" @click="saveAllergy">
          {{ allergyForm.id ? 'Save changes' : 'Record allergy' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyDialogOpen" title="History entry" width="560px">
      <label class="field">
        <span class="field-label">Diagnosis</span>
        <el-input v-model="historyForm.diagnosis" maxlength="200" placeholder="Required" />
      </label>

      <label class="field">
        <span class="field-label">Onset date</span>
        <el-date-picker
          v-model="historyForm.onsetDate"
          class="full"
          type="date"
          value-format="YYYY-MM-DD"
          clearable
          placeholder="Leave empty if the date is not known"
        />
        <span class="field-hint">
          Optional. Clearing it removes the date from the entry rather than sending
          today's.
        </span>
      </label>

      <label class="field">
        <span class="field-label">Notes</span>
        <el-input
          v-model="historyForm.notes"
          type="textarea"
          :rows="3"
          maxlength="2000"
          placeholder="Optional"
        />
      </label>

      <p v-if="historyError" class="form-error">{{ historyError }}</p>

      <template #footer>
        <el-button @click="historyDialogOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="historySaving" @click="saveHistory">
          {{ historyForm.id ? 'Save changes' : 'Add entry' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<!-- Page furniture (.page, .panel, .chip, .empty, .muted) lives in src/style.css;
     only what is specific to this screen is here. -->
<style scoped>
/* The page head: the identity block on the left, the page actions on the right.
   The badge takes the same 40px the account card gives its own -- this is the
   other screen where one person is the subject of the whole page -- and it stays
   the motif's grey, because teal is the signed-in reader's own card and this is
   the patient. */
.head-id {
  display: flex;
  gap: 12px;
  align-items: center;
  min-width: 0;
}

.head-id .who-badge {
  width: 40px;
  height: 40px;
  font-size: 13.5px;
}

/* A label and its value are one inline flex row, so they are spaced by the gap
   rather than by a space in the template, which the compiler is free to condense
   away. The label steps back; the value keeps the head's ink and the data face. */
.head-fact {
  display: inline-flex;
  gap: 5px;
  align-items: baseline;
}

.sub-label {
  color: var(--ink-3);
}

/* The face sheet: the strip that answers "what must I not do to this patient"
   before anything else on the page. */
.face-sheet {
  padding: 16px 20px;
  margin-bottom: 18px;
}

.notice-body {
  margin: 3px 0 0;
  font-size: 12.5px;
}

.face-none {
  margin: 0;
  font-size: 13px;
}

.face-rows {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px 24px;
  margin-top: 16px;
}

.face-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  font-size: 13px;
}

/* The timeline. Each entry is a block, not a table row: the notes underneath are
   prose. The left edge is the severity channel from the design system, which is
   what makes "no onset date" visible as a fact rather than as a blank. */
.timeline {
  padding: 0;
  margin: 0;
  list-style: none;
}

.timeline-entry {
  position: relative;
  padding: 14px 20px 14px 36px;
  border-bottom: 1px solid var(--line-2);
}

.timeline-entry:last-child {
  border-bottom: 0;
}

.timeline-entry::before {
  position: absolute;
  top: 16px;
  bottom: 17px;
  left: 20px;
  width: 2px;
  content: '';
  background: var(--sev, var(--ok));
  border-radius: 1px;
}

.timeline-head {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: baseline;
}

.timeline-when {
  min-width: 108px;
  font-size: 12.5px;
  color: var(--ink-2);
}

.timeline-diagnosis {
  font-size: 13.5px;
  font-weight: 600;
}

.timeline-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.timeline-notes {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--ink-2);
  white-space: pre-wrap;
}

/* The three below are the same rules the directory and the user screen carry;
   each view keeps its own copy rather than promoting them to src/style.css,
   which is how `.field-row` and `.dialog-note` already live in this repository. */
.field-row {
  display: flex;
  gap: 12px;
}

.field-row > .field {
  flex: 1 1 0;
  min-width: 0;
}

.dialog-note {
  margin: 0 0 16px;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-3);
}

.tag {
  display: inline-block;
  padding: 1px 7px;
  margin: 0 4px 2px 0;
  font-size: 11.5px;
  color: var(--ink-2);
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
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
