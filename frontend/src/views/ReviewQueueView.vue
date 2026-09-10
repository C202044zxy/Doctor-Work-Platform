<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Lock } from '@element-plus/icons-vue'
import { archivedRecords, reviewDetails, reviewQueue } from '../api/demo-data'

// M4 review. A chief physician reads a submitted record, sees what changed
// since the returned version, and either approves it or sends it back with a
// reason. Approving archives the record, and an archived record is read-only.
//
// Task T24 supplies the decision endpoint. The queue below is local, so
// approving really does move the record out of the queue on screen.

const MIN_COMMENT = 15

// Local copies: deciding a record mutates both lists.
const queue = ref(reviewQueue.map((item) => ({ ...item })))
const archived = ref(archivedRecords.map((item) => ({ ...item })))
const selectedId = ref(queue.value[0]?.id ?? null)

const selected = computed(() => queue.value.find((item) => item.id === selectedId.value) ?? null)
const detail = computed(() => (selectedId.value ? reviewDetails[selectedId.value] : null))

const returnOpen = ref(false)
const comment = ref('')
const commentError = ref('')

const canReturn = computed(() => comment.value.trim().length >= MIN_COMMENT)

function openReturn() {
  comment.value = ''
  commentError.value = ''
  returnOpen.value = true
}

function submitReturn() {
  if (!canReturn.value) {
    commentError.value = `Give the author at least ${MIN_COMMENT} characters to work with.`
    return
  }
  const record = selected.value
  returnOpen.value = false
  drop(record.id)
  ElMessage.success(`${record.id} returned to ${record.author} with a comment.`)
}

function approve() {
  const record = selected.value
  if (!record) return

  archived.value.unshift({
    id: record.id,
    patient: record.patient,
    patientId: record.patientId,
    template: record.template,
    version: record.version,
    archivedAt: '10 September 2026, 15:58',
    approvedBy: 'Dr. Sun',
  })

  drop(record.id)
  ElMessage.success(`${record.id} approved and archived read-only.`)
}

// Removing the open record moves the pane to whatever is next in the queue.
function drop(id) {
  const index = queue.value.findIndex((item) => item.id === id)
  queue.value = queue.value.filter((item) => item.id !== id)
  const next = queue.value[Math.min(index, queue.value.length - 1)]
  selectedId.value = next?.id ?? null
}
</script>

<template>
  <div class="page page-wide">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Review Queue</h2>
        <p class="page-sub">
          <span>Chief physician only</span>
          <span class="data">{{ queue.length }}</span>
          <span>awaiting a decision</span>
        </p>
      </div>
    </header>

    <div class="review">
      <!-- Queue -------------------------------------------------------------- -->
      <div class="stack">
        <section class="panel">
          <header class="panel-head">
            <h3>Waiting</h3>
            <span class="panel-count data">{{ queue.length }}</span>
          </header>

          <ul v-if="queue.length" class="queue">
            <li v-for="item in queue" :key="item.id">
              <button
                type="button"
                class="queue-item"
                :class="{ 'is-selected': item.id === selectedId }"
                :data-severity="item.severity"
                @click="selectedId = item.id"
              >
                <span class="queue-head">
                  <span class="queue-patient">{{ item.patient }}</span>
                  <span class="queue-id data">{{ item.id }}</span>
                </span>
                <span class="queue-meta">
                  {{ item.template }}, v{{ item.version }} · {{ item.author }}
                </span>
                <span class="queue-foot">
                  <span class="chip">Waiting {{ item.waiting }}</span>
                  <span class="queue-at data">{{ item.submittedAt }}</span>
                </span>
              </button>
            </li>
          </ul>
          <p v-else class="empty queue-empty">
            Nothing is waiting. Submitted records appear here.
          </p>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Archived</h3>
            <span class="panel-count data">{{ archived.length }}</span>
          </header>

          <ul class="archived">
            <li v-for="item in archived" :key="item.id" class="archive-item">
              <div class="archive-head">
                <span class="archive-patient">{{ item.patient }}</span>
                <el-icon class="archive-lock"><Lock /></el-icon>
              </div>
              <p class="archive-meta">
                {{ item.template }}, v{{ item.version }} · {{ item.id }}
              </p>
              <p class="archive-when">{{ item.archivedAt }} · {{ item.approvedBy }}</p>
            </li>
          </ul>
        </section>
      </div>

      <!-- Open record -------------------------------------------------------- -->
      <div v-if="detail" class="stack">
        <section v-if="detail.previous" class="notice" data-severity="warn">
          <el-icon class="notice-icon"><Lock /></el-icon>
          <span>
            <strong>Returned once already.</strong>
            {{ detail.previous.returnedBy }} sent v{{ detail.previous.version }} back to
            {{ detail.previous.author }}: “{{ detail.previous.comment }}”
          </span>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>{{ detail.template }}</h3>
            <span class="chip" data-severity="warn">v{{ detail.version }} for review</span>
            <span class="panel-tail">
              {{ detail.patient }}, {{ detail.age }}{{ detail.sex === 'Female' ? 'F' : 'M' }} ·
              <span class="data">{{ detail.id }}</span>
            </span>
          </header>

          <dl class="kv">
            <div>
              <dt>Author</dt>
              <dd>{{ detail.author }}</dd>
            </div>
            <div>
              <dt>Submitted</dt>
              <dd class="data">{{ detail.submittedAt }}</dd>
            </div>
          </dl>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Record</h3>
            <span v-if="detail.previous" class="panel-tail">Changed fields are marked</span>
          </header>

          <div class="fields">
            <div
              v-for="field in detail.fields"
              :key="field.label"
              class="field-row"
              :class="{ 'is-changed': field.changed && detail.previous }"
            >
              <div class="field-row-head">
                <h4 class="field-name">{{ field.label }}</h4>
                <span v-if="field.changed && detail.previous" class="changed-mark">Changed</span>
              </div>
              <p class="field-value">{{ field.value }}</p>
            </div>
          </div>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Medical orders</h3>
            <span class="panel-count data">{{ detail.orders.length }}</span>
          </header>

          <ul class="orders">
            <li
              v-for="order in detail.orders"
              :key="order.id"
              class="order"
              :data-severity="order.level"
            >
              <span class="order-drug">{{ order.drug }}</span>
              <span class="order-dose data">{{ order.dose }}</span>
              <span class="order-route data">{{ order.route }}</span>
              <span class="order-freq">{{ order.frequency }}</span>
            </li>
          </ul>
        </section>

        <section class="panel decision">
          <div class="panel-body decision-body">
            <p class="decision-text">
              Approving locks v{{ detail.version }} to read-only and moves it to the archive. Returning
              it sends it back to {{ detail.author }} and keeps this version on the record.
            </p>
            <div class="decision-actions">
              <el-button @click="openReturn">Return with a comment</el-button>
              <el-button type="primary" @click="approve">Approve and archive</el-button>
            </div>
          </div>
        </section>
      </div>

      <section v-else class="panel">
        <p class="empty queue-empty">Select a record from the queue to review it.</p>
      </section>
    </div>

    <el-dialog v-model="returnOpen" title="Return this record" width="500px">
      <p class="dialog-lede">
        The author sees this comment against v{{ detail?.version }}. Be specific about what has to
        change.
      </p>

      <label class="field">
        <span class="field-label">Comment for {{ detail?.author }}</span>
        <el-input
          v-model="comment"
          type="textarea"
          :rows="4"
          placeholder="What needs to change before this can be approved?"
        />
        <span class="field-hint">
          <span class="data">{{ comment.trim().length }}</span> of {{ MIN_COMMENT }} characters
          minimum.
        </span>
      </label>

      <p v-if="commentError" class="form-error" role="alert">{{ commentError }}</p>

      <template #footer>
        <el-button @click="returnOpen = false">Cancel</el-button>
        <el-button :disabled="!canReturn" @click="submitReturn">Return to author</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.review {
  display: grid;
  grid-template-columns: minmax(272px, 340px) minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.notice-icon {
  flex: none;
  margin-top: 2px;
}

/* Queue -------------------------------------------------------------------- */

.queue {
  padding: 6px;
  margin: 0;
  list-style: none;
}

.queue-item {
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

.queue-item:hover {
  background: var(--surface-2);
}

.queue-item.is-selected {
  background: var(--teal-soft);
  box-shadow: inset 2px 0 0 var(--teal);
}

.queue-head {
  display: flex;
  gap: 8px;
  align-items: baseline;
}

.queue-patient {
  font-size: 13.5px;
  font-weight: 600;
}

.queue-id {
  font-size: 11px;
  color: var(--ink-3);
}

.queue-meta {
  display: block;
  margin-top: 3px;
  font-size: 12px;
  color: var(--ink-2);
}

.queue-foot {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
}

.queue-at {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--ink-3);
}

.queue-empty {
  padding: 24px 20px;
}

/* Archive ------------------------------------------------------------------ */

.archived {
  padding: 0 20px;
  margin: 0;
  list-style: none;
}

.archive-item {
  padding: 12px 0;
  border-bottom: 1px solid var(--line-2);
}

.archive-item:last-child {
  border-bottom: 0;
}

.archive-head {
  display: flex;
  gap: 8px;
  align-items: center;
}

.archive-patient {
  font-size: 13px;
  font-weight: 600;
}

.archive-lock {
  margin-left: auto;
  font-size: 13px;
  color: var(--ink-3);
}

.archive-meta,
.archive-when {
  margin: 3px 0 0;
  font-size: 11.5px;
  color: var(--ink-2);
}

.archive-when {
  color: var(--ink-3);
}

/* Record ------------------------------------------------------------------- */

.fields {
  padding: 4px 20px 14px;
}

.field-row {
  position: relative;
  padding: 14px 0 15px 14px;
  border-bottom: 1px solid var(--line-2);
}

.field-row:last-child {
  border-bottom: 0;
}

.field-row.is-changed::before {
  position: absolute;
  top: 16px;
  bottom: 17px;
  left: 0;
  width: 2px;
  content: '';
  background: var(--warn);
  border-radius: 1px;
}

.field-row-head {
  display: flex;
  gap: 10px;
  align-items: baseline;
}

.field-name {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
}

.changed-mark {
  margin-left: auto;
  font-size: 11px;
  font-weight: 600;
  color: var(--warn);
}

.field-value {
  margin: 5px 0 0;
  font-size: 13.5px;
  line-height: 1.6;
}

.orders {
  padding: 0 20px 12px;
  margin: 0;
  list-style: none;
}

.order {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  gap: 3px 10px;
  align-items: baseline;
  padding: 11px 0 12px 16px;
  border-bottom: 1px solid var(--line-2);
}

.order:last-child {
  border-bottom: 0;
}

.order::before {
  position: absolute;
  top: 13px;
  bottom: 14px;
  left: 0;
  width: 2px;
  content: '';
  background: var(--sev, var(--ok));
  border-radius: 1px;
}

.order-drug {
  font-size: 13.5px;
  font-weight: 600;
}

.order-dose {
  font-weight: 600;
}

.order-route,
.order-freq {
  font-size: 12.5px;
  color: var(--ink-2);
}

/* Decision ----------------------------------------------------------------- */

.decision-body {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  align-items: center;
  justify-content: space-between;
}

.decision-text {
  flex: 1 1 340px;
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink-2);
}

.decision-actions {
  display: flex;
  gap: 8px;
}

.dialog-lede {
  margin: 0 0 18px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink-2);
}

@media (max-width: 1100px) {
  .review {
    grid-template-columns: 1fr;
  }
}
</style>
