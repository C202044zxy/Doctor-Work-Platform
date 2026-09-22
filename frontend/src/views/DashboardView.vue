<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import {
  meetings as meetingsApi,
  patients as patientsApi,
  reminders as remindersApi,
} from '../api/client'
import { currentClinician, currentUserId, currentUsername } from '../session'
import { clockTime, isToday, weekAgenda, weekBounds } from '../week'

// 0915意见 item 2, and the third rewrite of this screen.
//
// It used to render `worklist`, `schedule` and `counts` out of api/demo-data.js --
// a fabricated worklist, a fabricated four-row day, and three fabricated headline
// numbers -- with no visible marker that any of it was invented. The file's own
// comment said "Every value here is fabricated" while `docs/02-测试场景.md` §4
// refuses a demo path built on exactly that. Everything below reads the real
// service instead, and the three mock exports are deleted.
//
// What it shows, and where each part comes from:
//
//   your account      GET /api/me, already in the session -- no request of its own
//   invitations       GET /api/meetings -- the meetings I am invited to and have
//                     not answered, the same predicate RemoteConsultationView uses
//   reminders         GET /api/reminders?unread_only=true, plus the count from
//                     /api/reminders/unread-count
//   this week         GET /api/meetings, bucketed by the reader's local day in
//                     src/week.js -- there is no scheduling endpoint in the
//                     contract, so what a "week" can hold today is consultations
//   your patients     GET /api/patients, for the scope count and the names
//
// The one thing it deliberately does not have is patient messages. M3 owns them
// and has no code at all: every path under `/api/consultations` in the contract is
// unimplemented. The panel says so rather than showing a conversation nobody can
// send, which is the mistake the old Consultations screen made.

const ROLE_LABELS = { admin: 'Administrator', senior: 'Senior physician', junior: 'Junior physician' }

const clinician = currentClinician

const now = new Date()
const hour = now.getHours()
const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
const today = now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })
const roleLabel = computed(() => ROLE_LABELS[clinician.value.role] ?? clinician.value.role)

const loading = ref(false)
const loadError = ref('')
const meetings = ref([])
const patients = ref([])
const patientTotal = ref(0)
const unreadReminders = ref([])
const unreadCount = ref(0)

// The week the reader is in, fixed at load: a page left open overnight should not
// reorganise itself underneath them.
const bounds = weekBounds(now)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [meetingPage, patientPage, reminderPage, count] = await Promise.all([
      // One page of each: the dashboard is a summary, and every panel below says
      // how many it is not showing.
      meetingsApi.list({ size: 50 }),
      patientsApi.list({ size: 100 }),
      // `unreadOnly` and not the bare list: reading the plain list *consumes* the
      // red dot (see the note on `GET /api/reminders`), and a dashboard that
      // silently clears a notification by being looked at would both lose the
      // record for the reader and make M6-T6's "红点出现 → 打开列表 → 红点消失"
      // unobservable, because the dot would be gone before it was drawn.
      remindersApi.list({ unreadOnly: true, size: 5 }),
      remindersApi.unreadCount(),
    ])
    meetings.value = meetingPage.items
    patients.value = patientPage.items
    patientTotal.value = patientPage.total
    unreadReminders.value = reminderPage.items
    unreadCount.value = count.unread
  } catch (error) {
    loadError.value = error.message
    meetings.value = []
    patients.value = []
    patientTotal.value = 0
    unreadReminders.value = []
    unreadCount.value = 0
  } finally {
    loading.value = false
  }
}

onMounted(load)

// Patient names, so a consultation reads as a person rather than as P20260001.
// A meeting for a patient outside the caller's scope has no entry here and falls
// back to the number, which is the honest answer: the name was not readable.
const byPatientNo = computed(() => {
  const index = new Map()
  for (const patient of patients.value) index.set(patient.patient_no, patient)
  return index
})

function patientName(patientNo) {
  return byPatientNo.value.get(patientNo)?.name ?? patientNo
}

function invitationOf(meeting) {
  return meeting?.participants?.find((person) => person.user_id === currentUserId.value) ?? null
}

// The same rule RemoteConsultationView applies to its invitation box: I was
// invited, I have not answered, and the meeting is still waiting on someone.
const invitations = computed(() =>
  meetings.value.filter(
    (meeting) =>
      invitationOf(meeting)?.status === 'invited' &&
      ['requested', 'accepted'].includes(meeting.status),
  ),
)

const agenda = computed(() => weekAgenda(meetings.value, bounds))
const weekCount = computed(() => agenda.value.reduce((sum, day) => sum + day.items.length, 0))
const attention = computed(() => invitations.value.length + unreadCount.value)

const figures = computed(() => [
  { label: 'Patients in your scope', value: patientTotal.value },
  { label: 'Consultations this week', value: weekCount.value },
  { label: 'Unread reminders', value: unreadCount.value },
])

function attendees(meeting) {
  const others = (meeting.participants ?? []).filter((person) => person.user_id !== meeting.initiator_id)
  const names = others.map((person) => person.name)
  if (!names.length) return meeting.initiator_name
  return `${meeting.initiator_name} with ${names.join(', ')}`
}
</script>

<template>
  <div class="page">
    <header class="lede">
      <h2 class="page-heading">{{ greeting }}, {{ clinician.name }}</h2>
      <p class="page-sub">
        <span>{{ today }}</span>
        <span>{{ roleLabel }} · {{ clinician.department }}</span>
      </p>
    </header>

    <dl class="figures">
      <div v-for="figure in figures" :key="figure.label">
        <dt>{{ figure.label }}</dt>
        <dd class="data">{{ figure.value }}</dd>
      </div>
    </dl>

    <div v-if="loadError" class="load-error" role="alert">
      <p class="load-error-title">Could not load your dashboard</p>
      <p class="load-error-detail">{{ loadError }}</p>
      <el-button :icon="Refresh" :loading="loading" @click="load">Try again</el-button>
    </div>

    <div v-else class="grid">
      <section v-loading="loading" class="panel">
        <header class="panel-head">
          <h3>Needs your attention</h3>
          <span class="panel-count data">{{ attention }}</span>
        </header>

        <p v-if="!attention" class="empty">
          Nothing is waiting on you: no invitation to answer and no unread reminder.
        </p>

        <template v-else>
          <div v-if="invitations.length" class="group">
            <p class="group-label">Consultation invitations</p>
            <ul class="items">
              <li
                v-for="meeting in invitations"
                :key="`m-${meeting.id}`"
                class="item"
                data-severity="warn"
              >
                <div class="item-head">
                  <span class="item-title">{{ patientName(meeting.patient_no) }}</span>
                  <span class="item-ref data">RC-{{ String(meeting.id).padStart(5, '0') }}</span>
                  <span class="chip" data-severity="warn">Awaiting your reply</span>
                </div>
                <p class="item-detail">
                  {{ meeting.initiator_name }} invites you to consult on
                  {{ meeting.purpose }}
                </p>
                <p class="item-meta">
                  <span class="data">{{ clockTime(meeting.scheduled_at) }}</span>
                  <router-link :to="{ name: 'consultations', query: { tab: 'remote' } }">
                    Open the invitation
                  </router-link>
                </p>
              </li>
            </ul>
          </div>

          <div v-if="unreadReminders.length" class="group">
            <p class="group-label">
              Unread reminders
              <!-- The panel asks for five. Saying so beats letting a reader count
                   five dots and conclude that is all there is. -->
              <span v-if="unreadCount > unreadReminders.length" class="group-scope data">
                {{ unreadReminders.length }} of {{ unreadCount }}
              </span>
            </p>
            <ul class="items">
              <li
                v-for="reminder in unreadReminders"
                :key="`r-${reminder.id}`"
                class="item"
                data-severity="ok"
              >
                <div class="item-head">
                  <span class="item-title">{{ reminder.title }}</span>
                  <span class="item-ref data">{{ reminder.patient_no }}</span>
                  <span class="chip" data-severity="ok">Due</span>
                </div>
                <p class="item-detail">{{ patientName(reminder.patient_no) }}</p>
                <p class="item-meta">
                  <span class="data">{{ clockTime(reminder.due_at) }}</span>
                  <router-link :to="{ name: 'patient-detail', params: { patientNo: reminder.patient_no } }">
                    Open the patient
                  </router-link>
                </p>
              </li>
            </ul>
            <!-- The mechanism, stated where the reader meets it: the dot is not
                 cleared by looking at it here. -->
            <p class="group-note muted">
              These stay here until a patient's reminder list is opened, which is what
              marks them read.
            </p>
          </div>
        </template>

        <!-- M3 landed after this panel was written: `/api/consultations` answers (three
             seeded rooms, one per state) and the socket route exists, so the "no code at
             all" note that stood here would now be a false statement on a demo screen.
             The workbench still does not summarise messages -- the consultation screen
             does -- so this points there rather than drawing an empty inbox. -->
        <div class="group">
          <p class="group-label">Patient messages</p>
          <p class="gap">
            <span class="chip" data-severity="info">On its own screen</span>
            Messages with patients are read and answered on the consultation screen,
            which the workbench does not summarise.
            <router-link :to="{ name: 'consultations' }">Open the consultations</router-link>.
          </p>
        </div>
      </section>

      <div class="rail">
        <section v-loading="loading" class="panel">
          <header class="panel-head">
            <h3>This week's consultations</h3>
            <span class="panel-tail">Week of {{ agenda[0]?.label ?? 'today' }}</span>
          </header>

          <p v-if="!agenda.length" class="empty">
            No consultation is scheduled this week. The contract has no scheduling endpoint, so
            this panel holds consultations and nothing else.
          </p>

          <ol v-else class="agenda">
            <li v-for="day in agenda" :key="day.key" class="day">
              <p class="day-head">
                <span class="day-label">{{ day.label }}</span>
                <span v-if="isToday(day.day, now)" class="chip" data-severity="info">Today</span>
              </p>
              <ul class="items">
                <li v-for="meeting in day.items" :key="meeting.id" class="slot">
                  <span class="slot-time data">{{ clockTime(meeting.scheduled_at) }}</span>
                  <span class="slot-body">
                    <span class="slot-patient">{{ patientName(meeting.patient_no) }}</span>
                    <span class="slot-kind">{{ attendees(meeting) }}</span>
                  </span>
                  <span
                    class="chip"
                    :data-severity="meeting.status === 'requested' ? 'warn' : 'ok'"
                  >
                    {{ meeting.status }}
                  </span>
                </li>
              </ul>
            </li>
          </ol>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Your account</h3>
          </header>
          <dl class="kv">
            <div>
              <dt>Name</dt>
              <dd>{{ clinician.name }}</dd>
            </div>
            <div>
              <dt>Username</dt>
              <dd class="data">{{ currentUsername }}</dd>
            </div>
            <div>
              <dt>Role</dt>
              <dd>{{ roleLabel }}</dd>
            </div>
            <div>
              <dt>Department</dt>
              <dd>{{ clinician.department }}</dd>
            </div>
          </dl>
        </section>
      </div>
    </div>
  </div>
</template>

<!-- .page, .panel, .panel-head, .panel-count, .panel-tail, .chip, .empty, .muted,
     .data and .kv come from src/style.css. What is particular to this screen is
     the figure strip, the notification groups and the week agenda. -->
<style scoped>
.lede {
  margin-bottom: 20px;
}

/* Figures ------------------------------------------------------------------ */

/* Three real numbers, on one line. Deliberately not cards: they are context for
   the panels below, not the point of the screen. */
.figures {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  margin: 0 0 20px;
  overflow: hidden;
  background: var(--line-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
}

.figures > div {
  padding: 13px 18px;
  background: var(--surface);
}

.figures dt {
  font-size: 12.5px;
  color: var(--ink-2);
}

.figures dd {
  margin: 5px 0 0;
  font-size: 24px;
  font-weight: 600;
  line-height: 1;
  color: var(--ink);
}

/* Layout ------------------------------------------------------------------- */

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(290px, 1fr);
  gap: 20px;
  align-items: start;
}

.rail {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* Notification groups ------------------------------------------------------ */

.group {
  padding: 0 20px;
}

.group + .group {
  border-top: 1px solid var(--line-2);
}

.group-label {
  margin: 15px 0 2px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ink-3);
  text-transform: uppercase;
}

/* The "5 of 36" tail: data, so it drops the small-caps treatment. */
.group-scope {
  margin-left: 8px;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
}

.items {
  padding: 0;
  margin: 0;
  list-style: none;
}

.item {
  position: relative;
  padding: 12px 0 13px 14px;
  border-bottom: 1px solid var(--line-2);
}

.item:last-child {
  border-bottom: 0;
}

/* Severity as an edge bar as well as a chip, so it never rests on colour
   alone. Same device the old worklist used. */
.item::before {
  position: absolute;
  top: 14px;
  bottom: 15px;
  left: 0;
  width: 2px;
  content: '';
  background: var(--sev, var(--ink-3));
  border-radius: 1px;
}

.item[data-severity='warn'] {
  --sev: var(--warn);
}

.item[data-severity='ok'] {
  --sev: var(--ok);
}

.item-head {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  align-items: baseline;
}

.item-title {
  font-size: 14px;
  font-weight: 600;
}

.item-ref {
  color: var(--ink-3);
}

.item-head .chip {
  margin-left: auto;
}

.item-detail {
  margin: 5px 0 0;
  font-size: 13.5px;
  line-height: 1.5;
}

.item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  align-items: baseline;
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--ink-2);
}

.item-meta a {
  font-weight: 600;
  color: var(--teal);
  text-decoration: none;
}

.item-meta a:hover {
  text-decoration: underline;
}

.group-note {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.5;
}

/* The gap, stated as text rather than as an empty conversation. */
.gap {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  margin: 8px 0 16px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink-2);
}

/* Week agenda -------------------------------------------------------------- */

.agenda {
  padding: 4px 20px 12px;
  margin: 0;
  list-style: none;
}

.day + .day {
  margin-top: 10px;
}

.day-head {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 0 6px;
  margin: 0;
  border-bottom: 1px solid var(--line-2);
}

.day-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
}

.slot {
  display: flex;
  gap: 12px;
  align-items: baseline;
  padding: 9px 0;
  border-bottom: 1px solid var(--line-2);
}

.day .items .slot:last-child {
  border-bottom: 0;
}

.slot-time {
  flex: none;
  color: var(--ink-2);
}

.slot-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.slot-patient {
  font-size: 13.5px;
  font-weight: 600;
}

.slot-kind {
  font-size: 12.5px;
  color: var(--ink-2);
}

/* Load failure ------------------------------------------------------------- */

/* Scoped, like the copies in PatientListView and AuditLogView: this pair is not
   in the global sheet. */
.load-error {
  padding: 18px 20px;
  background: var(--alert-soft);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
}

.load-error-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--alert-dark);
}

.load-error-detail {
  margin: 6px 0 14px;
  font-size: 12.5px;
  color: var(--ink-2);
}

/* `.empty` carries vertical padding only, so as a direct child of a panel it
   runs into the border. The same override the health panel needs. */
.panel > .empty {
  padding: 28px 20px;
}

@media (max-width: 1000px) {
  .grid,
  .figures {
    grid-template-columns: 1fr;
  }
}
</style>
