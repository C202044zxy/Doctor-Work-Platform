<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDown,
  Avatar,
  Bell,
  ChatDotRound,
  Checked,
  Document,
  Odometer,
  SwitchButton,
  Tickets,
  User,
  UserFilled,
} from '@element-plus/icons-vue'

import { navigation } from './router'
import { canOpen } from './access'
import { currentClinician, isSignedIn, signOut } from './session'
import { ElMessage } from 'element-plus'
import { authentication, health, reminders } from './api/client'

// Navigation entries carry an icon name; resolve them to components here so the
// route table itself stays free of presentation concerns.
const ICONS = {
  Odometer,
  User,
  Document,
  ChatDotRound,
  Checked,
  Tickets,
  // `User` is the patient directory's entry, so user management gets the filled
  // variant rather than a second identical glyph in the rail.
  UserFilled,
}

const SERVICE_LABELS = {
  checking: 'Checking services',
  ready: 'All services ready',
  degraded: 'Service degraded',
  unreachable: 'Service unreachable',
}

const route = useRoute()
const router = useRouter()
const clinician = currentClinician
const pageTitle = computed(() => route.meta.title ?? 'Doctor Work Platform')

// T07 签收标准 3 — a `junior` sees no 病历审阅 and no 审计日志 entry. An entry
// without `roles` is for everyone. This hides the door; the route guard is what
// locks it, and both are required.
const visibleNavigation = computed(() =>
  navigation.filter((item) => canOpen(item.roles, clinician.value.role)),
)

const serviceState = ref('checking')
const serviceLabel = computed(() => SERVICE_LABELS[serviceState.value])

// M6-T6. This badge was `counts.alerts + counts.pendingReviews` -- two fabricated
// figures from api/demo-data.js, shown on every screen in the shell, so the one
// piece of the demo path that was visible everywhere was invented. It is now the
// real unread-reminder count, which is exactly what `GET /api/reminders/unread-count`
// exists for: "so the workspace shell can poll one cheap endpoint instead of
// fetching the list to decide whether to show it".
const unread = ref(0)
let unreadTimer = null

async function refreshUnread() {
  // Nothing to count while signed out, and the endpoint would answer 401.
  if (!isSignedIn.value) {
    unread.value = 0
    return
  }
  try {
    unread.value = (await reminders.unreadCount()).unread
  } catch {
    // A poll that fails leaves the last number on screen. There is nothing the
    // reader could do about it, and a toast per minute would be worse than a
    // stale badge.
  }
}

// A screen change is the natural moment to re-check: the reader may have just
// marked a reminder done, or opened the list that consumes them.
watch(() => route.fullPath, refreshUnread)

onMounted(async () => {
  try {
    const result = await health.ready()
    serviceState.value = result.status === 'ok' ? 'ready' : 'degraded'
  } catch {
    serviceState.value = 'unreachable'
  }
  await refreshUnread()
  // The reminder job fires on a cron the shell does not control, so the bell has
  // to ask. One minute is well inside the demo's "wait two minutes" step and
  // costs one indexed count.
  unreadTimer = setInterval(refreshUnread, 60_000)
})

onUnmounted(() => clearInterval(unreadTimer))

const accountBusy = ref(false)
async function handleAccount(command) {
  if (command === 'face-enroll') {
    router.push({ name: 'face-enroll' })
    return
  }
  if (accountBusy.value) return
  accountBusy.value = true
  try {
    await authentication.logout()
    signOut()
    router.push({ name: 'login' })
  } catch (error) { ElMessage.error(error.message) }
  finally { accountBusy.value = false }
}
</script>

<template>
  <!-- The sign-in screen sits outside the shell: there is no navigation to
       offer until someone is signed in. -->
  <router-view v-if="route.meta.public" />

  <div v-else class="shell">
    <aside class="sidebar">
      <div class="brand">
        <svg class="brand-mark" viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
          <rect width="24" height="24" rx="7" fill="var(--teal)" />
          <path
            d="M4 12.4h3.6l1.9-4.6 2.9 9 1.9-4.4H20"
            fill="none"
            stroke="#fff"
            stroke-width="1.7"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
        <span class="brand-name">Doctor Work<br />Platform</span>
      </div>

      <nav class="nav" aria-label="Primary">
        <router-link
          v-for="item in visibleNavigation"
          :key="item.name"
          :to="{ name: item.name }"
          class="nav-item"
        >
          <el-icon class="nav-icon"><component :is="ICONS[item.icon]" /></el-icon>
          <span class="nav-label">{{ item.label }}</span>
        </router-link>
      </nav>

      <p class="build-note">
        Development build. Some clinical screens still display synthetic demonstration data.
      </p>
    </aside>

    <div class="main">
      <header class="topbar">
        <h1 class="topbar-title">{{ pageTitle }}</h1>

        <div class="topbar-right">
          <span class="service" :data-state="serviceState">
            <span class="service-dot" aria-hidden="true"></span>
            {{ serviceLabel }}
          </span>

          <!-- No `:max`, so the badge shows the count it actually has. The
               dashboard is where the notifications are listed, so that is where
               the bell goes; there is no separate notifications screen. -->
          <el-badge :value="unread" class="bell">
            <el-button
              text
              circle
              :icon="Bell"
              aria-label="Notifications — open the dashboard"
              title="Notifications"
              @click="router.push({ name: 'dashboard' })"
            />
          </el-badge>

          <el-dropdown trigger="click" @command="handleAccount">
            <button type="button" class="clinician">
              <span class="avatar" aria-hidden="true">{{ clinician.initials }}</span>
              <span class="clinician-text">
                <span class="clinician-name">{{ clinician.name }}</span>
                <span class="clinician-role">{{ clinician.role }}</span>
              </span>
              <el-icon class="clinician-caret"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>{{ clinician.department }}</el-dropdown-item>
                <el-dropdown-item command="face-enroll" :icon="Avatar" divided>
                  Face enrolment
                </el-dropdown-item>
                <el-dropdown-item :disabled="accountBusy" command="sign-out" :icon="SwitchButton" divided>
                  Sign out
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  height: 100%;
}

/* Sidebar ------------------------------------------------------------------ */

.sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--surface);
  border-right: 1px solid var(--line);
}

.brand {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 16px 16px 15px;
  border-bottom: 1px solid var(--line-2);
}

.brand-mark {
  flex: none;
}

.brand-name {
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: -0.01em;
  color: var(--ink);
}

.nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 1px;
  min-height: 0;
  padding: 10px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  font-size: 13.5px;
  color: var(--ink-2);
  text-decoration: none;
  border-radius: var(--radius);
}

.nav-item:hover {
  background: var(--surface-2);
  color: var(--ink);
}

/* The active marker is an inset edge bar rather than a colour block: it reads
   as an instrument indicator and keeps the row quiet. */
.nav-item.router-link-active {
  font-weight: 600;
  color: var(--teal-dark);
  background: var(--teal-soft);
  box-shadow: inset 2px 0 0 var(--teal);
}

.nav-icon {
  flex: none;
  font-size: 15px;
}

.nav-label {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.build-note {
  padding: 12px 16px 14px;
  margin: 0;
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--ink-3);
  border-top: 1px solid var(--line-2);
}

/* Top bar ------------------------------------------------------------------ */

.main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.topbar {
  display: flex;
  flex: none;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  height: var(--topbar-h);
  padding: 0 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--line);
}

/* The screen name in the top bar, not the heading inside the screen. */
.topbar-title {
  font-size: 16px;
  font-weight: 600;
}

.topbar-right {
  display: flex;
  gap: 18px;
  align-items: center;
}

.service {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  font-size: 12.5px;
  color: var(--ink-2);
  white-space: nowrap;
}

.service-dot {
  width: 7px;
  height: 7px;
  background: var(--ink-3);
  border-radius: 50%;
}

.service[data-state='ready'] .service-dot {
  background: var(--ok);
}

.service[data-state='degraded'] .service-dot {
  background: var(--warn);
}

.service[data-state='unreachable'] .service-dot {
  background: var(--alert);
}

.bell {
  line-height: 0;
}

.clinician {
  display: flex;
  gap: 9px;
  align-items: center;
  padding: 4px 8px 4px 4px;
  font: inherit;
  color: var(--ink);
  cursor: pointer;
  background: none;
  border: 0;
  border-radius: var(--radius);
}

.clinician:hover {
  background: var(--surface-2);
}

.avatar {
  display: grid;
  flex: none;
  place-items: center;
  width: 30px;
  height: 30px;
  font-size: 11.5px;
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.02em;
  background: var(--teal);
  border-radius: 50%;
}

.clinician-text {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.25;
}

.clinician-name {
  font-size: 13px;
  font-weight: 600;
}

.clinician-role {
  font-size: 11.5px;
  color: var(--ink-2);
}

.clinician-caret {
  font-size: 12px;
  color: var(--ink-3);
}

.content {
  flex: 1;
  min-height: 0;
  padding: 24px;
  overflow-y: auto;
}

/* Below this width the labels go and the rail narrows to icons. */
@media (max-width: 900px) {
  .shell {
    grid-template-columns: 56px 1fr;
  }

  .brand-name,
  .nav-label,
  .build-note {
    display: none;
  }

  .brand {
    justify-content: center;
    padding: 16px 8px 15px;
  }

  .nav-item {
    justify-content: center;
    padding: 10px 0;
  }

  .clinician-text,
  .clinician-caret,
  .service {
    display: none;
  }
}
</style>
