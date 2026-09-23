import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { currentTitle, isSignedIn, restoreSession } from '../session'
import { setSessionLostHandler } from '../api/client'
import { canOpen, MODULE_ROLES } from '../access'

// The sidebar in App.vue renders from this array, so a menu entry and its route
// cannot drift apart. `icon` is resolved to a component in App.vue.
//
// `roles` is what T07 签收标准 3 asks for: a `junior` must not see 病历审阅 or
// 审计日志. Its absence means everyone signed in can see the entry. The route's
// `meta` below points at the same MODULE_ROLES entry — the menu is what the
// reader notices, the route guard is what actually closes the screen, and T12's
// S2 explicitly refuses a build that only does the first.
export const navigation = [
  { name: 'dashboard', label: 'Dashboard', icon: 'Odometer' },
  { name: 'forum', label: 'Medical Forum', icon: 'ChatDotRound' },
  { name: 'patients', label: 'Patients', icon: 'User' },
  { name: 'records', label: 'Medical Records', icon: 'Document' },
  { name: 'consultations', label: 'Consultations', icon: 'ChatDotRound' },
  { name: 'my-submissions', label: 'My submissions', icon: 'Document' },
  { name: 'review', label: 'Review Queue', icon: 'Checked', roles: MODULE_ROLES.review },
  { name: 'audit', label: 'Audit Log', icon: 'Tickets', roles: MODULE_ROLES.audit },
  { name: 'users', label: 'User Management', icon: 'UserFilled', roles: MODULE_ROLES.users },
  { name: 'profile', label: 'My profile', icon: 'User' },
]

const routes = [
  { path: '/forum', name: 'forum', component: () => import('../views/ForumView.vue'), meta: { title: 'Medical Forum' } },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('../views/ProfileView.vue'),
    meta: { title: 'My profile' },
  },
  {
    path: '/consultation-records',
    name: 'consultation-records',
    redirect: to => ({
      name: 'consultations',
      query: { ...to.query, tab: 'patient', view: 'records' },
      hash: to.hash,
    }),
  },
  {
    path: '/legacy/health-plans',
    name: 'legacy-health-plans',
    component: () => import('../views/HealthPlansView.vue'),
    meta: { title: 'Previous health plans' },
  },
  {
    path: '/legacy/reminders',
    name: 'legacy-reminders',
    component: () => import('../views/RemindersView.vue'),
    meta: { title: 'Previous reminders' },
  },
  { path: '/health-plans', redirect: '/legacy/health-plans' },
  { path: '/reminders', redirect: '/legacy/reminders' },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true, title: 'Sign in' },
  },
  { path: '/', redirect: { name: 'dashboard' } },
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('../views/DashboardView.vue'),
    meta: { title: 'Dashboard' },
  },
  {
    path: '/patients',
    name: 'patients',
    component: () => import('../views/PatientListView.vue'),
    meta: { title: 'Patients' },
  },
  // M5-T7. The consultation report is archived into the patient record, and the
  // tab that reads it back has to hang off a patient-scoped screen. M2-04 owns
  // this page; what stands here today is the header plus that one tab.
  {
    path: '/patients/:patientNo',
    name: 'patient-detail',
    component: () => import('../views/PatientDetailView.vue'),
    // The number is a prop so the view never reaches into the route object.
    props: true,
    meta: { title: 'Patient detail' },
  },

  // The remaining modules. Each screen is built and navigable; the content
  // behind it is fabricated (see api/demo-data.js) until the owning backend
  // task lands. Patients, the two patient-detail tabs (consultation records and
  // health data) and the remote-consultation tab under /consultations read the
  // real service today.
  {
    path: '/records',
    name: 'records',
    component: () => import('../views/MedicalRecordView.vue'),
    meta: { title: 'Medical Records' },
  },
  // M3 + M5 behind one entry: the patient thread and the expert consultation are
  // the two halves of `ConsultationsView.vue`, which picks between them with a tab
  // in the query string.
  {
    path: '/consultations',
    name: 'consultations',
    component: () => import('../views/ConsultationsView.vue'),
    meta: { title: 'Consultations' },
  },
  // M5 shipped remote consultation as a page of its own. The path stays as a
  // redirect so a link written before the merge -- a bookmark, a scenario sheet,
  // a screenshot in a slide -- still lands on the right tab. Deliberately no
  // sidebar entry: it is the same screen the entry above opens, one tab over.
  {
    path: '/remote-consultation',
    redirect: { name: 'consultations', query: { tab: 'remote' } },
  },
  {
    path: '/my-submissions',
    name: 'my-submissions',
    component: () => import('../views/ReviewQueueView.vue'),
    meta: { title: 'My submissions' },
  },
  {
    path: '/review',
    name: 'review',
    component: () => import('../views/ReviewQueueView.vue'),
    meta: { title: 'Review Queue', roles: MODULE_ROLES.review },
  },
  {
    path: '/audit',
    name: 'audit',
    component: () => import('../views/AuditLogView.vue'),
    meta: { title: 'Audit Log', roles: MODULE_ROLES.audit },
  },
  // M1-07. Both halves are stated: the sidebar entry above, and this guard, which
  // is what closes the screen to a junior who types the path in.
  {
    path: '/users',
    name: 'users',
    component: () => import('../views/UserManagementView.vue'),
    meta: { title: 'User Management', roles: MODULE_ROLES.users },
  },

  // T07 签收标准 3 / 场景 S1. Not `public`: nobody reaches this by being signed
  // out, they reach it by being signed in without the permission. No `roles`
  // either, or a junior would be refused the page explaining their refusal.
  {
    path: '/403',
    name: 'forbidden',
    component: () => import('../views/ForbiddenView.vue'),
    meta: { title: 'No access' },
  },

  // T42 §4.3.3【录入】. Signed in by definition — the image belongs to the caller's
  // own record and the endpoint identifies them from the token. Old enrolment
  // links now land in the unified profile page.
  {
    path: '/face/enroll',
    name: 'face-enroll',
    redirect: { name: 'profile', query: { section: 'face' } },
  },

  // Unknown paths fall back to the dashboard rather than a dead end.
  { path: '/:pathMatch(.*)*', redirect: { name: 'dashboard' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

// A session that ends mid-use has to take the reader somewhere that explains it.
// Deferred by a tick because this fires from inside `restoreSession()`, while the
// guard for that navigation is still deciding — redirecting first would race the
// guard's own redirect to /login and can leave the message with nowhere to land.
setSessionLostHandler(({ kind, message }) => {
  setTimeout(() => {
    if (kind === 'forbidden') {
      if (router.currentRoute.value.name !== 'forbidden') router.replace({ name: 'forbidden' })
      return
    }
    ElMessage.warning(message)
    if (router.currentRoute.value.name !== 'login') router.replace({ name: 'login' })
  }, 0)
})

// Front-end guards shape the experience, they are not a security boundary. The
// real check is the role and department filter on the API (tasks T08 and T09).
router.beforeEach(async (to) => {
  await restoreSession()
  if (!to.meta.public && !isSignedIn.value) {
    return { name: 'login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }
  if (to.name === 'login' && isSignedIn.value) {
    return { name: 'dashboard' }
  }
  // T07 签收标准 3: signed in but not allowed here goes to the 403 page — not back
  // to the sign-in form, and not a blank screen. `from` lets that page name the
  // screen that was refused instead of apologising vaguely.
  if (!canOpen(to.meta.roles, currentTitle.value)) {
    return { name: 'forbidden', query: { from: to.fullPath } }
  }
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Doctor Work Platform` : 'Doctor Work Platform'
})

export default router
