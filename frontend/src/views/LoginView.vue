<script setup>
import { computed, nextTick, onUnmounted, ref, useTemplateRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { signIn } from '../session'

import { USE_MOCK_AUTH, authentication } from '../api/client'
import CameraCapture from '../components/CameraCapture.vue'
import MockBadge from '../components/MockBadge.vue'
import SmsCodeInput from '../components/SmsCodeInput.vue'

// Two different clocks, and conflating them was the bug: the *code* lives for
// five minutes (the Redis TTL), but you may only ask for a *new* one once every
// sixty. The contract states both — "TTL of 300 seconds" and "One send per
// account per 60 seconds".
const CODE_TTL_SECONDS = 300
const SEND_COOLDOWN_SECONDS = 60

const route = useRoute()
const router = useRouter()

// The page is two steps, and the order carries the meaning: credentials first,
// then one of three ways to prove the second factor. The channel is a choice of
// *how* to verify an already-password-checked identity, so it cannot sit beside
// the password as a peer entry point. Plan M1 §3.2 and S2-05 name the three —
// `email` / `sms` / `face`, 三选一 — and M1-08 makes a failure on any of them
// count against the same lockout counter.
const step = ref('credentials') // 'credentials' | 'choose' | 'code'
const channel = ref('email') // 'email' | 'sms' | 'face'

const channels = [
  { value: 'email', label: 'Email code' },
  { value: 'sms', label: 'SMS code' },
  { value: 'face', label: 'Face' },
]

const registering = ref(false)
const name = ref('')
const email = ref('')
const department = ref('')
const notice = ref('')

const username = ref('')
const ticket = ref('')
const password = ref('')
const code = ref('')
const error = ref('')
const busy = ref(false)
const codeInput = useTemplateRef('codeInput')
const photo = ref(null)
const faceBusy = ref(false)

// Picking a channel must only pick it. Sending is a separate, deliberate press,
// so that the button — and the wait it reports — is something the user can see
// rather than a side effect of choosing where to look.
const codeSent = ref(false)
const cooldownLeft = ref(0) // gates "Send code"; the server's 60s window
const expiresLeft = ref(0) // the code's own five minutes; display only
let timer = null

const heading = computed(() => {
  if (step.value === 'choose') {
    if (channel.value === 'sms') return 'Verify by SMS'
    if (channel.value === 'face') return 'Verify with your face'
    return 'Verify by email'
  }
  if (step.value === 'code') return 'Check your email'
  return registering.value ? 'Create an account' : 'Sign in'
})

const expiryCountdown = computed(() => {
  const minutes = Math.floor(expiresLeft.value / 60)
  return `${minutes}:${String(expiresLeft.value % 60).padStart(2, '0')}`
})

onUnmounted(() => clearInterval(timer))

function tick() {
  if (cooldownLeft.value > 0) cooldownLeft.value -= 1
  if (expiresLeft.value > 0) expiresLeft.value -= 1
  if (cooldownLeft.value <= 0 && expiresLeft.value <= 0) {
    clearInterval(timer)
    timer = null
  }
}

function ensureTimer() {
  if (timer === null) timer = setInterval(tick, 1000)
}

function startClocks() {
  cooldownLeft.value = SEND_COOLDOWN_SECONDS
  expiresLeft.value = CODE_TTL_SECONDS
  ensureTimer()
}

function stopClocks() {
  clearInterval(timer)
  timer = null
  cooldownLeft.value = 0
  expiresLeft.value = 0
}

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

function submit() {
  if (step.value === 'credentials') return submitCredentials()
  if (step.value === 'code') return submitCode()
  if (channel.value === 'email' && codeSent.value) return submitCode()
}

// Step 1 only establishes *who* you are. It no longer sends anything: which code
// goes out is decided by the press in step 2, and mailing a code the user has not
// asked for yet would be a send against their daily cap for a path they may not
// take.
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
    if (registering.value) {
      // Signup has one channel by definition — there is no account to match a
      // face against yet — so it skips the chooser.
      const result = await requestSignup()
      ticket.value = result.ticket
      step.value = 'code'
      startClocks()
      await nextTick()
      codeInput.value?.focus()
    } else {
      const result = await authentication.login(username.value.trim(), password.value)
      ticket.value = result.ticket
      channel.value = 'email'
      step.value = 'choose'
    }
  } catch (err) { error.value = err.message }
  finally { busy.value = false }
}

function chooseChannel(value) {
  if (busy.value || faceBusy.value) return
  channel.value = value
  error.value = ''
  notice.value = ''
  // A photo belongs to one attempt; switching away must not leave it behind as
  // "already captured".
  photo.value = null
}

async function sendEmailCode() {
  if (cooldownLeft.value > 0 || busy.value) return
  error.value = ''
  busy.value = true
  try {
    await authentication.sendCode(ticket.value)
    codeSent.value = true
    startClocks()
    await nextTick()
    codeInput.value?.focus()
  } catch (err) {
    error.value = err.message
    // The server refuses a repeat inside its own window and names the remaining
    // seconds ("Please retry in about 45 seconds"). Mirror that onto the button
    // so the wait is visible instead of the button reading as broken.
    const wait = /(\d+)\s*second/i.exec(err.message ?? '')
    if (wait) {
      cooldownLeft.value = Number(wait[1])
      ensureTimer()
    }
  } finally { busy.value = false }
}

// Signup has no ticket to re-send against — the account does not exist yet — so
// asking again means repeating the signup call, which mails a fresh code.
async function resendSignup() {
  if (cooldownLeft.value > 0 || busy.value) return
  error.value = ''
  busy.value = true
  try {
    const result = await requestSignup()
    ticket.value = result.ticket
    startClocks()
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

// The SMS panel reports its own errors, so the only thing left here is what to do
// with a success. See the same note on the face channel below.
function handleSmsSuccess(data) {
  notice.value = ''
  if (data?.access_token) {
    finish(data)
    return
  }
  // No session came back. In the mock that is by design — it cannot mint a JWT,
  // and pretending otherwise would leave the user inside a shell where every
  // request 401s (§1.1 rule 3). Once `/api/auth/sms/*` lands, a response that is
  // not a token means the shape changed, and saying so beats a silent loop.
  notice.value = 'Simulated step reached the end of the flow. No session was issued: the SMS endpoints are still being built.'
}

function handleCaptured(blob) {
  photo.value = blob
  error.value = ''
}

// §4.3.1 ② — the photo is matched against the account named in step 1, so the
// username comes from there rather than being asked for again. `faceVerify` runs
// the dHash comparison (§2 冲突 1 方案 A) in the mock, which means "a different
// face is refused" is a real check and not a constant.
async function submitFace() {
  error.value = ''
  if (!photo.value) {
    error.value = 'Take a photo first.'
    return
  }
  faceBusy.value = true
  try {
    const data = await authentication.faceVerify(username.value.trim(), photo.value)
    notice.value = ''
    if (data?.simulated) {
      notice.value = 'Simulated step reached the end of the flow. No session was issued: the face endpoint is still being built.'
      return
    }
    finish(data)
  } catch (err) { error.value = err.message }
  finally { faceBusy.value = false }
}

function useAnotherAccount() {
  stopClocks()
  code.value = ''
  codeSent.value = false
  error.value = ''
  notice.value = ''
  photo.value = null
  channel.value = 'email'
  step.value = 'credentials'
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
            Your password, then a code by email or SMS, or a face match.
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
          <template v-if="step === 'credentials'">
            {{ registering ? 'Verify your email, then ask an administrator to activate your staff account.' : 'Use your hospital account.' }}
          </template>
          <template v-else-if="step === 'code'">
            Enter the code sent to your account’s registered email address.
          </template>
          <template v-else-if="channel === 'sms'">
            Enter the code sent to your registered mobile number.
          </template>
          <template v-else-if="channel === 'face'">
            Look at the camera to confirm it's you.
          </template>
          <template v-else>
            We'll email a 6-digit code to your account’s registered address.
          </template>
        </p>

        <p v-if="notice" class="form-notice" role="status">{{ notice }}</p>

        <template v-if="step === 'credentials'">
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
              <el-input v-model="department" size="large" placeholder="e.g. Cardiology" maxlength="100" :disabled="busy" required />
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

        <template v-else-if="step === 'choose'">
          <div class="methods" role="group" aria-label="Verification method">
            <button
              v-for="option in channels"
              :key="option.value"
              type="button"
              class="method"
              :class="{ active: channel === option.value }"
              :aria-pressed="channel === option.value"
              :disabled="busy || faceBusy"
              @click="chooseChannel(option.value)"
            >
              {{ option.label }}
            </button>
          </div>

          <div v-if="channel === 'email'" class="panel">
            <el-button
              type="primary"
              size="large"
              class="submit"
              :loading="busy"
              :disabled="cooldownLeft > 0 || busy"
              @click="sendEmailCode"
            >
              {{ codeSent ? 'Send a new code' : 'Send verification code' }}
            </el-button>
            <p v-if="cooldownLeft > 0" class="cooldown" role="status">
              Wait <span class="data">{{ cooldownLeft }}s</span> before requesting another code.
            </p>
          </div>

          <SmsCodeInput
            v-else-if="channel === 'sms'"
            scene="login"
            @success="handleSmsSuccess"
          />

          <div v-else class="panel">
            <CameraCapture purpose="verify" :busy="faceBusy" @captured="handleCaptured" />
            <el-button
              v-if="photo"
              type="primary"
              class="submit"
              :loading="faceBusy"
              :disabled="faceBusy"
              @click="submitFace"
            >
              Verify and sign in
            </el-button>
          </div>

          <template v-if="channel === 'email' && codeSent">
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
              <template v-if="expiresLeft > 0">
                Code expires in <span class="data">{{ expiryCountdown }}</span>
              </template>
              <template v-else> The code has expired. </template>
            </p>

            <el-button
              type="primary"
              size="large"
              class="submit"
              :loading="busy"
              @click="submitCode"
            >
              Verify and sign in
            </el-button>
          </template>
        </template>

        <template v-else-if="step === 'code'">
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
            <template v-if="expiresLeft > 0">
              Code expires in <span class="data">{{ expiryCountdown }}</span>
            </template>
            <template v-else> The code has expired. </template>
          </p>

          <div class="panel">
            <el-button
              type="primary"
              size="large"
              class="submit"
              :loading="busy"
              :disabled="cooldownLeft > 0 || busy"
              @click="resendSignup"
            >
              Send a new code
            </el-button>
            <p v-if="cooldownLeft > 0" class="cooldown" role="status">
              Wait <span class="data">{{ cooldownLeft }}s</span> before requesting another code.
            </p>
          </div>
        </template>

        <p v-if="error" class="form-error" role="alert">{{ error }}</p>

        <el-button
          v-if="step === 'credentials' || step === 'code'"
          type="primary"
          size="large"
          native-type="submit"
          class="submit"
          :loading="busy"
        >
          {{ step === 'credentials' ? 'Continue' : (registering ? 'Verify email and create account' : 'Verify and sign in') }}
        </el-button>

        <p v-if="step === 'choose'" class="back">
          <button type="button" class="resend" :disabled="busy || faceBusy" @click="useAnotherAccount">
            Use a different account
          </button>
        </p>

        <!-- Signup reaches this step as well, and its way back is the way *out*
             of signup: `useAnotherAccount` only resets the step and would leave
             `registering` set, which lands on the signup form again. -->
        <p v-if="step === 'code'" class="back">
          <button
            type="button"
            class="resend"
            :disabled="busy"
            @click="registering ? toggleSignup() : useAnotherAccount()"
          >
            {{ registering ? 'Back to sign in' : 'Use a different account' }}
          </button>
        </p>

        <p v-if="step === 'credentials' && !registering" class="back">
          <button type="button" class="resend" :disabled="busy" @click="toggleSignup">
            Create an account with email
          </button>
        </p>

        <!-- 0915意见 item 1. The link above takes you into signup and nothing took
             you back out: `toggleSignup` was only reachable while already signed
             out of signup mode, so the signup form was one-way. -->
        <p v-if="step === 'credentials' && registering" class="back">
          <button type="button" class="resend" :disabled="busy" @click="toggleSignup">
            Back to sign in
          </button>
        </p>

        <p v-if="!registering" class="demo-note">
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
  padding: 9px 10px;
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

.method:hover:not(.active):not(:disabled) {
  color: var(--teal);
}

.method:disabled {
  cursor: default;
  opacity: 0.6;
}

.panel {
  margin-bottom: 4px;
}

.cooldown {
  margin: 9px 0 0;
  font-size: 12.5px;
  text-align: center;
  color: var(--ink-3);
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

.submit + .submit,
.panel + .field {
  margin-top: 16px;
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
