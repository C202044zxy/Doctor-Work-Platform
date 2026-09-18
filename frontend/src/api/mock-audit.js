// §1.1 铁律 2：每个模拟能力都必须留下可查的审计记录。
//
// 这是短信验证码明文**唯一**能被人看到的地方。§3.3.1 的 send 响应只有
// `cooldown` / `mock` / `masked_phone` 三个字段，§1.2 更是把"把验证码返回给前端"
// 直接列为反面写法；§1.3 与 §3.3.4 第 8 步都把明文 code 放在 `detail` 里，
// 对应的验收判据是 §3.5 判据②「验证码可在审计页查到明文」。
//
// 行形状照抄 demo-data.js 的 auditRows，审计页因此不需要知道哪个是真的。
// 与其余 mock 文件一起删除。

import { computed, ref } from 'vue'

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const entries = ref([])
let sequence = 0

function stamp(at) {
  const pad = (value) => String(value).padStart(2, '0')
  const hours = pad(at.getHours())
  const minutes = pad(at.getMinutes())
  return {
    iso: `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${hours}:${minutes}`,
    at: `${at.getDate()} ${MONTHS[at.getMonth()]} ${at.getFullYear()}, ${hours}:${minutes}`,
  }
}

// `action` is written in the form the §6.2 demonstration script tells the
// presenter to search for ("找到 POST /api/auth/sms/send"), which is why these
// rows read differently from demo-data's semantic names like `patient.read`.
export function record({ action, actor = '', target = '', detail = '', outcome = 'ok', severity = 'info' }) {
  sequence += 1
  entries.value = [
    {
      id: `sim-${sequence}`,
      ...stamp(new Date()),
      actor,
      action,
      target,
      source: '127.0.0.1',
      outcome,
      severity,
      detail,
    },
    ...entries.value,
  ]
}

export const simulatedRows = computed(() => entries.value)

// The audit page's action filter is a select, so an action nothing offers can
// never be filtered down to. These feed the option list.
export const simulatedActions = computed(() => [...new Set(entries.value.map((row) => row.action))])
