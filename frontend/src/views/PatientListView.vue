<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import {
  allergens as allergensApi,
  departments as departmentsApi,
  patientGroups as patientGroupsApi,
  patients as patientsApi,
} from '../api/client'
import { currentClinician } from '../session'

// T15 + M2-03. Every search condition the service accepts is exposed here — fuzzy
// name, exact patient number, symptom tag, department, gender, the admission and
// birth-date ranges, allergen code and severity, the two identifier matches and the
// group filter — and they combine with AND, so any of them may be sent at once.
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
// Both option lists come from the service: the allergen dictionary is a real
// endpoint, and a group is a row another screen created, so neither is invented
// here. A missing option list degrades to a typed value rather than a dead filter.
const groups = ref([])
const allergenOptions = ref([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loadError = ref('')

const filters = reactive({
  name: '',
  patientNo: '',
  symptomTags: [],
  gender: '',
  admitted: null,
  birth: null,
  allergenCodes: [],
  allergySeverity: [],
  groupId: null,
  phone: '',
  idCard: '',
})

const dialogOpen = ref(false)
const saving = ref(false)
const formError = ref('')
const form = reactive({
  name: '',
  gender: 'male',
  department: '',
  birthDate: '',
  admittedAt: '',
  phone: '',
  idCard: '',
  symptomTags: [],
  allergies: [],
  notes: '',
})

function emptyAllergyRow() {
  return { allergen: '', allergyType: 'drug', severity: 'mild', recordedAt: '', reaction: '' }
}

// T09: a caller without `data.all` may write only in their own department, and the
// service refuses the rest with 403. The form offers what can actually succeed --
// the admin role is the only one carrying `data.all` -- instead of letting a senior
// pick a department whose only possible answer is a refusal. The server still
// decides; this is only the shape of the form.
const writableDepartments = computed(() =>
  currentClinician.value.role === 'admin'
    ? departments.value
    : departments.value.filter((item) => item.name === currentClinician.value.department),
)

const hasFilters = computed(
  () =>
    filters.name.trim() !== '' ||
    filters.patientNo.trim() !== '' ||
    filters.symptomTags.length > 0 ||
    filters.gender !== '' ||
    filters.admitted !== null ||
    filters.birth !== null ||
    filters.allergenCodes.length > 0 ||
    filters.allergySeverity.length > 0 ||
    filters.groupId !== null ||
    filters.phone.trim() !== '' ||
    filters.idCard.trim() !== '',
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
      gender: filters.gender,
      admittedFrom: filters.admitted?.[0] ?? '',
      admittedTo: filters.admitted?.[1] ?? '',
      birthFrom: filters.birth?.[0] ?? '',
      birthTo: filters.birth?.[1] ?? '',
      allergenCodes: filters.allergenCodes,
      allergySeverity: filters.allergySeverity,
      phone: filters.phone.trim(),
      idCard: filters.idCard.trim(),
      groupId: filters.groupId,
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
  filters.gender = ''
  filters.admitted = null
  filters.birth = null
  filters.allergenCodes = []
  filters.allergySeverity = []
  filters.groupId = null
  filters.phone = ''
  filters.idCard = ''
  search()
}

function changePage(next) {
  page.value = next
  load()
}

function openDialog() {
  form.name = ''
  form.gender = 'male'
  form.department = writableDepartments.value[0]?.name ?? ''
  form.birthDate = ''
  form.admittedAt = ''
  form.phone = ''
  form.idCard = ''
  form.symptomTags = []
  form.allergies = []
  form.notes = ''
  formError.value = ''
  dialogOpen.value = true
}

function addAllergyRow() {
  form.allergies.push(emptyAllergyRow())
}

function dropAllergyRow(index) {
  form.allergies.splice(index, 1)
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

  // The allergy rows are checked here only far enough to catch one that is still
  // empty. What a legal severity or a known code is, is the service's call, and its
  // 422 is what lands in the error line below.
  const allergies = form.allergies.map((row) => ({
    allergen: row.allergen.trim(),
    allergy_type: row.allergyType,
    severity: row.severity,
    recorded_at: row.recordedAt,
    ...(row.reaction.trim() ? { reaction: row.reaction.trim() } : {}),
  }))
  const unfinished = allergies.findIndex((row) => !row.allergen || !row.recorded_at)
  if (unfinished !== -1) {
    formError.value = `Allergy row ${unfinished + 1} needs a code and a recorded date.`
    return
  }

  saving.value = true
  try {
    await patientsApi.create({
      name: form.name.trim(),
      gender: form.gender,
      department: form.department,
      notes: form.notes,
      symptom_tags: form.symptomTags,
      allergies,
      // Omitted rather than sent blank: an empty string is not a date, and the
      // service refuses the whole request with 422 when it gets one.
      ...(form.birthDate ? { birth_date: form.birthDate } : {}),
      ...(form.admittedAt ? { admitted_at: form.admittedAt } : {}),
      ...(form.phone.trim() ? { phone: form.phone.trim() } : {}),
      ...(form.idCard.trim() ? { id_card: form.idCard.trim() } : {}),
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

// --- M2-05: groups ---------------------------------------------------------
//
// Six routes and no screen, until now: `app/groups.py` has had list, create,
// rename, delete, add members and remove members since T17, and `client.js` only
// published the read. This dialog is the missing half.
//
// Two things it deliberately does not do. It does not show who is in a group --
// the contract publishes `member_count` and no roster route, so the count is what
// there is to show, and the panel says so rather than leaving the gap to look
// like an omission. And it does not pre-check anything the service already
// refuses: a repeated add, a member from another department, a duplicate name and
// a removal of someone who is not in the group all come back as 409/422/409/404
// with the offending patient numbers in the message, and those messages are shown
// as they arrive. Re-deriving those rules here would be a second copy that a
// reviewer would have to keep true.

const groupsOpen = ref(false)
const groupSaving = ref(false)
const groupError = ref('')
const groupForm = reactive({ id: null, name: '', description: '', department: '' })

// The groups panel has two views. `inGroup` is null while the list is showing and
// holds the group being edited otherwise: one dialog that changes what it is about,
// rather than a second dialog stacked on the first.
const inGroup = ref(null)
// '' | 'add' | 'remove'. Only the button that was pressed spins; the other one
// is merely disabled, so the screen says which write is in flight.
const membersMode = ref('')
const membersError = ref('')
const membersPicked = ref([])
const memberOptions = ref([])

function openGroups() {
  groupForm.id = null
  groupForm.name = ''
  groupForm.description = ''
  groupForm.department = ''
  groupError.value = ''
  inGroup.value = null
  groupsOpen.value = true
}

function editGroup(group) {
  groupForm.id = group.id
  groupForm.name = group.name
  groupForm.description = group.description ?? ''
  // Renaming does not move a group between departments: `PatientGroupUpdate` has
  // no `department`, so the picker is part of the create form only and the save
  // sends the name and description.
  groupForm.department = ''
  groupError.value = ''
}

function cancelGroupEdit() {
  groupForm.id = null
  groupForm.name = ''
  groupForm.description = ''
  groupError.value = ''
}

async function refreshGroups() {
  try {
    groups.value = await patientGroupsApi.list()
  } catch {
    // The panel's own error line reports the failure; the filter keeps what it had.
  }
}

async function saveGroup() {
  groupError.value = ''
  if (!groupForm.name.trim()) {
    groupError.value = 'Enter a group name.'
    return
  }

  groupSaving.value = true
  try {
    if (groupForm.id) {
      await patientGroupsApi.update(groupForm.id, {
        name: groupForm.name.trim(),
        description: groupForm.description,
      })
    } else {
      await patientGroupsApi.create({
        name: groupForm.name.trim(),
        description: groupForm.description,
        // Left out rather than sent blank: the service defaults it to the caller's
        // own department, and an empty string is not a department name.
        ...(groupForm.department ? { department: groupForm.department } : {}),
      })
    }
    const wasEdit = Boolean(groupForm.id)
    cancelGroupEdit()
    await refreshGroups()
    ElMessage.success(wasEdit ? 'Group updated.' : 'Group created.')
  } catch (error) {
    // 409 for a name already used in this department, 403 for naming another one
    // without `data.all`: the form keeps what was typed either way.
    groupError.value = error.message
  } finally {
    groupSaving.value = false
  }
}

async function removeGroup(group) {
  try {
    await ElMessageBox.confirm(
      `Delete the group “${group.name}”? Its ${group.member_count} patients stay in the directory — only the grouping goes.`,
      'Delete group',
      { confirmButtonText: 'Delete', cancelButtonText: 'Cancel', type: 'warning' },
    )
  } catch {
    return // dismissed
  }

  try {
    await patientGroupsApi.remove(group.id)
    await refreshGroups()
    // Only then does the table need re-reading: deleting a group does not touch a
    // single patient, but it does invalidate a filter that was matching by it, and
    // clearing the filter without re-querying would leave the old rows on screen
    // under an empty filter.
    if (filters.groupId === group.id) {
      filters.groupId = null
      await load()
    }
    ElMessage.success('Group deleted.')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

// The picker offers the directory's first hundred live rows and accepts a number
// typed by hand, the same arrangement the symptom-tag and allergen controls use:
// a missing option list costs the convenience and not the ability to add anyone.
// The list is read here rather than filtered from `rows`, which is a page of
// whatever the current filters matched.
async function openMembers(group) {
  inGroup.value = group
  membersError.value = ''
  membersMode.value = ''
  membersPicked.value = []
  try {
    const page = await patientsApi.list({ size: 100 })
    memberOptions.value = page.items.map((row) => ({ patient_no: row.patient_no, name: row.name }))
  } catch {
    memberOptions.value = []
  }
}

async function writeMembers(mode) {
  membersError.value = ''
  if (!membersPicked.value.length) {
    membersError.value =
      mode === 'add'
        ? 'Choose at least one patient to add.'
        : 'Choose at least one patient to remove.'
    return
  }

  membersMode.value = mode
  try {
    if (mode === 'add') await patientGroupsApi.addMembers(inGroup.value.id, membersPicked.value)
    else await patientGroupsApi.removeMembers(inGroup.value.id, membersPicked.value)
    // The count on the group is what changed, so the list is re-read rather than
    // adjusted here -- and the group being viewed is refreshed with it.
    await refreshGroups()
    inGroup.value = groups.value.find((group) => group.id === inGroup.value.id) ?? inGroup.value
    if (filters.groupId === inGroup.value.id) await load()
    membersPicked.value = []
    ElMessage.success(mode === 'add' ? 'Patients added.' : 'Patients removed.')
  } catch (error) {
    // 409 already in the group, 422 from another department, 404 not in the group.
    // Each message names the patients it is about.
    membersError.value = error.message
  } finally {
    membersMode.value = ''
  }
}

onMounted(async () => {
  try {
    departments.value = await departmentsApi.list()
  } catch {
    // load() reports the failure; without departments the table still renders.
  }
  try {
    groups.value = await patientGroupsApi.list()
  } catch {
    // The group filter is optional; without the list it stays a free choice of none.
  }
  try {
    allergenOptions.value = await allergensApi.list()
  } catch {
    // Same for the allergen filter: it accepts a typed code either way.
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

        <el-select
          v-model="filters.gender"
          class="filter-gender"
          clearable
          placeholder="Any gender"
          :disabled="loading"
          @change="search"
        >
          <el-option label="Male" value="male" />
          <el-option label="Female" value="female" />
          <el-option label="Unknown" value="unknown" />
        </el-select>

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

        <el-date-picker
          v-model="filters.birth"
          class="filter-range"
          type="daterange"
          value-format="YYYY-MM-DD"
          start-placeholder="Born from"
          end-placeholder="to"
          :disabled="loading"
          @change="search"
        />

        <el-select
          v-model="filters.allergenCodes"
          class="filter-allergen"
          multiple
          filterable
          allow-create
          default-first-option
          collapse-tags
          clearable
          placeholder="Allergens"
          :disabled="loading"
          @change="search"
        >
          <el-option
            v-for="item in allergenOptions"
            :key="item.code"
            :label="`${item.name} · ${item.code}`"
            :value="item.code"
          />
        </el-select>

        <el-select
          v-model="filters.allergySeverity"
          class="filter-severity"
          multiple
          collapse-tags
          clearable
          placeholder="Allergy severity"
          :disabled="loading"
          @change="search"
        >
          <el-option label="Mild" value="mild" />
          <el-option label="Moderate" value="moderate" />
          <el-option label="Severe" value="severe" />
        </el-select>

        <el-select
          v-model="filters.groupId"
          class="filter-group"
          clearable
          placeholder="Patient group"
          :disabled="loading"
          @change="search"
        >
          <el-option
            v-for="group in groups"
            :key="group.id"
            :label="`${group.name} (${group.member_count})`"
            :value="group.id"
          />
        </el-select>

        <!-- The filter reads groups; this is the only place that writes them. It
             sits with the filter because the two are about the same rows. -->
        <el-button link @click="openGroups">Manage groups</el-button>

        <!-- Both identifiers are exact matches. The input is the whole number: a
             prefix is not a hit, because the comparison is against the digest kept
             beside the ciphertext, not against a prefix of anything. -->
        <el-input
          v-model="filters.phone"
          class="filter-id"
          placeholder="Phone, full number"
          clearable
          :disabled="loading"
          @keyup.enter="search"
          @clear="search"
        />

        <el-input
          v-model="filters.idCard"
          class="filter-id"
          placeholder="National ID, full number"
          clearable
          :disabled="loading"
          @keyup.enter="search"
          @clear="search"
        />

        <el-button v-if="hasFilters" link @click="clearFilters">Clear filters</el-button>

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

      </div>

      <p class="toolbar-note">
        Every condition is sent to the service and they combine with AND. The list is
        limited to your own department unless you are an administrator, and a group from
        another department matches nothing rather than widening it. Phone and national ID
        are exact matches against the blind index kept beside the encrypted column, so the
        whole number is required — spaces and hyphens are ignored. Symptom tags are typed
        rather than chosen: no endpoint publishes the tag vocabulary.
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
            <!-- M5-T7. The consultation report is archived into the patient
                 record, and the tab that reads it back lives on the detail
                 screen, so the name is the way in rather than a dead label. -->
            <router-link
              class="name-link"
              :to="{ name: 'patient-detail', params: { patientNo: row.patient_no } }"
            >
              <span class="name">{{ row.name }}</span>
            </router-link>
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

    <el-dialog v-model="dialogOpen" title="New patient record" width="640px">
      <p class="dialog-note">
        One request builds the whole record: the fields below, the symptom tags and every
        allergy row. The service writes them in a single transaction, so a rejected field
        leaves no patient behind rather than half of one.
      </p>

      <label class="field">
        <span class="field-label">Name</span>
        <el-input v-model="form.name" maxlength="100" placeholder="Patient name" />
      </label>

      <div class="field-row">
        <label class="field">
          <span class="field-label">Gender</span>
          <el-select v-model="form.gender" class="full">
            <el-option label="Male" value="male" />
            <el-option label="Female" value="female" />
            <el-option label="Unknown" value="unknown" />
          </el-select>
        </label>

        <label class="field">
          <span class="field-label">Date of birth</span>
          <el-date-picker
            v-model="form.birthDate"
            class="full"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="Optional"
          />
        </label>
      </div>

      <div class="field-row">
        <label class="field">
          <span class="field-label">Department</span>
          <el-select v-model="form.department" placeholder="Select a department" class="full">
            <el-option
              v-for="department in writableDepartments"
              :key="department.id"
              :label="department.name"
              :value="department.name"
            />
          </el-select>
          <span v-if="writableDepartments.length < departments.length" class="field-hint">
            Your role writes in its own department only — everyone else's patients stay
            out of reach (T09).
          </span>
        </label>

        <label class="field">
          <span class="field-label">Admitted</span>
          <el-date-picker
            v-model="form.admittedAt"
            class="full"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="Optional"
          />
        </label>
      </div>

      <div class="field-row">
        <label class="field">
          <span class="field-label">Phone</span>
          <el-input v-model="form.phone" maxlength="32" placeholder="Stored encrypted" />
        </label>

        <label class="field">
          <span class="field-label">National ID</span>
          <el-input v-model="form.idCard" maxlength="32" placeholder="Stored encrypted" />
        </label>
      </div>

      <label class="field">
        <span class="field-label">Symptom tags</span>
        <el-select
          v-model="form.symptomTags"
          class="full"
          multiple
          filterable
          allow-create
          default-first-option
          collapse-tags
          clearable
          placeholder="Type a tag and press enter"
        />
      </label>

      <div class="field">
        <span class="field-label">Allergies</span>
        <div v-for="(row, index) in form.allergies" :key="index" class="allergy-row">
          <el-select
            v-model="row.allergen"
            class="allergy-code"
            filterable
            allow-create
            default-first-option
            placeholder="Code"
          >
            <el-option
              v-for="item in allergenOptions"
              :key="item.code"
              :label="`${item.name} · ${item.code}`"
              :value="item.code"
            />
          </el-select>

          <el-select v-model="row.allergyType" class="allergy-type">
            <el-option label="Drug" value="drug" />
            <el-option label="Food" value="food" />
            <el-option label="Other" value="other" />
          </el-select>

          <el-select v-model="row.severity" class="allergy-severity">
            <el-option label="Mild" value="mild" />
            <el-option label="Moderate" value="moderate" />
            <el-option label="Severe" value="severe" />
          </el-select>

          <el-date-picker
            v-model="row.recordedAt"
            class="allergy-date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="Recorded"
          />

          <el-input
            v-model="row.reaction"
            class="allergy-reaction"
            maxlength="255"
            placeholder="Reaction (optional)"
          />

          <el-button link @click="dropAllergyRow(index)">Remove</el-button>
        </div>
        <el-button link :icon="Plus" @click="addAllergyRow">Add an allergy</el-button>
      </div>

      <label class="field">
        <span class="field-label">Notes</span>
        <el-input
          v-model="form.notes"
          type="textarea"
          :rows="3"
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

    <el-dialog
      v-model="groupsOpen"
      :title="inGroup ? inGroup.name : 'Patient groups'"
      width="640px"
    >
      <!-- The members view. One dialog with two faces, rather than a second dialog
           stacked on the first: there is no roster route to fill a third. -->
      <template v-if="inGroup">
        <p class="dialog-note">
          <span class="data">{{ inGroup.member_count }}</span> patients in this group.
          The service publishes the count and not the names, so which patients are in it
          is answered by filtering the directory by this group. Choose numbers below to
          change the membership; a refusal names the patients it is about.
        </p>

        <label class="field">
          <span class="field-label">Patients</span>
          <el-select
            v-model="membersPicked"
            class="full"
            multiple
            filterable
            allow-create
            default-first-option
            collapse-tags
            placeholder="Type a patient number and press enter"
          >
            <el-option
              v-for="person in memberOptions"
              :key="person.patient_no"
              :label="`${person.name} · ${person.patient_no}`"
              :value="person.patient_no"
            />
          </el-select>
          <span class="field-hint">
            A member has to be in the group's own department; the service refuses one from
            elsewhere with the patient number in the message.
          </span>
        </label>

        <p v-if="membersError" class="form-error" role="alert">{{ membersError }}</p>

        <div class="member-actions">
          <el-button
            type="primary"
            :loading="membersMode === 'add'"
            :disabled="membersMode !== ''"
            @click="writeMembers('add')"
          >
            Add to group
          </el-button>
          <el-button
            :loading="membersMode === 'remove'"
            :disabled="membersMode !== ''"
            @click="writeMembers('remove')"
          >
            Remove from group
          </el-button>
        </div>
      </template>

      <!-- The list view: every group in scope, and the form that writes one. -->
      <template v-else>
        <p class="dialog-note">
          Groups belong to one department, and a member has to be in it. Deleting a group
          deletes the grouping, never the patients.
        </p>

        <ul v-if="groups.length" class="group-list">
          <li v-for="group in groups" :key="group.id" class="group-row">
            <div class="group-text">
              <span class="group-name">{{ group.name }}</span>
              <span class="group-count data">{{ group.member_count }}</span>
              <span v-if="group.description" class="group-description">
                {{ group.description }}
              </span>
            </div>
            <span class="group-actions">
              <el-button link @click="openMembers(group)">Members</el-button>
              <el-button link @click="editGroup(group)">Rename</el-button>
              <el-button link @click="removeGroup(group)">Delete</el-button>
            </span>
          </li>
        </ul>

        <p v-else class="empty">
          No groups in your scope yet. Create one below to start grouping patients.
        </p>

        <div class="group-form">
          <div class="field-row">
            <label class="field">
              <span class="field-label">{{ groupForm.id ? 'New name' : 'Name' }}</span>
              <el-input v-model="groupForm.name" maxlength="100" placeholder="Group name" />
            </label>

            <label class="field">
              <span class="field-label">Description</span>
              <el-input
                v-model="groupForm.description"
                maxlength="255"
                placeholder="Optional"
              />
            </label>
          </div>

          <!-- Only on creation: `PatientGroupUpdate` carries no department, so a
               group does not move between departments by renaming it. -->
          <label v-if="!groupForm.id" class="field">
            <span class="field-label">Department</span>
            <el-select v-model="groupForm.department" class="full" clearable placeholder="Your own department">
              <el-option
                v-for="department in writableDepartments"
                :key="department.id"
                :label="department.name"
                :value="department.name"
              />
            </el-select>
          </label>

          <p v-if="groupError" class="form-error" role="alert">{{ groupError }}</p>
        </div>
      </template>

      <template #footer>
        <template v-if="inGroup">
          <el-button @click="inGroup = null">Back to groups</el-button>
        </template>
        <template v-else>
          <el-button @click="groupsOpen = false">Close</el-button>
          <el-button v-if="groupForm.id" link @click="cancelGroupEdit">Cancel rename</el-button>
          <el-button type="primary" :loading="groupSaving" @click="saveGroup">
            {{ groupForm.id ? 'Save changes' : 'Create group' }}
          </el-button>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<!-- Page furniture (.page, .page-head, .panel, .toolbar, .field, .empty, .muted)
     lives in src/style.css; only what is specific to this screen is here. -->
<style scoped>
/* The page .toolbar spreads its children to both ends. This bar is a run of
   filters that pack from the left; only the search is pushed to the right. */
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-start;
}

/* The name search is the one condition people reach for first, so it sits at the
   right end of the row, pushed there by the auto margin: the other filters fill the
   left, and the eye lands on the search box where a toolbar usually keeps it. */
.search {
  display: flex;
  gap: 8px;
  width: min(100%, 320px);
  margin-left: auto;
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

.filter-gender {
  width: 132px;
}

.filter-allergen {
  width: 220px;
}

.filter-severity {
  width: 190px;
}

.filter-group {
  width: 200px;
}

/* Exact matches, so the placeholder says the whole number is wanted. */
.filter-id {
  width: 190px;
}

/* Two fields on one line, each taking half: the dialog is a form, not a list, and
   a single column of eight rows scrolls the way out of view. */
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

/* The groups panel. Rows rather than a table: a group has three short fields and
   three actions, and a table's columns would be mostly empty. */
.group-list {
  padding: 0;
  margin: 0 0 4px;
  list-style: none;
  border-top: 1px solid var(--line-2);
}

.group-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: baseline;
  justify-content: space-between;
  padding: 11px 0;
  border-bottom: 1px solid var(--line-2);
}

.group-text {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  min-width: 0;
}

.group-name {
  font-size: 13.5px;
  font-weight: 600;
}

.group-count {
  font-size: 11.5px;
  color: var(--ink-3);
}

.group-description {
  font-size: 12.5px;
  color: var(--ink-2);
}

.group-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

/* The form sits under the list it writes, separated by a rule so the two are not
   read as one column of the same thing. */
.group-form {
  padding-top: 18px;
  margin-top: 18px;
  border-top: 1px solid var(--line-2);
}

.member-actions {
  display: flex;
  gap: 8px;
}

.allergy-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-bottom: 6px;
}

.allergy-code {
  width: 150px;
}

.allergy-type {
  width: 104px;
}

.allergy-severity {
  width: 118px;
}

.allergy-date {
  width: 140px;
}

.allergy-reaction {
  flex: 1 1 120px;
  width: 160px;
}

.name {
  display: block;
}

/* The name keeps the table's ink and gains an underline on hover: a blue link
   in a clinical table reads as a different kind of thing than it is. */
.name-link {
  color: inherit;
  text-decoration: none;
}

.name-link:hover .name {
  text-decoration: underline;
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
  .filter-range,
  .filter-gender,
  .filter-allergen,
  .filter-severity,
  .filter-group,
  .filter-id {
    width: 100%;
  }

  .field-row {
    display: block;
  }

  .search {
    width: 100%;
    margin-left: 0;
  }
}
</style>
