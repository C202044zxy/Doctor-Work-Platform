<script setup>
// S1: password ticket scopes the simulated message and the one-time code.
import { computed, onUnmounted, ref, useTemplateRef } from 'vue'

import { authentication } from '../api/client'

const props = defineProps({
  ticket: { type: String, required: true },
  // Set for the second-factor step, where the number is already known from the
  // password step and must not be edited.
  phone: { type: String, default: '' },
  prefilled: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['success'])

const PHONE_PATTERN = /^1[3-9]\d{9}$/

const number = ref(props.phone)
const code = ref('')
const error = ref('')
const notice = ref('')
const preview = ref(null)
const busy = ref(false)
const secondsLeft = ref(0)
const codeInput = useTemplateRef('codeInput')

let timer = null

const phoneValid = computed(() => PHONE_PATTERN.test(number.value.trim()))
const countdown = computed(() => {
  const minutes = Math.floor(secondsLeft.value / 60)
  const seconds = String(secondsLeft.value % 60).padStart(2, '0')
  return `${minutes}:${seconds}`
})
// §3.4: the resend state must survive a page refresh, and localStorage is the
// wrong place to keep it — the server owns the cooldown. A rejected send carries
// `retry_after`, and that is what restores the countdown.
const canSend = computed(() => !busy.value && !props.disabled && phoneValid.value && secondsLeft.value === 0)
const canVerify = computed(() => !busy.value && !props.disabled && phoneValid.value && /^\d{6}$/.test(code.value.trim()))

function startCountdown(seconds) {
  secondsLeft.value = seconds
  clearInterval(timer)
  timer = setInterval(() => {
    secondsLeft.value -= 1
    if (secondsLeft.value <= 0) clearInterval(timer)
  }, 1000)
}

onUnmounted(() => clearInterval(timer))

async function send() {
  error.value = ''
  notice.value = ''
  busy.value = true
  try {
    const result = await authentication.smsSend(props.ticket, number.value.trim())
    startCountdown(result.cooldown ?? 60)
    preview.value = null
    notice.value = `Simulated delivery to ${result.masked_phone}. No real message was sent.`
  } catch (err) {
    // 429 means the server is still holding a cooldown this page did not know
    // about — the user reloaded, or another tab sent a code. Adopt the remaining
    // seconds it reports instead of leaving the button looking clickable.
    if (err.status === 429 && err.retryAfter) startCountdown(err.retryAfter)
    error.value = err.message
  } finally {
    busy.value = false
  }
}

async function verify() {
  error.value = ''
  busy.value = true
  try {
    const data = await authentication.smsVerify(props.ticket, code.value.trim())
    emit('success', data)
  } catch (err) {
    // An expired or spent code cannot be retried as-is: clear the field and hand
    // the button back so the user can request a new one (§3.4).
    if (err.status === 400 && /expired/i.test(err.message)) {
      code.value = ''
      secondsLeft.value = 0
      clearInterval(timer)
    }
    error.value = err.message
  } finally {
    busy.value = false
  }
}
async function showPreview() {
  error.value = ''
  busy.value = true
  try { preview.value = await authentication.smsPreview(props.ticket) }
  catch (err) { preview.value = null; error.value = err.message }
  finally { busy.value = false }
}
</script>

<template>
  <div class="sms">
    <label class="field">
      <span class="field-label">Mobile number</span>
      <el-input
        v-model="number"
        size="large"
        inputmode="numeric"
        maxlength="11"
        placeholder="13800138000"
        :disabled="busy || disabled || prefilled"
      />
    </label>

    <div class="row">
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
          :disabled="busy || disabled"
        />
      </label>
      <el-button
        class="send"
        size="large"
        :disabled="!canSend"
        :loading="busy"
        @click="send"
      >
        {{ secondsLeft > 0 ? `Resend in ${countdown}` : 'Send code' }}
      </el-button>
    </div>

    <p v-if="notice" class="sms-notice" role="status">{{ notice }}</p>
    <el-button :disabled="busy || disabled" @click="showPreview">View simulated SMS</el-button>
    <p v-if="preview" class="sms-notice" role="status">
      Simulated message — nothing was sent. Code: <strong>{{ preview.code }}</strong>
      (valid for up to {{ preview.expires_in }} seconds).
    </p>
    <p v-if="error" class="sms-error" role="alert">{{ error }}</p>

    <el-button
      type="primary"
      size="large"
      class="submit"
      :disabled="!canVerify"
      :loading="busy"
      @click="verify"
    >
      Verify and sign in
    </el-button>
  </div>
</template>

<style scoped>
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

.row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 10px;
  align-items: end;
}

.row .field {
  margin-bottom: 18px;
}

.send {
  margin-bottom: 18px;
}

.code-input :deep(.el-input__inner) {
  font-family: var(--font-data);
  font-size: 20px;
  letter-spacing: 0.42em;
  text-indent: 0.42em;
}

.sms-notice {
  padding: 10px 12px;
  margin: -4px 0 16px;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-2);
  background: var(--surface-2);
  border-radius: var(--radius);
}

.sms-error {
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
</style>
