import { ref } from 'vue'

// Query the scoped patient API and ignore responses for older search terms.
export function usePatientSearch(request, delay = 250) {
  const patients = ref([]), searching = ref(false), searchError = ref('')
  let version = 0, timer

  function searchPatients(value) {
    const current = ++version
    clearTimeout(timer)
    const name = value.trim()
    patients.value = []
    searchError.value = ''
    searching.value = Boolean(name)
    if (!name) return
    timer = setTimeout(async () => {
      try {
        const data = await request(`/patients?${new URLSearchParams({ name, size: 100 })}`)
        if (version === current) patients.value = data.items
      } catch (err) {
        if (version === current) searchError.value = err.message || 'Unable to search patients'
      } finally {
        if (version === current) searching.value = false
      }
    }, delay)
  }

  function stopSearch() {
    version++
    clearTimeout(timer)
    searching.value = false
  }

  return { patients, searching, searchError, searchPatients, stopSearch }
}
