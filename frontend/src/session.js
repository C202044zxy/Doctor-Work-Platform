import { computed, ref } from 'vue'
import { authentication } from './api/client.js'

const STORAGE_KEY = 'dwp.access-token'
const token = ref(sessionStorage.getItem(STORAGE_KEY))
const user = ref(null)
let restoration
export const isSignedIn = computed(() => Boolean(token.value && user.value))
export const currentClinician = computed(() => ({
  name: user.value?.name || '',
  role: user.value?.title || '',
  department: user.value?.department || '',
  initials: (user.value?.name || '').split(/\s+/).map((part) => part[0]).join('').slice(0, 2),
}))
export function accessToken() { return token.value }
export function signIn(data) {
  token.value = data.access_token
  user.value = data.user
  sessionStorage.setItem(STORAGE_KEY, token.value)
}
export function signOut() {
  token.value = null
  user.value = null
  sessionStorage.removeItem(STORAGE_KEY)
}
export async function restoreSession() {
  if (!token.value || user.value) return
  if (!restoration) {
    restoration = (async () => {
      try { user.value = await authentication.me() }
      catch { signOut() }
      finally { restoration = null }
    })()
  }
  await restoration
}
