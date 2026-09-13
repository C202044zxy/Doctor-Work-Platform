<script setup>
import { computed, nextTick, onUnmounted, ref, useTemplateRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { signIn } from '../session'

import { USE_MOCK_AUTH, authentication } from '../api/client'
import CameraCapture from '../components/CameraCapture.vue'
import MockBadge from '../components/MockBadge.vue'
import SmsCodeInput from '../components/SmsCodeInput.vue'

const CODE_TTL_SECONDS = 300 // five minutes, matching the planned Redis expiry

const route = useRoute()
const router = useRouter()

// T41 §3.4: the sign-in page carries two methods. `password` is the T05/T06 email
// second factor; `sms` is the T41 code, which needs no password at all.
const method = ref('password')
const methods = [
  { value: 'password', label: 'Password' },
  { value: 'sms', label: 'SMS code' },
]

const heading = computed(() => {
  if (method.value === 'sms') return 'Sign in by SMS'
  if (step.value !== 'credentials') return 'Check your email'
  return registering.value ? 'Create an account' : 'Sign in'
})

function chooseMethod(value) {
  method.value = value
  error.value = ''
  notice.value = ''
  useAnotherAccount()
}

// The second factor is one thing, not a menu: the email code. The password step
// is what decides whether a factor is needed at all, so a second factor that is
// itself a way in without a password would make the password decorative.
//
// SMS and face are therefore *entry points* alongside password, not alternatives
// to the email code: §3.4's top-level 「短信验证码登录」 tab, and §4.3.3's own
// 【校验】 flow (登录页 →「人脸识别」→ 用户名 → 拍照). Both are simulated.
function submit() {
  if (method.value !== 'password') return
  return step.value === 'credentials' ? submitCredentials() : submitCode()
}

const step = ref('credentials')
const registering = ref(false)
const name = ref('')
const email = ref('')
const department = ref('')
const notice = ref('')

function toggleSignup() {
  useAnotherAccount()
  registering.value = !registering.value
  password.value = ''
  notice.value = ''
}

async function requestSignup() {
  return authentication.signup({
    username: username.value.trim(), password: password.value,
    name: name.value.trim(), email: email.value.trim(), department: department.value.trim(),
  })
}
const username = ref('')
const ticket = ref('')
const password = ref('')
const code = ref('')
const error = ref('')
const busy = ref(false)
const secondsLeft = ref(0)
const codeInput = useTemplateRef('codeInput')
const photo = ref(null)
const faceBusy = ref(false)

let timer = null

const countdown = computed(() => {
  const minutes = Math.floor(secondsLeft.value / 60)
  const seconds = String(secondsLeft.value % 60).padStart(2, '0')
  return `${minutes}:${seconds}`
})

onUnmounted(() => clearInterval(timer))

function startCountdown() {
  secondsLeft.value = CODE_TTL_SECONDS
  clearInterval(timer)
  timer = setInterval(() => {
    if (secondsLeft.value <= 0) {
      clearInterval(timer)
      return
    }
    secondsLeft.value -= 1
  }, 1000)
}

async function submitCredentials() {
  error.value = ''
  if (!username.value.trim()) {
    error.value = 'Enter your username.'
    return
  }
  if (!password.value) {
    error.value = 'Enter your password.'
    return
  }

  busy.value = true
  try {
    const result = registering.value
      ? await requestSignup()
      : await authentication.login(username.value.trim(), password.value)
    ticket.value = result.ticket
    step.value = 'code'
    if (!registering.value) await authentication.sendCode(ticket.value)
    startCountdown()
    await nextTick()
    codeInput.value?.focus()
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}

function finish(data) {
  signIn(data)
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  router.replace(redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : { name: 'dashboard' })
}

async function submitCode() {
  error.value = ''
  if (!/^\d{6}$/.test(code.value.trim())) {
    error.value = 'Enter the 6-digit code from the email.'
    return
  }
  busy.value = true
  try {
    if (registering.value) {
      await authentication.verifySignup(ticket.value, code.value.trim())
      toggleSignup()
      notice.value = 'Email verified. Your account is awaiting administrator activation. Contact your administrator before signing in.'
    } else {
      finish(await authentication.verifyCode(ticket.value, code.value.trim()))
    }
  }
  catch (err) { error.value = err.message }
  finally { busy.value = false }
}

// T41 §3.4 — the SMS panel reports its own errors, so the only thing left here is
// what to do with a success, and there is only one scene reachable from this page:
// the passwordless one.
function handleSmsSuccess(data) {
  notice.value = ''
  if (data?.access_token) {
    finish(data)
    return
  }
  // No session came back. In the mock that is by design — it cannot mint a JWT,
  // and pretending otherwise would leave the user inside a shell where every
  // request 401s (§1.1 rule 3). Once the endpoints land, a response that is not a
  // token means the shape changed, and saying so beats a silent loop.
  notice.value = 'Simulated sign-in reached the end of the flow. No session was issued: the real endpoint is still being built.'
}

function handleCaptured(blob) {
  photo.value = blob
  error.value = ''
}

// T42 §4.3.1 ② — username plus photo. Replaces the T05 demo route
// (`/auth/face/login`), whose matcher returned True for every photo and so could
// never satisfy "a different face is refused".
//
// This is a way in without a password, so it answers to the credentials step and
// nothing else. No `scene` argument: §8 item 4 (B+A+C) is what settles whether an
// `mfa` variant of this endpoint exists, and sending one here would settle it by
// accident.
async function submitFace() {
  error.value = ''
  if (!username.value.trim()) {
    error.value = 'Enter your username first.'
    return
  }
  if (!photo.value) {
    error.value = 'Take a photo first.'
    return
  }
  faceBusy.value = true
  try {
    const data = await authentication.faceVerify(username.value.trim(), photo.value)
    notice.value = ''
    if (data?.simulated) {
      notice.value = 'Simulated sign-in reached the end of the flow. No session was issued: the real endpoint is still being built.'
      return
    }
    finish(data)
  } catch (err) { error.value = err.message }
  finally { faceBusy.value = false }
}

function useAnotherAccount() {
  clearInterval(timer)
  secondsLeft.value = 0
  code.value = ''
  error.value = ''
  // A photo belongs to one attempt at one account; leaving the credentials step
  // must not leave it behind as "already captured".
  photo.value = null
  step.value = 'credentials'
}

async function resend() {
  code.value = ''
  error.value = ''
  busy.value = true
  try {
    if (registering.value) {
      const result = await requestSignup()
      ticket.value = result.ticket
    } else {
      await authentication.sendCode(ticket.value)
    }
    startCountdown()
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}
</script>

<template>
  <div class="login">
    <section class="pitch">
      <div class="pitch-brand">
        <svg viewBox="0 0 24 24" width="30" height="30" aria-hidden="true">
          <rect width="24" height="24" rx="7" fill="#fff" />
          <path
            d="M4 12.4h3.6l1.9-4.6 2.9 9 1.9-4.4H20"
            fill="none"
            stroke="var(--teal)"
            stroke-width="1.7"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <span>Doctor Work Platform</span>
      </div>

      <div class="pitch-body">
        <h1>One workspace for the clinical day.</h1>
        <p class="pitch-lede">
          Patient records, medical order entry, online and specialist consultation, and long-term
          care management, in a single place.
        </p>

        <ul class="pitch-points">
          <li>
            <strong>Two-factor sign-in</strong>
            Password plus a one-time code sent by email.
          </li>
          <li>
            <strong>Scoped access</strong>
            Role decides what you can do; department decides whose records you can open.
          </li>
          <li>
            <strong>Full audit trail</strong>
            Every write and every sensitive read is recorded and cannot be altered.
          </li>
        </ul>
      </div>

      <p class="pitch-foot">Software Engineering course project · 2026</p>
    </section>

    <section class="form-side">
      <form class="form" @submit.prevent="submit">
        <div class="form-head">
          <h2 class="form-title">
            {{ heading }}
          </h2>
          <MockBadge />
        </div>
        <p class="form-lede">
          <template v-if="method === 'sms'">
            Sign in with a one-time code sent to your registered mobile number. No password.
          </template>
          <template v-else-if="step === 'credentials'">
            {{ registering ? 'Verify your email, then ask an administrator to activate your staff account.' : 'Use your hospital account.' }}
          </template>
          <template v-else>
            Enter the code sent to your account’s registered email address.
          </template>
        </p>

        <div v-if="step === 'credentials' && !registering" class="methods" role="tablist">
          <button
            v-for="option in methods"
            :key="option.value"
            type="button"
            role="tab"
            class="method"
            :class="{ active: method === option.value }"
            :aria-selected="method === option.value"
            :disabled="busy"
            @click="chooseMethod(option.value)"
          >
            {{ option.label }}
          </button>
        </div>

        <p v-if="notice" class="form-notice" role="status">{{ notice }}</p>

        <SmsCodeInput
          v-if="method === 'sms'"
          scene="login"
          @success="handleSmsSuccess"
        />

        <template v-else-if="step === 'credentials'">
          <template v-if="registering">
            <label class="field">
              <span class="field-label">Full name</span>
              <el-input v-model="name" size="large" autocomplete="name" maxlength="100" :disabled="busy" required />
            </label>
            <label class="field">
              <span class="field-label">Email</span>
              <el-input v-model="email" type="email" size="large" autocomplete="email" maxlength="254" :disabled="busy" required />
            </label>
            <label class="field">
              <span class="field-label">Department</span>
              <el-input v-model="department" size="large" placeholder="e.g. General Medicine" maxlength="100" :disabled="busy" required />
            </label>
          </template>
          <label class="field">
            <span class="field-label">Username</span>
            <el-input
              v-model="username"
              type="text"
              size="large"
              autocomplete="username"
              placeholder="Your username"
              :disabled="busy"
            />
          </label>

          <label class="field">
            <span class="field-label">Password</span>
            <el-input
              v-model="password"
              type="password"
              size="large"
              :autocomplete="registering ? 'new-password' : 'current-password'"
              :minlength="registering ? 8 : 1"
              maxlength="72"
              required
              show-password
              placeholder="Your password"
              :disabled="busy"
            />
          </label>
        </template>

        <template v-else>
          <label class="field">
            <span class="field-label">6-digit code</span>
            <el-input
              ref="codeInput"
              v-model="code"
              size="large"
              class="code-input"
              inputmode="numeric"
              maxlength="6"
              autocomplete="one-time-code"
              placeholder="000000"
              :disabled="busy"
            />
          </label>

          <p class="expiry">
            <template v-if="secondsLeft > 0">
              Code expires in <span class="data">{{ countdown }}</span>
            </template>
            <template v-else> The code has expired. </template>
            <button
              type="button"
              class="resend"
              :disabled="secondsLeft > 0 || busy"
              @click="resend"
            >
              Send a new code
            </button>
          </p>
        </template>

        <template v-if="method === 'password'">
          <p v-if="error" class="form-error" role="alert">{{ error }}</p>

          <el-button
            type="primary"
            size="large"
            native-type="submit"
            class="submit"
            :loading="busy"
          >
            {{ step === 'credentials' ? 'Continue' : (registering ? 'Verify email and create account' : 'Verify and sign in') }}
          </el-button>

          <p v-if="step === 'code'" class="back">
            <button type="button" class="resend" :disabled="busy" @click="useAnotherAccount">
              Use a different account
            </button>
          </p>

          <p v-if="step === 'credentials'" class="back">
            <button type="button" class="resend" :disabled="busy" @click="toggleSignup">
              {{ registering ? 'Already have an account? Sign in' : 'Create an account with email' }}
            </button>
          </p>

          <div v-if="step === 'credentials' && !registering" class="face-entry">
            <p class="face-lede">Or sign in with your face — no password.</p>
            <CameraCapture purpose="verify" :busy="faceBusy" @captured="handleCaptured" />
            <el-button
              v-if="photo"
              type="primary"
              class="submit"
              :loading="faceBusy"
              :disabled="faceBusy || !username.trim()"
              @click="submitFace"
            >
              Sign in as {{ username.trim() }}
            </el-button>
          </div>
        </template>
        <p v-if="method === 'password' && !registering" class="demo-note">
          SMS and face recognition are simulated: the pages, the countdown, the
          lockout and the photo capture are real, but nothing leaves for a real
          gateway or provider. Sign-in still needs the endpoints being built for
          T41 and T42.
        </p>
      </form>
    </section>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  grid-template-columns: 1fr 1fr;
  min-height: 100%;
}

/* Left panel --------------------------------------------------------------- */

.pitch {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 44px 48px;
  color: #fff;
  background: var(--teal-dark);
}

.pitch-brand {
  display: flex;
  gap: 11px;
  align-items: center;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.pitch-body {
  max-width: 46ch;
  padding: 40px 0;
}

.pitch h1 {
  font-size: 30px;
  font-weight: 600;
  line-height: 1.25;
  letter-spacing: -0.02em;
}

.pitch-lede {
  margin: 16px 0 0;
  font-size: 14.5px;
  line-height: 1.6;
  color: rgb(255 255 255 / 72%);
}

.pitch-points {
  padding: 0;
  margin: 34px 0 0;
  list-style: none;
}

.pitch-points li {
  position: relative;
  padding: 0 0 0 20px;
  margin-bottom: 15px;
  font-size: 13.5px;
  line-height: 1.55;
  color: rgb(255 255 255 / 72%);
}

.pitch-points li::before {
  position: absolute;
  top: 8px;
  left: 2px;
  width: 6px;
  height: 6px;
  content: '';
  border: 1.5px solid rgb(255 255 255 / 55%);
  border-radius: 50%;
}

.pitch-points strong {
  font-weight: 600;
  color: #fff;
}

.pitch-foot {
  margin: 0;
  font-size: 12px;
  color: rgb(255 255 255 / 50%);
}

/* Right panel -------------------------------------------------------------- */

.form-side {
  display: grid;
  place-items: center;
  padding: 40px;
  background: var(--surface);
}

.form {
  width: 100%;
  max-width: 372px;
}

.form-title {
  font-size: 22px;
  letter-spacing: -0.015em;
}

.form-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
}

.methods {
  display: flex;
  gap: 4px;
  padding: 3px;
  margin-bottom: 22px;
  background: var(--surface-2);
  border: 1px solid var(--line-2);
  border-radius: var(--radius);
}

.method {
  flex: 1;
  padding: 7px 10px;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
  cursor: pointer;
  background: none;
  border: 0;
  border-radius: 4px;
}

.method.active {
  color: var(--teal);
  background: var(--surface);
  box-shadow: 0 1px 2px rgb(20 33 43 / 8%);
}

.method:disabled {
  cursor: default;
  opacity: 0.6;
}

.form-notice {
  padding: 10px 12px;
  margin: -4px 0 16px;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-2);
  background: var(--surface-2);
  border-radius: var(--radius);
}

.face-entry {
  padding-top: 20px;
  margin-top: 22px;
  border-top: 1px solid var(--line-2);
}

.face-lede {
  margin: 0 0 12px;
  font-size: 12.5px;
  color: var(--ink-2);
}

.form-lede {
  margin: 8px 0 28px;
  font-size: 13.5px;
  line-height: 1.55;
  color: var(--ink-2);
}

.field {
  display: block;
  margin-bottom: 18px;
}

.field-label {
  display: block;
  margin-bottom: 7px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
}

.code-input :deep(.el-input__inner) {
  font-family: var(--font-data);
  font-size: 20px;
  letter-spacing: 0.42em;
  text-indent: 0.42em;
}

.expiry {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 10px;
  align-items: baseline;
  justify-content: space-between;
  margin: 0 0 18px;
  font-size: 12.5px;
  color: var(--ink-2);
}

.resend {
  padding: 0;
  font: inherit;
  font-weight: 600;
  color: var(--teal);
  cursor: pointer;
  background: none;
  border: 0;
}

.resend:hover:not(:disabled) {
  text-decoration: underline;
}

.resend:disabled {
  color: var(--ink-3);
  cursor: default;
}

.form-error {
  padding: 10px 12px;
  margin: -4px 0 16px;
  font-size: 13px;
  color: var(--alert-dark);
  background: var(--alert-soft);
  border-radius: var(--radius);
}

.submit {
  width: 100%;
}

.back {
  margin: 14px 0 0;
  text-align: center;
}

.demo-note {
  padding-top: 20px;
  margin: 26px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-3);
  border-top: 1px solid var(--line-2);
}

@media (max-width: 900px) {
  .login {
    grid-template-columns: 1fr;
  }

  .pitch {
    display: none;
  }
}
</style>
