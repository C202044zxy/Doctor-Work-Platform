// M2-04's two pieces of shaping: the allergy banner's tier and the history
// timeline's rows.
//
// Both are computed from a response the detail page already has, so neither is
// visible by looking at a page that loaded — a banner one shade too quiet and a
// timeline that quietly puts the undated entry first both render fine.
import test from 'node:test'
import assert from 'node:assert/strict'

import { allergySeverity, onsetLabel, timelineOf } from '../src/patient-record.js'

// The baseline's patient, as `GET /api/patients/P20260001` returns it.
const SEVERE = [
  { id: 1, allergen: 'PENICILLIN', allergy_type: 'drug', severity: 'severe' },
  { id: 2, allergen: 'SULFONAMIDE', allergy_type: 'drug', severity: 'moderate' },
]

test('a severe record is the reserved red, and only a severe one is', () => {
  assert.equal(allergySeverity(SEVERE), 'alert')
  assert.equal(allergySeverity([SEVERE[1]]), 'warn')
})

test('no allergies at all is not a warning', () => {
  // The banner still renders for a patient with none -- it says so -- and a
  // yellow bar over an empty list would read as a hazard that is not there.
  assert.equal(allergySeverity([]), 'info')
  assert.equal(allergySeverity(undefined), 'info')
})

test('a date-only onset is not shifted by the reader’s timezone', () => {
  // `new Date('2019-05-01')` is UTC midnight: the day before for anyone west of
  // Greenwich, which is why `onsetLabel` never builds a Date.
  assert.equal(onsetLabel('2019-05-01'), '1 May 2019')
  assert.equal(onsetLabel('2024-12-31'), '31 Dec 2024')
  // A full timestamp on the same field still lands on the right day.
  assert.equal(onsetLabel('2019-05-01T00:00:00Z'), '1 May 2019')
})

test('an unusable date is shown as it arrived rather than as a placeholder', () => {
  assert.equal(onsetLabel('unknown'), 'unknown')
})

test('the timeline keeps the order the server sent and labels the undated entry', () => {
  // Newest onset first and the undated entry last is the reader's rule, and it
  // lives on the server -- `backend/app/histories.py` orders by
  // `onset_date IS NULL, onset_date DESC`. Sorting again here would be a second
  // copy of that rule, so this asserts the order survives untouched.
  const rows = timelineOf([
    { id: 3, diagnosis: 'Angina pectoris', onset_date: '2024-02-27', notes: '' },
    { id: 2, diagnosis: 'Type 2 diabetes', onset_date: '2019-11-04', notes: 'Diet-controlled' },
    { id: 1, diagnosis: 'Hypertension', onset_date: '2015-06-18', notes: '' },
    { id: 4, diagnosis: 'Peptic ulcer disease', onset_date: null, notes: '' },
  ])

  assert.deepEqual(
    rows.map((row) => row.diagnosis),
    ['Angina pectoris', 'Type 2 diabetes', 'Hypertension', 'Peptic ulcer disease'],
  )
  assert.equal(rows[0].onsetLabel, '27 Feb 2024')
  assert.equal(rows[3].onsetLabel, 'Date unknown')
  assert.equal(rows[3].undated, true)
  assert.equal(rows[0].undated, false)
  // The raw record survives the shaping: the editor's Edit button hands the row
  // back to a date picker, which binds to `onset_date` and not to its label.
  assert.equal(rows[0].onset_date, '2024-02-27')
  assert.equal(rows[3].onset_date, null)
  assert.equal(rows[1].notes, 'Diet-controlled')
})

test('missing notes and an absent list both fall back rather than throwing', () => {
  // `notes` is a column with a server-side default, but a row written before the
  // field existed has no key at all, and the timeline renders `''` for it.
  assert.equal(timelineOf([{ id: 1, diagnosis: 'Asthma', onset_date: null }])[0].notes, '')
  assert.deepEqual(timelineOf([]), [])
  assert.deepEqual(timelineOf(undefined), [])
})
