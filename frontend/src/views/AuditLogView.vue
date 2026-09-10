<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Search } from '@element-plus/icons-vue'
import { auditActions, auditRows } from '../api/demo-data'

// M8. An append-only trail: every write and every sensitive read, recorded
// with who did it, when, from where, on what, and how it turned out.
//
// The three filters and the CSV export below really work against the mock
// rows. Task T11 replaces the array with the query endpoint; the column set
// here is what that endpoint has to return.

const action = ref(auditActions[0])
const actor = ref('')
const range = ref(null)

const filtered = computed(() => {
  const needle = actor.value.trim().toLowerCase()
  const [from, to] = range.value ?? []

  return auditRows.filter((row) => {
    if (action.value !== auditActions[0] && row.action !== action.value) return false
    if (needle && !row.actor.toLowerCase().includes(needle)) return false
    if (from && row.iso < from) return false
    // The picker gives a day; compare against the end of that day.
    if (to && row.iso > `${to}T23:59`) return false
    return true
  })
})

const isFiltered = computed(
  () => action.value !== auditActions[0] || actor.value.trim() !== '' || range.value !== null,
)

function reset() {
  action.value = auditActions[0]
  actor.value = ''
  range.value = null
}

// The export is real: it builds a CSV from exactly the rows on screen.
function exportCsv() {
  if (!filtered.value.length) {
    ElMessage.info('Nothing to export with these filters.')
    return
  }

  const header = ['id', 'timestamp', 'actor', 'action', 'target', 'source', 'outcome', 'detail']
  const escape = (value) => `"${String(value).replaceAll('"', '""')}"`
  const body = filtered.value.map((row) =>
    [row.id, row.at, row.actor, row.action, row.target, row.source, row.outcome, row.detail]
      .map(escape)
      .join(','),
  )

  const blob = new Blob([[header.join(','), ...body].join('\r\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `audit-log-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)

  ElMessage.success(`${filtered.value.length} rows exported.`)
}
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
        <el-button :icon="Download" @click="exportCsv">Export CSV</el-button>
      </div>
    </header>

    <section class="panel">
      <div class="toolbar">
        <div class="filters">
          <el-select v-model="action" class="filter-action" aria-label="Action">
            <el-option v-for="item in auditActions" :key="item" :label="item" :value="item" />
          </el-select>

          <el-input
            v-model="actor"
            class="filter-actor"
            clearable
            placeholder="Search by account"
            :prefix-icon="Search"
          />

          <el-date-picker
            v-model="range"
            type="daterange"
            value-format="YYYY-MM-DD"
            start-placeholder="From"
            end-placeholder="To"
            class="filter-range"
          />
        </div>

        <div class="toolbar-right">
          <span class="result-count">
            <span class="data">{{ filtered.length }}</span>
            of <span class="data">{{ auditRows.length }}</span> entries
          </span>
          <el-button v-if="isFiltered" link @click="reset">Clear filters</el-button>
        </div>
      </div>

      <el-table :data="filtered" class="table" row-key="id">
        <el-table-column type="expand">
          <template #default="{ row }">
            <p class="detail">{{ row.detail }}</p>
          </template>
        </el-table-column>

        <el-table-column label="Time" width="184">
          <template #default="{ row }">
            <span class="data">{{ row.at }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Account" prop="actor" min-width="210" />

        <el-table-column label="Action" width="150">
          <template #default="{ row }">
            <span class="chip" :data-severity="row.severity">{{ row.action }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Target" min-width="150">
          <template #default="{ row }">
            <span class="data">{{ row.target }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Source" width="132">
          <template #default="{ row }">
            <span class="data">{{ row.source }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Outcome" width="110">
          <template #default="{ row }">
            <span :class="row.outcome === 'ok' ? 'outcome' : 'outcome outcome-bad'">
              {{ row.outcome }}
            </span>
          </template>
        </el-table-column>

        <template #empty>
          <p class="empty">No entries match these filters.</p>
        </template>
      </el-table>

      <p class="panel-foot table-foot">
        Every field shown here is a stored column. Rows are inserted, never updated or deleted, and
        the database account holds no UPDATE or DELETE grant on this table — which is what makes the
        trail worth reading.
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
  width: 168px;
}

.filter-actor {
  width: 220px;
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

.table {
  width: 100%;
}

.detail {
  padding: 4px 16px 6px 48px;
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ink-2);
}

.outcome {
  font-size: 12.5px;
  color: var(--ok);
}

.outcome-bad {
  font-weight: 600;
  color: var(--alert);
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
