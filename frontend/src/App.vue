<script setup>
import { onMounted, ref } from 'vue'

const patients = ref([])
const departments = ref([])
const query = ref('')
const name = ref('')
const departmentId = ref('')
const notes = ref('')
const total = ref(0)
const offset = ref(0)
const error = ref('')
const busy = ref(false)
const health = ref('Checking services…')
const selected = ref(null)

async function api(path, options) {
  const response = await fetch(`/api${path}`, options)
  const body = response.status === 204 ? null : await response.json()
  if (!response.ok) throw new Error(body?.error?.message || 'Service unavailable')
  return body
}
async function load() {
  const result = await api(`/patients?q=${encodeURIComponent(query.value)}&offset=${offset.value}&limit=20`)
  patients.value = result.data
  total.value = result.total
}
async function run(action) {
  error.value = ''
  busy.value = true
  try { await action() } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function create() {
  await run(async () => {
    await api('/patients', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.value, department_id: Number(departmentId.value), notes: notes.value }) })
    name.value = ''; notes.value = ''; offset.value = 0
    await load()
  })
}
async function remove(patient) {
  if (!window.confirm(`Delete synthetic patient ${patient.name}?`)) return
  await run(async () => {
    await api(`/patients/${patient.id}`, { method: 'DELETE' })
    selected.value = null
    if (patients.value.length === 1 && offset.value > 0) offset.value -= 20
    await load()
  })
}
async function search() { offset.value = 0; await run(load) }
async function page(change) { offset.value += change; await run(load) }
onMounted(() => run(async () => {
  try {
    const result = await api('/health/ready')
    health.value = result.status === 'ok' ? 'Services ready' : 'Services unavailable'
  } catch { health.value = 'Services unavailable' }
  departments.value = (await api('/departments')).data
  departmentId.value = departments.value[0]?.id || ''
  await load()
}))
</script>

<template>
  <main>
    <header><div><p class="eyebrow">DOCTOR WORK PLATFORM</p><h1>Patient workspace</h1></div><span class="status">{{ health }}</span></header>
    <p class="notice">Development demo · Use synthetic patient data only. Sign-in and access controls are not implemented yet.</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <div class="layout">
      <section><h2>Add a patient</h2>
        <form @submit.prevent="create">
          <label>Name<input v-model="name" required maxlength="100" placeholder="Demo Patient"></label>
          <label>Department<select v-model="departmentId" required><option value="" disabled>Select department</option><option v-for="department in departments" :key="department.id" :value="department.id">{{ department.name }}</option></select></label>
          <label>Notes<textarea v-model="notes" maxlength="2000" rows="4" placeholder="Synthetic record notes"></textarea></label>
          <button :disabled="busy || !name.trim() || !departmentId">Add patient</button>
        </form>
      </section>
      <section><h2>Patient directory <small>{{ total }} records</small></h2>
        <form class="search" @submit.prevent="search"><input v-model="query" aria-label="Search patients by name" maxlength="100" placeholder="Search by name"><button :disabled="busy">Search</button></form>
        <p v-if="!patients.length">No patients found. Add a synthetic record to get started.</p>
        <ul><li v-for="patient in patients" :key="patient.id"><div><button class="link" :disabled="busy" @click="run(async () => selected = (await api(`/patients/${patient.id}`)).data)">{{ patient.name }}</button><p>#{{ patient.id }} · {{ departments.find(d => d.id === patient.department_id)?.name }}</p></div><button class="secondary" :disabled="busy" @click="remove(patient)">Delete</button></li></ul>
        <div class="pagination"><button class="secondary" :disabled="busy || offset === 0" @click="page(-20)">Previous</button><button class="secondary" :disabled="busy || offset + 20 >= total" @click="page(20)">Next</button></div>
        <aside v-if="selected"><h3>{{ selected.name }}</h3><p class="notes">{{ selected.notes || 'No notes recorded.' }}</p><button class="secondary" @click="selected = null">Close details</button></aside>
      </section>
    </div>
  </main>
</template>
