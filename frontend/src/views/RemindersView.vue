<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { work } from '../api/work'
const logs = ref([]), rules = ref([]), error = ref(''), busy = ref(false), page = ref(1), total = ref(0), unread = ref(0)
const form = ref({ patient_no: '', title: '', rtype: 'medication', cron_expr: '0 9 * * *', active: true })
let timer
async function load() {
  try {
    const [data, schedules] = await Promise.all([work(`/legacy/reminders?page=${page.value}&size=20`), work('/legacy/reminder-rules')])
    logs.value = data.items; total.value = data.total; unread.value = data.unread_count; rules.value = schedules
    window.dispatchEvent(new Event('reminders-read'))
  } catch (err) { error.value = err.message }
}
async function create() {
  busy.value = true; error.value = ''
  try { await work('/legacy/reminder-rules', 'POST', form.value); await load() } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
async function toggle(rule) { try { await work(`/legacy/reminder-rules/${rule.id}`, 'PATCH', { active: !rule.active }); await load() } catch (err) { error.value = err.message } }
async function done(log) { try { await work(`/legacy/reminders/${log.id}/done`, 'POST', {}); await load() } catch (err) { error.value = err.message } }
async function schedule(rule) { try { await work(`/legacy/reminder-rules/${rule.id}`, 'PATCH', { cron_expr: rule.cron_expr }); await load() } catch (err) { error.value = err.message } }
onMounted(() => { load(); timer = setInterval(load, 30000) })
onUnmounted(() => clearInterval(timer))
</script>
<template>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <section class="panel"><h2>Reminders</h2><p>Opening this list marks this page as read. {{ unread }} unread reminder(s) remain.</p><el-button @click="load">Refresh</el-button><p v-if="!logs.length">No reminders yet.</p><article v-for="log in logs" :key="log.id" class="row"><div><strong>{{ log.title }}</strong><p>{{ log.patient_no }} · {{ new Date(log.due_at).toLocaleString() }}</p></div><el-button :disabled="log.done" @click="done(log)">{{ log.done ? 'Done' : 'Mark done' }}</el-button></article><el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next" @current-change="load" /></section>
  <section class="panel"><h2>Reminder rules</h2><p>Schedules use Asia/Shanghai time. Linked rules run only during an active health plan's dates.</p><article v-for="rule in rules" :key="rule.id" class="row"><div><strong>{{ rule.title }}</strong><p>{{ rule.patient_no }} · {{ rule.rtype }} · {{ rule.active ? 'Active' : 'Disabled' }}<span v-if="rule.health_plan_id"> · Plan #{{ rule.health_plan_id }}</span></p><el-input v-model="rule.cron_expr" aria-label="Cron schedule" style="width:190px" /><el-button @click="schedule(rule)">Update schedule</el-button></div><el-button @click="toggle(rule)">{{ rule.active ? 'Disable' : 'Enable' }}</el-button></article></section>
  <form class="panel" @submit.prevent="create"><h2>Create a reminder</h2><label>Patient number<el-input v-model="form.patient_no" required /></label><label>Title<el-input v-model="form.title" required maxlength="200" /></label><label>Type<el-select v-model="form.rtype"><el-option value="medication" label="Medication" /><el-option value="followup" label="Follow-up" /><el-option value="checkin" label="Check-in" /></el-select></label><label>Schedule<el-select v-model="form.cron_expr"><el-option value="0 9 * * *" label="Daily at 09:00" /><el-option value="0 9 * * 0" label="Monday at 09:00" /><el-option value="* * * * *" label="Every minute (demo)" /></el-select></label><el-button native-type="submit" type="primary" :loading="busy">Create reminder</el-button></form>
</template>
<style scoped>
.panel{padding:24px;background:#fff;border:1px solid #dde6e3;border-radius:12px;margin-bottom:20px}.row{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:16px 0;border-bottom:1px solid #dde6e3}label{display:block;margin:16px 0;max-width:420px}label .el-input,label .el-select{margin-top:6px}.error{color:#a42222}
</style>
