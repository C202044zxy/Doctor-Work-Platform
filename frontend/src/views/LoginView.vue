<script setup>
import { computed, nextTick, onUnmounted, ref, useTemplateRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { signIn } from '../session'

// Two-step sign-in: credentials, then a one-time code by email. Task T05 wires
// this to the real endpoints, where the code lives in Redis with a five-minute
// expiry and the success path returns a JWT. Until then the form validates
// shape only and the code is accepted without a server check.

const CODE_TTL_SECONDS = 300 // five minutes, matching the planned Redis expiry

const route = useRoute()
const router = useRouter()

const step = ref('credentials')
const email = ref('')
const password = ref('')
const code = ref('')
const error = ref('')
const busy = ref(false)
const secondsLeft = ref(0)
const codeInput = useTemplateRef('codeInput')

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
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value.trim())) {
    error.value = 'Enter a valid email address.'
    return
  }
  if (!password.value) {
    error.value = 'Enter your password.'
    return
  }

  busy.value = true
  await new Promise((resolve) => setTimeout(resolve, 280)) // stand-in for the request
  busy.value = false

  step.value = 'code'
  startCountdown()
  await nextTick()
  codeInput.value?.focus()
}

async function submitCode() {
  error.value = ''
  if (!/^\d{6}$/.test(code.value.trim())) {
    error.value = 'Enter the 6-digit code from the email.'
    return
  }

  busy.value = true
  await new Promise((resolve) => setTimeout(resolve, 280))
  busy.value = false

  signIn()
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : null
  router.replace(redirect ?? { name: 'dashboard' })
}

function useAnotherAccount() {
  clearInterval(timer)
  secondsLeft.value = 0
  code.value = ''
  error.value = ''
  step.value = 'credentials'
}

function resend() {
  code.value = ''
  error.value = ''
  startCountdown()
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
      <form class="form" @submit.prevent="step === 'credentials' ? submitCredentials() : submitCode()">
        <h2 class="form-title">
          {{ step === 'credentials' ? 'Sign in' : 'Check your email' }}
        </h2>
        <p class="form-lede">
          <template v-if="step === 'credentials'">
            Use your hospital account.
          </template>
          <template v-else>
            We sent a 6-digit code to <span class="data">{{ email.trim() }}</span>.
          </template>
        </p>

        <template v-if="step === 'credentials'">
          <label class="field">
            <span class="field-label">Email</span>
            <el-input
              v-model="email"
              type="email"
              size="large"
              autocomplete="username"
              placeholder="chen@hospital.example"
              :disabled="busy"
            />
          </label>

          <label class="field">
            <span class="field-label">Password</span>
            <el-input
              v-model="password"
              type="password"
              size="large"
              autocomplete="current-password"
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

        <p v-if="error" class="form-error" role="alert">{{ error }}</p>

        <el-button
          type="primary"
          size="large"
          native-type="submit"
          class="submit"
          :loading="busy"
        >
          {{ step === 'credentials' ? 'Continue' : 'Verify and sign in' }}
        </el-button>

        <p v-if="step === 'code'" class="back">
          <button type="button" class="resend" :disabled="busy" @click="useAnotherAccount">
            Use a different account
          </button>
        </p>

        <p class="demo-note">
          Development build. Sign-in is not connected to a service yet, so any 6-digit code is
          accepted.
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
