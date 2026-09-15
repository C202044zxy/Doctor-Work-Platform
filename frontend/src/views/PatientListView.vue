<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { departments as departmentsApi, patients as patientsApi } from '../api/client'

// T15. The four search conditions the contract defines — fuzzy name, exact
// patient number, symptom tag, admission-date range — combine with AND, and all
// four may be sent at once.
//
// This screen talks to the real service and only to the real service. There is
// no offline mode: a second data path meant a second thing to keep correct, and
// the one it was hiding was a real bug — the mock read a blank admission date as
// "no filter" while the service answers a blank one with 422.
//
// The one thing the service cannot supply is the symptom-tag vocabulary: no
// endpoint exposes it, and `symptom_tags` arrives with the rows. So the tag
// control is free-text (`allow-create`) and the note under the toolbar says so,
// rather than offering a dropdown whose options were invented here.

const PAGE_SIZE = 20

const rows = ref([])
const departments = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadError = ref('')

const filters = reactive({ name: '', patientNo: '', symptomTags: [], admitted: null })

const dialogOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const form = reactive({ name: '', gender: 'male', department: '', notes: '' })

const hasFilters = computed(
  () =>
    filters.name.trim() !== '' ||
    filters.patientNo.trim() !== '' ||
    filters.symptomTags.length > 0 ||
    filters.admitted !== null,
)

// Age is derived rather than stored: `PatientSummary` carries a birth date, and a
// stored age would be wrong the day after it was written.
function ageFrom(birthDate) {
  if (!birthDate) return null
  const born = new Date(`${birthDate}T00:00:00Z`)
  if (Number.isNaN(born.getTime())) return null
  const now = new Date()
  let age = now.getUTCFullYear() - born.getUTCFullYear()
  const month = now.getUTCMonth() - born.getUTCMonth()
  if (month < 0 || (month === 0 && now.getUTCDate() < born.getUTCDate())) age -= 1
  return age
}

function genderLabel(gender) {
  return { male: 'Male', female: 'Female' }[gender] ?? 'Unknown'
}

function sexAge(row) {
  const age = ageFrom(row.birth_date)
  return age === null ? genderLabel(row.gender) : `${genderLabel(row.gender)} · ${age}`
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const result = await patientsApi.list({
      name: filters.name.trim(),
      patientNo: filters.patientNo.trim(),
      symptomTags: filters.symptomTags,
      admittedFrom: filters.admitted?.[0] ?? '',
      admittedTo: filters.admitted?.[1] ?? '',
      page: page.value,
      size: PAGE_SIZE,
    })
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

function search() {
  // Back to the first page on every new search: staying on page 3 of a result
  // set that now has one row is how a search looks broken.
  page.value = 1
  load()
}

function clearFilters() {
  filters.name = ''
  filters.patientNo = ''
  filters.symptomTags = []
  filters.admitted = null
  search()
}

function changePage(next) {
  page.value = next
  load()
}

function openDialog() {
  form.name = ''
  form.gender = 'male'
  form.department = departments.value[0]?.name ?? ''
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
  if (!form.department) {
    formError.value = 'Select a department.'
    return
  }

  saving.value = true
  try {
    await patientsApi.create({
      name: form.name.trim(),
      gender: form.gender,
      department: form.department,
      notes: form.notes,
    })
    dialogOpen.value = false
    page.value = 1
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
    await patientsApi.remove(row.patient_no)
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
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
      <div class="toolbar filters">
        <form class="search" @submit.prevent="search">
          <el-input
            v-model="filters.name"
            placeholder="Search by name"
            clearable
            :disabled="loading"
            @clear="search"
          />
          <el-button native-type="submit" :loading="loading">Search</el-button>
        </form>

        <el-input
          v-model="filters.patientNo"
          class="filter-no"
          placeholder="Patient number"
          clearable
          :disabled="loading"
          @keyup.enter="search"
          @clear="search"
        />

        <el-select
          v-model="filters.symptomTags"
          class="filter-tags"
          multiple
          filterable
          allow-create
          default-first-option
          collapse-tags
          clearable
          placeholder="Symptom tags"
          :disabled="loading"
          @change="search"
        />

        <el-date-picker
          v-model="filters.admitted"
          class="filter-range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="Admitted from"
          end-placeholder="to"
          :disabled="loading"
          @change="search"
        />

        <el-button v-if="hasFilters" link @click="clearFilters">Clear filters</el-button>
      </div>

      <p class="toolbar-note">
        All four conditions are sent to the service. The list is limited to your own
        department unless you are an administrator. Symptom tags are typed rather than
        chosen — no endpoint publishes the tag vocabulary.
      </p>

      <div v-if="loadError" class="load-error">
        <div>
          <p class="load-error-title">Could not load the patient list</p>
          <p class="load-error-detail">{{ loadError }}</p>
        </div>
        <el-button :icon="Refresh" :loading="loading" @click="load">Try again</el-button>
      </div>

      <el-table v-else v-loading="loading" :data="rows" class="table">
        <el-table-column label="Patient number" width="150">
          <template #default="{ row }">
            <span class="data">{{ row.patient_no }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Name" min-width="180">
          <template #default="{ row }">
            <span class="name">{{ row.name }}</span>
            <!-- Already masked by the server; showing it in the data face keeps
                 it from being mistaken for something a reader can dial. -->
            <span v-if="row.phone_masked" class="phone data">{{ row.phone_masked }}</span>
          </template>
        </el-table-column>

        <el-table-column label="Sex · Age" width="118">
          <template #default="{ row }">{{ sexAge(row) }}</template>
        </el-table-column>

        <el-table-column label="Department" prop="department" min-width="150" />

        <el-table-column label="Symptom tags" min-width="210">
          <template #default="{ row }">
            <template v-if="row.symptom_tags?.length">
              <span v-for="tag in row.symptom_tags" :key="tag" class="tag">{{ tag }}</span>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>

        <el-table-column label="Allergies" width="118">
          <template #default="{ row }">
            <!-- The server computes the severity flag so the list does not walk
                 the allergy array; the colour is what makes it readable at a
                 glance, which is the point of computing it at all. -->
            <span
              v-if="row.allergy_count"
              class="chip"
              :data-severity="row.has_severe_allergy ? 'alert' : 'info'"
            >
              {{ row.allergy_count }}
              {{ row.has_severe_allergy ? 'severe' : 'recorded' }}
            </span>
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
              hasFilters
                ? 'No records match these filters. Clear one and try again.'
                : 'No patient records yet. Create one to get started.'
            }}
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
    </section>

    <el-dialog v-model="dialogOpen" title="New patient record" width="480px">
      <label class="field">
        <span class="field-label">Name</span>
        <el-input v-model="form.name" maxlength="100" placeholder="Patient name" />
      </label>

      <label class="field">
        <span class="field-label">Gender</span>
        <el-select v-model="form.gender" class="full">
          <el-option label="Male" value="male" />
          <el-option label="Female" value="female" />
          <el-option label="Unknown" value="unknown" />
        </el-select>
      </label>

      <label class="field">
        <span class="field-label">Department</span>
        <el-select v-model="form.department" placeholder="Select a department" class="full">
          <el-option
            v-for="department in departments"
            :key="department.id"
            :label="department.name"
            :value="department.name"
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
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.search {
  display: flex;
  gap: 8px;
  width: min(100%, 320px);
}

.filter-no {
  width: 168px;
}

.filter-tags {
  width: 240px;
}

.filter-range {
  width: 280px;
}

.name {
  display: block;
}

.phone {
  display: block;
  font-size: 11.5px;
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

.table {
  width: 100%;
}

/* T15's second scenario stops the service and expects "load failed, click to
   retry" rather than a spinner that never resolves or a blank panel. */
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

@media (max-width: 900px) {
  .filter-no,
  .filter-tags,
  .filter-range {
    width: 100%;
  }
}
</style>