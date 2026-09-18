<script setup>
import { computed, onMounted, ref } from 'vue'
import { patients as patientsApi } from '../api/client'
import PatientHealth from '../components/PatientHealth.vue'

// M6. This screen is the module's own front door: a patient picker, then the
// shared health panels. The same panels are the "Health data" tab of the patient
// detail page — `0915意见` item 3 asks for health management and patient
// management to be one screen, and that tab is the merge. Keeping a standalone
// screen too means a clinician working through a list of patients does not have
// to go back and forth through the patient record for each one.
//
// Every panel is patient-scoped server-side, so the picker is not a security
// boundary: choosing a patient outside the caller's department returns 404 the
// same way the patient record does. The picker itself is fed by
// `GET /api/patients`, which already filters to what the caller may see.

const options = ref([])
const selected = ref('')
const loadingPatients = ref(false)
const patientsError = ref('')

const chosen = computed(() => options.value.find((row) => row.patient_no === selected.value) || null)

function describe(patient) {
  return [patient.name, patient.patient_no, patient.department].filter(Boolean).join(' · ')
}

async function searchPatients(query = '') {
  loadingPatients.value = true
  patientsError.value = ''
  try {
    options.value = (await patientsApi.list({ name: query, size: 20 })).items
    // A search that does not match the patient already chosen would drop it from
    // the list, and the option Element Plus needs in order to render the label
    // would disappear -- the box would show a bare number. Keep it.
    if (selected.value && !options.value.some((row) => row.patient_no === selected.value)) {
      options.value = [...options.value, chosen.value].filter(Boolean)
    }
  } catch (err) {
    patientsError.value = err.message
    options.value = []
  } finally {
    loadingPatients.value = false
  }
}

onMounted(() => searchPatients())
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Health Management</h2>
        <p class="page-sub">
          <span>Vitals, care plans, reminders and periodic assessments</span>
          <span v-if="chosen">
            <span class="data">{{ chosen.patient_no }}</span> · {{ chosen.department }}
          </span>
        </p>
      </div>
      <div class="page-actions">
        <el-select
          v-model="selected"
          class="patient-picker"
          placeholder="Search a patient by name"
          filterable
          remote
          clearable
          :remote-method="searchPatients"
          :loading="loadingPatients"
        >
          <el-option
            v-for="patient in options"
            :key="patient.patient_no"
            :label="describe(patient)"
            :value="patient.patient_no"
          />
        </el-select>
        <el-button v-if="chosen" tag="router-link" :to="`/patients/${chosen.patient_no}`">
          Open the patient record
        </el-button>
      </div>
    </header>

    <p v-if="patientsError" class="notice" data-severity="alert">
      <span>Could not load the patient list: {{ patientsError }}</span>
      <el-button size="small" :loading="loadingPatients" @click="searchPatients()">
        Try again
      </el-button>
    </p>

    <PatientHealth
      v-else-if="selected"
      :key="selected"
      :patient-no="selected"
      :patient-name="chosen?.name || ''"
    />

    <section v-else class="panel">
      <p class="empty">
        Pick a patient to see their readings, care plan and reminders. Only patients in
        your department are listed — a patient outside it is not hidden here so much as
        not yours to read.
      </p>
    </section>
  </div>
</template>

<style scoped>
.patient-picker {
  width: 320px;
}
</style>
