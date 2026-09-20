// The dashboard's week view. These pin the two failures that a rendered page
// cannot show you: which week a Sunday belongs to, and whether the clock time is
// the reader's or Greenwich's.
//
// A caveat worth stating rather than hiding: on a machine running in UTC, a
// UTC-based implementation and a local one agree, so the two tests that guard the
// conversion pass either way. The team's machines are all at UTC+8, where an
// 09:30 consultation printed as 01:30 is the visible symptom, and that is what
// these would have caught — see the note in each.
import test from 'node:test'
import assert from 'node:assert/strict'

import { clockTime, dayLabel, isToday, startOfWeek, weekAgenda, weekBounds } from '../src/week.js'

// 2026-09-21 is a Monday and 2026-09-27 the Sunday that closes that week.
const WEDNESDAY = new Date(2026, 8, 23, 10, 0)

function meeting(id, at, extra = {}) {
  return { id, scheduled_at: at.toISOString(), ...extra }
}

test('the week starts on Monday at midnight and ends seven days later', () => {
  const start = startOfWeek(WEDNESDAY)
  assert.equal(start.getDay(), 1) // Monday
  assert.equal(start.getDate(), 21)
  assert.equal(start.getHours(), 0)
  assert.equal(start.getMinutes(), 0)

  const { end } = weekBounds(WEDNESDAY)
  assert.equal(end.getDate(), 28)
  assert.equal(end.getHours(), 0)
})

test('a Sunday evening belongs to the week that began that Monday', () => {
  const { start, end } = weekBounds(WEDNESDAY)
  // Local, because the reader's week is the one their calendar shows. Under a
  // UTC-based calculation this lands 8 hours earlier and still reads Sunday, so
  // the assertion only bites on a machine east of Greenwich — which is the case
  // this repository ships to.
  const sunday = new Date(2026, 8, 27, 23, 30)
  assert.ok(sunday >= start)
  assert.ok(sunday < end)
})

test('the following Monday midnight is the next week, not this one', () => {
  const { end } = weekBounds(WEDNESDAY)
  // Half-open on purpose: an inclusive end would show a consultation in two weeks.
  assert.equal(new Date(2026, 8, 28, 0, 0).getTime(), end.getTime())
  assert.equal(new Date(2026, 8, 28, 0, 1) < end, false)
})

test('the clock time is the reader clock, not the raw UTC text', () => {
  // Built from an explicit UTC instant so the ISO string and the local reading
  // differ by this machine's offset.
  const utc = new Date(Date.UTC(2026, 8, 22, 1, 30))
  const pad = (value) => String(value).padStart(2, '0')
  const expected = `${pad(utc.getHours())}:${pad(utc.getMinutes())}`
  assert.equal(clockTime(utc.toISOString()), expected)
  // `slice(11, 16)` of the ISO string would answer 01:30 here and 09:30 for the
  // reader who booked it.
  assert.equal(clockTime('not a date'), '')
})

test('only days that carry a consultation are returned, in time order', () => {
  const { start, end } = weekBounds(WEDNESDAY)
  const agenda = weekAgenda(
    [
      meeting(3, new Date(2026, 8, 22, 16, 30)),
      meeting(1, new Date(2026, 8, 22, 9, 0)),
      meeting(2, new Date(2026, 8, 24, 11, 15)),
      // Outside the week in both directions.
      meeting(4, new Date(2026, 8, 20, 20, 0)),
      meeting(5, new Date(2026, 8, 28, 9, 0)),
    ],
    { start, end },
  )

  assert.deepEqual(
    agenda.map((day) => day.label),
    ['Tue 22 Sep', 'Thu 24 Sep'],
  )
  assert.deepEqual(
    agenda[0].items.map((item) => item.id),
    [1, 3],
  )
  assert.deepEqual(
    agenda[1].items.map((item) => item.id),
    [2],
  )
})

test('two consultations at the same minute keep a stable order', () => {
  const { start, end } = weekBounds(WEDNESDAY)
  const same = new Date(2026, 8, 22, 9, 0)
  const agenda = weekAgenda([meeting(9, same), meeting(4, same)], { start, end })
  assert.deepEqual(
    agenda[0].items.map((item) => item.id),
    [4, 9],
  )
})

test('an empty week is an empty list, not seven empty days', () => {
  const { start, end } = weekBounds(WEDNESDAY)
  assert.deepEqual(weekAgenda([], { start, end }), [])
  assert.deepEqual(weekAgenda(null, { start, end }), [])
})

test('a malformed instant is dropped rather than bucketed into today', () => {
  const { start, end } = weekBounds(WEDNESDAY)
  const agenda = weekAgenda([{ id: 1, scheduled_at: null }, { id: 2, scheduled_at: 'x' }], {
    start,
    end,
  })
  assert.deepEqual(agenda, [])
})

test('the label is fixed text, not the browser locale', () => {
  // Pinned arrays rather than `toLocaleDateString`: even a pinned locale is the
  // browser's ICU data, and this column has to read the same everywhere.
  assert.equal(dayLabel(new Date(2026, 8, 21)), 'Mon 21 Sep')
  assert.equal(dayLabel(new Date(2026, 0, 4)), 'Sun 4 Jan')
  assert.equal(dayLabel(new Date(2026, 11, 31)), 'Thu 31 Dec')
})

test('today is recognised by the calendar date, not by the clock', () => {
  assert.equal(isToday(new Date(2026, 8, 23, 0, 1), WEDNESDAY), true)
  assert.equal(isToday(new Date(2026, 8, 23, 23, 59), WEDNESDAY), true)
  assert.equal(isToday(new Date(2026, 8, 24, 0, 0), WEDNESDAY), false)
})
