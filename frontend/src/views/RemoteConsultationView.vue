<script setup>
import { computed, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Plus } from '@element-plus/icons-vue'
import { meeting } from '../api/demo-data'

// M5. The demo moment this screen exists for is the time-limited access grant:
// an invited specialist can read one patient, and only until the consultation
// closes. The countdown is live, so a viewer can watch a grant lapse.
//
// Task T31 supplies the room and the grant lifecycle. Everything here is the
// fabricated consultation in api/demo-data.js.

const RENEW_SECONDS = 1800

// A copy, because the grants are decremented and renewed on screen.
const grants = reactive(meeting.participants.map((p) => ({ ...p })))

function tick() {
  for (const grant of grants) {
    if (grant.expiresInSeconds > 0) grant.expiresInSeconds -= 1
  }
}
const timer = setInterval(tick, 1000)
onUnmounted(() => clearInterval(timer))

function clock(seconds) {
  const m = Math.floor(Math.max(seconds, 0) / 60)
  const s = String(Math.max(seconds, 0) % 60).padStart(2, '0')
  return `${m}:${s}`
}

function renew(grant) {
  grant.expiresInSeconds = RENEW_SECONDS
  ElMessage.success(`Access for ${grant.name} extended by 30 minutes.`)
}

function saveReport() {
  ElMessage.info('Report rendering and print arrive with task T32.')
}

// The first state without a time is where the consultation stands.
const currentIndex = computed(() => {
  const index = meeting.states.findIndex((s) => !s.at)
  return index === -1 ? meeting.states.length - 1 : index
})

const reportOpen = ref(false)
const reportLine = computed(
  () =>
    `${meeting.patient} was reviewed jointly by ${grants.map((g) => g.name).join(', ')}. ` +
    `${meeting.opinions.length} specialist opinions are recorded against consultation ${meeting.id}.`,
)
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Remote Consultation</h2>
        <p class="page-sub">
          <span class="data">{{ meeting.id }}</span>
          <span>{{ meeting.patient }}, {{ meeting.age }}{{ meeting.sex === 'Male' ? 'M' : 'F' }}</span>
          <span>Opened {{ meeting.openedAt }}</span>
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Plus">Invite a specialist</el-button>
        <el-button type="primary" @click="reportOpen = true">Draft the report</el-button>
      </div>
    </header>

    <p class="topic">{{ meeting.topic }}</p>

    <div class="split">
      <div class="stack">
        <!-- State machine ---------------------------------------------------- -->
        <section class="panel">
          <header class="panel-head">
            <h3>Progress</h3>
            <span class="panel-tail">Requested by {{ meeting.requestedBy }}</span>
          </header>

          <ol class="states">
            <li
              v-for="(state, index) in meeting.states"
              :key="state.key"
              class="state"
              :data-position="index < currentIndex ? 'done' : index === currentIndex ? 'current' : 'ahead'"
            >
              <span class="state-mark" aria-hidden="true"></span>
              <span class="state-label">{{ state.label }}</span>
              <span class="state-at data">{{ state.at ?? '—' }}</span>
            </li>
          </ol>
        </section>

        <!-- Specialist opinions ---------------------------------------------- -->
        <section class="panel">
          <header class="panel-head">
            <h3>Specialist opinions</h3>
            <span class="panel-count data">{{ meeting.opinions.length }}</span>
          </header>

          <ul class="opinions">
            <li v-for="opinion in meeting.opinions" :key="opinion.id" class="opinion">
              <div class="opinion-head">
                <span class="opinion-author">{{ opinion.author }}</span>
                <span class="opinion-dept">{{ opinion.department }}</span>
                <span class="opinion-at data">{{ opinion.at }}</span>
              </div>
              <p class="opinion-text">{{ opinion.text }}</p>
            </li>
          </ul>
        </section>

        <!-- Report ------------------------------------------------------------ -->
        <section class="panel">
          <header class="panel-head">
            <h3>Consultation report</h3>
            <span class="panel-tail">Rendered on close, then printable</span>
          </header>
          <div class="panel-body">
            <p class="report-line">{{ reportLine }}</p>
            <p class="report-note">
              The report assembles the patient summary, the participants, the opinions above and the
              agreed conclusion. Saving it moves the consultation to Archived.
            </p>
            <el-button @click="reportOpen = true">Preview the report</el-button>
          </div>
        </section>
      </div>

      <!-- Rail ----------------------------------------------------------------- -->
      <div class="stack">
        <section class="panel">
          <header class="panel-head">
            <h3>Participants</h3>
            <span class="panel-count data">{{ grants.length }}</span>
          </header>

          <ul class="grants">
            <li
              v-for="grant in grants"
              :key="grant.name"
              class="grant"
              :data-severity="grant.expiresInSeconds === 0 ? 'alert' : 'ok'"
              :class="{ 'is-expired': grant.expiresInSeconds === 0 }"
            >
              <span class="grant-avatar" aria-hidden="true">{{ grant.initials }}</span>
              <div class="grant-body">
                <span class="grant-name">{{ grant.name }}</span>
                <span class="grant-dept">{{ grant.department }}</span>
                <span class="grant-role">{{ grant.role }}</span>

                <span v-if="grant.expiresInSeconds === null" class="grant-access">
                  Access for the duration of the consultation
                </span>

                <span v-else-if="grant.expiresInSeconds > 0" class="grant-access">
                  <span class="chip">{{ clock(grant.expiresInSeconds) }} left</span>
                </span>

                <span v-else class="grant-access">
                  <span class="chip">Access expired</span>
                  <button type="button" class="renew" @click="renew(grant)">Extend</button>
                </span>
              </div>
            </li>
          </ul>

          <p class="panel-foot grant-foot">
            Each invited specialist is granted access to this patient alone, and it lapses when the
            consultation closes.
          </p>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Shared materials</h3>
            <span class="panel-count data">{{ meeting.materials.length }}</span>
          </header>

          <ul class="materials">
            <li v-for="item in meeting.materials" :key="item.id" class="material">
              <span class="material-kind data">{{ item.kind }}</span>
              <div class="material-body">
                <span class="material-name">{{ item.name }}</span>
                <span class="material-meta data">
                  {{ item.size }} · {{ item.sharedBy }} · {{ item.at }}
                </span>
              </div>
              <el-button text size="small" :icon="Download" aria-label="Download" />
            </li>
          </ul>
        </section>
      </div>
    </div>

    <el-dialog v-model="reportOpen" title="Consultation report" width="640px">
      <article class="report">
        <h4 class="report-title">Remote consultation {{ meeting.id }}</h4>
        <dl class="report-meta">
          <div><dt>Patient</dt><dd>{{ meeting.patient }}, {{ meeting.age }}, {{ meeting.sex }}</dd></div>
          <div><dt>Topic</dt><dd>{{ meeting.topic }}</dd></div>
          <div><dt>Requested by</dt><dd>{{ meeting.requestedBy }}</dd></div>
          <div><dt>Opened</dt><dd class="data">{{ meeting.openedAt }}</dd></div>
        </dl>

        <h5 class="report-section">Participants</h5>
        <ul class="report-list">
          <li v-for="grant in grants" :key="grant.name">
            {{ grant.name }}, {{ grant.department }} — {{ grant.role }}
          </li>
        </ul>

        <h5 class="report-section">Opinions</h5>
        <div v-for="opinion in meeting.opinions" :key="opinion.id" class="report-opinion">
          <p class="report-opinion-head">{{ opinion.author }}, {{ opinion.department }}</p>
          <p class="report-opinion-text">{{ opinion.text }}</p>
        </div>

        <h5 class="report-section">Conclusion</h5>
        <p class="report-line">{{ reportLine }}</p>
      </article>

      <template #footer>
        <el-button @click="reportOpen = false">Close</el-button>
        <el-button type="primary" @click="saveReport">Save and print</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.topic {
  margin: -6px 0 18px;
  font-size: 13.5px;
  color: var(--ink-2);
}

/* State rail --------------------------------------------------------------- */

.states {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 1px;
  padding: 20px;
  margin: 0;
  list-style: none;
}

.state {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 18px;
}

/* The connecting line sits behind every mark but the first. */
.state::before {
  position: absolute;
  top: 5px;
  right: 0;
  left: 0;
  height: 1px;
  content: '';
  background: var(--line);
}

.state:first-child::before {
  left: 50%;
}

.state:last-child::before {
  right: 50%;
}

.state-mark {
  position: absolute;
  top: 0;
  left: 0;
  width: 11px;
  height: 11px;
  background: var(--surface);
  border: 2px solid var(--line);
  border-radius: 50%;
}

.state[data-position='done'] .state-mark {
  background: var(--teal);
  border-color: var(--teal);
}

.state[data-position='current'] .state-mark {
  background: var(--surface);
  border-color: var(--teal);
  box-shadow: 0 0 0 3px var(--teal-soft);
}

.state[data-position='done']::before,
.state[data-position='current']::before {
  background: var(--teal);
}

.state-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-3);
}

.state[data-position='done'] .state-label,
.state[data-position='current'] .state-label {
  color: var(--ink);
}

.state-at {
  font-size: 11.5px;
  color: var(--ink-3);
}

/* Opinions ----------------------------------------------------------------- */

.opinions {
  padding: 0 20px;
  margin: 0;
  list-style: none;
}

.opinion {
  padding: 15px 0 16px;
  border-bottom: 1px solid var(--line-2);
}

.opinion:last-child {
  border-bottom: 0;
}

.opinion-head {
  display: flex;
  gap: 9px;
  align-items: baseline;
}

.opinion-author {
  font-size: 13.5px;
  font-weight: 600;
}

.opinion-dept {
  font-size: 12.5px;
  color: var(--ink-2);
}

.opinion-at {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--ink-3);
}

.opinion-text {
  margin: 6px 0 0;
  font-size: 13.5px;
  line-height: 1.6;
}

/* Report panel ------------------------------------------------------------- */

.report-line {
  margin: 0 0 10px;
  font-size: 13.5px;
  line-height: 1.6;
}

.report-note {
  margin: 0 0 14px;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--ink-2);
}

/* Grants ------------------------------------------------------------------- */

.grants {
  padding: 6px 20px 10px;
  margin: 0;
  list-style: none;
}

.grant {
  display: flex;
  gap: 11px;
  padding: 12px 0;
  border-bottom: 1px solid var(--line-2);
}

.grant:last-child {
  border-bottom: 0;
}

.grant.is-expired {
  opacity: 0.72;
}

.grant-avatar {
  display: grid;
  flex: none;
  place-items: center;
  width: 30px;
  height: 30px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-2);
  background: var(--surface-2);
  border-radius: 50%;
}

.grant-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.grant-name {
  font-size: 13.5px;
  font-weight: 600;
}

.grant-dept,
.grant-role {
  font-size: 12px;
  color: var(--ink-2);
}

.grant-access {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 6px;
  font-size: 12px;
  color: var(--ink-3);
}

.renew {
  padding: 0;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  color: var(--teal);
  cursor: pointer;
  background: none;
  border: 0;
}

.renew:hover {
  text-decoration: underline;
}

.grant-foot {
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-3);
}

/* Materials ---------------------------------------------------------------- */

.materials {
  padding: 6px 12px 10px;
  margin: 0;
  list-style: none;
}

.material {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 9px 8px;
  border-bottom: 1px solid var(--line-2);
}

.material:last-child {
  border-bottom: 0;
}

.material-kind {
  flex: none;
  padding: 2px 6px;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--ink-2);
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  border-radius: 4px;
}

.material-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.material-name {
  overflow: hidden;
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.material-meta {
  font-size: 11px;
  color: var(--ink-3);
}

/* Report dialog ------------------------------------------------------------ */

.report-title {
  font-size: 16px;
}

.report-meta {
  padding: 0;
  margin: 14px 0 0;
}

.report-meta > div {
  display: flex;
  gap: 14px;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px solid var(--line-2);
}

.report-meta dt {
  font-size: 12.5px;
  color: var(--ink-2);
}

.report-meta dd {
  margin: 0;
  font-size: 12.5px;
  text-align: right;
}

.report-section {
  margin: 20px 0 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
}

.report-list {
  padding-left: 18px;
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
}

.report-opinion {
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--surface-2);
  border-radius: var(--radius);
}

.report-opinion-head {
  margin: 0;
  font-size: 12.5px;
  font-weight: 600;
}

.report-opinion-text {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 1.55;
}

@media (max-width: 720px) {
  .states {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .state::before {
    display: none;
  }
}
</style>
