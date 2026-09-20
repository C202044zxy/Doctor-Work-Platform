<script setup>
import { onMounted, ref } from 'vue'
import { work } from '../api/work'
const plans = ref([]), selected = ref(null), error = ref(''), busy = ref(false), query = ref(''), page = ref(1), total = ref(0)
const today = () => new Date().toLocaleDateString('en-CA')
const blank = () => ({ patient_no: '', title: '', goals: '', instructions: '', entries: [{ kind: 'medication', text: '', done: false }], start_date: today(), end_date: today(), status: 'active' })
const form = ref(blank()), editing = ref(false), reminder = ref(false), cron = ref('0 9 * * *'), rtype = ref('medication')
async function load() {
  try { const data = await work(`/legacy/health-plans?${new URLSearchParams({ page: page.value, size: 20, ...(query.value ? { patient_no: query.value.trim() } : {}) })}`); plans.value = data.items; total.value = data.total }
  catch (err) { error.value = err.message }
}
async function open(id) { try { selected.value = await work(`/legacy/health-plans/${id}`); editing.value = false } catch (err) { error.value = err.message } }
function create() { selected.value = null; form.value = blank(); reminder.value = false; editing.value = true; error.value = '' }
function edit() {
  const p = selected.value
  form.value = { patient_no: p.patient_no, title: p.title, goals: p.goals, instructions: p.instructions, entries: p.entries.map(e => ({ ...e })), start_date: p.start_date, end_date: p.end_date, status: p.status }
  reminder.value = false; editing.value = true
}
async function save() {
  busy.value = true; error.value = ''
  try {
    const body = { ...form.value, ...(reminder.value ? { new_reminder_rules: [{ patient_no: form.value.patient_no, title: form.value.title, rtype: rtype.value, cron_expr: cron.value, active: true }] } : {}) }
    selected.value = await work(selected.value ? `/legacy/health-plans/${selected.value.id}` : '/legacy/health-plans', selected.value ? 'PATCH' : 'POST', body)
    editing.value = false; await load()
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
onMounted(load)
</script>
<template>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <div class="toolbar"><el-input v-model="query" placeholder="Patient number" clearable style="width:220px" /><el-button @click="page = 1; load()">Search</el-button><el-button type="primary" @click="create">Create health plan</el-button><router-link to="/legacy/reminders">Reminders</router-link></div>
  <div class="columns">
    <section class="panel"><h2>Health plans</h2><p v-if="!plans.length">No plans found.</p><button v-for="plan in plans" :key="plan.id" class="plan" @click="open(plan.id)"><strong>{{ plan.title }}</strong><p>{{ plan.patient_no }} · {{ plan.status }}</p><small>{{ plan.start_date }} — {{ plan.end_date }}</small></button><el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next" @current-change="load" /></section>
    <section class="panel">
      <form v-if="editing" @submit.prevent="save">
        <h2>{{ selected ? 'Edit plan' : 'New health plan' }}</h2>
        <label>Patient number<el-input v-model="form.patient_no" required :disabled="Boolean(selected)" /></label>
        <label>Title<el-input v-model="form.title" required maxlength="200" /></label>
        <label>Goals<el-input v-model="form.goals" type="textarea" maxlength="10000" /></label>
        <label>Instructions<el-input v-model="form.instructions" type="textarea" maxlength="10000" /></label>
        <div class="toolbar"><label>Start date<input v-model="form.start_date" type="date" required /></label><label>End date<input v-model="form.end_date" type="date" :min="form.start_date" required /></label></div>
        <label>Status<el-select v-model="form.status"><el-option value="active" label="Active" /><el-option value="completed" label="Completed" /><el-option value="terminated" label="Terminated" /></el-select></label>
        <h3>Plan entries</h3>
        <div v-for="(entry, index) in form.entries" :key="index" class="entry"><el-select v-model="entry.kind"><el-option value="medication" label="Medication" /><el-option value="followup" label="Follow-up" /><el-option value="diet_exercise" label="Diet / exercise" /></el-select><el-input v-model="entry.text" placeholder="Instructions" required maxlength="2000" /><el-checkbox v-model="entry.done">Done</el-checkbox><el-button @click="form.entries.splice(index, 1)">Remove</el-button></div>
        <el-button @click="form.entries.push({ kind: 'followup', text: '', done: false })">Add entry</el-button>
        <label><el-checkbox v-model="reminder">Create a linked reminder</el-checkbox></label>
        <template v-if="reminder"><label>Reminder type<el-select v-model="rtype"><el-option value="medication" label="Medication" /><el-option value="followup" label="Follow-up" /><el-option value="checkin" label="Check-in" /></el-select></label><label>Schedule (Asia/Shanghai)<el-select v-model="cron"><el-option value="0 9 * * *" label="Every day at 09:00" /><el-option value="0 9 * * 0" label="Every Monday at 09:00" /><el-option value="* * * * *" label="Every minute (demo)" /></el-select></label></template>
        <div class="toolbar"><el-button native-type="submit" type="primary" :loading="busy">Save plan</el-button><el-button @click="editing = false">Cancel</el-button></div>
      </form>
      <template v-else-if="selected"><h2>{{ selected.title }}</h2><p>{{ selected.patient_no }} · {{ selected.status }}</p><p>{{ selected.start_date }} — {{ selected.end_date }}</p><h3>Goals</h3><p>{{ selected.goals || 'No goals recorded.' }}</p><h3>Instructions</h3><p class="text">{{ selected.instructions }}</p><h3>Entries</h3><p v-for="(entry, i) in selected.entries" :key="i">{{ entry.done ? '✓ Done' : '○ Pending' }} · {{ entry.kind }} — {{ entry.text }}</p><p>Linked reminder rules: {{ selected.reminder_rule_ids.join(', ') || 'None' }}</p><el-button @click="edit">Edit plan / update progress</el-button></template>
      <p v-else>Select a plan or create one.</p>
    </section>
  </div>
</template>
<style scoped>
.columns{display:grid;grid-template-columns:1fr 2fr;gap:20px}.panel{padding:24px;border:1px solid #dde6e3;border-radius:12px;background:#fff;min-width:0}.toolbar,.entry{display:flex;gap:12px;align-items:center;margin:16px 0;flex-wrap:wrap}.entry .el-input{flex:1;min-width:160px}.entry .el-select{width:150px}.plan{display:block;width:100%;text-align:left;padding:16px;background:none;border:0;border-bottom:1px solid #dde6e3;cursor:pointer;font:inherit}label{display:block;margin:14px 0}label>.el-input,label>.el-select,label>input{display:block;margin-top:6px}input{padding:8px}.error{color:#a42222}.text{white-space:pre-wrap}@media(max-width:950px){.columns{grid-template-columns:1fr}}
</style>
