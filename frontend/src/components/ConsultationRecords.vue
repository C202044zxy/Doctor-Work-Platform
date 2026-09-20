<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { accessToken } from '../session'
import { work } from '../api/work'

const router = useRouter()
const patient = ref(''), keyword = ref(''), from = ref(''), to = ref('')
const rows = ref([]), total = ref(0), page = ref(1), busy = ref(false), error = ref('')
let generation = 0
const applied = ref(new URLSearchParams())
function filters() {
  return new URLSearchParams(Object.entries({ patient: patient.value.trim(), q: keyword.value.trim(), from: from.value, to: to.value }).filter(([, value]) => value))
}
async function load(search = false) {
  if (search) { page.value = 1; applied.value = filters() }
  const current = ++generation
  busy.value = true
  error.value = ''
  try {
    const query = new URLSearchParams(applied.value)
    query.set('page', page.value)
    query.set('size', 20)
    const result = await work(`/consultations/records?${query}`)
    if (generation === current) { rows.value = result.items; total.value = result.total }
  } catch (err) { if (generation === current) error.value = err.message }
  finally { if (generation === current) busy.value = false }
}
async function download() {
  error.value = ''
  try {
    const response = await fetch(`/api/consultations/export?${applied.value}`, { headers: { Authorization: `Bearer ${accessToken()}` } })
    if (!response.ok) throw new Error((await response.json()).message || 'Export failed')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '')?.[1] || 'consultations.csv'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (err) { error.value = err.message }
}
onMounted(() => load(true))
</script>

<template>
  <section>
    <h3>Consultation records</h3>
    <form class="filters" @submit.prevent="load(true)">
      <el-input v-model="patient" placeholder="Patient name or number" aria-label="Patient name or number" />
      <el-input v-model="keyword" placeholder="Message keyword" aria-label="Message keyword" />
      <label>From <input v-model="from" type="date" /></label>
      <label>To <input v-model="to" type="date" /></label>
      <el-button native-type="submit" type="primary" :loading="busy">Search</el-button>
      <el-button :disabled="busy || !!error" @click="download">Export matching CSV</el-button>
    </form>
    <p class="muted">Dates filter when the consultation was created (Asia/Shanghai). Export includes all {{ total }} matching records.</p>
    <p v-if="error" role="alert">{{ error }} <el-button @click="load()">Retry</el-button></p>
    <p v-else-if="busy" role="status">Loading records…</p>
    <p v-else-if="!rows.length">No matching consultations.</p>
    <el-table v-else :data="rows">
      <el-table-column prop="id" label="Session" width="90" />
      <el-table-column prop="patient_name" label="Patient" />
      <el-table-column prop="patient_no" label="Patient number" />
      <el-table-column prop="doctor_name" label="Doctor" />
      <el-table-column prop="status" label="Status" />
      <el-table-column prop="last_message" label="Last message" />
      <el-table-column label="Created"><template #default="{ row }">{{ new Date(row.created_at).toLocaleString() }}</template></el-table-column>
      <el-table-column label="Ended"><template #default="{ row }">{{ row.ended_at ? new Date(row.ended_at).toLocaleString() : '—' }}</template></el-table-column>
      <el-table-column label="Details"><template #default="{ row }"><el-button @click="router.push({ name: 'consultations', query: { room: row.id } })">Open record</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="total, prev, pager, next" @current-change="load()" />
  </section>
</template>

<style scoped>
.filters{display:flex;gap:12px;flex-wrap:wrap;align-items:center}.filters .el-input{width:200px}label{display:flex;gap:6px;align-items:center}.muted{color:#657871;font-size:13px}[role=alert]{color:#a42222}
</style>
