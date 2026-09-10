<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheckFilled, Lock, Plus, WarningFilled } from '@element-plus/icons-vue'
import { allergens, formulary, orders as seedOrders, record, versions } from '../api/demo-data'

// M4, the centrepiece of the planned system. Three things it has to show:
//
//   1. A record is authored from a structured template, not a blank page.
//   2. Writing an order runs a three-level check - blocked on an allergy
//      conflict, warned above the usual dose, passed otherwise.
//   3. An archived version locks to read-only and cannot be edited in place.
//
// All three are driven by the fabricated data in api/demo-data.js. Task T21
// supplies the real verification endpoint; the shape of this screen is what
// that endpoint has to answer.

const FREQUENCIES = ['once daily', 'twice daily', 'three times daily', 'every 12 hours', 'as required']

// Selecting a version is the read-only switch: only a draft is editable.
const selectedVersion = ref(3)
const selected = computed(() => versions.find((v) => v.version === selectedVersion.value))
const isReadOnly = computed(() => selected.value?.state !== 'draft')

const fields = reactive(Object.fromEntries(record.fields.map((f) => [f.label, f.value])))
const orderList = ref([...seedOrders])

const dialogOpen = ref(false)
const orderForm = reactive({ drug: '', dose: '', frequency: FREQUENCIES[0], justification: '' })

const chosen = computed(() => formulary.find((item) => item.drug === orderForm.drug) ?? null)

// The three-level check. An allergy conflict outranks a dose concern: a drug
// the patient reacts to is refused outright, whatever the dose.
const check = computed(() => {
  const item = chosen.value
  if (!item) return null

  const conflict = allergens.find((allergy) => allergy.classes.includes(item.class))
  if (conflict) {
    return {
      level: 'alert',
      title: 'Order entry blocked',
      body: `${item.drug} is a ${item.class.toLowerCase()}, and ${record.patient} has a recorded allergy to ${conflict.substance.toLowerCase()}. ${conflict.reaction}, noted ${conflict.recorded}.`,
    }
  }

  const dose = Number(orderForm.dose)
  if (Number.isFinite(dose) && dose > item.max) {
    return {
      level: 'warn',
      title: 'Above the usual ceiling',
      body: `${dose} ${item.unit} exceeds the ${item.max} ${item.unit} ceiling for ${item.drug}. Enter a clinical justification to continue.`,
    }
  }

  return {
    level: 'ok',
    title: 'Within the usual range',
    body: `${item.drug} ${orderForm.dose} ${item.unit} ${item.route} matches the standard order for the ${item.class.toLowerCase()} class.`,
  }
})

const canAdd = computed(() => {
  if (!check.value) return false
  if (check.value.level === 'ok') return true
  // A warned order may proceed, but only with a reason attached to it.
  if (check.value.level === 'warn') return orderForm.justification.trim().length >= 10
  return false
})

function openDialog() {
  orderForm.drug = ''
  orderForm.dose = ''
  orderForm.frequency = FREQUENCIES[0]
  orderForm.justification = ''
  dialogOpen.value = true
}

// Picking a drug pre-fills its standard order, so the dose field starts
// somewhere sensible and the check has something to compare against.
function chooseDrug() {
  orderForm.dose = chosen.value ? String(chosen.value.typical) : ''
  orderForm.justification = ''
}

function addOrder() {
  const item = chosen.value
  orderList.value.push({
    id: `ord-${orderList.value.length + 1}`,
    drug: item.drug,
    dose: `${orderForm.dose} ${item.unit}`,
    route: item.route,
    frequency: orderForm.frequency,
    level: check.value.level,
    message:
      check.value.level === 'warn'
        ? check.value.body.split('. ')[0] + '.'
        : 'Within the usual range.',
    justification: orderForm.justification.trim() || undefined,
  })
  dialogOpen.value = false
  ElMessage.success(
    check.value.level === 'warn'
      ? `${item.drug} added with a justification on file.`
      : `${item.drug} added.`,
  )
}

const LEVEL_LABELS = {
  ok: 'Passed',
  warn: 'Needs a reason',
  alert: 'Blocked',
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Medical Records</h2>
        <p class="page-sub">
          <span class="data">{{ record.id }}</span>
          <span>{{ record.patient }}</span>
          <span class="data">#{{ record.patientId }}</span>
        </p>
      </div>
      <div class="page-actions">
        <el-button :disabled="isReadOnly">Save draft</el-button>
        <el-button type="primary" :disabled="isReadOnly">Submit for review</el-button>
      </div>
    </header>

    <p v-if="isReadOnly && selected" class="notice banner" data-severity="info">
      <el-icon class="notice-icon"><Lock /></el-icon>
      <span>
        <strong>{{ selected.label }} is read-only.</strong>
        {{ selected.note }} Further edits create a linked new version rather than altering this one.
      </span>
    </p>

    <div class="split">
      <div class="stack">
        <dl class="meta-strip">
          <div>
            <dt>Template</dt>
            <dd>{{ record.template }}</dd>
          </div>
          <div>
            <dt>Department</dt>
            <dd>{{ record.department }}</dd>
          </div>
          <div>
            <dt>Author</dt>
            <dd>{{ record.author }}</dd>
          </div>
          <div>
            <dt>Last updated</dt>
            <dd class="data">{{ record.updatedAt }}</dd>
          </div>
        </dl>

        <section class="panel">
          <header class="panel-head">
            <h3>{{ record.template }}</h3>
            <span class="panel-tail">Fields generated from the template</span>
          </header>
          <div class="panel-body">
            <label v-for="field in record.fields" :key="field.label" class="field">
              <span class="field-label">{{ field.label }}</span>
              <el-input
                v-model="fields[field.label]"
                type="textarea"
                :rows="field.lines"
                :disabled="isReadOnly"
                resize="vertical"
              />
            </label>
          </div>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Medical orders</h3>
            <span class="panel-count data">{{ orderList.length }}</span>
            <span class="panel-tail">
              <el-button
                size="small"
                :icon="Plus"
                :disabled="isReadOnly"
                @click="openDialog"
              >
                Add order
              </el-button>
            </span>
          </header>

          <ul class="orders">
            <li
              v-for="order in orderList"
              :key="order.id"
              class="order"
              :data-severity="order.level"
            >
              <div class="order-head">
                <span class="order-drug">{{ order.drug }}</span>
                <span class="order-dose data">{{ order.dose }}</span>
                <span class="order-route data">{{ order.route }}</span>
                <span class="order-freq">{{ order.frequency }}</span>
                <span class="chip order-chip">{{ LEVEL_LABELS[order.level] }}</span>
              </div>
              <p class="order-msg">{{ order.message }}</p>
              <p v-if="order.justification" class="order-just">
                <span class="order-just-label">Justification on file</span>
                {{ order.justification }}
              </p>
            </li>
          </ul>
        </section>
      </div>

      <div class="stack">
        <section class="panel allergy-panel">
          <header class="panel-head">
            <h3>Allergies</h3>
          </header>
          <ul class="allergies">
            <li
              v-for="allergy in allergens"
              :key="allergy.substance"
              class="allergy"
              data-severity="alert"
            >
              <div class="allergy-head">
                <span class="allergy-substance">{{ allergy.substance }}</span>
                <span class="chip">Allergy</span>
              </div>
              <p class="allergy-reaction">{{ allergy.reaction }}</p>
              <p class="allergy-date">Recorded {{ allergy.recorded }}</p>
            </li>
          </ul>
          <p class="panel-foot allergy-foot">
            Order entry is checked against this list. A matching drug class is refused, not warned.
          </p>
        </section>

        <section class="panel">
          <header class="panel-head">
            <h3>Version history</h3>
          </header>
          <ul class="versions">
            <li v-for="version in versions" :key="version.version">
              <button
                type="button"
                class="version"
                :class="{ 'is-selected': version.version === selectedVersion }"
                :data-severity="version.state === 'archived' ? 'info' : version.state === 'submitted' ? 'warn' : 'ok'"
                @click="selectedVersion = version.version"
              >
                <span class="version-head">
                  <span class="version-label data">{{ version.label }}</span>
                  <span class="chip">{{ version.state }}</span>
                  <span class="version-time data">{{ version.at.split(', ')[1] }}</span>
                </span>
                <span class="version-note">{{ version.note }}</span>
              </button>
            </li>
          </ul>
        </section>
      </div>
    </div>

    <el-dialog v-model="dialogOpen" title="Write a medical order" width="520px">
      <label class="field">
        <span class="field-label">Medication</span>
        <el-select
          v-model="orderForm.drug"
          placeholder="Select a medication"
          class="full"
          @change="chooseDrug"
        >
          <el-option v-for="item in formulary" :key="item.drug" :label="item.drug" :value="item.drug">
            <span class="option-drug">{{ item.drug }}</span>
            <span class="option-class">{{ item.class }}</span>
          </el-option>
        </el-select>
      </label>

      <div class="dose-row">
        <label class="field">
          <span class="field-label">Dose</span>
          <el-input v-model="orderForm.dose" :disabled="!chosen" inputmode="decimal">
            <template #append>{{ chosen?.unit ?? '—' }}</template>
          </el-input>
        </label>
        <label class="field">
          <span class="field-label">Frequency</span>
          <el-select v-model="orderForm.frequency" class="full" :disabled="!chosen">
            <el-option v-for="f in FREQUENCIES" :key="f" :label="f" :value="f" />
          </el-select>
        </label>
      </div>

      <p v-if="!chosen" class="field-hint">
        The check runs as soon as a medication is chosen.
      </p>

      <!-- The check result. An allergy conflict is the only place in the
           interface that goes red, which is why it reads instantly. -->
      <div v-else class="check" :data-severity="check.level">
        <p class="check-head">
          <el-icon class="check-icon">
            <WarningFilled v-if="check.level === 'alert'" />
            <WarningFilled v-else-if="check.level === 'warn'" />
            <CircleCheckFilled v-else />
          </el-icon>
          {{ check.title }}
        </p>
        <p class="check-body">{{ check.body }}</p>
      </div>

      <label v-if="check?.level === 'warn'" class="field justification">
        <span class="field-label">Clinical justification</span>
        <el-input
          v-model="orderForm.justification"
          type="textarea"
          :rows="3"
          placeholder="Why this dose is appropriate for this patient"
        />
        <span class="field-hint">
          Recorded against the order and written to the audit log. At least 10 characters.
        </span>
      </label>

      <template #footer>
        <el-button @click="dialogOpen = false">Cancel</el-button>
        <el-button type="primary" :disabled="!canAdd" @click="addOrder">
          {{ check?.level === 'warn' ? 'Add with justification' : 'Add order' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.banner {
  margin-bottom: 18px;
}

.notice-icon {
  flex: none;
  margin-top: 2px;
}

/* Record meta -------------------------------------------------------------- */

.meta-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 1px;
  padding: 0;
  margin: 0;
  overflow: hidden;
  background: var(--line-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
}

.meta-strip > div {
  padding: 12px 16px;
  background: var(--surface);
}

.meta-strip dt {
  font-size: 11.5px;
  color: var(--ink-3);
}

.meta-strip dd {
  margin: 3px 0 0;
  font-size: 13.5px;
  font-weight: 600;
}

/* Orders ------------------------------------------------------------------- */

.orders {
  padding: 0 20px;
  margin: 0;
  list-style: none;
}

.order {
  position: relative;
  padding: 14px 0 15px 16px;
  border-bottom: 1px solid var(--line-2);
}

.order:last-child {
  border-bottom: 0;
}

/* Same edge-bar convention as the dashboard worklist, so severity reads the
   same way wherever it appears. */
.order::before {
  position: absolute;
  top: 16px;
  bottom: 17px;
  left: 0;
  width: 2px;
  content: '';
  background: var(--sev, var(--ok));
  border-radius: 1px;
}

.order-head {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  align-items: baseline;
}

.order-drug {
  font-size: 14px;
  font-weight: 600;
}

.order-dose {
  font-weight: 600;
  color: var(--ink);
}

.order-route,
.order-freq {
  font-size: 12.5px;
  color: var(--ink-2);
}

.order-chip {
  margin-left: auto;
}

.order-msg {
  margin: 5px 0 0;
  font-size: 12.5px;
  color: var(--ink-2);
}

.order-just {
  padding: 8px 10px;
  margin: 8px 0 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-2);
  background: var(--surface-2);
  border-radius: var(--radius);
}

.order-just-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-3);
}

/* Allergies ---------------------------------------------------------------- */

.allergies {
  padding: 0 20px;
  margin: 0;
  list-style: none;
}

.allergy {
  padding: 14px 0;
  border-bottom: 1px solid var(--line-2);
}

.allergy:last-child {
  border-bottom: 0;
}

.allergy-head {
  display: flex;
  gap: 10px;
  align-items: center;
}

.allergy-substance {
  font-size: 14px;
  font-weight: 600;
  color: var(--alert-dark);
}

.allergy-head .chip {
  margin-left: auto;
}

.allergy-reaction {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-2);
}

.allergy-date {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ink-3);
}

.allergy-foot {
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-3);
}

/* Versions ----------------------------------------------------------------- */

.versions {
  padding: 8px;
  margin: 0;
  list-style: none;
}

.version {
  display: block;
  width: 100%;
  padding: 10px 12px;
  font: inherit;
  text-align: left;
  cursor: pointer;
  background: none;
  border: 0;
  border-radius: var(--radius);
}

.version:hover {
  background: var(--surface-2);
}

.version.is-selected {
  background: var(--teal-soft);
  box-shadow: inset 2px 0 0 var(--teal);
}

.version-head {
  display: flex;
  gap: 8px;
  align-items: center;
}

.version-label {
  font-size: 13px;
  font-weight: 600;
}

.version-time {
  margin-left: auto;
  font-size: 11.5px;
  color: var(--ink-3);
}

.version-note {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--ink-2);
}

/* Order dialog ------------------------------------------------------------- */

.option-drug {
  font-weight: 600;
}

.option-class {
  float: right;
  font-size: 12px;
  color: var(--ink-3);
}

.dose-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.check {
  padding: 12px 14px;
  margin-bottom: 18px;
  color: var(--sev);
  background: var(--sev-soft);
  border-radius: var(--radius);
}

.check-head {
  display: flex;
  gap: 7px;
  align-items: center;
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
}

.check-icon {
  flex: none;
  font-size: 15px;
}

.check-body {
  margin: 6px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--ink);
}

.justification {
  margin-top: 2px;
}
</style>
