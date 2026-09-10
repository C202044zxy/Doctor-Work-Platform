<script setup>
import { computed, nextTick, reactive, ref, useTemplateRef } from 'vue'
import { ElMessage } from 'element-plus'
import { Paperclip, Promotion } from '@element-plus/icons-vue'
import { consultMessages, consultPatient, consultSessions } from '../api/demo-data'

// M3. Three columns: the queue, the conversation, and the patient the
// conversation is about. Task T27 wires this to the WebSocket; the composer
// below is already local-first, so sending appends to the thread exactly the
// way the socket will echo it back.

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'waiting', label: 'Waiting' },
  { key: 'active', label: 'In progress' },
  { key: 'ended', label: 'Ended' },
]

const STATE_LABELS = {
  waiting: 'Waiting',
  active: 'In progress',
  ended: 'Ended',
}

const STATE_SEVERITY = {
  waiting: 'warn',
  active: 'ok',
  ended: 'info',
}

const filter = ref('all')
const selectedId = ref(2)
const draft = ref('')
const threadEl = useTemplateRef('thread')

// One editable copy of every transcript, keyed by session.
const threads = reactive(
  Object.fromEntries(consultSessions.map((s) => [s.id, [...(consultMessages[s.id] ?? [])]])),
)

const visibleSessions = computed(() =>
  filter.value === 'all'
    ? consultSessions
    : consultSessions.filter((s) => s.state === filter.value),
)

const session = computed(() => consultSessions.find((s) => s.id === selectedId.value))
const messages = computed(() => threads[selectedId.value] ?? [])
const composerDisabled = computed(() => session.value?.state !== 'active')

function countFor(key) {
  return key === 'all'
    ? consultSessions.length
    : consultSessions.filter((s) => s.state === key).length
}

function open(id) {
  selectedId.value = id
  draft.value = ''
  scrollToEnd()
}

async function scrollToEnd() {
  await nextTick()
  if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight
}

async function send() {
  const text = draft.value.trim()
  if (!text) return

  const at = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  threads[selectedId.value].push({ id: `local-${Date.now()}`, from: 'doctor', text, at })
  draft.value = ''
  await scrollToEnd()
}

function attachImage() {
  // T27 uploads to server storage. Until then this only says what it will do.
  ElMessage.info('Image upload arrives with task T27.')
}

function endSession() {
  ElMessage.info('Ending a session arrives with task T27.')
}

scrollToEnd()
</script>

<template>
  <div class="page page-wide">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Consultations</h2>
        <p class="page-sub">
          <span>Text and image sessions with patients</span>
          <span>Video calls open from Remote Consultation</span>
        </p>
      </div>
    </header>

    <div class="workbench">
      <!-- Queue ------------------------------------------------------------ -->
      <section class="panel queue">
        <div class="filters" role="tablist">
          <button
            v-for="item in FILTERS"
            :key="item.key"
            type="button"
            role="tab"
            class="filter"
            :class="{ 'is-active': filter === item.key }"
            :aria-selected="filter === item.key"
            @click="filter = item.key"
          >
            {{ item.label }}
            <span class="filter-count data">{{ countFor(item.key) }}</span>
          </button>
        </div>

        <ul class="sessions">
          <li v-for="item in visibleSessions" :key="item.id">
            <button
              type="button"
              class="session"
              :class="{ 'is-selected': item.id === selectedId }"
              :data-severity="STATE_SEVERITY[item.state]"
              @click="open(item.id)"
            >
              <span class="session-head">
                <span class="session-name">{{ item.patient }}</span>
                <span class="session-id data">#{{ item.patientId }}</span>
                <span class="session-time data">{{ item.lastAt }}</span>
              </span>
              <span class="session-topic">{{ item.topic }}</span>
              <span class="session-preview">{{ item.preview }}</span>
              <span class="session-foot">
                <span class="chip">{{ STATE_LABELS[item.state] }}</span>
                <span v-if="item.unread" class="unread data">{{ item.unread }}</span>
              </span>
            </button>
          </li>
        </ul>
      </section>

      <!-- Conversation ----------------------------------------------------- -->
      <section v-if="session" class="panel conversation">
        <header class="panel-head">
          <h3>{{ session.patient }}</h3>
          <span class="chip" :data-severity="STATE_SEVERITY[session.state]">
            {{ STATE_LABELS[session.state] }}
          </span>
          <span class="panel-tail conv-topic">{{ session.topic }}</span>
          <el-button
            size="small"
            :disabled="session.state !== 'active'"
            @click="endSession"
          >
            End session
          </el-button>
        </header>

        <div ref="thread" class="thread">
          <template v-for="message in messages" :key="message.id">
            <p v-if="message.kind === 'system'" class="system">
              <span>{{ message.text }}</span>
              <span class="data">{{ message.at }}</span>
            </p>

            <article
              v-else
              class="bubble-row"
              :class="message.from === 'doctor' ? 'is-doctor' : 'is-patient'"
            >
              <div class="bubble">
                <p v-if="message.text" class="bubble-text">{{ message.text }}</p>

                <figure v-else-if="message.kind === 'image'" class="attachment">
                  <span class="attachment-art" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="20" height="20">
                      <path
                        d="M4 7.5h3l1.4-2h7.2l1.4 2h3v11H4z"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="1.5"
                        stroke-linejoin="round"
                      />
                      <circle cx="12" cy="12.6" r="3.1" fill="none" stroke="currentColor" stroke-width="1.5" />
                    </svg>
                  </span>
                  <figcaption class="attachment-meta">
                    <span class="attachment-name data">{{ message.file }}</span>
                    <span class="attachment-size data">{{ message.size }}</span>
                    <span class="attachment-caption">{{ message.caption }}</span>
                  </figcaption>
                </figure>

                <span class="bubble-time data">{{ message.at }}</span>
              </div>
            </article>
          </template>
        </div>

        <div class="composer">
          <el-input
            v-model="draft"
            type="textarea"
            :rows="2"
            resize="none"
            :disabled="composerDisabled"
            :placeholder="
              composerDisabled
                ? 'This session has ended. The transcript stays readable.'
                : 'Write to the patient'
            "
            @keydown.enter.exact.prevent="send"
          />
          <div class="composer-actions">
            <el-button :icon="Paperclip" :disabled="composerDisabled" @click="attachImage">
              Attach image
            </el-button>
            <el-button
              type="primary"
              :icon="Promotion"
              :disabled="composerDisabled || !draft.trim()"
              @click="send"
            >
              Send
            </el-button>
          </div>
        </div>
      </section>

      <!-- Patient context -------------------------------------------------- -->
      <div class="stack">
        <section class="panel">
          <header class="panel-head">
            <h3>Patient</h3>
            <span class="panel-tail data">#{{ consultPatient.id }}</span>
          </header>
          <dl class="kv">
            <div>
              <dt>Name</dt>
              <dd>{{ consultPatient.name }}</dd>
            </div>
            <div>
              <dt>Age and sex</dt>
              <dd class="data">{{ consultPatient.age }} · {{ consultPatient.sex }}</dd>
            </div>
            <div>
              <dt>Department</dt>
              <dd>{{ consultPatient.department }}</dd>
            </div>
            <div>
              <dt>Problem</dt>
              <dd>{{ consultPatient.problem }}</dd>
            </div>
          </dl>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Current medication</h3>
          </header>
          <ul class="meds">
            <li v-for="item in consultPatient.medication" :key="item">{{ item }}</li>
          </ul>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Last reading</h3>
          </header>
          <dl class="kv kv-lg">
            <div>
              <dt>Blood pressure</dt>
              <dd class="data">{{ consultPatient.lastReading }}</dd>
            </div>
            <div>
              <dt>Taken</dt>
              <dd class="data">{{ consultPatient.lastReadingAt }}</dd>
            </div>
          </dl>
        </section>

        <p class="conn">
          <span class="conn-dot" aria-hidden="true"></span>
          Connected over WebSocket
        </p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: 272px minmax(0, 1fr) 296px;
  gap: 20px;
  align-items: start;
}

/* Queue -------------------------------------------------------------------- */

.queue {
  overflow: hidden;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line-2);
}

.filter {
  padding: 5px 9px;
  font: inherit;
  font-size: 12.5px;
  color: var(--ink-2);
  cursor: pointer;
  background: none;
  border: 0;
  border-radius: var(--radius);
}

.filter:hover {
  background: var(--surface-2);
}

.filter.is-active {
  font-weight: 600;
  color: var(--teal-dark);
  background: var(--teal-soft);
}

.filter-count {
  margin-left: 4px;
  font-size: 11.5px;
  color: var(--ink-3);
}

.sessions {
  padding: 6px;
  margin: 0;
  list-style: none;
}

.session {
  display: block;
  width: 100%;
  padding: 10px 12px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: none;
  border: 0;
  border-radius: var(--radius);
}

.session:hover {
  background: var(--surface-2);
}

.session.is-selected {
  background: var(--teal-soft);
  box-shadow: inset 2px 0 0 var(--teal);
}

.session-head {
  display: flex;
  gap: 7px;
  align-items: baseline;
}

.session-name {
  font-size: 13.5px;
  font-weight: 600;
}

.session-id {
  font-size: 11.5px;
  color: var(--ink-3);
}

.session-time {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--ink-3);
}

.session-topic {
  display: block;
  margin-top: 3px;
  font-size: 12.5px;
  color: var(--ink-2);
}

.session-preview {
  display: -webkit-box;
  margin-top: 4px;
  overflow: hidden;
  font-size: 12px;
  line-height: 1.45;
  color: var(--ink-3);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.session-foot {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
}

.unread {
  padding: 1px 6px;
  margin-left: auto;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  background: var(--teal);
  border-radius: 9px;
}

/* Conversation ------------------------------------------------------------- */

.conversation {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.conv-topic {
  margin-left: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.thread {
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 460px;
  padding: 18px 20px;
  overflow-y: auto;
}

.system {
  display: flex;
  gap: 10px;
  align-items: baseline;
  justify-content: center;
  margin: 0;
  font-size: 11.5px;
  color: var(--ink-3);
}

.bubble-row {
  display: flex;
}

.bubble-row.is-doctor {
  justify-content: flex-end;
}

.bubble {
  max-width: min(78%, 46ch);
  padding: 9px 13px 7px;
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  border-radius: var(--radius-lg);
}

.bubble-row.is-doctor .bubble {
  color: var(--teal-dark);
  background: var(--teal-soft);
  border-color: transparent;
}

.bubble-text {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--ink);
}

.bubble-row.is-doctor .bubble-text {
  color: inherit;
}

.bubble-time {
  display: block;
  margin-top: 3px;
  font-size: 10.5px;
  color: var(--ink-3);
  text-align: right;
}

.bubble-row.is-doctor .bubble-time {
  color: var(--teal);
  opacity: 0.7;
}

/* An image message reads as a file, because there is no image to show. */
.attachment {
  display: flex;
  gap: 11px;
  align-items: center;
  padding: 4px 0 2px;
  margin: 0;
}

.attachment-art {
  display: grid;
  flex: none;
  place-items: center;
  width: 38px;
  height: 38px;
  color: var(--ink-3);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.attachment-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.attachment-name {
  font-size: 12.5px;
  font-weight: 600;
}

.attachment-size {
  font-size: 11px;
  color: var(--ink-3);
}

.attachment-caption {
  margin-top: 3px;
  font-size: 12px;
  color: var(--ink-2);
}

/* Composer ----------------------------------------------------------------- */

.composer {
  padding: 14px 20px 16px;
  border-top: 1px solid var(--line-2);
}

.composer-actions {
  display: flex;
  gap: 8px;
  justify-content: space-between;
  margin-top: 10px;
}

/* Rail --------------------------------------------------------------------- */

.meds {
  padding: 6px 20px 12px;
  margin: 0;
  list-style: none;
}

.meds li {
  padding: 7px 0;
  font-size: 12.5px;
  line-height: 1.45;
  color: var(--ink-2);
  border-bottom: 1px solid var(--line-2);
}

.meds li:last-child {
  border-bottom: 0;
}

.conn {
  display: flex;
  gap: 7px;
  align-items: center;
  margin: 0;
  font-size: 12px;
  color: var(--ink-3);
}

.conn-dot {
  width: 7px;
  height: 7px;
  background: var(--ok);
  border-radius: 50%;
}

@media (max-width: 1360px) {
  .workbench {
    grid-template-columns: 272px minmax(0, 1fr);
  }

  .stack {
    grid-column: 1 / -1;
    flex-direction: row;
    flex-wrap: wrap;
  }

  .stack > * {
    flex: 1 1 240px;
  }

  .conn {
    flex-basis: 100%;
  }
}

@media (max-width: 940px) {
  .workbench {
    grid-template-columns: 1fr;
  }

  .thread {
    height: 380px;
  }
}
</style>
