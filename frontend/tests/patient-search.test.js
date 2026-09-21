import test from 'node:test'
import assert from 'node:assert/strict'
import { setTimeout as tick } from 'node:timers/promises'
import { usePatientSearch } from '../src/patient-search.js'

test('search uses trimmed fuzzy name and preserves IDs for duplicate names', async () => {
  const matches = [{ name: 'Alex Chen', patient_no: 'P001' }, { name: 'Alex Chen', patient_no: 'P002' }]
  const search = usePatientSearch(async path => {
    const url = new URL(path, 'https://example.test')
    assert.equal(url.searchParams.get('name'), 'Alex')
    assert.equal(url.searchParams.has('patient_no'), false)
    return { items: matches }
  }, 0)
  search.searchPatients(' Alex ')
  await tick(10)
  assert.deepEqual(search.patients.value, matches)
  assert.equal(search.searching.value, false)
})

test('out-of-order search and cleared query cannot restore stale patients', async () => {
  const pending = []
  const search = usePatientSearch(() => new Promise(resolve => pending.push(resolve)), 0)
  search.searchPatients('A')
  await tick(10)
  search.searchPatients('B')
  await tick(10)
  pending[1]({ items: [{ name: 'B', patient_no: 'P002' }] })
  await tick(0)
  pending[0]({ items: [{ name: 'A', patient_no: 'P001' }] })
  await tick(0)
  assert.equal(search.patients.value[0].name, 'B')
  search.searchPatients('C')
  await tick(10)
  search.searchPatients(' ')
  pending[2]({ items: [{ name: 'C' }] })
  await tick(0)
  assert.deepEqual(search.patients.value, [])
  assert.equal(search.searching.value, false)
})

test('search errors are visible and pending debounce is cancelled on unmount', async () => {
  let requests = 0
  const search = usePatientSearch(async () => { requests++; throw new Error('Search unavailable') }, 0)
  search.searchPatients('Alex')
  await tick(10)
  assert.equal(search.searchError.value, 'Search unavailable')
  assert.equal(search.searching.value, false)
  search.searchPatients('Chen')
  search.stopSearch()
  await tick(10)
  assert.equal(requests, 1)
})
