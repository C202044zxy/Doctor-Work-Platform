<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, useTemplateRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import {
  assessments as assessmentsApi,
  healthPlans as plansApi,
  reminderRules as rulesApi,
  reminders as remindersApi,
  vitals as vitalsApi,
} from '../api/client'
import { currentUserId } from '../session'

// M6. Everything on this panel is patient-scoped, so it is one component used
// from two places: the Health Management screen (with a patient picker above it)
// and the Health data tab of the patient detail page. 0915意见 item 3 asks for the
// two to be one screen, and the tab is that merge; the standalone screen keeps
// the module reachable from the sidebar for a clinician working through patients.
//
// The chart is the point of the panel. Out-of-range points are drawn red and the
// reference bounds are dashed rules; the readings and the assessments below give
// the same verdict in words, so colour is never the only channel.

const props = defineProps({
  patientNo: { type: String, required: true },
  patientName: { type: String, default: '' },
})

// Only the components this chart uses are imported, so the rest of ECharts stays
// out of the bundle.
echarts.use([
  LineChart,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
])

const METRICS = [
  { key: 'bp', label: 'Blood pressure' },
  { key: 'gl', label: 'Blood glucose' },
  { key: 'hr', label: 'Heart rate' },
]
const RANGES = [
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: 365, label: '12 months' },
]
const ENTRY_KINDS = [
  { value: 'medication', label: 'Medication' },
  { value: 'followup', label: 'Follow-up' },
  { value: 'diet_exercise', label: 'Diet and exercise' },
]
const REMINDER_TYPES = [
  { value: 'medication', label: 'Medication' },
  { value: 'followup', label: 'Follow-up' },
  { value: 'checkin', label: 'Check-in' },
]
const PERIOD_PATTERN = /^\d{4}-(0[1-9]|1[0-2])$/

const INK = '#14212b'
const INK_3 = '#8a9ba5'
const LINE = '#e8eef0'
const TEAL = '#0f5f5c'
const ALERT = '#b3261e'

const metricKey = ref('bp')
const rangeDays = ref(90)

const trend = ref(null)
const trendError = ref('')
const loadingTrend = ref(false)

const readings = ref([])
const readingsError = ref('')
const loadingReadings = ref(false)

const plans = ref([])
const plansError = ref('')
const loadingPlans = ref(false)

const rules = ref([])
const fired = ref([])
const unread = ref(0)
const reminderError = ref('')
const loadingReminders = ref(false)

const reviews = ref([])
const reviewError = ref('')
const loadingReviews = ref(false)

const chartEl = useTemplateRef('chart')
let chartInstance = null

// `toLocaleString(undefined, ...)` means "whatever the reader's machine is set
// to", which on a zh-CN browser renders "2026年9月18日" inside otherwise English
// copy. Every date on this screen is English, so the locale is named.
function stamp(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('en-GB', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function day(value) {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-GB', { month: 'short', day: 'numeric' })
}

function isoDay(date) {
  // The trend endpoint takes dates, so send the day the reader is looking at
  // rather than an instant: `toISOString` would shift it by the UTC offset and
  // silently move the window by a day at either end.
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 10)
}

// --- trend -----------------------------------------------------------------

// The nearest 1, 2, 2.5 or 5 times a power of ten to span/4, which is the family
// ECharts picks its own tick interval from, so bounds rounded to it land on round
// labels instead of 3.2 and 4.8.
function niceStep(span) {
  const rough = span / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const scaled = rough / magnitude
  const factor = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10
  return factor * magnitude
}

// One pad-and-round rule has to serve mmHg (a span near 70) and mmol/L (a span
// near 4). A fixed offset tuned for the first drove the glucose axis down to -10,
// so pad and round as a fraction of the span instead.
function axisBounds(lo, hi) {
  const span = hi - lo || Math.abs(hi) || 1
  const step = niceStep(span)
  const pad = span * 0.08
  return {
    min: Math.floor((lo - pad) / step) * step,
    max: Math.ceil((hi + pad) / step) * step,
  }
}

function buildOption(data) {
  // `is_abnormal` is the server's verdict on the whole reading, and a blood
  // pressure is one reading with two halves. So both points take the colour when
  // either half broke a bound: the client is explicitly not allowed to work out
  // which half it was, because that is the same threshold arithmetic that would
  // let the chart and the record disagree.
  const series = (name, pick, bounds) => ({
    name,
    type: 'line',
    smooth: 0.28,
    symbolSize: 7,
    connectNulls: false,
    lineStyle: { width: 2, color: TEAL },
    data: data.points.map((point) => ({
      value: point[pick],
      itemStyle: {
        color: point.is_abnormal ? ALERT : TEAL,
        borderColor: '#ffffff',
        borderWidth: 1.5,
      },
    })),
    markLine: {
      silent: true,
      symbol: 'none',
      label: {
        formatter: (params) => `${params.value} ${data.unit}`,
        position: 'insideEndTop',
        color: INK_3,
        fontSize: 11,
      },
      lineStyle: { type: 'dashed', color: ALERT, width: 1, opacity: 0.55 },
      data: bounds,
    },
  })

  const lines =
    data.sign_type === 'bp'
      ? [
          series('Systolic', 'value', [
            ...(data.threshold.max !== null ? [{ yAxis: data.threshold.max }] : []),
            ...(data.threshold.min !== null ? [{ yAxis: data.threshold.min }] : []),
          ]),
          series('Diastolic', 'value_secondary', [
            ...(data.threshold.max_secondary !== null
              ? [{ yAxis: data.threshold.max_secondary }]
              : []),
            ...(data.threshold.min_secondary !== null
              ? [{ yAxis: data.threshold.min_secondary }]
              : []),
          ]),
        ]
      : [
          series('Reading', 'value', [
            ...(data.threshold.max !== null ? [{ yAxis: data.threshold.max }] : []),
            ...(data.threshold.min !== null ? [{ yAxis: data.threshold.min }] : []),
          ]),
        ]

  // Thresholds are part of the extent, so a dashed limit is never off-screen and
  // a run of normal readings still shows what "normal" was measured against.
  const values = data.points.flatMap((point) => [point.value, point.value_secondary])
  values.push(
    data.threshold.min,
    data.threshold.max,
    data.threshold.min_secondary,
    data.threshold.max_secondary,
  )
  const extent = values.filter((value) => value !== null && value !== undefined)
  const { min, max } = axisBounds(Math.min(...extent), Math.max(...extent))

  return {
    animationDuration: 420,
    grid: { top: 30, right: 24, bottom: 26, left: 48 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#ffffff',
      borderColor: LINE,
      textStyle: { color: INK, fontSize: 12 },
      valueFormatter: (value) => `${value} ${data.unit}`,
    },
    legend:
      lines.length > 1
        ? {
            top: 0,
            right: 0,
            itemWidth: 14,
            itemHeight: 2,
            textStyle: { color: INK_3, fontSize: 11 },
          }
        : { show: false },
    xAxis: {
      type: 'category',
      data: data.points.map((point) => day(point.recorded_at)),
      boundaryGap: false,
      axisLine: { lineStyle: { color: LINE } },
      axisTick: { show: false },
      axisLabel: { color: INK_3, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      min,
      max,
      axisLabel: { color: INK_3, fontSize: 11 },
      splitLine: { lineStyle: { color: LINE } },
    },
    series: lines,
  }
}

function render() {
  if (!trend.value?.points.length) {
    // An empty range has its own empty state in the template, and leaving the
    // previous metric's lines on the canvas underneath it would read as data.
    chartInstance?.dispose()
    chartInstance = null
    return
  }
  // Created here rather than in `onMounted`, because the canvas is `v-show`n: a
  // chart initialised while the container is `display: none` measures zero and
  // keeps that size, so it draws nothing even once readings arrive.
  if (chartInstance) chartInstance.resize()
  else chartInstance = echarts.init(chartEl.value)
  // `notMerge` so switching metric drops the previous series rather than layering
  // the new one on top of it.
  chartInstance.setOption(buildOption(trend.value), { notMerge: true })
}

function resize() {
  chartInstance?.resize()
}

async function loadTrend() {
  loadingTrend.value = true
  trendError.value = ''
  try {
    const to = new Date()
    const from = new Date(to.getTime() - rangeDays.value * 86400000)
    trend.value = await vitalsApi.trend(props.patientNo, {
      signType: metricKey.value,
      from: isoDay(from),
      to: isoDay(to),
    })
  } catch (err) {
    trendError.value = err.message
    trend.value = null
  } finally {
    loadingTrend.value = false
    await nextTick()
    render()
  }
}

const outOfRangeCount = computed(
  () => (trend.value?.points ?? []).filter((point) => point.is_abnormal).length,
)

// --- readings --------------------------------------------------------------

async function loadReadings() {
  loadingReadings.value = true
  readingsError.value = ''
  try {
    // The list is newest first, so the first row for a sign is its latest reading.
    // One page of 50 covers every sign for any patient whose readings are not all
    // of a single kind; the chart above is where the full history lives.
    const page = await vitalsApi.list(props.patientNo, { size: 50 })
    readings.value = page.items
  } catch (err) {
    readingsError.value = err.message
  } finally {
    loadingReadings.value = false
  }
}

const latestReading = computed(() => {
  const seen = new Set()
  return readings.value.filter((row) => {
    if (seen.has(row.sign_type)) return false
    seen.add(row.sign_type)
    return true
  })
})

// --- plans -----------------------------------------------------------------

async function loadPlans() {
  loadingPlans.value = true
  plansError.value = ''
  try {
    plans.value = (await plansApi.list({ patientNo: props.patientNo, size: 50 })).items
  } catch (err) {
    plansError.value = err.message
  } finally {
    loadingPlans.value = false
  }
}

// --- reminders -------------------------------------------------------------

async function loadReminders() {
  loadingReminders.value = true
  reminderError.value = ''
  try {
    const [ruleList, page] = await Promise.all([
      rulesApi.list(props.patientNo),
      // Reading this list clears the red dot for its entries; that is the
      // contract's rule, not an accident of this screen.
      remindersApi.list({ patientNo: props.patientNo, size: 20 }),
    ])
    rules.value = ruleList
    fired.value = page.items
    unread.value = page.unread
  } catch (err) {
    reminderError.value = err.message
  } finally {
    loadingReminders.value = false
  }
}

async function toggleRule(rule, active) {
  reminderError.value = ''
  try {
    const updated = await rulesApi.update(rule.id, { active })
    Object.assign(rule, updated)
  } catch (err) {
    // Nothing to undo: the switch is bound with `:model-value`, so it never moved
    // on its own -- the row only changes once the server has agreed.
    reminderError.value = err.message
  }
}

async function markDone(entry) {
  reminderError.value = ''
  try {
    Object.assign(entry, await remindersApi.markDone(entry.id))
    unread.value = (await remindersApi.unreadCount()).unread
  } catch (err) {
    reminderError.value = err.message
  }
}

// --- assessments -----------------------------------------------------------

async function loadReviews() {
  loadingReviews.value = true
  reviewError.value = ''
  try {
    reviews.value = await assessmentsApi.list(props.patientNo)
  } catch (err) {
    reviewError.value = err.message
  } finally {
    loadingReviews.value = false
  }
}

// --- dialogs ---------------------------------------------------------------

const readingOpen = ref(false)
const readingError = ref('')
const readingBusy = ref(false)
const readingDraft = ref(blankReading())

function blankReading() {
  return { sign_type: 'bp', value: '', value_secondary: '', recorded_at: new Date() }
}

function openReading() {
  readingDraft.value = blankReading()
  readingError.value = ''
  readingOpen.value = true
}

// `Number('')` and `Number('  ')` are both 0, so a box left blank would otherwise
// be saved as a real reading of zero.
function numberOrNull(input) {
  const text = String(input ?? '').trim()
  if (!text) return null
  const value = Number(text)
  return Number.isNaN(value) ? null : value
}

async function saveReading() {
  readingError.value = ''
  const draft = readingDraft.value
  const value = numberOrNull(draft.value)
  if (value === null) {
    readingError.value = 'Enter the reading as a number.'
    return
  }
  const secondary = numberOrNull(draft.value_secondary)
  if (draft.sign_type === 'bp' && secondary === null) {
    readingError.value = 'A blood pressure needs both the systolic and the diastolic value.'
    return
  }
  if (!draft.recorded_at) {
    readingError.value = 'Say when the reading was taken.'
    return
  }
  readingBusy.value = true
  try {
    await vitalsApi.create(props.patientNo, {
      sign_type: draft.sign_type,
      value,
      value_secondary: draft.sign_type === 'bp' ? secondary : null,
      recorded_at: new Date(draft.recorded_at).toISOString(),
      source: 'manual',
    })
    readingOpen.value = false
    await Promise.all([loadReadings(), loadTrend()])
  } catch (err) {
    readingError.value = err.message
  } finally {
    readingBusy.value = false
  }
}

const planOpen = ref(false)
const planError = ref('')
const planBusy = ref(false)
const planDraft = ref(blankPlan())

function blankPlan() {
  const start = new Date()
  const end = new Date(start.getTime() + 30 * 86400000)
  return {
    title: '',
    goals: '',
    instructions: '',
    entries: [{ kind: 'medication', text: '' }],
    start_date: start,
    end_date: end,
    rule: { on: false, rtype: 'medication', title: '', cron_expr: '0 9 * * *' },
  }
}

function openPlan() {
  planDraft.value = blankPlan()
  planError.value = ''
  planOpen.value = true
}

function addEntry() {
  planDraft.value.entries.push({ kind: 'followup', text: '' })
}

function removeEntry(index) {
  planDraft.value.entries.splice(index, 1)
}

async function savePlan() {
  planError.value = ''
  const draft = planDraft.value
  if (!draft.title.trim()) {
    planError.value = 'Give the plan a title.'
    return
  }
  const entries = draft.entries
    .filter((entry) => entry.text.trim())
    .map((entry) => ({ kind: entry.kind, text: entry.text.trim() }))
  if (!entries.length) {
    planError.value = 'Add at least one item to the plan.'
    return
  }
  if (!draft.start_date || !draft.end_date) {
    // A cleared picker hands back null, which would date the plan 1970.
    planError.value = 'Give the plan a start and an end date.'
    return
  }
  const payload = {
    patient_no: props.patientNo,
    title: draft.title.trim(),
    goals: draft.goals,
    instructions: draft.instructions,
    entries,
    start_date: isoDay(draft.start_date),
    end_date: isoDay(draft.end_date),
  }
  if (draft.rule.on) {
    // Created in the same call, which is what T35 §3 asks for and what scenario
    // S1 does: the rule has no id yet, so it cannot be linked by id.
    payload.new_reminder_rules = [
      {
        patient_no: props.patientNo,
        rtype: draft.rule.rtype,
        title: draft.rule.title.trim() || draft.title.trim(),
        cron_expr: draft.rule.cron_expr.trim(),
      },
    ]
  }
  planBusy.value = true
  try {
    await plansApi.create(payload)
    planOpen.value = false
    await Promise.all([loadPlans(), loadReminders()])
  } catch (err) {
    planError.value = err.message
  } finally {
    planBusy.value = false
  }
}

const reviewOpen = ref(false)
// Distinct from the list's `reviewError`: one is "the panel could not load",
// the other is "this form was refused", and they are shown in different places.
const reviewFormError = ref('')
const reviewBusy = ref(false)
const reviewDraft = ref({ period: '', conclusion: '', plan_adjustment: '', revising: null })

function openReview(revising = null) {
  reviewDraft.value = revising
    ? {
        period: revising.period,
        conclusion: revising.conclusion,
        plan_adjustment: revising.plan_adjustment || '',
        revising,
      }
    : { period: new Date().toISOString().slice(0, 7), conclusion: '', plan_adjustment: '', revising: null }
  reviewFormError.value = ''
  reviewOpen.value = true
}

async function saveReview() {
  reviewFormError.value = ''
  const draft = reviewDraft.value
  // A convenience check, not the enforcement: the server states the pattern in
  // the contract and refuses anything else with a 422 naming the field.
  if (!PERIOD_PATTERN.test(draft.period)) {
    reviewFormError.value = 'The period is the calendar month, written as 2026-08.'
    return
  }
  if (!draft.conclusion.trim()) {
    reviewFormError.value = 'Write the conclusion.'
    return
  }
  const payload = {
    period: draft.period,
    conclusion: draft.conclusion.trim(),
    plan_adjustment: draft.plan_adjustment,
  }
  reviewBusy.value = true
  try {
    if (draft.revising) await assessmentsApi.revise(draft.revising.id, payload)
    else await assessmentsApi.create(props.patientNo, payload)
    reviewOpen.value = false
    await loadReviews()
  } catch (err) {
    reviewFormError.value = err.message
  } finally {
    reviewBusy.value = false
  }
}

// --- lifecycle -------------------------------------------------------------

function loadAll() {
  return Promise.all([
    loadTrend(),
    loadReadings(),
    loadPlans(),
    loadReminders(),
    loadReviews(),
  ])
}

onMounted(async () => {
  window.addEventListener('resize', resize)
  await loadAll()
  render()
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
})

watch(metricKey, loadTrend)
watch(rangeDays, loadTrend)
watch(
  () => props.patientNo,
  () => loadAll(),
)
</script>

<template>
  <div class="health">
    <section class="panel">
      <header class="panel-head">
        <h3>Trend</h3>
        <span class="panel-tail">
          <span v-if="outOfRangeCount" class="chip" data-severity="alert">
            {{ outOfRangeCount }} out of range
          </span>
          <span v-else-if="trend?.points?.length" class="chip" data-severity="ok">
            All in range
          </span>
          <el-radio-group v-model="rangeDays" size="small">
            <el-radio-button v-for="option in RANGES" :key="option.days" :value="option.days">
              {{ option.label }}
            </el-radio-button>
          </el-radio-group>
        </span>
      </header>

      <!-- A group of toggles rather than a tablist: there is no tabpanel element
           to point at, and half a tab pattern reads worse than none. -->
      <div class="metrics" role="group" aria-label="Sign">
        <button
          v-for="item in METRICS"
          :key="item.key"
          type="button"
          class="metric"
          :class="{ 'is-active': metricKey === item.key }"
          :aria-pressed="metricKey === item.key"
          @click="metricKey = item.key"
        >
          {{ item.label }}
          <span v-if="trend && trend.sign_type === item.key" class="metric-unit data">
            {{ trend.unit }}
          </span>
        </button>
      </div>

      <div v-if="trendError" class="load-error">
        <div>
          <p class="load-error-title">Could not load the trend</p>
          <p class="load-error-detail">{{ trendError }}</p>
        </div>
        <el-button :loading="loadingTrend" @click="loadTrend">Try again</el-button>
      </div>

      <template v-else>
        <div
          v-show="trend?.points?.length"
          ref="chart"
          class="chart"
          role="img"
          :aria-label="`${metricKey} trend`"
        ></div>
        <p v-if="loadingTrend && !trend?.points?.length" class="empty">Loading the readings…</p>
        <p v-else-if="!trend?.points?.length" class="empty">
          No {{ METRICS.find((item) => item.key === metricKey)?.label.toLowerCase() }} has been
          recorded in this range. Record one and the chart draws it.
        </p>
      </template>

      <p class="chart-note">
        Dashed rules mark the reference limits. A point is drawn red when the server judged the
        reading out of range — the same verdict the list below states in words.
      </p>
    </section>

    <div class="split">
      <div class="stack">
        <section class="panel">
          <header class="panel-head">
            <h3>Latest readings</h3>
            <span class="panel-tail">
              <el-button size="small" type="primary" @click="openReading">
                Record a reading
              </el-button>
            </span>
          </header>

          <div v-if="readingsError" class="load-error">
            <div>
              <p class="load-error-title">Could not load the readings</p>
              <p class="load-error-detail">{{ readingsError }}</p>
            </div>
            <el-button :loading="loadingReadings" @click="loadReadings">Try again</el-button>
          </div>

          <ul v-else-if="latestReading.length" class="readings">
            <li
              v-for="reading in latestReading"
              :key="reading.id"
              class="reading"
              :data-severity="reading.is_abnormal ? 'alert' : 'ok'"
            >
              <div class="reading-head">
                <span class="reading-name">
                  {{ METRICS.find((item) => item.key === reading.sign_type)?.label }}
                </span>
                <span class="reading-value data">
                  {{ reading.value }}
                  <template v-if="reading.value_secondary !== null">
                    /{{ reading.value_secondary }}
                  </template>
                  {{ reading.unit }}
                </span>
                <span class="chip">
                  {{ reading.is_abnormal ? 'Out of range' : 'In range' }}
                </span>
              </div>
              <p class="reading-verdict">
                <span class="data">{{ stamp(reading.recorded_at) }}</span> ·
                {{ reading.source === 'mock' ? 'Simulated reading' : 'Recorded by hand' }}
              </p>
            </li>
          </ul>

          <p v-else class="empty">Nothing has been recorded for this patient yet.</p>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Assessments</h3>
            <span class="panel-count data">{{ reviews.length }}</span>
            <span class="panel-tail">
              <el-button size="small" type="primary" @click="openReview()">
                Record an assessment
              </el-button>
            </span>
          </header>

          <div v-if="reviewError" class="load-error">
            <div>
              <p class="load-error-title">Could not load the assessments</p>
              <p class="load-error-detail">{{ reviewError }}</p>
            </div>
            <el-button :loading="loadingReviews" @click="loadReviews">Try again</el-button>
          </div>

          <ul v-else-if="reviews.length" class="assess">
            <li v-for="review in reviews" :key="review.id" class="assessment">
              <div class="assessment-head">
                <span class="assessment-date data">{{ review.period }}</span>
                <span v-if="review.version > 1" class="chip" data-severity="info">
                  Revision {{ review.version }}
                </span>
                <span class="assessment-author">
                  {{ review.assessed_by_name || `User #${review.assessed_by}` }} ·
                  <span class="data">{{ stamp(review.assessed_at) }}</span>
                </span>
              </div>
              <p class="assessment-text">{{ review.conclusion }}</p>
              <p v-if="review.plan_adjustment" class="assessment-plan">
                Plan adjustment: {{ review.plan_adjustment }}
              </p>
              <!-- The server refuses anyone but the assessing physician with a
                   403; offering the button to everyone else would be a promise
                   the API does not keep. -->
              <el-button
                v-if="review.assessed_by === currentUserId"
                link
                size="small"
                @click="openReview(review)"
              >
                Revise
              </el-button>
            </li>
          </ul>

          <p v-else class="empty">
            No periodic assessment has been written. It is where a review of the plan's effect
            goes, and revising one keeps the earlier conclusion readable.
          </p>
        </section>
      </div>

      <div class="stack">
        <section class="panel">
          <header class="panel-head">
            <h3>Care plans</h3>
            <span class="panel-count data">{{ plans.length }}</span>
            <span class="panel-tail">
              <el-button size="small" @click="openPlan">New plan</el-button>
            </span>
          </header>

          <div v-if="plansError" class="load-error">
            <div>
              <p class="load-error-title">Could not load the care plans</p>
              <p class="load-error-detail">{{ plansError }}</p>
            </div>
            <el-button :loading="loadingPlans" @click="loadPlans">Try again</el-button>
          </div>

          <template v-else-if="plans.length">
            <article v-for="plan in plans" :key="plan.id" class="plan">
              <header class="plan-head">
                <span class="plan-title">{{ plan.title }}</span>
                <span class="chip" :data-severity="plan.status === 'active' ? 'ok' : 'info'">
                  {{ plan.status }}
                </span>
              </header>
              <p class="plan-range data">{{ plan.start_date }} → {{ plan.end_date }}</p>
              <p v-if="plan.goals" class="plan-goals">{{ plan.goals }}</p>
              <p v-if="plan.instructions" class="plan-goals muted">{{ plan.instructions }}</p>
              <ul class="plan-items">
                <li v-for="(entry, index) in plan.entries" :key="index" class="plan-item">
                  <span class="plan-kind">{{ entry.kind.replace('_', ' ') }}</span>
                  <span class="plan-text">{{ entry.text }}</span>
                </li>
              </ul>
            </article>
          </template>

          <p v-else class="empty">
            No care plan yet. A plan can be created with its reminder rules in the same step.
          </p>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Reminders</h3>
            <span v-if="unread" class="chip" data-severity="warn">{{ unread }} unread</span>
          </header>

          <div v-if="reminderError" class="load-error">
            <div>
              <p class="load-error-title">Could not load the reminders</p>
              <p class="load-error-detail">{{ reminderError }}</p>
            </div>
            <el-button :loading="loadingReminders" @click="loadReminders">Try again</el-button>
          </div>

          <template v-else>
            <p class="reminder-foot">A rule is a schedule; a fired entry is one occurrence of it.</p>
            <ul v-if="rules.length" class="rules">
              <li v-for="rule in rules" :key="rule.id" class="rule">
                <div>
                  <span class="rule-title">{{ rule.title }}</span>
                  <span class="rule-meta data">
                    {{ rule.rtype }} · <code>{{ rule.cron_expr }}</code>
                    <template v-if="rule.health_plan_id"> · plan #{{ rule.health_plan_id }}</template>
                  </span>
                </div>
                <el-switch
                  :model-value="rule.active"
                  size="small"
                  @change="(value) => toggleRule(rule, value)"
                />
              </li>
            </ul>
            <p v-else class="empty">No reminder rule is set for this patient.</p>

            <ul v-if="fired.length" class="reminders">
              <li
                v-for="entry in fired"
                :key="entry.id"
                class="reminder"
                :data-severity="entry.done ? 'info' : 'warn'"
              >
                <div>
                  <span class="reminder-text">{{ entry.title }}</span>
                  <span class="reminder-when data">Due {{ stamp(entry.due_at) }}</span>
                </div>
                <el-button v-if="!entry.done" link size="small" @click="markDone(entry)">
                  Mark done
                </el-button>
                <span v-else class="muted reminder-done">Done</span>
              </li>
            </ul>
            <p v-else class="empty">Nothing has fired yet.</p>
          </template>
        </section>
      </div>
    </div>

    <el-dialog v-model="readingOpen" title="Record a reading" width="440px">
      <div class="field">
        <label class="field-label">Sign</label>
        <el-select v-model="readingDraft.sign_type">
          <el-option v-for="item in METRICS" :key="item.key" :label="item.label" :value="item.key" />
        </el-select>
      </div>
      <div class="field">
        <label class="field-label">
          {{ readingDraft.sign_type === 'bp' ? 'Systolic' : 'Value' }}
        </label>
        <el-input v-model="readingDraft.value" inputmode="decimal" />
      </div>
      <div v-if="readingDraft.sign_type === 'bp'" class="field">
        <label class="field-label">Diastolic</label>
        <el-input v-model="readingDraft.value_secondary" inputmode="decimal" />
        <p class="field-hint">A blood pressure is stored as a pair, so both values are needed.</p>
      </div>
      <div class="field">
        <label class="field-label">Taken at</label>
        <el-date-picker
          v-model="readingDraft.recorded_at"
          type="datetime"
          :disabled-date="(date) => date.getTime() > Date.now()"
        />
        <p class="field-hint">The server refuses a reading dated in the future.</p>
      </div>
      <p v-if="readingError" class="form-error">{{ readingError }}</p>
      <template #footer>
        <el-button @click="readingOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="readingBusy" @click="saveReading">Save</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="planOpen" title="New care plan" width="620px">
      <div class="field">
        <label class="field-label">Title</label>
        <el-input v-model="planDraft.title" placeholder="Blood pressure management plan" />
      </div>
      <div class="field">
        <label class="field-label">Goal</label>
        <el-input v-model="planDraft.goals" placeholder="Keep the systolic under 139" />
      </div>
      <div class="field">
        <label class="field-label">Instructions</label>
        <el-input v-model="planDraft.instructions" type="textarea" :rows="2" />
      </div>
      <div class="field">
        <label class="field-label">Dates</label>
        <el-date-picker v-model="planDraft.start_date" type="date" placeholder="Start" />
        <el-date-picker v-model="planDraft.end_date" type="date" placeholder="End" />
        <p class="field-hint">An end date before the start is refused, naming the field.</p>
      </div>
      <div class="field">
        <label class="field-label">Items</label>
        <div v-for="(entry, index) in planDraft.entries" :key="index" class="entry-row">
          <el-select v-model="entry.kind">
            <el-option
              v-for="kind in ENTRY_KINDS"
              :key="kind.value"
              :label="kind.label"
              :value="kind.value"
            />
          </el-select>
          <el-input v-model="entry.text" placeholder="Amlodipine 5mg once daily" />
          <el-button link @click="removeEntry(index)">Remove</el-button>
        </div>
        <el-button link @click="addEntry">Add an item</el-button>
      </div>

      <div class="field rule-field">
        <label class="field-label">
          <el-switch v-model="planDraft.rule.on" size="small" />
          Create a reminder rule with this plan
        </label>
        <template v-if="planDraft.rule.on">
          <el-select v-model="planDraft.rule.rtype">
            <el-option
              v-for="kind in REMINDER_TYPES"
              :key="kind.value"
              :label="kind.label"
              :value="kind.value"
            />
          </el-select>
          <el-input v-model="planDraft.rule.title" placeholder="Daily 09:00 medication reminder" />
          <el-input v-model="planDraft.rule.cron_expr" placeholder="0 9 * * *" />
          <p class="field-hint">
            A five-field cron expression, read in UTC. <code>* * * * *</code> fires every minute.
          </p>
        </template>
      </div>

      <p v-if="planError" class="form-error">{{ planError }}</p>
      <template #footer>
        <el-button @click="planOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="planBusy" @click="savePlan">Create</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="reviewOpen"
      :title="reviewDraft.revising ? 'Revise the assessment' : 'Record an assessment'"
      width="560px"
    >
      <p v-if="reviewDraft.revising" class="muted revision-note">
        This writes a new revision. The version being revised stays readable as it was written.
      </p>
      <div class="field">
        <label class="field-label">Period</label>
        <el-input v-model="reviewDraft.period" placeholder="2026-08" />
        <p class="field-hint">The calendar month, written as YYYY-MM.</p>
      </div>
      <div class="field">
        <label class="field-label">Conclusion</label>
        <el-input v-model="reviewDraft.conclusion" type="textarea" :rows="4" />
      </div>
      <div class="field">
        <label class="field-label">Plan adjustment</label>
        <el-input v-model="reviewDraft.plan_adjustment" type="textarea" :rows="2" />
      </div>
      <p v-if="reviewFormError" class="form-error">{{ reviewFormError }}</p>
      <template #footer>
        <el-button @click="reviewOpen = false">Cancel</el-button>
        <el-button type="primary" :loading="reviewBusy" @click="saveReview">
          {{ reviewDraft.revising ? 'Save the revision' : 'Save' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<!-- Page furniture (.panel, .chip, .split, .stack, .kv, .empty, .muted, .field)
     lives in src/style.css; only what is specific to this panel is here. -->
<style scoped>
/* `.empty` is a full-width paragraph with no side padding of its own, so as a
   direct child of a panel it would run into the panel's edge. */
.panel > .empty {
  padding: 28px 20px;
}

.metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  padding: 10px 20px 0;
}

.metric {
  display: flex;
  gap: 6px;
  align-items: baseline;
  padding: 6px 10px;
  font: inherit;
  font-size: 13px;
  color: var(--ink-2);
  cursor: pointer;
  background: none;
  border: 0;
  border-radius: var(--radius);
}

.metric:hover {
  background: var(--surface-2);
}

.metric.is-active {
  font-weight: 600;
  color: var(--teal-dark);
  background: var(--teal-soft);
}

.metric-unit {
  font-size: 11px;
  color: var(--ink-3);
}

.chart {
  height: 300px;
  margin: 12px 8px 0;
}

.chart-note {
  padding: 0 20px 16px;
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-3);
}

.readings,
.assess,
.reminders,
.rules {
  padding: 0 20px;
  margin: 0;
  list-style: none;
}

/* A care plan is a block, not a row: its title, dates, prose and items belong on
   one inset line, so the inset goes on the block. Padding the item list instead
   left the title and goals flush against the panel edge, one step to the left of
   everything they describe. */
.plan-items {
  padding: 0;
  margin: 6px 0 0;
  list-style: none;
}

.reading,
.assessment,
.rule,
.reminder {
  position: relative;
  padding: 14px 0;
  border-bottom: 1px solid var(--line-2);
}

.plan {
  position: relative;
  padding: 14px 20px;
  border-bottom: 1px solid var(--line-2);
}

.reading:last-child,
.assessment:last-child,
.plan:last-child,
.rule:last-child,
.reminder:last-child {
  border-bottom: 0;
}

.reading,
.assessment,
.reminder {
  padding-left: 16px;
}

.reading::before,
.assessment::before,
.reminder::before {
  position: absolute;
  top: 16px;
  bottom: 17px;
  left: 0;
  width: 2px;
  content: '';
  background: var(--sev, var(--ok));
  border-radius: 1px;
}

.reading-head,
.assessment-head,
.plan-head,
.rule,
.reminder {
  display: flex;
  gap: 10px;
  align-items: baseline;
}

.reading-head,
.reminder,
.rule {
  justify-content: space-between;
}

.reading-name,
.plan-title,
.rule-title,
.reminder-text {
  font-size: 13.5px;
  font-weight: 600;
}

.reading-value {
  font-size: 15px;
  font-weight: 600;
}

.reading-verdict,
.plan-range,
.plan-goals,
.assessment-plan,
.rule-meta,
.reminder-when {
  margin: 5px 0 0;
  font-size: 12.5px;
  color: var(--ink-2);
}

.assessment-text {
  margin: 7px 0 0;
  font-size: 13.5px;
  line-height: 1.6;
}

/* A fixed column, not intrinsic width: "medication" and "followup" are different
   lengths, and sizing to the text would leave every value starting at its own x. */
.plan-kind {
  flex: 0 0 92px;
  font-size: 11.5px;
  color: var(--ink-3);
  text-transform: capitalize;
}

.plan-item {
  display: flex;
  gap: 4px;
  align-items: baseline;
  padding: 4px 0;
  font-size: 13px;
}

.plan-text {
  line-height: 1.5;
}

.rule,
.reminder {
  align-items: center;
}

.reminder-meta,
.rule-meta {
  display: block;
}

.rule-meta code {
  font-size: 11.5px;
}

.reminder-foot {
  padding: 14px 20px 0;
  margin: 0;
  font-size: 12px;
  color: var(--ink-3);
}

.revision-note {
  margin: 0 0 16px;
  font-size: 12.5px;
}

.reminder-done {
  font-size: 12px;
}

.entry-row {
  display: grid;
  grid-template-columns: 160px 1fr auto;
  gap: 8px;
  margin-bottom: 8px;
}

.rule-field .field-label {
  display: flex;
  gap: 8px;
  align-items: center;
}

.load-error {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
}

.load-error-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
}

.load-error-detail {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--ink-2);
}
</style>
