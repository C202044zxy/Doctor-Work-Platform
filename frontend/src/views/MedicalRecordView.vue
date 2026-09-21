<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { emr } from '../api/client.js'
import { currentUserId, currentTitle } from '../session.js'
import { saveDraft, readDraft, clearDraft } from '../emr-draft.js'

const route = useRoute()
const router = useRouter()
const templates = ref([])
const patients = ref([])
const drugs = ref([])
const records = ref({ items: [], total: 0 })
const patientNo = ref(route.query.patient_no || '')
const status = ref('')
const page = ref(1)
const templateId = ref(null)
const selected = ref(null)
const versions = ref([])
const orders = ref([])
const busy = ref(false)
const error = ref('')
const notice = ref('')
const mine = computed(() => selected.value?.author_id === currentUserId.value)
const editable = computed(() => mine.value && ['draft', 'rejected'].includes(selected.value?.status))
const orderEditable = computed(() => mine.value && selected.value?.status !== 'archived')
const fields = computed(() => selected.value?.template_snapshot.fields_json.fields || [])
const item = ref({ order_type: 'drug', drug_code: '', dose: '', frequency: 'qd', route: '' })
const editingOrder = ref(null)
const validation = ref(null)
const reason = ref('')
const templateEditor = ref('')
const templateEditId = ref(null)
const amendment = ref('')
let restoring = false

function failure(e) {
  error.value = e.status === 409 ? 'The record changed or is locked. Refresh before retrying. Your draft is retained.'
    : e.status === 422 ? `Check the form fields. ${e.message}` : 'Unable to complete the request. Your draft is retained. Please retry.'
}
async function run(fn) {
  busy.value = true
  error.value = ''
  try { await fn() } catch (e) { failure(e) } finally { busy.value = false }
}
async function list() {
  const query = new URLSearchParams({ page: page.value, size: 10 })
  if (patientNo.value) query.set('patient_no', patientNo.value)
  if (status.value) query.set('status', status.value)
  records.value = await emr.get(`/emr/records?${query}`)
}
async function open(id) {
  const data = await emr.get(`/emr/records/${id}`)
  const [history, prescriptions] = await Promise.all([
    emr.get(`/emr/records/${id}/versions`), emr.get(`/emr/orders?record_id=${id}`),
  ])
  restoring = true
  const draft = readDraft(sessionStorage, currentUserId.value, id)
  if (draft && data.author_id === currentUserId.value && ['draft', 'rejected'].includes(data.status)) {
    notice.value = draft.revision === data.revision ? 'Restored your local draft.' : 'A newer revision exists. Your local draft is shown; copy your changes before refreshing from the server.'
    Object.assign(data, draft)
  } else notice.value = ''
  selected.value = data
  versions.value = history
  orders.value = prescriptions
  restoring = false
  await router.replace({ query: { ...route.query, record: id } })
}
watch(() => selected.value?.content_json, () => {
  if (!restoring && editable.value) {
    try { saveDraft(sessionStorage, currentUserId.value, selected.value.id, selected.value) }
    catch { error.value = 'Local storage is unavailable. Keep this page open until your draft is saved.' }
  }
}, { deep: true, flush: 'sync' })
async function create() {
  const row = await emr.post('/emr/records', { patient_no: patientNo.value, template_id: templateId.value })
  await open(row.id)
  await list()
}
function validContent() {
  for (const f of fields.value) {
    if (f.required && (selected.value.content_json[f.key] == null || selected.value.content_json[f.key] === '')) {
      error.value = `${f.label} is required.`
      return false
    }
  }
  return true
}
async function save(submit = false) {
  if (!validContent()) return
  const row = selected.value
  saveDraft(sessionStorage, currentUserId.value, row.id, row)
  const saved = await emr.patch(`/emr/records/${row.id}`, {
    content_json: row.content_json, version: row.version, revision: row.revision,
  })
  selected.value = saved
  saveDraft(sessionStorage, currentUserId.value, saved.id, saved)
  if (submit) selected.value = await emr.post(`/emr/records/${row.id}/submit`)
  clearDraft(sessionStorage, currentUserId.value, row.id)
  notice.value = submit ? 'Submitted for review.' : 'Draft saved.'
  await list()
  versions.value = await emr.get(`/emr/records/${row.id}/versions`)
}
async function refresh() {
  clearDraft(sessionStorage, currentUserId.value, selected.value.id)
  await open(selected.value.id)
}
function chooseDrug() {
  const drug = drugs.value.find(d => d.code === item.value.drug_code)
  if (drug) Object.assign(item.value, { dose: drug.spec, frequency: drug.default_frequency })
}
async function preflight() {
  reason.value = ''
  try {
    validation.value = await emr.post('/emr/orders/validate', { patient_no: selected.value.patient_no, items: [item.value] })
    if (validation.value.overall === 'passed') await persistOrder()
  } catch (e) {
    if (e.data?.overall === 'blocked') validation.value = e.data
    else throw e
  }
}
async function persistOrder() {
  try {
    if (editingOrder.value) await emr.patch(`/emr/orders/${editingOrder.value}`, item.value)
    else await emr.post('/emr/orders', { record_id: selected.value.id, items: [item.value], override_reason: reason.value })
    validation.value = null
    editingOrder.value = null
    orders.value = await emr.get(`/emr/orders?record_id=${selected.value.id}`)
    // Order mutations also advance the record's independent revision.
    const current = await emr.get(`/emr/records/${selected.value.id}`)
    syncOrderRevision(current)
  } catch (e) {
    if (e.data?.overall === 'blocked') validation.value = e.data
    else throw e
  }
}
function syncOrderRevision(current) {
  if (current.revision === selected.value.revision + 1 && current.version === selected.value.version && current.status === selected.value.status) {
    selected.value.revision = current.revision
    if (editable.value) saveDraft(sessionStorage, currentUserId.value, selected.value.id, selected.value)
  } else {
    notice.value = 'The record changed in another session. Copy your local changes and refresh before saving.'
  }
}
function editOrder(order) {
  editingOrder.value = order.id
  item.value = { order_type: order.order_type, ...Object.fromEntries(['drug_code', 'dose', 'frequency', 'route'].map(k => [k, order.content_json[k] || ''])) }
}
async function stop(order) {
  await emr.post(`/emr/orders/${order.id}/stop`)
  orders.value = await emr.get(`/emr/orders?record_id=${selected.value.id}`)
  const current = await emr.get(`/emr/records/${selected.value.id}`)
  syncOrderRevision(current)
}
async function amend() {
  await emr.post(`/emr/records/${selected.value.id}/amend`, { content_json: { plan: amendment.value } })
  amendment.value = ''
  await open(selected.value.id)
}
function editTemplate(t) {
  templateEditId.value = t?.id || null
  templateEditor.value = JSON.stringify(t ? { name: t.name, description: t.description, fields_json: t.fields_json, is_active: t.is_active } : {
    name: '', fields_json: { fields: [{ key: 'note', label: 'Note', type: 'textarea', required: true }] }, is_active: true,
  }, null, 2)
}
async function saveTemplate() {
  const body = JSON.parse(templateEditor.value)
  if (templateEditId.value) await emr.patch(`/emr/templates/${templateEditId.value}`, body)
  else await emr.post('/emr/templates', body)
  templates.value = await emr.get('/emr/templates')
  templateEditor.value = ''
}
onMounted(() => run(async () => {
  const [t, p, d] = await Promise.all([emr.get('/emr/templates'), emr.get('/patients?size=100'), emr.get('/drugs')])
  templates.value = t
  patients.value = p.items
  drugs.value = d
  templateId.value = t.find(x => x.is_active)?.id
  await list()
  if (route.query.record) await open(route.query.record)
}))
</script>

<template>
  <section class="emr-workspace">
    <header class="records-header">
      <div>
        <h1>Medical records</h1>
        <p class="subtitle">Find patient records or start a new draft.</p>
      </div>
      <button type="button" @click="router.push('/my-submissions')">My submissions</button>
    </header>
    <p v-if="busy" role="status">Loading…</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="records-controls">
      <div class="toolbar field-toolbar filter-toolbar">
        <label>Patient <select v-model="patientNo" aria-label="Patient"><option value="">All patients</option><option v-for="p in patients" :key="p.patient_no" :value="p.patient_no">{{ p.patient_no }} · {{ p.name }}</option></select></label>
        <label>Patient number (exact)<input v-model="patientNo" placeholder="P20260001"></label>
        <label>Status <select v-model="status" aria-label="Status"><option value="">All statuses</option><option v-for="s in ['draft', 'pending', 'rejected', 'archived']" :key="s">{{ s }}</option></select></label>
        <button :disabled="busy" @click="run(async () => { page = 1; await list() })">Search</button>
      </div>
      <div class="toolbar field-toolbar draft-toolbar">
        <label>Template <select v-model="templateId" aria-label="Template"><option v-for="t in templates.filter(t => t.is_active)" :key="t.id" :value="t.id">{{ t.name }}</option></select></label>
        <button class="primary-button" :disabled="busy || !patientNo || !templateId" @click="run(create)">New draft</button>
      </div>
    </div>
    <div class="records-results">
      <p v-if="!busy && !records.items.length" class="empty-state">No records match these filters.</p>
      <div v-else class="table-scroll"><table><thead><tr><th>Patient</th><th>Template</th><th>Status</th><th>Version</th><th>Author</th><th>Actions</th></tr></thead><tbody>
        <tr v-for="r in records.items" :key="r.id"><td>{{ r.patient_no }} · {{ r.patient_name }}</td><td>{{ r.template_name }}</td><td>{{ r.status }}</td><td>{{ r.version }}</td><td>{{ r.author_name }}</td><td><button :disabled="busy" @click="run(() => open(r.id))">Open</button></td></tr>
      </tbody></table></div>
      <div class="toolbar pagination"><button :disabled="busy || page <= 1" @click="run(async () => { page--; await list() })">Previous</button><span>Page {{ page }} · {{ records.total }} records</span><button :disabled="busy || page * 10 >= records.total" @click="run(async () => { page++; await list() })">Next</button></div>
    </div>
    <article v-if="selected">
      <h2>{{ selected.template_name }} · {{ selected.patient_name }}</h2>
      <p>{{ selected.status }} · Version {{ selected.version }} · Revision {{ selected.revision }}</p>
      <p v-if="selected.review_comment">Review comment: {{ selected.review_comment }}</p>
      <p v-if="selected.status === 'archived'">Archived. The original record and its orders are read-only.</p>
      <form @submit.prevent="run(() => save(false))">
        <fieldset :disabled="!editable || busy">
          <label v-for="f in fields" :key="f.key">{{ f.label }}{{ f.required ? ' *' : '' }}
            <textarea v-if="f.type === 'textarea'" v-model="selected.content_json[f.key]" :aria-label="f.label" :required="f.required" />
            <select v-else-if="f.type === 'select'" v-model="selected.content_json[f.key]" :aria-label="f.label" :required="f.required"><option value="">Select…</option><option v-for="o in f.options" :key="o">{{ o }}</option></select>
            <input v-else-if="f.type === 'number'" v-model.number="selected.content_json[f.key]" type="number" step="any" :aria-label="f.label" :required="f.required">
            <input v-else v-model="selected.content_json[f.key]" :type="f.type" :aria-label="f.label" :required="f.required">
          </label>
        </fieldset>
        <div v-if="editable" class="toolbar"><button :disabled="busy">Save draft</button><button type="button" :disabled="busy" @click="run(() => save(true))">Save and submit</button><button type="button" :disabled="busy" @click="run(refresh)">Discard local draft and refresh</button></div>
      </form>
      <details><summary>Version history</summary><details v-for="v in versions" :key="v.version"><summary>Version {{ v.version }} · {{ v.author_name }} · {{ v.created_at }}</summary><pre>{{ JSON.stringify(v.content_json, null, 2) }}</pre></details></details>
      <div v-if="mine && selected.status === 'archived'"><h3>Append an amendment</h3><label>Treatment plan addendum<textarea v-model="amendment" /></label><button :disabled="busy || !amendment.trim()" @click="run(amend)">Append new version</button></div>
      <h2>Medical orders</h2>
      <p v-if="!orders.length">No orders for this record.</p>
      <ul><li v-for="o in orders" :key="o.id">{{ o.content_json.drug_name || o.order_type }} · {{ o.content_json.dose }} {{ o.content_json.frequency }} · {{ o.status }} <strong :class="o.validation_status">{{ o.validation_status }}</strong><p v-for="r in o.validation_detail" :key="r.message">{{ r.message }}</p><span v-if="orderEditable"><button :disabled="busy || o.status === 'stopped'" @click="editOrder(o)">Modify</button><button :disabled="busy || o.status === 'stopped'" @click="run(() => stop(o))">Stop</button></span></li></ul>
      <form v-if="orderEditable" @submit.prevent="run(preflight)"><fieldset :disabled="busy"><legend>{{ editingOrder ? 'Modify order' : 'New order' }}</legend>
        <label>Drug<select v-model="item.drug_code" aria-label="Drug" required @change="chooseDrug"><option value="">Choose drug</option><option v-for="d in drugs" :key="d.code" :value="d.code">{{ d.name }}</option></select></label>
        <label>Dose with units<input v-model="item.dose" required placeholder="20mg"></label><label>Frequency<select v-model="item.frequency" aria-label="Frequency"><option v-for="f in ['qd', 'bid', 'tid', 'qid']" :key="f">{{ f }}</option></select></label><label>Route<input v-model="item.route"></label><button>Validate and save</button>
      </fieldset></form>
    </article>
    <dialog :open="Boolean(validation && validation.overall !== 'passed')" :class="validation?.overall" aria-label="Order validation">
      <h2>{{ validation?.overall === 'blocked' ? 'Order blocked' : 'Dose warning' }}</h2>
      <template v-for="r in validation?.results" :key="r.index"><p v-for="reasonItem in r.reasons" :key="reasonItem.message">{{ reasonItem.message }}</p></template>
      <template v-if="validation?.overall === 'warning'"><label v-if="!editingOrder">Reason (optional)<input v-model="reason"></label><button :disabled="busy" @click="run(persistOrder)">Confirm and continue</button></template>
      <button :disabled="busy" @click="validation = null">Cancel / change drug</button>
    </dialog>
    <details v-if="currentTitle === 'admin'"><summary>Template management</summary><button @click="editTemplate(null)">New template</button><p v-for="t in templates" :key="t.id">{{ t.name }} · {{ t.is_active ? 'Active' : 'Inactive' }} <button @click="editTemplate(t)">Edit</button></p><form v-if="templateEditor" @submit.prevent="run(saveTemplate)"><label>Template definition (text, number, date, select, textarea)<textarea v-model="templateEditor" rows="15" /></label><button :disabled="busy">Save template</button></form></details>
  </section>
</template>

<style scoped>
.emr-workspace { padding: 24px; max-width: 1200px; margin: auto; color: var(--ink); }
.records-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 24px; }
h1 { margin: 0; font-size: 26px; }
h2 { font-size: 20px; margin: 24px 0 12px; }
.subtitle { margin: 8px 0 0; color: var(--ink-2); }
.records-controls, .records-results, article, .emr-workspace > details {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
}
.records-controls { padding: 20px; margin-bottom: 20px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: end; justify-content: flex-start; gap: 12px; margin: 16px 0; padding: 0; border: 0; }
.field-toolbar { margin: 0; }
.filter-toolbar { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1.4fr) minmax(0, 1fr) auto; }
.draft-toolbar { border-top: 1px solid var(--line-2); padding-top: 16px; margin-top: 20px; }
.draft-toolbar > label { flex: 0 1 360px; }
label { display: flex; flex-direction: column; gap: 8px; margin: 16px 0; min-width: 0; color: var(--ink-2); font-size: 13px; font-weight: 600; }
.field-toolbar > label { margin: 0; }
fieldset { min-width: 0; margin: 0; border: 1px solid var(--line); border-radius: var(--radius); padding: 16px; }
input, select, textarea, button { font: inherit; padding: 9px 12px; border: 1px solid var(--line); border-radius: var(--radius); color: var(--ink); background: var(--surface); }
input, select, button { min-height: 40px; }
input, select, textarea { width: 100%; min-width: 0; font-weight: 400; }
textarea { min-height: 100px; resize: vertical; }
button { cursor: pointer; margin: 0; font-size: 14px; font-weight: 600; white-space: nowrap; }
button:hover:not(:disabled) { border-color: var(--teal); color: var(--teal); background: var(--teal-soft); }
button:disabled { cursor: default; opacity: .5; }
button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, summary:focus-visible { outline: 2px solid var(--teal); outline-offset: 2px; }
.primary-button { background: var(--teal); border-color: var(--teal); color: white; }
.primary-button:hover:not(:disabled) { background: var(--teal-dark); color: white; }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 14px 16px; text-align: left; border-bottom: 1px solid var(--line-2); }
th { background: var(--surface-2); color: var(--ink-2); font-size: 12px; font-weight: 600; }
tbody tr:hover { background: var(--surface-2); }
.empty-state { padding: 40px 20px; margin: 0; text-align: center; color: var(--ink-2); }
.pagination { align-items: center; justify-content: flex-end; margin: 0; padding: 16px; }
.pagination span { margin-right: auto; order: -1; color: var(--ink-2); font-size: 13px; }
article, .emr-workspace > details { padding: 20px; margin-top: 24px; }
article > h2:first-child { margin-top: 0; }
details { margin: 20px 0; }
summary { cursor: pointer; font-weight: 600; }
details[open] > summary { margin-bottom: 16px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; background: var(--surface-2); border-radius: var(--radius); }
ul { list-style: none; padding: 0; }
li { padding: 16px 0; border-bottom: 1px solid var(--line-2); }
li button + button, dialog button + button { margin-left: 8px; }
.error, .blocked { color: var(--alert-dark); }
.warning { color: var(--warn); }
.passed { color: var(--ok); }
dialog { position: fixed; top: 22%; width: calc(100% - 32px); max-width: 600px; padding: 24px; border: 3px solid; border-radius: var(--radius-lg); background: var(--surface); z-index: 100; box-shadow: 0 12px 80px #0005; }
@media (max-width: 900px) {
  .filter-toolbar { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 600px) {
  .emr-workspace { padding: 16px; }
  .records-header { align-items: flex-start; flex-direction: column; }
  .records-controls, article, .emr-workspace > details { padding: 16px; }
  .filter-toolbar { grid-template-columns: minmax(0, 1fr); }
  .draft-toolbar > label { flex-basis: 100%; }
  .pagination { gap: 8px; }
}
</style>
