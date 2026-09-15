<script setup>
// §1.1 rule 3: the interface says out loud which capabilities are simulated,
// rather than letting an audience assume they are real. §5.3 shares this badge
// across T41, T42 and the other simulated capabilities that follow.
//
// `simulated` defaults to true because SMS and face recognition are both still
// mock. The authority on this is the backend, not this file: once B and D land,
// drive it from the `mock` field their responses return
// (`SMS_PROVIDER=mock|aliyun`), so the badge follows the server rather than a
// front-end guess.
// The label is the one string in this interface the spec spells out verbatim
// (§1.1 铁律 3, and §5.3 names the file as the 「模拟环境」角标). The rest of the
// UI is English; this badge is deliberately not, because §3.5 判据1 and §7 both
// check for that wording.
defineProps({
  simulated: { type: Boolean, default: true },
  label: { type: String, default: '模拟环境' },
  detail: {
    type: String,
    default: '仅"向外部服务发起的那一次网络请求"是模拟的，其余链路真实。Nothing is sent to a real SMS gateway or face provider.',
  },
})
</script>

<template>
  <span v-if="simulated" class="mock-badge" :title="detail">
    <span class="mock-dot" aria-hidden="true" />
    {{ label }}
  </span>
</template>

<style scoped>
.mock-badge {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  padding: 4px 10px;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--warn);
  cursor: help;
  background: var(--warn-soft);
  border-radius: 999px;
}

.mock-dot {
  width: 6px;
  height: 6px;
  background: var(--warn);
  border-radius: 50%;
}
</style>
