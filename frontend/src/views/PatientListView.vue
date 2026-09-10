<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { departments as departmentsApi, patients as patientsApi } from '../api/client'

// The one screen wired to the running service. Search, paging, create and
// delete all round-trip to FastAPI for real.
//
// The API currently accepts a name fragment, an offset and a limit. Patient ID,
// symptom tag and admission-date filters belong to task T13, so the toolbar
// shows only what actually works rather than controls that quietly do nothing.

const PAGE_SIZE = 20

const rows = ref([])
const departments = ref([])
const total = ref(0)
const offset = ref(0)
const query = ref('')
const loading = ref(false)
const loadError = ref('')

const dialogOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const form = reactive({ name: '', department_id: '', notes: '' })

const currentPage = computed(() => Math.floor(offset.value / PAGE_SIZE) + 1)
const departmentName = (id) => departments.value.find((item) => item.id === id)?.name ?? '—'

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const result = await patientsApi.list({
      q: query.value.trim(),
      offset: offset.value,
      limit: PAGE_SIZE,
    })
    rows.value = result.data
    total.value = result.total
  } catch (error) {
    loadError.value = error.message
    rows.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function search() {
  offset.value = 0
  load()
}

function changePage(page) {
  offset.value = (page - 1) * PAGE_SIZE
  load()
}

function openDialog() {
  form.name = ''
  form.department_id = departments.value[0]?.id ?? ''
  form.notes = ''
  formError.value = ''
  dialogOpen.value = true
}

async function save() {
  formError.value = ''
  if (!form.name.trim()) {
    formError.value = 'Enter the patient name.'
    return
  }
  if (!form.department_id) {
    formError.value = 'Select a department.'
    return
  }

  saving.value = true
  try {
    await patientsApi.create({
      name: form.name.trim(),
      department_id: Number(form.department_id),
      notes: form.notes,
    })
    dialogOpen.value = false
    offset.value = 0
    await load()
    ElMessage.success('Patient record created.')
  } catch (error) {
    formError.value = error.message
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `Delete the record for ${row.name}? This cannot be undone.`,
      'Delete patient record',
      { confirmButtonText: 'Delete', cancelButtonText: 'Cancel', type: 'warning' },
    )
  } catch {
    return // dismissed
  }

  try {
    await patientsApi.remove(row.id)
    if (rows.value.length === 1 && offset.value > 0) offset.value -= PAGE_SIZE
    await load()
    ElMessage.success('Patient record deleted.')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(async () => {
  try {
    departments.value = await departmentsApi.list()
  } catch {
    // load() reports the failure; without departments the table still renders.
  }
  await load()
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Patient directory</h2>
        <p class="page-sub">
          <span class="data">{{ total }}</span> records in scope
        </p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openDialog">New patient</el-button>
    </header>

    <section class="panel">
      <div class="toolbar">
        <form class="search" @submit.prevent="search">
          <el-input
            v-model="query"
            placeholder="Search by name"
            clearable
            :disabled="loading"
            @clear="search"
          />
          <el-button native-type="submit" :loading="loading">Search</el-button>
        </form>
        <p class="toolbar-note">
          Patient ID, symptom tag and admission-date filters arrive with task T13.
        </p>
      </div>

      <el-alert
        v-if="loadError"
        class="alert"
        type="error"
        :closable="false"
        show-icon
        :title="loadError"
      />

      <el-table v-loading="loading" :data="rows" class="table">
        <el-table-column label="Patient" prop="name" min-width="170" />
        <el-table-column label="Record ID" width="120">
          <template #default="{ row }">
            <span class="data">#{{ row.id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Department" min-width="150">
          <template #default="{ row }">{{ departmentName(row.department_id) }}</template>
        </el-table-column>
        <el-table-column label="Notes" min-width="240">
          <template #default="{ row }">
            <span v-if="row.notes" class="notes">{{ row.notes }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column width="96" align="right">
          <template #default="{ row }">
            <el-button link @click="remove(row)">Delete</el-button>
          </template>
        </el-table-column>

        <template #empty>
          <p class="empty">
            {{
              query
                ? `No records match “${query}”. Try a shorter name fragment.`
                : 'No patient records yet. Create one to get started.'
            }}
          </p>
        </template>
      </el-table>

      <footer v-if="total > PAGE_SIZE" class="pager">
        <el-pagination
          layout="prev, pager, next"
          :current-page="currentPage"
          :page-size="PAGE_SIZE"
          :total="total"
          @current-change="changePage"
        />
      </footer>
    </section>

    <el-dialog v-model="dialogOpen" title="New patient record" width="480px">
      <label class="field">
        <span class="field-label">Name</span>
        <el-input v-model="form.name" maxlength="100" placeholder="Patient name" />
      </label>

      <label class="field">
        <span class="field-label">Department</span>
        <el-select v-model="form.department_id" placeholder="Select a department" class="full">
          <el-option
            v-for="department in departments"
            :key="department.id"
            :label="department.name"
            :value="department.id"
          />
        </el-select>
      </label>

      <label class="field">
        <span class="field-label">Notes</span>
        <el-input
          v-model="form.notes"
          type="textarea"
          :rows="4"
          maxlength="2000"
          placeholder="Synthetic record notes"
        />
      </label>

      <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>

      <template #footer>
        <el-button :disabled="saving" @click="dialogOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="saving" @click="save">Create record</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<!-- Page furniture (.page, .page-head, .panel, .toolbar, .field, .empty, .muted)
     lives in src/style.css; only what is specific to this screen is here. -->
<style scoped>
.search {
  display: flex;
  gap: 8px;
  width: min(100%, 380px);
}

.alert {
  width: auto;
  margin: 16px 20px 0;
}

.table {
  width: 100%;
}

.notes {
  display: inline-block;
  max-width: 42ch;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  vertical-align: bottom;
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding: 14px 20px;
  border-top: 1px solid var(--line-2);
}
</style>
