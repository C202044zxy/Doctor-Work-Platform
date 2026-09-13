import { computed, ref } from 'vue'
import { authentication } from './api/client.js'

const STORAGE_KEY = 'dwp.access-token'

// T07 签收标准 2 says the token survives a refresh, which sessionStorage does not
// do — it is scoped to the tab and cleared when it closes. It used to live there,
// so anyone with a live session has their token in the old store: move it across
// on the first read rather than signing them out over a storage change.
function readToken() {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored) return stored

  const legacy = sessionStorage.getItem(STORAGE_KEY)
  if (legacy) {
    localStorage.setItem(STORAGE_KEY, legacy)
    sessionStorage.removeItem(STORAGE_KEY)
    return legacy
  }
  return null
}

const token = ref(readToken())
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
// T42 §4.3.1 ② names the account by username rather than by id, and the face
// sign-in page has to send the one being claimed.
export const currentUsername = computed(() => user.value?.username || '')
// The API calls this `title`, not `role`, and the contract forbids renaming it.
// The route guard reads it to decide who may open a gated screen.
export const currentTitle = computed(() => user.value?.title || '')
export function signIn(data) {
  token.value = data.access_token
  user.value = data.user
  localStorage.setItem(STORAGE_KEY, token.value)
}
export function signOut() {
  token.value = null
  user.value = null
  localStorage.removeItem(STORAGE_KEY)
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
