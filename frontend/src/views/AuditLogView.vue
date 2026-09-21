<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Refresh } from '@element-plus/icons-vue'
import { audit as auditApi, users as usersApi } from '../api/client'

// M8. An append-only trail: every write and every sensitive read, recorded with who
// did it, when, from where, on what, and how it turned out.
//
// T12. The rows are real now — `GET /api/audit-logs`, admin-only, paginated and
// filtered on the server. The CSV is real too, and it is produced by the backend
// rather than assembled here, because criterion 2 asks for three things the browser
// cannot promise on its own: the file agrees with the current filter, the filename
// carries the time range, and the bytes open in Excel without mojibake.

const PAGE_SIZE = 20

// The vocabulary the service can write, read from the service. This was a hand-copied
// array, and it had drifted in the way hand-copied arrays do: T17's five
// `patient_group.*` actions and T11's `temp_grant.expire` were never added, so the
// entries those tasks wrote could not be filtered for on the screen whose whole purpose
// is reviewing them. `GET /api/audit-logs/actions` publishes `audit.MARKED` now, and a
// task that adds an action makes it filterable without a change here.
//
// It stays a convenience and not a precondition: `action` is an exact-match string on
// the query, so the select still allows a typed value, and an empty list (the request
// failed, or a deployment older than the route) costs the dropdown and nothing else.
const actionVocabulary = ref([])

// `''` is "no condition" for both selects, and it is a real option value rather than a
// cleared select: `clearable` sets the model to `undefined`, which would leave the state
// saying "filtered" while nothing was being filtered.
const filters = reactive({ action: '', actor: '', range: null })

const rows = ref([])
const actors = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const exporting = ref(false)
const loadError = ref('')

// The user filter takes a `user_id`, so the dropdown needs ids. The accounts come
// from `loadActors()`; the rows on screen are merged in on top because a search
// narrows the list, and a selected value that is no longer an option would leave the
// filter saying "filtered by someone" with nothing to show which. The merge cannot
// resurrect an account the directory no longer lists — it only keeps one visible
// while its own entries are.
const actorOptions = computed(() => {
  const merged = new Map(actors.value.map((item) => [item.id, item.label]))
  rows.value.forEach((row) => {
    if (row.user_id !== null && row.user_id !== undefined && !merged.has(row.user_id)) {
      merged.set(row.user_id, row.username || `User #${row.user_id}`)
    }
  })
  if (filters.actor !== '' && !merged.has(filters.actor)) {
    merged.set(filters.actor, `User #${filters.actor}`)
  }
  return [...merged]
    .map(([id, label]) => ({ id, label }))
    .sort((left, right) => left.id - right.id)
})

// A row can have no account for two legitimate reasons, and neither is an error: the
// request failed before an identity was resolved (a rejected login, a signup), or the
// scheduler wrote it -- `temp_grant.expire` has no request behind it and tags itself
// `method: 'SYSTEM'`. Both used to render as the literal string `User #null`.
function actor(row) {
  if (row.username) return row.username
  if (row.user_id !== null && row.user_id !== undefined) return `User #${row.user_id}`
  return row.method === 'SYSTEM' ? 'System' : 'Unauthenticated'
}

const isFiltered = computed(
  () => filters.action !== '' || filters.actor !== '' || filters.range !== null,
)

// The picker gives a calendar day; the API wants an instant. `new Date('2026-09-13')` is
// parsed as UTC midnight, which for a UTC+8 reader is 8am the *previous* day, so the
// local time is built from the parts and `.toISOString()` converts it to the UTC instant
// the column is actually stored in.
function localInstant(day, hours, minutes, seconds, milliseconds) {
  const [year, month, date] = day.split('-').map(Number)
  return new Date(year, month - 1, date, hours, minutes, seconds, milliseconds).toISOString()
}

function currentParams() {
  const [from, to] = filters.range ?? []
  return {
    userId: filters.actor === '' ? null : filters.actor,
    action: filters.action,
    // The backend also filters on `object_type`. T12's criteria do not ask for it, so
    // the toolbar does not offer it rather than showing a control nothing demonstrates.
    objectType: '',
    from: from ? localInstant(from, 0, 0, 0, 0) : '',
    // The end of the chosen day, not the start of the next one: the server's `to` is
    // inclusive, so next-midnight would pull in a row written after the range ended.
    to: to ? localInstant(to, 23, 59, 59, 999) : '',
    page: page.value,
    size: PAGE_SIZE,
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const result = await auditApi.list(currentParams())
    rows.value = result.items
    // `total` counts every row matching the filter, not the rows on this page.
    total.value = result.total
  } catch (error) {
    loadError.value = error.message
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

// M1-07 landed `GET /api/users`, so the options come from the account table rather
// than being scraped out of the log. That matters for the empty case: an account
// with no entries yet is exactly the one an administrator may be looking for after
// creating it, and the log-derived list could never show it.
async function loadActors() {
  try {
    const result = await usersApi.list({ size: 100 })
    actors.value = result.items.map((row) => ({ id: row.id, label: row.name || row.username }))
  } catch {
    // `load()` reports the failure. Without this list the table still renders and the
    // other two conditions still work.
  }
}

function search() {
  // Back to the first page on every new search: staying on page 3 of a result set that
  // now has one row is how a search looks broken.
  page.value = 1
  load()
}

function clearFilters() {
  filters.action = ''
  filters.actor = ''
  filters.range = null
  search()
}

function changePage(next) {
  page.value = next
  load()
}

// `created_at` is a UTC instant and the reader is not. Showing it in local time is not a
// nicety here: the date filter is stated in local days, so a trail printed in UTC would
// disagree with the range that selected it.
function stamp(value) {
  if (!value) return ''
  const at = new Date(value)
  if (Number.isNaN(at.getTime())) return value
  const pad = (number) => String(number).padStart(2, '0')
  return (
    `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}` +
    ` ${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`
  )
}

function target(row) {
  return [row.object_type, row.object_id].filter(Boolean).join(' ')
}

// The contract has no `severity` column — the mock invented one for chip colour.
// `result` is the only outcome the log stores, so a failure is the only thing that earns
// a colour. A table where every successful read is green says nothing at all.
function severity(row) {
  return row.result === 'failure' ? 'alert' : 'info'
}

async function exportCsv() {
  if (!total.value) {
    ElMessage.info('Nothing to export with these filters.')
    return
  }

  exporting.value = true
  try {
    // The same conditions the list is showing, and no page number: the file covers every
    // match rather than the page on screen (criterion 2).
    await auditApi.exportCsv(currentParams())
    ElMessage.success(`${total.value} rows exported.`)
  } catch (error) {
    // The server's `message` is written for developers and does not go on screen, so the
    // reader gets copy that says what to do about it.
    console.error(error)
    ElMessage.error('The export could not be produced. Try again in a moment.')
  } finally {
    exporting.value = false
  }
}

async function loadActions() {
  try {
    actionVocabulary.value = await auditApi.actions()
  } catch {
    // The action filter stays typeable without it, which is how it worked before the
    // route existed at all.
    actionVocabulary.value = []
  }
}

onMounted(() => {
  loadActors()
  loadActions()
  load()
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Audit Log</h2>
        <p class="page-sub">
          <span>Append-only</span>
          <span>Updated to the second</span>
        </p>
      </div>
      <div class="page-actions">
        <el-button :icon="Download" :loading="exporting" @click="exportCsv">Export CSV</el-button>
      </div>
    </header>

    <section class="panel">
      <div class="toolbar">
        <div class="filters">
          <el-select
            v-model="filters.action"
            class="filter-action"
            filterable
            allow-create
            default-first-option
            aria-label="Action"
          >
            <el-option label="All actions" value="" />
            <el-option v-for="item in actionVocabulary" :key="item" :label="item" :value="item" />
          </el-select>

          <el-select
            v-model="filters.actor"
            class="filter-actor"
            filterable
            aria-label="Account"
          >
            <el-option label="All accounts" value="" />
            <el-option
              v-for="item in actorOptions"
              :key="item.id"
              :label="item.label"
              :value="item.id"
            />
          </el-select>

          <el-date-picker
            v-model="filters.range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="From"
            end-placeholder="To"
            class="filter-range"
          />
        </div>

        <div class="toolbar-right">
          <span class="result-count"><span class="data">{{ total }}</span> entries</span>
          <el-button v-if="isFiltered" link @click="clearFilters">Clear filters</el-button>
        </div>
      </div>

      <div v-if="loadError" class="load-error">
        <div>
          <p class="load-error-title">Could not load the audit log</p>
          <p class="load-error-detail">{{ loadError }}</p>
        </div>
        <el-button :icon="Refresh" :loading="loading" @click="load">Try again</el-button>
      </div>

      <el-table v-else v-loading="loading" :data="rows" class="table" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <pre v-if="row.detail" class="detail">{{ JSON.stringify(row.detail, null, 2) }}</pre>
            <p v-else class="detail detail-empty">This entry records no detail.</p>
          </template>
        </el-table-column>

        <el-table-column label="Time" width="184">
          <template #default="{ row }">
            <span class="data">{{ stamp(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Account" min-width="180">
          <template #default="{ row }">
            <span>{{ actor(row) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Action" width="190">
          <template #default="{ row }">
            <span class="chip" :data-severity="severity(row)">{{ row.action }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Target" min-width="150">
          <template #default="{ row }">
            <span class="data">{{ target(row) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Source" width="132">
          <template #default="{ row }">
            <span class="data">{{ row.ip }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Outcome" width="110">
          <template #default="{ row }">
            <span :class="row.result === 'success' ? 'outcome' : 'outcome outcome-bad'">
              {{ row.result }}
            </span>
          </template>
        </el-table-column>

        <template #empty>
          <p class="empty">
            {{ isFiltered ? 'No entries match these filters.' : 'The audit log is empty.' }}
          </p>
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

      <p class="panel-foot table-foot">
        Every field here is a stored column. Rows are inserted, never updated or deleted —
        the database refuses both — which is what makes the trail worth reading. Expand a row
        to see the detail its writer recorded.
      </p>
    </section>
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.filter-action {
  width: 190px;
}

.filter-actor {
  width: 200px;
}

.filter-range {
  width: 260px;
}

.toolbar-right {
  display: flex;
  gap: 14px;
  align-items: center;
}

.result-count {
  font-size: 12.5px;
  color: var(--ink-2);
}

/* T15's second scenario stops the service and expects "load failed, click to retry"
   rather than a spinner that never resolves or a blank panel. Same block as the
   patient list, which is scoped there rather than shared. */
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

.table {
  width: 100%;
}

/* `detail` is a JSON object, not a sentence: it gets the data font and keeps its own
   line breaks, or the one thing the row was expanded to read is the one thing that
   becomes unreadable. */
.detail {
  padding: 6px 16px 8px 48px;
  margin: 0;
  font-family: var(--font-data);
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-2);
  white-space: pre-wrap;
  overflow-x: auto;
}

.detail-empty {
  font-family: var(--font-ui);
  font-style: italic;
  color: var(--ink-3);
}

.outcome {
  font-size: 12.5px;
  color: var(--ok);
}

.outcome-bad {
  font-weight: 600;
  color: var(--alert);
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding: 14px 20px;
  border-top: 1px solid var(--line-2);
}

.table-foot {
  font-size: 12px;
  line-height: 1.55;
  color: var(--ink-3);
}

@media (max-width: 900px) {
  .filter-action,
  .filter-actor,
  .filter-range {
    width: 100%;
  }
}
</style>
