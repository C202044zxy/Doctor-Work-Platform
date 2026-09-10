import { computed, ref } from 'vue'

// Placeholder session. Task T05 replaces this with a real JWT from the
// password + email-code flow, and task T08 replaces the hard-coded clinician
// with the role matrix. Until then sign-in is a local flag so the interface
// can be demonstrated without an auth backend.
//
// sessionStorage rather than localStorage: a refresh keeps you signed in
// while building, but a fresh tab starts at the sign-in screen.

const STORAGE_KEY = 'dwp.signed-in'

const signedIn = ref(sessionStorage.getItem(STORAGE_KEY) === 'true')

// The one hard-coded clinician this build renders as. The menu in App.vue is
// written for this role; it is not yet driven by the role matrix.
const clinician = ref({
  name: 'Dr. Chen',
  role: 'Chief Physician',
  department: 'Cardiology',
  initials: 'DC',
})

export const isSignedIn = computed(() => signedIn.value)
export const currentClinician = computed(() => clinician.value)

export function signIn() {
  signedIn.value = true
  sessionStorage.setItem(STORAGE_KEY, 'true')
}

export function signOut() {
  signedIn.value = false
  sessionStorage.removeItem(STORAGE_KEY)
}
