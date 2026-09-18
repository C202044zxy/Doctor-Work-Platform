<script setup>
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
// The patient half is M3 and has no code. The panel below says exactly that
// instead of dressing the place up: fabricated rows here would sit inside the
// demo path pretending to be a delivered feature, and the previous screen went
// further than most -- it announced "Connected over WebSocket" on a build with no
// WebSocket route anywhere in it. That screen is in `git show 65eaf88` if the
// layout is worth reusing; what M3 replaces is one `el-tab-pane`.
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
  router.replace({ query: name === 'patient' ? {} : { tab: name } })
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

    <el-tabs v-model="active" @tab-change="select">
      <el-tab-pane label="Patient consultation" name="patient">
        <section class="panel">
          <header class="panel-head">
            <h3>Patient consultation</h3>
            <span class="chip" data-severity="info">Not built</span>
          </header>
          <p class="empty">
            Text and image sessions with patients, one thread each, in the shape of a chat app.
            <strong>M3 owns this module and has no code yet</strong>, so the tab states the gap
            rather than showing a conversation that does not exist. The remote consultation tab
            beside it is the half that works today.
          </p>
        </section>
      </el-tab-pane>

      <!-- M5's screen, mounted as delivered. `lazy` because it asks the API for its
           list, its counts and its invitation box on mount, and a visit that only
           wants the patient half should not pay for four requests it will not read. -->
      <el-tab-pane label="Remote consultation" name="remote" lazy>
        <RemoteConsultationView />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<!-- Page furniture (.page, .panel, .chip, .empty, .muted) lives in src/style.css. -->
<style scoped>
/* `.empty` carries vertical padding only, so as a direct child of a panel it runs
   into the border. Same override the health panel needs, for the same reason. */
.panel > .empty {
  padding: 28px 20px;
}
</style>
