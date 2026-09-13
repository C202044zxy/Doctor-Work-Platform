import { createRouter, createWebHistory } from 'vue-router'
import { isSignedIn, restoreSession } from '../session'

// The sidebar in App.vue renders from this array, so a menu entry and its route
// cannot drift apart. `icon` is resolved to a component in App.vue.
export const navigation = [
  { name: 'dashboard', label: 'Dashboard', icon: 'Odometer' },
  { name: 'patients', label: 'Patients', icon: 'User' },
  { name: 'records', label: 'Medical Records', icon: 'Document' },
  { name: 'consultations', label: 'Consultations', icon: 'ChatDotRound' },
  { name: 'remote-consultation', label: 'Remote Consultation', icon: 'VideoCamera' },
  { name: 'health-plans', label: 'Health Plans', icon: 'Document' },
  { name: 'reminders', label: 'Reminders', icon: 'Tickets' },
  { name: 'health', label: 'Health Management', icon: 'TrendCharts' },
  { name: 'review', label: 'Review Queue', icon: 'Checked' },
  { name: 'audit', label: 'Audit Log', icon: 'Tickets' },
]

const routes = [
  { path: '/health-plans', name: 'health-plans', component: () => import('../views/HealthPlansView.vue'), meta: { title: 'Health Plans' } },
  { path: '/reminders', name: 'reminders', component: () => import('../views/RemindersView.vue'), meta: { title: 'Reminders' } },
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

  // B consultations, health plans and reminders use real APIs.
  // Other owners replace their own demo screens.
  {
    path: '/records',
    name: 'records',
    component: () => import('../views/MedicalRecordView.vue'),
    meta: { title: 'Medical Records' },
  },
  {
    path: '/consultations',
    name: 'consultations',
    component: () => import('../views/ConsultationsView.vue'),
    meta: { title: 'Consultations' },
  },
  {
    path: '/remote-consultation',
    name: 'remote-consultation',
    component: () => import('../views/RemoteConsultationView.vue'),
    meta: { title: 'Remote Consultation' },
  },
  {
    path: '/health',
    name: 'health',
    component: () => import('../views/HealthManagementView.vue'),
    meta: { title: 'Health Management' },
  },
  {
    path: '/review',
    name: 'review',
    component: () => import('../views/ReviewQueueView.vue'),
    meta: { title: 'Review Queue' },
  },
  {
    path: '/audit',
    name: 'audit',
    component: () => import('../views/AuditLogView.vue'),
    meta: { title: 'Audit Log' },
  },

  // Unknown paths fall back to the dashboard rather than a dead end.
  { path: '/:pathMatch(.*)*', redirect: { name: 'dashboard' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
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
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Doctor Work Platform` : 'Doctor Work Platform'
})

export default router
