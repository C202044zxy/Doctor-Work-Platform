<script setup>
import PatientConsultationView from './PatientConsultationView.vue'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import RemoteConsultationView from './RemoteConsultationView.vue'

// One sidebar entry, two modules (0915意见 item 5: "点进去之后两个模块，一个病人
// 问诊（仿微信），一个远程问诊"). They are both consultations -- one is a thread
// with the patient, the other is a colleague brought in about that patient -- so a
// reader looking for either starts at the same word.
//
// The remote half is M5. `RemoteConsultationView.vue` renders here **untouched**:
// it is a screen rather than a component, but it reads no route state of its own,
// so mounting it inside a tab costs nothing and M5 can keep editing its own file
// without this one breaking. Its own heading stays visible under the tabs -- the
// repetition of the word is the price of not reaching into another module's markup
// to hide half its header.
//
// M3 mounts the real patient workbench here; unmounting releases media and sockets.
//
// The tab lives in the URL so either half can be linked to. M5 shipped as its own
// page, so `/remote-consultation` is now a redirect to `?tab=remote`.

const TABS = ['patient', 'remote']
const route = useRoute()
const router = useRouter()

const active = ref(fromQuery(route.query.tab))

function fromQuery(value) {
  return TABS.includes(value) ? value : 'patient'
}

// Covers the arrival path as well as the tab click: the redirect above changes
// the query without the component being re-created.
watch(
  () => route.query.tab,
  (value) => {
    active.value = fromQuery(value)
  },
)

function select(name) {
  // `replace`, because switching tabs is not a step the back button should
  // replay. The patient tab is the default, so it keeps a clean URL.
  const query = { ...route.query }
  delete query.tab
  router.replace({ query: name === 'patient' ? query : { ...query, tab: name } })
}
</script>

<template>
  <div class="page page-wide">
    <header class="page-head">
      <div>
        <h2 class="page-heading">Consultations</h2>
        <p class="page-sub">
          <span>Two conversations: one with the patient, one with a colleague about them</span>
        </p>
      </div>
    </header>

    <el-tabs class="tabs" v-model="active" @tab-change="select">
      <el-tab-pane label="Patient consultation" name="patient">
        <PatientConsultationView v-if="active === 'patient'" />
      </el-tab-pane>

      <!-- M5's screen, mounted as delivered. `lazy` because it asks the API for its
           list, its counts and its invitation box on mount, and a visit that only
           wants the patient half should not pay for four requests it will not read. -->
      <el-tab-pane label="Remote consultation" name="remote" lazy>
        <RemoteConsultationView v-if="active === 'remote'" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<!-- Page furniture (.page, .panel, .chip, .empty, .muted) lives in src/style.css. -->
<style scoped>
/* Element Plus' strip reads as a library default: a hairline across the full
   width under a thick active bar. Tightened so the strip belongs to the page
   rather than to the component library. */
.tabs :deep(.el-tabs__header) {
  margin: 0 0 18px;
}

.tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
  background: var(--line);
}

.tabs :deep(.el-tabs__item) {
  height: 36px;
  font-size: 13.5px;
  color: var(--ink-2);
}

.tabs :deep(.el-tabs__item.is-active) {
  font-weight: 600;
  color: var(--teal-dark);
}

.tabs :deep(.el-tabs__active-bar) {
  height: 2px;
  background: var(--teal);
}
</style>
