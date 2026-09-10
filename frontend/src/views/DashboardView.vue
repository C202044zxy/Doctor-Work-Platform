<script setup>
import { computed } from 'vue'
import { currentClinician } from '../session'
import { counts, schedule, worklist } from '../api/demo-data'

// A clinician opens the platform to find out what needs doing, so the first
// screen is a worklist ordered by urgency rather than a row of headline
// figures. The figures sit in the rail as supporting detail.
//
// Every value here is fabricated (see api/demo-data.js). Nothing on this screen
// reads from the API yet.

const SEVERITY_LABELS = {
  alert: 'Needs action',
  warn: 'Waiting on you',
  info: 'For information',
}

const clinician = currentClinician

const now = new Date()
const hour = now.getHours()
const greeting = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
const today = now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })

const urgentCount = computed(() => worklist.filter((item) => item.severity !== 'info').length)

const figures = [
  { label: "Today's consultations", value: counts.consultations },
  { label: 'Records awaiting review', value: counts.pendingReviews },
  { label: 'Patients under your care', value: counts.myPatients },
]
</script>

<template>
  <div class="page">
    <header class="lede">
      <h2 class="page-heading">{{ greeting }}, {{ clinician.name }}</h2>
      <p class="page-sub">
        <span>{{ today }}</span>
        <span>{{ clinician.department }}</span>
      </p>
    </header>

    <div class="grid">
      <section class="panel">
        <header class="panel-head">
          <h3>Needs your attention</h3>
          <span class="panel-count data">{{ urgentCount }}</span>
        </header>

        <ol class="worklist">
          <li
            v-for="item in worklist"
            :key="item.id"
            class="wl-item"
            :data-severity="item.severity"
          >
            <div class="wl-head">
              <span class="wl-name">{{ item.patient }}</span>
              <span class="wl-id data">#{{ item.patientId }}</span>
              <span class="wl-sev">{{ SEVERITY_LABELS[item.severity] }}</span>
            </div>
            <p class="wl-detail">{{ item.detail }}</p>
            <p class="wl-action">{{ item.action }}</p>
          </li>
        </ol>
      </section>

      <div class="rail">
        <section class="panel">
          <header class="panel-head">
            <h3>Today</h3>
          </header>
          <ul class="schedule">
            <li v-for="slot in schedule" :key="slot.time" class="slot">
              <span class="slot-time data">{{ slot.time }}</span>
              <span class="slot-body">
                <span class="slot-patient">{{ slot.patient }}</span>
                <span class="slot-kind">{{ slot.kind }}</span>
              </span>
            </li>
          </ul>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>At a glance</h3>
          </header>
          <dl class="kv kv-lg">
            <div v-for="figure in figures" :key="figure.label">
              <dt>{{ figure.label }}</dt>
              <dd class="data">{{ figure.value }}</dd>
            </div>
          </dl>
        </section>
      </div>
    </div>
  </div>
</template>

<!-- .page, .panel and .kv come from src/style.css. The worklist, the schedule
     and the severity edge bar are particular to this screen. -->
<style scoped>
.lede {
  margin-bottom: 22px;
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.65fr) minmax(280px, 1fr);
  gap: 20px;
  align-items: start;
}

/* Worklist ----------------------------------------------------------------- */

.worklist {
  padding: 0 20px;
  margin: 0;
  list-style: none;
}

.wl-item {
  position: relative;
  padding: 15px 0 16px 16px;
  border-bottom: 1px solid var(--line-2);
}

.wl-item:last-child {
  border-bottom: 0;
}

/* Severity is carried by an edge bar and by the label text, so it never
   depends on colour alone. */
.wl-item::before {
  position: absolute;
  top: 17px;
  bottom: 18px;
  left: 0;
  width: 2px;
  content: '';
  background: var(--ink-3);
  border-radius: 1px;
}

.wl-item[data-severity='alert']::before {
  background: var(--alert);
}

.wl-item[data-severity='warn']::before {
  background: var(--warn);
}

.wl-head {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  align-items: baseline;
}

.wl-name {
  font-size: 14.5px;
  font-weight: 600;
}

.wl-id {
  color: var(--ink-3);
}

.wl-sev {
  margin-left: auto;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-2);
  white-space: nowrap;
}

.wl-item[data-severity='alert'] .wl-sev {
  color: var(--alert);
}

.wl-item[data-severity='warn'] .wl-sev {
  color: var(--warn);
}

.wl-detail {
  margin: 6px 0 0;
  font-size: 13.5px;
  line-height: 1.5;
  color: var(--ink);
}

.wl-action {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: var(--ink-2);
}

/* Rail --------------------------------------------------------------------- */

.rail {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.schedule {
  padding: 6px 20px 8px;
  margin: 0;
  list-style: none;
}

.slot {
  display: flex;
  gap: 14px;
  padding: 10px 0;
  border-bottom: 1px solid var(--line-2);
}

.slot:last-child {
  border-bottom: 0;
}

.slot-time {
  flex: none;
  padding-top: 1px;
  color: var(--ink-2);
}

.slot-body {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.slot-patient {
  font-size: 13.5px;
  font-weight: 600;
}

.slot-kind {
  font-size: 12.5px;
  color: var(--ink-2);
}

@media (max-width: 1000px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
