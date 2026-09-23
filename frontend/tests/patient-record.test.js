// M2's shaping: the allergy banner's tier, the history timeline's rows, and the
// sex and age the directory and the detail head both print.
//
// All of it is computed from a response a patient screen already has, so none of
// it is visible by looking at a page that loaded — a banner one shade too quiet,
// a timeline that quietly puts the undated entry first, and an age that is a year
// out for the week before a birthday all render fine.
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  ageFrom,
  allergySeverity,
  dateLabel,
  genderLabel,
  sexAge,
  timelineOf,
} from '../src/patient-record.js'

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

test('a date-only field is not shifted by the reader’s timezone', () => {
  // `new Date('2019-05-01')` is UTC midnight: the day before for anyone west of
  // Greenwich, which is why `dateLabel` never builds a Date.
  assert.equal(dateLabel('2019-05-01'), '1 May 2019')
  assert.equal(dateLabel('2024-12-31'), '31 Dec 2024')
  // A full timestamp on the same field still lands on the right day.
  assert.equal(dateLabel('2019-05-01T00:00:00Z'), '1 May 2019')
})

test('an unusable date is shown as it arrived rather than as a placeholder', () => {
  assert.equal(dateLabel('unknown'), 'unknown')
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

// The baseline's patient: male, born 12 Mar 1968. Every assertion below is made
// at a fixed instant rather than "now", because an age read from the wall clock
// is a test that fails on the patient's birthday.
const BORN = { gender: 'male', birth_date: '1968-03-12' }
const TODAY = new Date('2026-09-23T12:00:00Z')

test('the age is whole years, and this year’s birthday has to have happened', () => {
  // 58 on 12 Mar 2026, and still 58 in September.
  assert.equal(ageFrom('1968-03-12', TODAY), 58)
  assert.equal(ageFrom('1968-09-23', TODAY), 58) // birthday today counts
  assert.equal(ageFrom('1968-09-24', TODAY), 57) // tomorrow does not
  // The year after a birthday nobody has reached yet.
  assert.equal(ageFrom('1968-12-31', new Date('2026-01-01T12:00:00Z')), 57)
})

test('a birth date nobody can read is no age rather than a wrong one', () => {
  // `null` is what the directory renders as its dash; a computed NaN would print
  // as "Male · NaN".
  assert.equal(ageFrom('', TODAY), null)
  assert.equal(ageFrom(null, TODAY), null)
  assert.equal(ageFrom(undefined, TODAY), null)
  assert.equal(ageFrom('unknown', TODAY), null)
})

test('the identity line is one rule for both screens', () => {
  assert.equal(sexAge(BORN, TODAY), 'Male · 58')
  assert.equal(sexAge({ gender: 'female', birth_date: '1985-07-01' }, TODAY), 'Female · 41')
  // No birth date on record: the sex alone, with no dangling separator.
  assert.equal(sexAge({ gender: 'male' }, TODAY), 'Male')
  // The enum's third value, and a record with no gender key at all.
  assert.equal(genderLabel('unknown'), 'Unknown')
  assert.equal(sexAge({}, TODAY), 'Unknown')
  assert.equal(sexAge(undefined, TODAY), 'Unknown')
})
