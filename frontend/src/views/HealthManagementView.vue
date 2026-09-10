<script setup>
import { computed, onMounted, onUnmounted, ref, useTemplateRef, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { carePlan, reminders, assessments, vitalDates, vitalMetrics } from '../api/demo-data'

// M6. The trend chart is the point of this screen: a clinician should be able
// to see at a glance that a value is out of range, without reading the numbers.
// Out-of-range points are drawn red, the reference ceiling is a dashed rule,
// and the values themselves are listed underneath.
//
// Task T34 replaces the fabricated series with readings from the API. Only the
// components this chart uses are imported, so the rest of ECharts is not
// pulled into the bundle.

echarts.use([LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, CanvasRenderer])

const TIMELINE = vitalDates
const metricKey = ref('bp')

const metric = computed(() => vitalMetrics.find((m) => m.key === metricKey.value))
const chartEl = useTemplateRef('chart')
let chartInstance = null

const INK = '#14212b'
const INK_3 = '#8a9ba5'
const LINE = '#e8eef0'
const TEAL = '#0f5f5c'
const ALERT = '#b3261e'

// The nearest 1, 2, 2.5 or 5 times a power of ten to span/4. That is the family
// ECharts picks its own tick interval from, so bounds rounded to it land on
// round labels instead of 3.2 and 4.8.
function niceStep(span) {
  const rough = span / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const scaled = rough / magnitude
  const factor = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10
  return factor * magnitude
}

// One pad-and-round rule has to serve mmHg (a span near 70) and mmol/L (a span
// near 4). A fixed offset tuned for the first drove the glucose axis down to
// -10, so pad and round as a fraction of the span instead.
function axisBounds(lo, hi) {
  const span = hi - lo || Math.abs(hi) || 1
  const step = niceStep(span)
  const pad = span * 0.08
  return {
    min: Math.floor((lo - pad) / step) * step,
    max: Math.ceil((hi + pad) / step) * step,
  }
}

function buildOption(current) {
  const isOut = (series, value) =>
    (series.high !== undefined && value > series.high) ||
    (series.low !== undefined && value < series.low)

  const lines = current.series.map((series) => ({
    name: series.name,
    type: 'line',
    smooth: 0.28,
    symbolSize: 7,
    lineStyle: { width: 2, color: TEAL },
    // Colour carries severity, but the tooltip and the table below repeat it in
    // words, so the chart is not the only channel.
    data: series.points.map((value) => ({
      value,
      itemStyle: {
        color: isOut(series, value) ? ALERT : TEAL,
        borderColor: '#ffffff',
        borderWidth: 1.5,
      },
    })),
    // A dashed rule at the reference limit. Anything crossing it is red.
    markLine: {
      silent: true,
      symbol: 'none',
      label: {
        formatter: (params) => `${params.value} ${current.unit}`,
        position: 'insideEndTop',
        color: INK_3,
        fontSize: 11,
      },
      lineStyle: { type: 'dashed', color: ALERT, width: 1, opacity: 0.55 },
      data: [
        ...(series.high !== undefined ? [{ yAxis: series.high }] : []),
        ...(series.low !== undefined ? [{ yAxis: series.low }] : []),
      ],
    },
  }))

  // Thresholds are part of the extent, so a dashed limit is never off-screen.
  const extent = [
    ...current.series.flatMap((s) => s.points),
    ...current.series.map((s) => s.high),
    ...current.series.map((s) => s.low),
  ].filter((value) => value !== undefined)
  const { min, max } = axisBounds(Math.min(...extent), Math.max(...extent))

  return {
    animationDuration: 420,
    grid: { top: 28, right: 22, bottom: 26, left: 46 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#ffffff',
      borderColor: LINE,
      textStyle: { color: INK, fontSize: 12 },
      valueFormatter: (value) => `${value} ${current.unit}`,
    },
    legend:
      current.series.length > 1
        ? { top: 0, right: 0, itemWidth: 14, itemHeight: 2, textStyle: { color: INK_3, fontSize: 11 } }
        : { show: false },
    xAxis: {
      type: 'category',
      data: TIMELINE,
      boundaryGap: false,
      axisLine: { lineStyle: { color: LINE } },
      axisTick: { show: false },
      axisLabel: { color: INK_3, fontSize: 11, interval: 1 },
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
  if (!chartInstance) return
  // `notMerge` so switching metric drops the previous series rather than
  // layering the new one on top of it.
  chartInstance.setOption(buildOption(metric.value), { notMerge: true })
}

function resize() {
  chartInstance?.resize()
}

onMounted(() => {
  chartInstance = echarts.init(chartEl.value)
  render()
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
})

watch(metricKey, render)

// Latest reading per series, with its verdict, for the table and the summary.
const readings = computed(() =>
  metric.value.series.map((series) => {
    const value = series.points.at(-1)
    const out = (series.high !== undefined && value > series.high) || (series.low !== undefined && value < series.low)
    return {
      name: series.name,
      value,
      unit: metric.value.unit,
      level: out ? 'alert' : 'ok',
      verdict: out
        ? `Above the ${series.high} ${metric.value.unit} reference ceiling`
        : 'Within the reference range',
    }
  }),
)

const outOfRangeCount = computed(() =>
  metric.value.series.reduce(
    (total, series) =>
      total +
      series.points.filter(
        (value) =>
          (series.high !== undefined && value > series.high) ||
          (series.low !== undefined && value < series.low),
      ).length,
    0,
  ),
)

const LEVEL_LABELS = { alert: 'Out of range', ok: 'In range' }
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Health Management</h2>
        <p class="page-sub">
          <span>Zhang Wei</span>
          <span class="data">#1</span>
          <span>12 readings, 28 August to 10 September</span>
        </p>
      </div>
      <div class="page-actions">
        <el-button>Record a reading</el-button>
      </div>
    </header>

    <div class="split">
      <div class="stack">
        <section class="panel">
          <header class="panel-head">
            <h3>Trend</h3>

            <span class="panel-tail">
              <span
                v-if="outOfRangeCount"
                class="chip"
                data-severity="alert"
              >
                {{ outOfRangeCount }} out of range
              </span>
              <span v-else class="chip" data-severity="ok">All in range</span>
            </span>
          </header>

          <div class="metrics" role="tablist">
            <button
              v-for="item in vitalMetrics"
              :key="item.key"
              type="button"
              role="tab"
              class="metric"
              :class="{ 'is-active': metricKey === item.key }"
              :aria-selected="metricKey === item.key"
              @click="metricKey = item.key"
            >
              {{ item.label }}
              <span class="metric-unit data">{{ item.unit }}</span>
            </button>
          </div>

          <div ref="chart" class="chart" role="img" :aria-label="`${metric.label} trend over twelve readings`"></div>

          <p class="chart-note">
            Dashed rules mark the reference limits. Points outside them are drawn red; the
            readings below give the same verdict in words.
          </p>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Latest readings</h3>
            <span class="panel-tail">10 September 2026</span>
          </header>

          <ul class="readings">
            <li
              v-for="reading in readings"
              :key="reading.name"
              class="reading"
              :data-severity="reading.level"
            >
              <div class="reading-head">
                <span class="reading-name">{{ reading.name }}</span>
                <span class="reading-value data">{{ reading.value }} {{ reading.unit }}</span>
                <span class="chip">{{ LEVEL_LABELS[reading.level] }}</span>
              </div>
              <p class="reading-verdict">{{ reading.verdict }}</p>
            </li>
          </ul>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Assessment history</h3>
            <span class="panel-count data">{{ assessments.length }}</span>
          </header>

          <ul class="assess">
            <li
              v-for="item in assessments"
              :key="item.id"
              class="assessment"
              :data-severity="item.severity"
            >
              <div class="assessment-head">
                <span class="assessment-date data">{{ item.date }}</span>
                <span class="chip">{{ item.verdict }}</span>
              </div>
              <p class="assessment-text">{{ item.summary }}</p>
              <p class="assessment-author">{{ item.author }}</p>
            </li>
          </ul>
        </section>
      </div>

      <div class="stack">
        <section class="panel">
          <header class="panel-head">
            <h3>{{ carePlan.title }}</h3>
          </header>
          <dl class="kv">
            <div>
              <dt>Started</dt>
              <dd class="data">{{ carePlan.startedOn }}</dd>
            </div>
            <div>
              <dt>Owner</dt>
              <dd>{{ carePlan.owner }}</dd>
            </div>
          </dl>

          <ul class="plan">
            <li v-for="item in carePlan.items" :key="item.text" class="plan-item" :class="{ 'is-done': item.done }">
              <span class="plan-mark" aria-hidden="true">{{ item.done ? '✓' : '' }}</span>
              <span class="plan-text">{{ item.text }}</span>
              <span class="plan-state">{{ item.done ? 'Done' : 'Open' }}</span>
            </li>
          </ul>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Reminders</h3>
          </header>
          <ul class="reminders">
            <li
              v-for="item in reminders"
              :key="item.id"
              class="reminder"
              :data-severity="item.state === 'due' ? 'warn' : 'info'"
            >
              <span class="reminder-text">{{ item.text }}</span>
              <span class="reminder-when data">{{ item.when }}</span>
            </li>
          </ul>
          <p class="panel-foot reminder-foot">
            Reminders are raised by a scheduled job rather than by a person.
          </p>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Metric switcher ---------------------------------------------------------- */

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

/* Readings ----------------------------------------------------------------- */

.readings {
  padding: 0 20px;
  margin: 0;
  list-style: none;
}

.reading {
  position: relative;
  padding: 14px 0 15px 16px;
  border-bottom: 1px solid var(--line-2);
}

.reading:last-child {
  border-bottom: 0;
}

.reading::before {
  position: absolute;
  top: 16px;
  bottom: 17px;
  left: 0;
  width: 2px;
  content: '';
  background: var(--sev, var(--ok));
  border-radius: 1px;
}

.reading-head {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  align-items: baseline;
}

.reading-name {
  font-size: 13.5px;
  font-weight: 600;
}

.reading-value {
  font-size: 15px;
  font-weight: 600;
}

.reading-head .chip {
  margin-left: auto;
}

.reading-verdict {
  margin: 5px 0 0;
  font-size: 12.5px;
  color: var(--ink-2);
}

/* Assessments -------------------------------------------------------------- */

.assess {
  padding: 0 20px;
  margin: 0;
  list-style: none;
}

.assessment {
  position: relative;
  padding: 14px 0 15px 16px;
  border-bottom: 1px solid var(--line-2);
}

.assessment:last-child {
  border-bottom: 0;
}

.assessment::before {
  position: absolute;
  top: 16px;
  bottom: 17px;
  left: 0;
  width: 2px;
  content: '';
  background: var(--sev, var(--ink-3));
  border-radius: 1px;
}

.assessment-head {
  display: flex;
  gap: 10px;
  align-items: center;
}

.assessment-date {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-2);
}

.assessment-head .chip {
  margin-left: auto;
}

.assessment-text {
  margin: 7px 0 0;
  font-size: 13.5px;
  line-height: 1.6;
}

.assessment-author {
  margin: 5px 0 0;
  font-size: 12px;
  color: var(--ink-3);
}

/* Care plan ---------------------------------------------------------------- */

.plan {
  padding: 4px 20px 14px;
  margin: 0;
  list-style: none;
}

.plan-item {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 8px 0;
  border-bottom: 1px solid var(--line-2);
}

.plan-item:last-child {
  border-bottom: 0;
}

.plan-mark {
  display: grid;
  flex: none;
  place-items: center;
  width: 16px;
  height: 16px;
  font-size: 11px;
  line-height: 1;
  color: #fff;
  background: var(--ok);
  border: 1px solid var(--ok);
  border-radius: 4px;
  transform: translateY(2px);
}

.plan-item:not(.is-done) .plan-mark {
  background: none;
  border-color: var(--line);
}

.plan-text {
  font-size: 13px;
  line-height: 1.5;
}

.plan-item.is-done .plan-text {
  color: var(--ink-2);
}

.plan-state {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--ink-3);
}

/* Reminders ---------------------------------------------------------------- */

.reminders {
  padding: 0 20px;
  margin: 0;
  list-style: none;
}

.reminder {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 0 12px 14px;
  border-bottom: 1px solid var(--line-2);
}

.reminder:last-child {
  border-bottom: 0;
}

.reminder::before {
  position: absolute;
  top: 13px;
  bottom: 14px;
  left: 0;
  width: 2px;
  content: '';
  background: var(--sev, var(--ink-3));
  border-radius: 1px;
}

.reminder-text {
  font-size: 13px;
  line-height: 1.5;
}

.reminder-when {
  font-size: 11.5px;
  color: var(--ink-3);
}

.reminder-foot {
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-3);
}
</style>
