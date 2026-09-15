<script setup>
// T07 签收标准 3 与签收场景 S1: a role that is not allowed somewhere has to land
// on a page that says so. The criterion is explicit that this is neither a blank
// screen nor an entry still sitting in the menu — the route guard sends people
// here and the sidebar drops the item, and both halves have to hold.
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { currentClinician } from '../session'

const route = useRoute()
const router = useRouter()

const clinician = currentClinician
const attempted = computed(() => (typeof route.query.from === 'string' ? route.query.from : ''))

// Naming the path is the difference between "something went wrong" and "you
// asked for the audit log, which is an administrator's screen".
const lede = computed(() =>
  attempted.value
    ? `Your account does not have access to ${attempted.value}.`
    : 'Your account does not have access to this screen.',
)
</script>

<template>
  <div class="page">
    <section class="panel denied">
      <p class="code">403</p>
      <h2 class="heading">No access</h2>
      <p class="lede">{{ lede }}</p>

      <dl class="facts">
        <div>
          <dt>Signed in as</dt>
          <dd>{{ clinician.name || 'Unknown' }}</dd>
        </div>
        <div>
          <dt>Role</dt>
          <dd class="data">{{ clinician.role || '—' }}</dd>
        </div>
      </dl>

      <p class="hint">
        Permissions are decided by role and by department, and they are enforced on
        the API as well as here — hiding a menu entry is not what keeps this screen
        closed. If you need it, ask an administrator for a role change or a
        temporary grant.
      </p>

      <el-button type="primary" @click="router.replace({ name: 'dashboard' })">
        Back to the dashboard
      </el-button>
    </section>
  </div>
</template>

<style scoped>
.denied {
  max-width: 560px;
  padding: 34px 36px;
  margin: 40px auto;
}

.code {
  margin: 0;
  font-family: var(--font-data);
  font-size: 13px;
  font-weight: 600;
  color: var(--alert);
}

.heading {
  margin: 8px 0 0;
  font-size: 22px;
  letter-spacing: -0.015em;
}

.lede {
  margin: 12px 0 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--ink-2);
}

.facts {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 36px;
  padding: 16px 0;
  margin: 22px 0;
  border-top: 1px solid var(--line-2);
  border-bottom: 1px solid var(--line-2);
}

.facts dt {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-3);
}

.facts dd {
  margin: 0;
  font-size: 13px;
}

.hint {
  margin: 0 0 22px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--ink-3);
}
</style>
