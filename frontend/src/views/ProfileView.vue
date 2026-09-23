<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { profile } from '../api/client'
import { currentUserId, signOut, updateCurrentUser } from '../session'
import { appearance, FONTS, THEMES, saveAppearance } from '../appearance'
import FaceEnrollView from './FaceEnrollView.vue'

const router = useRouter()
const route = useRoute()
const section = computed({
  get: () => ['appearance', 'face'].includes(route.query.section) ? route.query.section : 'details',
  set: value => router.replace({ name: 'profile', query: value === 'details' ? {} : { section: value } }),
})
const saved = ref(null), loading = ref(true), error = ref(''), saving = ref(false), sending = ref(false)
const passwordBusy = ref(false), passwordError = ref('')
const appearanceError = ref('')
const form = reactive({ name: '', email: '', current_password: '', email_code: '' })
const passwords = reactive({ current_password: '', new_password: '', confirmation: '' })
const emailChanged = computed(() => saved.value && form.email.toLowerCase() !== saved.value.email.toLowerCase())

async function load() {
  loading.value = true
  error.value = ''
  try {
    saved.value = await profile.get()
    form.name = saved.value.name
    form.email = saved.value.email
  } catch (err) { error.value = err.message }
  finally { loading.value = false }
}
async function sendCode() {
  error.value = ''
  sending.value = true
  try {
    await profile.sendEmailCode({ email: form.email.trim(), current_password: form.current_password })
    ElMessage.success('Verification code sent to your new email. It expires in 5 minutes.')
  } catch (err) { error.value = err.message }
  finally { sending.value = false }
}
async function save() {
  error.value = ''
  saving.value = true
  try {
    const payload = { name: form.name.trim(), email: form.email.trim() }
    if (emailChanged.value) Object.assign(payload, { current_password: form.current_password, email_code: form.email_code })
    saved.value = await profile.update(payload)
    updateCurrentUser(saved.value)
    form.name = saved.value.name
    form.email = saved.value.email
    form.current_password = ''; form.email_code = ''
    ElMessage.success('Profile updated.')
  } catch (err) { error.value = err.message }
  finally { saving.value = false }
}
async function changePassword() {
  passwordError.value = ''
  if (passwords.new_password !== passwords.confirmation) {
    passwordError.value = 'The new passwords do not match.'
    return
  }
  if (new TextEncoder().encode(passwords.new_password).length > 72) {
    passwordError.value = 'Use at most 72 UTF-8 bytes for your password.'
    return
  }
  passwordBusy.value = true
  try {
    await profile.changePassword({ current_password: passwords.current_password, new_password: passwords.new_password })
    signOut()
    ElMessage.success('Password changed. Sign in with your new password.')
    await router.push({ name: 'login' })
  } catch (err) { passwordError.value = err.message }
  finally { passwordBusy.value = false }
}
onMounted(load)

function changeAppearance(patch) {
  appearanceError.value = ''
  try { saveAppearance(currentUserId.value, { ...appearance, ...patch }) }
  catch { appearanceError.value = 'Your browser could not save these settings. Check storage permissions and try again.' }
}
</script>

<template>
  <div class="profile-page">
    <header><p class="eyebrow">YOUR ACCOUNT</p><h2>My profile</h2><p class="muted">Keep your name and sign-in details up to date.</p></header>
    <p v-if="loading" role="status">Loading profile…</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <el-button v-if="!loading && !saved" @click="load">Try again</el-button>
    <template v-if="saved">
      <section class="panel identity">
        <span class="profile-avatar" aria-hidden="true">{{ saved.name.slice(0, 1).toUpperCase() }}</span>
        <div><h3>{{ saved.name }}</h3><p>{{ saved.username }} · {{ saved.title }} · {{ saved.department }}</p><p class="muted">Your administrator manages your role and department.</p></div>
      </section>
      <dl class="panel account-facts">
        <div><dt>Account ID</dt><dd>{{ saved.id }}</dd></div>
        <div><dt>Username</dt><dd>{{ saved.username }}</dd></div>
        <div><dt>Role</dt><dd>{{ { admin: 'Administrator', senior: 'Senior physician', junior: 'Junior physician' }[saved.title] ?? saved.title }}</dd></div>
        <div><dt>Department</dt><dd>{{ saved.department }}</dd></div>
        <div><dt>Account status</dt><dd>{{ { active: 'Active', disabled: 'Disabled', pending: 'Pending' }[saved.status] ?? saved.status }}</dd></div>
        <div><dt>Created</dt><dd>{{ saved.created_at ? new Date(saved.created_at).toLocaleString() : '—' }}</dd></div>
      </dl>
      <el-tabs v-model="section" class="profile-tabs">
        <el-tab-pane label="Personal information" name="details" />
        <el-tab-pane label="Appearance" name="appearance" />
        <el-tab-pane label="Face enrolment" name="face" />
      </el-tabs>
      <div v-if="section === 'details'" class="profile-grid">
        <form class="panel editor" @submit.prevent="save">
          <h3>Personal details</h3>
          <label>Doctor name<input v-model="form.name" autocomplete="name" required maxlength="100" /></label>
          <label>Email<input v-model="form.email" type="email" autocomplete="email" required maxlength="254" /></label>
          <template v-if="emailChanged">
            <p class="muted">Confirm your password and verify the new email before saving.</p>
            <label>Current password<input v-model="form.current_password" type="password" autocomplete="current-password" required /></label>
            <el-button :loading="sending" :disabled="!form.current_password || saving" @click="sendCode">Send email code</el-button>
            <label>Email verification code<input v-model="form.email_code" autocomplete="one-time-code" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required /></label>
          </template>
          <el-button type="primary" native-type="submit" :loading="saving" :disabled="sending">Save changes</el-button>
        </form>
        <form class="panel editor" @submit.prevent="changePassword">
          <h3>Change password</h3><p class="muted">At least 8 characters. Changing your password signs out existing sessions.</p>
          <label>Current password<input v-model="passwords.current_password" type="password" autocomplete="current-password" required /></label>
          <label>New password<input v-model="passwords.new_password" type="password" autocomplete="new-password" minlength="8" required /></label>
          <label>Confirm new password<input v-model="passwords.confirmation" type="password" autocomplete="new-password" minlength="8" required /></label>
          <p v-if="passwordError" class="error" role="alert">{{ passwordError }}</p>
          <el-button native-type="submit" :loading="passwordBusy">Update password</el-button>
        </form>
      </div>
      <section v-if="section === 'appearance'" class="panel editor appearance" aria-label="Appearance settings">
        <h3>Appearance</h3>
        <p class="muted">Choose your font and theme color. Changes apply immediately and are remembered for your account in this browser.</p>
        <label>Font family
          <select :value="appearance.font" @change="changeAppearance({ font: $event.target.value })">
            <option v-for="font in FONTS" :key="font.id" :value="font.id">{{ font.label }}</option>
          </select>
        </label>
        <fieldset><legend>Theme color</legend><div class="theme-options">
          <button v-for="theme in THEMES" :key="theme.id" type="button" :aria-pressed="appearance.theme === theme.id" :aria-label="`${theme.label} theme`" @click="changeAppearance({ theme: theme.id })">
            <span class="swatch" :style="{ background: theme.color }" aria-hidden="true"></span>{{ theme.label }}<span v-if="appearance.theme === theme.id" aria-hidden="true"> ✓</span>
          </button>
        </div></fieldset>
        <div class="appearance-preview"><strong>Your workspace, your preferences</strong><p>The quick brown fox jumps over the lazy dog. 0123456789</p><el-button type="primary">Theme preview</el-button></div>
        <p v-if="appearanceError" class="error" role="alert">{{ appearanceError }}</p>
        <el-button link @click="changeAppearance({ font: 'system', theme: 'teal' })">Restore default appearance</el-button>
      </section>
      <FaceEnrollView v-if="section === 'face'" />
    </template>
  </div>
</template>

<style scoped>
.account-facts{padding:20px 26px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin:0}.account-facts dt{font-size:12px;color:var(--ink-2);margin-bottom:5px}.account-facts dd{margin:0;font-size:14px;overflow-wrap:anywhere}.profile-tabs{margin-bottom:-18px}@media(max-width:760px){.account-facts{grid-template-columns:repeat(2,minmax(0,1fr))}}
.profile-page{max-width:1040px;margin:0 auto;display:grid;gap:22px}.eyebrow{font-size:11px;letter-spacing:.14em;color:var(--teal);font-weight:700}h2{font-size:28px;margin:6px 0}h3{margin:0;font-size:17px}.muted{color:var(--text-muted,#657871);font-size:13px;line-height:1.6}.identity{padding:24px;display:flex;align-items:center;gap:20px}.identity p{margin:6px 0}.profile-avatar{width:60px;height:60px;border-radius:18px;display:grid;place-items:center;background:#e1f0eb;color:var(--teal);font-size:28px;flex-shrink:0}.profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px}.editor{padding:26px;display:flex;flex-direction:column;align-items:stretch;gap:18px}.editor label{display:grid;gap:8px;font-size:13px;font-weight:600}.editor input{font:inherit;font-weight:400;padding:11px 12px;border:1px solid var(--line,#dce6e3);border-radius:7px;width:100%;box-sizing:border-box}.editor input:focus{outline:2px solid var(--teal);outline-offset:2px}.editor .el-button{align-self:flex-start;margin:0}.error{color:#a42222;font-size:13px}@media(max-width:760px){.profile-grid{grid-template-columns:1fr}.identity{align-items:flex-start}}
</style>
<style scoped>
.appearance select{font:inherit;padding:10px;border:1px solid var(--line);border-radius:7px;background:var(--surface);color:var(--ink);max-width:360px}.appearance fieldset{border:0;padding:0;margin:0}.appearance legend{font-size:13px;font-weight:600;margin-bottom:12px}.theme-options{display:flex;flex-wrap:wrap;gap:10px}.theme-options button{display:flex;align-items:center;gap:8px;padding:10px 14px;border:1px solid var(--line);border-radius:7px;background:var(--surface);color:var(--ink);font:inherit;cursor:pointer}.theme-options button[aria-pressed='true']{border-color:var(--teal);box-shadow:0 0 0 1px var(--teal);background:var(--teal-soft)}.swatch{width:18px;height:18px;border-radius:50%}.appearance-preview{padding:20px;background:var(--teal-soft);border-radius:7px;color:var(--ink)}.appearance-preview p{margin:8px 0 15px}
</style>
